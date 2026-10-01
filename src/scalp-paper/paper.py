import fcntl
import json
import math
import os
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, "/opt/trading-scanner")
from scanner import api

ROOT = Path("/var/lib/scalp-paper")
STATE = ROOT/"state.json"
FEED = Path("/var/lib/trading-live/live.json")
CONFIG = dict(
    version=1, capital=600.0, notional=100.0,
    fee=0.00055, slippage=0.0005,
    take_profit=0.60, stop_loss=0.40,
    max_hold=180, cooldown=120, max_loss=18.0,
)

def save(s):
    s["updated"] = time.time()
    tmp = STATE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(s, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)

def event(s, text):
    s["events"].append(dict(time=time.time(), text=text))
    s["events"] = s["events"][-100:]
    print(text, flush=True)

def feed():
    s = json.loads(FEED.read_text())
    now = time.time()
    if s["status"] != "live" or not 0 <= now-s["updated"] <= 6:
        raise ValueError("LIVE unavailable or stale")
    rows = {}
    for r in s["rows"]:
        if not r["ready"] or not 0 <= now-r["book_time"] <= 5:
            continue
        for key in ("price","spread","bid_depth","ask_depth",
                    "buy60","sell60","imbalance"):
            if not math.isfinite(float(r[key])):
                raise ValueError("Invalid numeric data")
        if r["price"] <= 0 or not 0 <= r["spread"] < 10:
            raise ValueError("Invalid price or spread")
        rows[r["symbol"]] = r
    return s["updated"], rows

def execution(q, side):
    # Восстанавливаем лучшие bid/ask из mid и процентного спреда.
    return q["price"]*(1+side*q["spread"]/200)*(
        1+side*CONFIG["slippage"]
    )

def close_values(p, q):
    price = execution(q, -p["side"])
    gross = p["side"]*p["quantity"]*(price-p["entry"])
    fee = p["quantity"]*price*CONFIG["fee"]
    net = gross-fee-p["entry_fee"]+p["funding"]
    return gross, fee, net

def halt(s, reason):
    s["phase"] = "halted"
    s["reason"] = reason
    event(s, "PAPER HALTED: "+reason)
    save(s)


def close_position(s, q, reason):
    p = s["position"]
    if p is None:
        return
    gross, fee, net = close_values(p, q)
    closed_at = time.time()
    record = dict(
        id=f"{p['symbol']}:{p['opened']:.9f}:{p['side']}",
        symbol=p["symbol"],
        side="LONG" if p["side"] == 1 else "SHORT",
        opened=p["opened"], closed=closed_at,
        seconds=closed_at-p["opened"],
        quantity=p["quantity"],
        entry=p["entry"], exit=execution(q, -p["side"]),
        gross=gross, entry_fee=p["entry_fee"],
        exit_fee=fee, funding=p["funding"], net=net,
        reason=reason,
        quote_time=q.get("book_time", s["market_time"]),
    )
    ledger = s.setdefault("journal_trades", [])
    if any(r["id"] == record["id"] for r in ledger):
        raise RuntimeError("Duplicate journal trade")

    s["balance"] += gross-fee
    s["fees"] += fee
    s["closed"] += 1
    s["wins"] += int(net > 0)
    s["losses"] += int(net < 0)
    ledger.append(record)
    s["position"] = None
    s["equity"] = s["balance"]
    s["peak"] = max(s["peak"], s["equity"])
    s["cooldown_until"] = closed_at+CONFIG["cooldown"]
    text = f"CLOSE {p['symbol']} {reason}; net={net:+.4f} USDT"
    s["events"].append(dict(time=closed_at, text=text))
    s["events"] = s["events"][-100:]
    save(s)
    print(text, flush=True)


def selftest():
    q = dict(price=100.0, spread=0.02)
    for side in (1,-1):
        entry = execution(q,side)
        p = dict(side=side,quantity=100/entry,entry=entry,
                 entry_fee=100*CONFIG["fee"],funding=0)
        assert close_values(p,q)[2] < 0
        favorable = dict(q,price=100+side)
        adverse = dict(q,price=100-side)
        assert close_values(p,favorable)[2] > 0
        assert close_values(p,adverse)[2] < 0
    print("SELFTEST OK: long, short, spread, fees, slippage")

def main():
    lock = (ROOT/"paper.lock").open("a")
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if STATE.exists():
        s = json.loads(STATE.read_text())
        if s["config"] != CONFIG:
            raise RuntimeError("Saved configuration differs")
        if s["phase"] == "halted":
            print("Experiment remains halted: "+s["reason"],flush=True)
            return
    else:
        s = dict(
            config=CONFIG, balance=600.0, equity=600.0, peak=600.0,
            position=None, fees=0.0, funding=0.0,
            closed=0,wins=0,losses=0,phase="waiting",reason="",
            market_time=0,cooldown_until=0,events=[],
        )

    history, confirmations = {}, {}
    last_tick = 0
    while True:
        now = time.time()
        try:
            tick, rows = feed()
        except Exception as exc:
            history.clear()
            confirmations.clear()
            if s["position"]:
                halt(s,"DATA_GAP: позиция не закрыта; последняя оценка устарела")
                return
            s["phase"], s["reason"] = "waiting", str(exc)[:160]
            save(s)
            time.sleep(2)
            continue

        if s["position"] and (
            tick-s["market_time"] > 6 or now-s["market_time"] > 6
        ):
            halt(s,"DATA_GAP: пропуск наблюдений при открытой позиции")
            return
        if tick <= last_tick:
            time.sleep(0.5)
            continue
        if last_tick and tick-last_tick > 6:
            history.clear()
            confirmations.clear()
        last_tick = tick
        s["market_time"] = tick
        s["phase"], s["reason"] = "running", ""

        p = s["position"]
        if p:
            q = rows.get(p["symbol"])
            if q is None:
                halt(s,"DATA_GAP: отсутствует свежий стакан открытой позиции")
                return

            if not p["funding_applied"] and now >= p["funding_time"]:
                amount = -p["side"]*p["quantity"]*q["price"]*p["funding_rate"]
                s["balance"] += amount
                s["funding"] += amount
                p["funding"] += amount
                p["funding_applied"] = True
                event(s,f"ESTIMATED FUNDING {amount:+.6f} USDT")

            gross, fee, net = close_values(p,q)
            s["equity"] = s["balance"]+gross-fee
            reason = None
            if s["equity"] <= CONFIG["capital"]-CONFIG["max_loss"]:
                reason = "Лимит потерь эксперимента"
            elif net <= -CONFIG["stop_loss"]:
                reason = "Стоп сделки"
            elif net >= CONFIG["take_profit"]:
                reason = "Цель сделки"
            elif now-p["opened"] >= CONFIG["max_hold"]:
                reason = "Лимит времени"
            if reason:
                close_position(s,q,reason)
                history.clear()
                confirmations.clear()

        if s["equity"] <= CONFIG["capital"]-CONFIG["max_loss"]:
            halt(s,"Достигнут лимит потерь эксперимента")
            return

        if s["position"] is None and now >= s["cooldown_until"]:
            signals = []
            for symbol in list(history):
                if symbol not in rows:
                    history.pop(symbol,None)
                    confirmations.pop(symbol,None)

            for symbol,q in rows.items():
                h = history.setdefault(symbol,deque(maxlen=40))
                h.append((tick,q["price"]))
                old = [v for v in h if 10 <= tick-v[0] <= 14]
                side = 0
                total = q["buy60"]+q["sell60"]
                if old and total >= 5000 and q["trades60"] >= 20:
                    reference = old[-1][1]
                    move = (q["price"]/reference-1)*100
                    flow = (q["buy60"]-q["sell60"])/total
                    if (
                        q["spread"] <= 0.03
                        and min(q["bid_depth"],q["ask_depth"]) >= 5000
                        and 0.03 <= abs(move) <= 0.25
                    ):
                        if flow >= 0.4 and q["imbalance"] >= 20 and move > 0:
                            side = 1
                        elif flow <= -0.4 and q["imbalance"] <= -20 and move < 0:
                            side = -1

                previous,count = confirmations.get(symbol,(0,0))
                count = count+1 if side and side == previous else int(bool(side))
                confirmations[symbol] = (side,count)
                if side and count >= 3:
                    signals.append((abs(q["buy60"]-q["sell60"]),symbol,side))

            if signals:
                _,symbol,side = max(signals)
                try:
                    # Оценка funding по ставке, известной в момент входа.
                    result,_ = api("tickers",category="linear",symbol=symbol)
                    t = result["list"][0]
                    rate = float(t["fundingRate"])
                    funding_time = int(t["nextFundingTime"])/1000
                    if not math.isfinite(rate) or funding_time <= time.time():
                        raise ValueError("Invalid funding data")
                    new_tick, latest = feed()
                    q = latest[symbol]
                    if new_tick-tick > 6:
                        raise ValueError("Entry signal expired")
                except Exception as exc:
                    confirmations.clear()
                    s["reason"] = "Вход пропущен: "+str(exc)[:140]
                else:
                    entry = execution(q,side)
                    fee = CONFIG["notional"]*CONFIG["fee"]
                    s["balance"] -= fee
                    s["fees"] += fee
                    s["market_time"] = new_tick
                    s["position"] = dict(
                        symbol=symbol,side=side,entry=entry,
                        quantity=CONFIG["notional"]/entry,
                        entry_fee=fee,opened=time.time(),
                        funding=0.0,funding_rate=rate,
                        funding_time=funding_time,funding_applied=False,
                    )
                    gross,exit_fee,_ = close_values(s["position"],q)
                    s["equity"] = s["balance"]+gross-exit_fee
                    event(s,f"OPEN {symbol} {'LONG' if side == 1 else 'SHORT'} "
                          f"nominal=100 USDT entry={entry:.8f}")
                    confirmations.clear()

        if s["position"] is None:
            s["equity"] = s["balance"]
        s["peak"] = max(s["peak"],s["equity"])
        save(s)
        time.sleep(0.5)


def write_journal_report(s):
    trades = s.get("journal_trades", [])
    positive = sum(r["net"] for r in trades if r["net"] > 0)
    negative = sum(r["net"] for r in trades if r["net"] < 0)
    total = sum(r["net"] for r in trades)
    report = dict(
        updated=time.time(),
        recorded=len(trades),
        legacy_closed=max(0, s["closed"]-len(trades)),
        net=total,
        wins=sum(r["net"] > 0 for r in trades),
        losses=sum(r["net"] < 0 for r in trades),
        average=total/len(trades) if trades else None,
        profit_factor=positive/abs(negative) if negative < 0 else None,
        rows=list(reversed(trades[-30:])),
    )
    path = ROOT/"journal-report.json"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(report, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)

_save_state_without_report = save

def save(s):
    _save_state_without_report(s)
    try:
        write_journal_report(s)
    except Exception as exc:
        print("JOURNAL REPORT ERROR: "+str(exc), flush=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
