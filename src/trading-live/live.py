import json
import math
import os
import re
import sqlite3
import sys
import time
from collections import deque
from pathlib import Path

import websocket

ROOT = Path("/var/lib/trading-live")
SOURCE = Path("/var/lib/trading-scalp/scalp.json")
URL = "wss://stream.bybit.com/v5/public/linear"

def num(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Non-finite number")
    return value

def publish(status, rows=None, message=""):
    data = dict(
        updated=time.time(), status=status, message=message,
        rows=rows or [], mode="OBSERVATION ONLY",
    )
    temporary = ROOT/"live.tmp"
    with temporary.open("w") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, ROOT/"live.json")
    return data

def select_symbols():
    s = json.loads(SOURCE.read_text())
    now = time.time()
    if s.get("status") not in ("ok", "partial"):
        return []
    if not 0 <= now-s.get("finished", 0) <= 180:
        return []
    selected = []
    for r in s.get("rows", []):
        symbol = r["symbol"]
        if (
            r["candidate"]
            and 0 <= now-r["sampled_at"] <= 120
            and 0 <= now-r["candle_end"] <= 180
            and re.fullmatch(r"[A-Z0-9]+USDT", symbol)
            and symbol not in selected
        ):
            selected.append(symbol)
    return selected[:3]

class Market:
    def __init__(self, symbol):
        self.symbol = symbol
        self.b = {}
        self.a = {}
        self.u = None
        self.seq = None
        self.ts = 0
        self.buckets = {}
        self.ids = deque()
        self.seen = set()
        self.previous_walls = {}
        self.events = deque(maxlen=8)
        self.started = time.time()

    def book(self, message):
        d = message["data"]
        if d["s"] != self.symbol:
            raise ValueError("Wrong symbol")
        stamp = num(message["ts"])/1000
        if not -2 <= time.time()-stamp <= 5:
            raise ValueError("Delayed book or incorrect server clock")

        uid, seq = int(d["u"]), int(d["seq"])
        reset = message["type"] == "snapshot" or uid == 1
        if reset:
            self.b.clear()
            self.a.clear()
            self.previous_walls.clear()
            self.events.clear()
        else:
            if self.u is None:
                raise ValueError("Delta before snapshot")
            if uid == self.u:
                return
            if uid < self.u or seq < self.seq:
                raise ValueError("Out-of-order orderbook")
            # Bybit does not promise consecutive numeric update IDs.

        for side, target in (("b", self.b), ("a", self.a)):
            for price, quantity in d[side]:
                p, q = num(price), num(quantity)
                if p <= 0 or q < 0:
                    raise ValueError("Invalid book level")
                if q == 0:
                    target.pop(p, None)
                else:
                    target[p] = q
        if not self.b or not self.a or max(self.b) >= min(self.a):
            raise ValueError("Empty or crossed book")
        if max(len(self.b), len(self.a)) > 500:
            raise ValueError("Unexpected book size")
        self.u, self.seq, self.ts = uid, seq, stamp

    def trades(self, message):
        now = time.time()
        if not -2 <= now-num(message["ts"])/1000 <= 5:
            raise ValueError("Delayed trade stream")
        while self.ids and self.ids[0][0] < now-120:
            _, tid = self.ids.popleft()
            self.seen.discard(tid)

        for trade in message["data"]:
            if trade["s"] != self.symbol:
                raise ValueError("Wrong trade symbol")
            tid = str(trade["i"])
            if tid in self.seen:
                continue
            if len(self.ids) >= 100000:
                raise ValueError("Trade buffer limit reached")
            self.ids.append((now, tid))
            self.seen.add(tid)
            if trade.get("BT", False):
                continue
            stamp = num(trade["T"])/1000
            if not -2 <= now-stamp <= 60:
                continue
            p, q = num(trade["p"]), num(trade["v"])
            if p <= 0 or q <= 0 or trade["S"] not in ("Buy", "Sell"):
                raise ValueError("Invalid trade")
            bucket = self.buckets.setdefault(int(stamp), [0.0, 0.0, 0])
            bucket[0 if trade["S"] == "Buy" else 1] += p*q
            bucket[2] += 1
        for second in list(self.buckets):
            if second < int(now)-60:
                del self.buckets[second]

    def metrics(self, now):
        if self.u is None:
            return dict(symbol=self.symbol, ready=False, reason="Ожидание snapshot")
        bids = sorted(self.b.items(), reverse=True)
        asks = sorted(self.a.items())
        mid = (bids[0][0]+asks[0][0])/2
        nb = [(p,q) for p,q in bids if p >= mid*0.999]
        na = [(p,q) for p,q in asks if p <= mid*1.001]
        db, da = sum(p*q for p,q in nb), sum(p*q for p,q in na)
        walls = {}
        for side, near, full in (("bid", nb, self.b), ("ask", na, self.a)):
            old = self.previous_walls.get(side)
            if old and min(full) <= old["price"] <= max(full):
                remaining = full.get(old["price"], 0)*old["price"]
                if remaining < old["value"]*0.5:
                    self.events.append(dict(
                        time=now, side=side, price=old["price"],
                        before=old["value"], after=remaining,
                    ))
            if near:
                p,q = max(near, key=lambda level: level[0]*level[1])
                walls[side] = dict(price=p, value=p*q)
        self.previous_walls = walls

        buckets = [
            value for second,value in self.buckets.items()
            if now-60 <= second <= now
        ]
        buy = sum(v[0] for v in buckets)
        sell = sum(v[1] for v in buckets)
        age = now-self.ts
        warm = now-self.started >= 60
        return dict(
            symbol=self.symbol, ready=warm and 0 <= age <= 5,
            reason="Наблюдение" if warm else "Накопление 60 секунд ленты",
            book_time=self.ts, price=mid,
            spread=(asks[0][0]-bids[0][0])/mid*100,
            bid_depth=db, ask_depth=da,
            covered=bids[-1][0] <= mid*0.999 and asks[-1][0] >= mid*1.001,
            imbalance=(db-da)/(db+da)*100 if db+da else 0,
            buy60=buy, sell60=sell, delta60=buy-sell,
            trades60=sum(v[2] for v in buckets),
            flow_window=min(60, max(0, now-self.started)),
            walls=walls, events=list(self.events),
        )

def selftest():
    now = time.time()
    m = Market("TESTUSDT")
    def msg(kind, uid, b, a):
        return dict(type=kind, ts=time.time()*1000,
                    data=dict(s="TESTUSDT", u=uid, seq=uid, b=b, a=a))
    m.book(msg("snapshot", 10, [["99","2"]], [["101","3"]]))
    m.book(msg("delta", 15, [["99","0"],["98","4"]], []))
    assert 99 not in m.b and m.b[98] == 4
    m.book(msg("snapshot", 1, [["97","5"]], [["102","6"]]))
    assert 98 not in m.b and m.b == {97.0:5.0}
    t = dict(ts=now*1000, data=[
        dict(s="TESTUSDT", i="one", T=now*1000, S="Buy", p="100", v="2")
    ])
    m.trades(t)
    m.trades(t)
    assert sum(v[0] for v in m.buckets.values()) == 200
    print("SELFTEST OK: snapshot, delta, deletion, reset, trade deduplication")

def main():
    db = sqlite3.connect(ROOT/"history.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("CREATE TABLE IF NOT EXISTS samples (t REAL PRIMARY KEY, data TEXT)")
    db.execute("DELETE FROM samples WHERE t < ?", (time.time()-48*3600,))
    db.commit()

    symbols = []
    while not symbols:
        try:
            symbols = select_symbols()
            if not symbols:
                publish("waiting", message="Нет свежих кандидатов сканера")
        except Exception as exc:
            publish("waiting", message=str(exc)[:200])
        if not symbols:
            time.sleep(10)

    print("LIVE selected: "+", ".join(symbols), flush=True)
    backoff = 3
    cleanup_at = 0

    while True:
        ws = None
        publish("connecting", message=", ".join(symbols))
        markets = {s:Market(s) for s in symbols}
        try:
            ws = websocket.create_connection(URL, timeout=10)
            ws.settimeout(2)
            args = [
                topic+"."+s for s in symbols
                for topic in ("orderbook.200", "publicTrade")
            ]
            ws.send(json.dumps(dict(op="subscribe", args=args)))
            connected = time.monotonic()
            for market in markets.values():
                market.started = time.time()
            last_ping = last_receive = connected
            last_write = last_history = 0
            subscribed = False
            print("LIVE connected; waiting for snapshots", flush=True)

            while True:
                raw = None
                try:
                    raw = ws.recv()
                    if not raw:
                        raise RuntimeError("WebSocket closed")
                    last_receive = time.monotonic()
                except websocket.WebSocketTimeoutException:
                    pass

                if raw:
                    msg = json.loads(raw)
                    if msg.get("op") == "subscribe":
                        if msg.get("success") is not True:
                            raise RuntimeError("Subscription rejected: "+str(msg)[:200])
                        subscribed = True
                    topic = msg.get("topic", "")
                    if topic.startswith("orderbook."):
                        symbol = topic.rsplit(".",1)[-1]
                        markets[symbol].book(msg)
                    elif topic.startswith("publicTrade."):
                        symbol = topic.rsplit(".",1)[-1]
                        markets[symbol].trades(msg)

                mono, now = time.monotonic(), time.time()
                if mono-last_receive > 15:
                    raise RuntimeError("No WebSocket messages for 15 seconds")
                if not subscribed and mono-connected > 15:
                    raise RuntimeError("No subscription confirmation")
                if mono-connected > 15 and any(
                    not m.ts or now-m.ts > 10 for m in markets.values()
                ):
                    raise RuntimeError("Missing or stale orderbook; resynchronizing")

                if mono-last_ping >= 20:
                    ws.send(json.dumps({"op":"ping"}))
                    last_ping = mono

                if mono-last_write >= 2:
                    rows = [m.metrics(now) for m in markets.values()]
                    status = "live" if subscribed and all(r["ready"] for r in rows) \
                        else "warming"
                    data = publish(status, rows, ", ".join(symbols))
                    if mono-last_history >= 10:
                        db.execute(
                            "INSERT INTO samples VALUES (?,?)",
                            (now, json.dumps(data, ensure_ascii=False, allow_nan=False))
                        )
                        if now-cleanup_at >= 300:
                            db.execute(
                                "DELETE FROM samples WHERE t < ?", (now-48*3600,)
                            )
                            cleanup_at = now
                        db.commit()
                        last_history = mono
                    last_write = mono
                    if status == "live":
                        backoff = 3
        except Exception as exc:
            message = type(exc).__name__+": "+str(exc)[:200]
            publish("offline", message=message)
            print("LIVE reconnect: "+message, flush=True)
        finally:
            if ws:
                try:
                    ws.close()
                except Exception:
                    pass
        time.sleep(backoff)
        backoff = min(60, backoff*2)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
