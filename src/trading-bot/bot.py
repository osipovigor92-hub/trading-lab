import fcntl
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

CONFIG = {
    "version": 1,
    "mode": "PAPER",
    "symbol": "LINKUSDT",
    "capital": 600.0,
    "lower": 12.793,
    "upper": 16.552,
    "grids": 22,
    "quantity": 6.2,
    "max_position": 31.0,
    "maker_fee": 0.0002,
    "taker_fee": 0.00055,
    "exit_slippage": 0.0005,
    "max_loss": 18.0,
    "trailing": 0.05,
    "poll_seconds": 15,
}
ROOT = Path("/var/lib/trading-bot")
STATE = ROOT / "state.json"


def log(message):
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
          "UTC", message, flush=True)


def trade(s, quantity, price, fee_rate):
    """One-way perpetual accounting; quantity > 0 means buy."""
    old = s["position"]
    new = round(old + quantity, 8)
    average = s["average"]

    if old * quantity < 0:
        closed = min(abs(old), abs(quantity))
        realized = closed * (price - average) * (1 if old > 0 else -1)
        s["balance"] += realized
        s["realized"] += realized

    if old == 0:
        s["average"] = price
    elif old * quantity > 0:
        s["average"] = (
            abs(old) * average + abs(quantity) * price
        ) / abs(new)
    elif new == 0:
        s["average"] = 0.0
    elif old * new < 0:
        s["average"] = price

    fee = abs(quantity) * price * fee_rate
    s["balance"] -= fee
    s["fees"] += fee
    s["position"] = new


def selftest():
    s = dict(balance=1000.0, position=0.0, average=0.0,
             realized=0.0, fees=0.0)
    trade(s, 2, 10, 0)
    trade(s, -1, 12, 0)
    assert s["position"] == 1 and s["balance"] == 1002
    trade(s, -2, 9, 0)
    assert s["position"] == -1 and s["average"] == 9
    trade(s, 1, 8, 0)
    assert s["position"] == 0 and s["balance"] == 1002
    trade(s, 1, 10, 0.001)
    trade(s, -1, 10, 0.001)
    assert abs(s["balance"] - 1001.98) < 1e-8
    print("SELFTEST OK: long, short, reversal, fees")


def snapshot():
    params = urlencode({
        "category": "linear",
        "symbol": CONFIG["symbol"],
    })
    url = "https://api.bybit.com/v5/market/tickers?" + params
    with urlopen(url, timeout=10) as response:
        data = json.load(response)
    if data.get("retCode") != 0:
        raise RuntimeError(str(data.get("retMsg", data)))

    timestamp = int(data["time"]) / 1000
    if abs(time.time() - timestamp) > 30:
        raise RuntimeError("Stale response or incorrect server clock")

    row = data["result"]["list"][0]
    result = {
        "time": timestamp,
        "bid": float(row["bid1Price"]),
        "ask": float(row["ask1Price"]),
        "mark": float(row["markPrice"]),
        "rate": float(row["fundingRate"]),
        "next_funding": int(row["nextFundingTime"]) / 1000,
    }
    if not all(math.isfinite(x) for x in result.values()):
        raise RuntimeError("Non-finite market data")
    if not (0 < result["bid"] <= result["ask"] and result["mark"] > 0):
        raise RuntimeError("Invalid market prices")
    if result["next_funding"] <= result["time"]:
        raise RuntimeError("Funding schedule not refreshed yet")
    return result


def save(s):
    temporary = STATE.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(s, stream, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, STATE)


def liquidation_equity(s, quote):
    quantity = s["position"]
    if quantity == 0:
        return s["balance"]
    price = (
        quote["bid"] * (1 - CONFIG["exit_slippage"])
        if quantity > 0 else
        quote["ask"] * (1 + CONFIG["exit_slippage"])
    )
    return (
        s["balance"]
        + quantity * (price - s["average"])
        - abs(quantity) * price * CONFIG["taker_fee"]
    )


def finish(s, quote, reason):
    quantity = s["position"]
    if quantity:
        price = (
            quote["bid"] * (1 - CONFIG["exit_slippage"])
            if quantity > 0 else
            quote["ask"] * (1 + CONFIG["exit_slippage"])
        )
        trade(s, -quantity, price, CONFIG["taker_fee"])
    s["orders"] = []
    s["halted"] = True
    s["reason"] = reason
    s["equity"] = s["balance"]
    save(s)
    log(f"PAPER STOP: {reason}; balance={s['balance']:.4f}")


def main():
    lock = (ROOT / "bot.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    s = json.loads(STATE.read_text()) if STATE.exists() else None
    if s and s["config"] != CONFIG:
        raise RuntimeError("Configuration differs from saved experiment")
    if s and s["halted"]:
        log("Experiment remains stopped: " + s["reason"])
        return

    last_report = 0
    log("PAPER ONLY. No exchange orders. No API keys.")

    while True:
        if s and time.time() - s["last_seen"] > 60:
            s["halted"] = True
            s["reason"] = "DATA_GAP: results incomplete; position not closed"
            save(s)
            log(s["reason"])
            return

        try:
            quote = snapshot()
        except Exception as exc:
            log(f"DATA ERROR: {type(exc).__name__}: {exc}")
            time.sleep(10)
            continue

        now = quote["time"]
        if s and now - s["last_seen"] > 60:
            s["halted"] = True
            s["reason"] = "DATA_GAP: results incomplete; position not closed"
            save(s)
            log(s["reason"])
            return
        if s and now <= s["last_seen"]:
            time.sleep(CONFIG["poll_seconds"])
            continue

        if s is None:
            if not CONFIG["lower"] < quote["mark"] < CONFIG["upper"]:
                raise RuntimeError("Price outside experimental grid range")
            step = (CONFIG["upper"] - CONFIG["lower"]) / CONFIG["grids"]
            levels = [
                CONFIG["lower"] + i * step
                for i in range(CONFIG["grids"] + 1)
            ]
            pivot = min(
                range(len(levels)),
                key=lambda i: abs(levels[i] - quote["mark"])
            )
            orders = []
            for i, price in enumerate(levels):
                if i == pivot:
                    continue
                orders.append({"level": i, "side": 1 if i < pivot else -1})
            s = {
                "config": CONFIG,
                "balance": CONFIG["capital"],
                "position": 0.0,
                "average": 0.0,
                "realized": 0.0,
                "fees": 0.0,
                "funding_estimate": 0.0,
                "peak": CONFIG["capital"],
                "equity": CONFIG["capital"],
                "levels": levels,
                "orders": orders,
                "fills": 0,
                "events": [],
                "halted": False,
                "reason": "",
                "last_seen": now,
                "funding_time": quote["next_funding"],
                "funding_rate": quote["rate"],
            }
            save(s)
            log(f"Initialized {len(orders)} virtual orders")
            time.sleep(CONFIG["poll_seconds"])
            continue

        # Approximation: last observed funding rate, current mark price.
        # This is explicitly not exact settlement accounting.
        if now >= s["funding_time"]:
            funding = -s["position"] * quote["mark"] * s["funding_rate"]
            s["balance"] += funding
            s["funding_estimate"] += funding
            log(f"ESTIMATED FUNDING: {funding:+.6f}")

        s["funding_time"] = quote["next_funding"]
        s["funding_rate"] = quote["rate"]
        s["last_seen"] = now

        equity = liquidation_equity(s, quote)
        s["peak"] = max(s["peak"], equity)
        reason = None
        if equity <= CONFIG["capital"] - CONFIG["max_loss"]:
            reason = "Maximum loss"
        elif equity <= s["peak"] * (1 - CONFIG["trailing"]):
            reason = "Trailing equity stop"
        elif not CONFIG["lower"] <= quote["mark"] <= CONFIG["upper"]:
            reason = "Price left grid range"
        if reason:
            finish(s, quote, reason)
            return

        # Large spread: do not simulate new grid executions.
        if quote["ask"] / quote["bid"] - 1 <= 0.002:
            buys = sorted(
                [o for o in s["orders"] if o["side"] == 1],
                key=lambda o: -o["level"],
            )
            sells = sorted(
                [o for o in s["orders"] if o["side"] == -1],
                key=lambda o: o["level"],
            )
            for order in buys + sells:
                price = s["levels"][order["level"]]
                side = order["side"]
                touched = (
                    quote["ask"] < price if side == 1
                    else quote["bid"] > price
                )
                if not touched:
                    continue
                quantity = side * CONFIG["quantity"]
                new_position = s["position"] + quantity
                if abs(new_position) > CONFIG["max_position"] + 1e-8:
                    continue

                trade(s, quantity, price, CONFIG["maker_fee"])
                s["fills"] += 1
                event = {
                    "time": now, "side": "BUY" if side == 1 else "SELL",
                    "quantity": abs(quantity), "price": price,
                    "position": s["position"],
                }
                s["events"].append(event)
                s["events"] = s["events"][-1000:]
                log("PAPER FILL " + json.dumps(event))
                order["level"] += side
                order["side"] = -side

        s["equity"] = liquidation_equity(s, quote)
        s["peak"] = max(s["peak"], s["equity"])
        if s["equity"] <= CONFIG["capital"] - CONFIG["max_loss"]:
            finish(s, quote, "Maximum loss after fill")
            return
        if s["equity"] <= s["peak"] * (1 - CONFIG["trailing"]):
            finish(s, quote, "Trailing stop after fill")
            return

        save(s)
        if now - last_report >= 60:
            log(
                f"PAPER mark={quote['mark']:.4f} "
                f"equity={s['equity']:.4f} "
                f"pnl={s['equity']-CONFIG['capital']:+.4f} "
                f"position={s['position']:.2f} "
                f"fills={s['fills']} fees={s['fees']:.4f} "
                f"funding_est={s['funding_estimate']:+.4f}"
            )
            last_report = now
        time.sleep(CONFIG["poll_seconds"])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
