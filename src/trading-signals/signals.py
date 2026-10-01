import json
import math
import os
import statistics
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path("/var/lib/trading-signals")
FEED = Path("/var/lib/trading-live/live.json")
STATE = ROOT/"signals.json"

# Начальные экспериментальные пороги, не результат оптимизации.
NOTIONAL = 100.0
MIN_DEPTH = max(5000.0, NOTIONAL*50)
MAX_SPREAD = 0.025
MIN_FLOW = 5000.0

def publish(status, rows, message=""):
    data = dict(
        version=1, updated=time.time(), status=status,
        message=message, notional=NOTIONAL, rows=rows,
    )
    temporary = STATE.with_suffix(".tmp")
    with temporary.open("w") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, STATE)

def inspect(symbol, history):
    last = history[-1]
    q = last["q"]
    window = last["t"]-history[0]["t"]
    spreads = [x["q"]["spread"] for x in history]
    imbalances = [x["q"]["imbalance"] for x in history]
    bid_min = min(x["q"]["bid_depth"] for x in history)
    ask_min = min(x["q"]["ask_depth"] for x in history)
    median_imbalance = statistics.median(imbalances)
    total = q["buy60"]+q["sell60"]
    flow = (q["buy60"]-q["sell60"])/total if total else 0
    side = 1 if median_imbalance > 0 else -1 if median_imbalance < 0 else 0

    reference = [
        x for x in history if 10 <= last["t"]-x["t"] <= 14
    ]
    move10 = (
        (q["price"]/reference[-1]["q"]["price"]-1)*100
        if reference else None
    )
    move30 = (q["price"]/history[0]["q"]["price"]-1)*100
    stability = (
        sum(side*x >= 20 for x in imbalances)/len(imbalances)
        if side else 0
    )

    reasons = []
    if window < 30:
        reasons.append("накопление 30 секунд наблюдений")
    if max(spreads) > MAX_SPREAD:
        reasons.append("спред за окно превышал 0.025%")
    if min(bid_min, ask_min) < MIN_DEPTH:
        reasons.append("глубина одной стороны опускалась ниже 5000 USDT")
    if stability < 0.8:
        reasons.append("дисбаланс ≥20% не удерживался в 80% снимков")
    if q["flow_window"] < 55:
        reasons.append("не накоплено достаточное окно ленты")
    if total < MIN_FLOW or q["trades60"] < 20:
        reasons.append("недостаточная активность исполненных сделок")
    if side*flow < 0.25:
        reasons.append("лента не подтверждает направление стакана")
    if move10 is None or not 0.03 <= side*move10 <= 0.20:
        reasons.append("движение за 10 секунд вне условий подтверждения")
    if side*move30 <= 0:
        reasons.append("движение за окно не подтверждает направление")

    # Не разрешаем использовать старую устойчивость после разворота.
    if side*q["imbalance"] < 20:
        reasons.append("текущий дисбаланс перестал подтверждать направление")

    walls = {}
    for name, wall in (q.get("walls") or {}).items():
        observed_since = last["t"]
        for item in reversed(history):
            previous = (item["q"].get("walls") or {}).get(name)
            if not previous or previous["price"] != wall["price"]:
                break
            observed_since = item["t"]
        walls[name] = dict(
            price=wall["price"], value=wall["value"],
            observed_seconds=last["t"]-observed_since,
        )

    return dict(
        symbol=symbol, book_time=q["book_time"],
        status="WATCH_LONG" if not reasons and side == 1 else
               "WATCH_SHORT" if not reasons and side == -1 else
               "WARMING" if window < 30 else "FILTERED",
        reasons=reasons,
        window=window, samples=len(history), price=q["price"],
        spread=q["spread"], spread_max=max(spreads),
        spread_median=statistics.median(spreads),
        bid_depth=q["bid_depth"], ask_depth=q["ask_depth"],
        bid_min=bid_min, ask_min=ask_min,
        depth_multiple=min(bid_min, ask_min)/NOTIONAL,
        imbalance=q["imbalance"],
        imbalance_median=median_imbalance,
        stability=stability*100,
        buy=q["buy60"], sell=q["sell60"],
        flow=flow*100, trades=q["trades60"],
        flow_window=q["flow_window"],
        move10=move10, move30=move30,
        covered=all(x["q"].get("covered", False) for x in history),
        walls=walls,
    )

def selftest():
    def series(side):
        rows = []
        for i in range(17):
            q = dict(
                price=100*(1+side*i*0.0001),
                spread=0.01, bid_depth=20000, ask_depth=15000,
                imbalance=side*30, buy60=9000 if side == 1 else 1000,
                sell60=1000 if side == 1 else 9000,
                flow_window=60, trades60=50,
                book_time=1000+i*2, covered=True, walls={},
            )
            rows.append(dict(t=1000+i*2, q=q))
        return rows

    assert inspect("TEST", series(1))["status"] == "WATCH_LONG"
    assert inspect("TEST", series(-1))["status"] == "WATCH_SHORT"
    h = series(1)
    h[3]["q"]["ask_depth"] = 1000
    assert inspect("TEST", h)["status"] == "FILTERED"
    h = series(1)
    h[2]["q"]["spread"] = 0.1
    assert inspect("TEST", h)["status"] == "FILTERED"
    h = series(1)
    h[-1]["q"]["imbalance"] = -30
    assert inspect("TEST", h)["status"] == "FILTERED"
    assert inspect("TEST", series(1)[:5])["status"] == "WARMING"
    print("SIGNALS TEST OK: long, short, depth, spread, reversal, warmup")

def main():
    histories = {}
    last_update = 0
    while True:
        try:
            source = json.loads(FEED.read_text())
            now = time.time()
            updated = float(source["updated"])
            if source["status"] != "live" or not 0 <= now-updated <= 6:
                raise ValueError("LIVE недоступен или устарел")
            if updated <= last_update:
                if updated < last_update:
                    raise ValueError("Время LIVE пошло назад")
                time.sleep(0.5)
                continue
            if last_update and updated-last_update > 6:
                histories.clear()
            last_update = updated
            valid = set()
            results = []

            for q in source["rows"]:
                symbol = q["symbol"]
                if not q["ready"] or not 0 <= now-q["book_time"] <= 5:
                    histories.pop(symbol, None)
                    continue
                for key in (
                    "price", "spread", "bid_depth", "ask_depth",
                    "imbalance", "buy60", "sell60",
                    "trades60", "flow_window", "book_time",
                ):
                    if not math.isfinite(float(q[key])):
                        raise ValueError("Некорректное число: "+symbol)
                if q["price"] <= 0 or any(q[k] < 0 for k in (
                    "spread", "bid_depth", "ask_depth", "buy60", "sell60",
                    "trades60", "flow_window",
                )) or abs(q["imbalance"]) > 100:
                    raise ValueError("Некорректные значения: "+symbol)

                valid.add(symbol)
                h = histories.setdefault(symbol, deque(maxlen=64))
                if h and q["book_time"] < h[-1]["q"]["book_time"]:
                    h.clear()
                if not h or q["book_time"] > h[-1]["q"]["book_time"]:
                    h.append(dict(t=q["book_time"], q=q))
                    while len(h) > 1 and h[-1]["t"]-h[0]["t"] > 34:
                        h.popleft()
                results.append(inspect(symbol, h))

            for symbol in list(histories):
                if symbol not in valid:
                    histories.pop(symbol)
            publish("ok" if results else "waiting", results)
        except Exception as exc:
            histories.clear()
            last_update = 0
            publish("waiting", [], str(exc)[:180])
        time.sleep(0.5)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
