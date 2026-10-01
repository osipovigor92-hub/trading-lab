import json
import math
import os
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

DEST = Path("/var/lib/trading-scanner/market.json")

# Первичные правила отбора, а не оптимизированная стратегия.
MAX_PAIRS = 30
MIN_TURNOVER = 20_000_000
MAX_SPREAD_PCT = 0.05
MAX_FUNDING_DAY_PCT = 0.10
EXCLUDED_TYPES = {"commodity", "stock", "forex", "ETF", "xstocks", "mstocks"}
EXCLUDED_BASES = {"USDC", "USDE", "USDD", "DAI", "TUSD", "FDUSD", "PAXG", "XAUT"}

def number(value):
    n = float(value)
    if not math.isfinite(n):
        raise ValueError("Non-finite number")
    return n

def api(endpoint, **params):
    time.sleep(0.25)
    url = "https://api.bybit.com/v5/market/" + endpoint
    with urlopen(url + "?" + urlencode(params), timeout=12) as r:
        data = json.load(r)
    if data.get("retCode") != 0:
        raise RuntimeError("Bybit: " + str(data.get("retMsg")))
    stamp = number(data["time"]) / 1000
    if abs(time.time() - stamp) > 60:
        raise RuntimeError("Stale API response or incorrect clock")
    return data["result"], stamp

def save(data):
    temp = DEST.with_suffix(".tmp")
    with temp.open("w") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, DEST)

def grid_options(low, high, cost):
    # Минимальный процентный шаг: относительно верхней границы.
    return [
        dict(
            grids=n,
            step=(high-low)/n/high*100,
            passes=(high-low)/n/high*100 >= 3*cost,
        )
        for n in (8, 12, 16, 22, 30, 40)
    ]

def efficiency(closes):
    path = sum(abs(b-a) for a, b in zip(closes, closes[1:]))
    return abs(closes[-1]-closes[0]) / path if path else 1.0

def candles(symbol):
    result, stamp = api(
        "kline", category="linear", symbol=symbol, interval="60", limit=750
    )
    bars = []
    for row in result["list"]:
        start = int(row[0]) / 1000
        if start + 3600 > stamp:
            continue
        o, h, l, c = map(number, row[1:5])
        if not (0 < l <= min(o, c) <= max(o, c) <= h):
            raise ValueError("Invalid OHLC")
        bars.append((start, o, h, l, c))
    bars.sort()
    bars = bars[-720:]
    if len(bars) != 720:
        raise ValueError("Need 720 closed hourly candles")
    if any(b[0]-a[0] != 3600 for a, b in zip(bars, bars[1:])):
        raise ValueError("Missing or duplicate candles")
    lag = stamp - (bars[-1][0] + 3600)
    if not 0 <= lag < 3600:
        raise ValueError("Stale candles")
    return bars

def analyze(ticker, instrument):
    symbol = ticker["symbol"]
    bid, ask = number(ticker["bid1Price"]), number(ticker["ask1Price"])
    if not 0 < bid <= ask:
        raise ValueError("Invalid bid/ask")
    spread = (ask-bid) / ((ask+bid)/2) * 100
    interval = number(instrument["fundingInterval"])
    if interval <= 0:
        raise ValueError("Invalid funding interval")
    rate = number(ticker["fundingRate"])
    funding_day = abs(rate) * 1440 / interval * 100

    bars = candles(symbol)
    closes = [b[4] for b in bars]
    week = bars[-168:]
    low7, high7 = min(b[3] for b in week), max(b[2] for b in week)
    low30, high30 = min(b[3] for b in bars), max(b[2] for b in bars)
    range7 = (high7/low7-1) * 100
    range30 = (high30/low30-1) * 100
    move24 = (closes[-1]/closes[-25]-1) * 100
    move7 = (closes[-1]/closes[-169]-1) * 100
    er24 = efficiency(closes[-25:])
    er7 = efficiency(closes[-169:])

    # Средний истинный диапазон последних 24 закрытых часов.
    trs = [
        max(bars[i][2]-bars[i][3],
            abs(bars[i][2]-bars[i-1][4]),
            abs(bars[i][3]-bars[i-1][4]))
        for i in range(len(bars)-24, len(bars))
    ]
    atr = sum(trs)/len(trs)/closes[-1]*100
    shock = max(
        (b[2]-b[3])/bars[i-1][4]*100
        for i, b in enumerate(bars) if i >= len(bars)-168
    )

    # Только модель издержек: две taker-комиссии по 0.055%,
    # суммарное проскальзывание 0.10% и текущий спред.
    # Funding сюда не включён; он проверяется отдельно.
    cycle_cost = 2*0.055 + 0.10 + spread
    step_test = (high7-low7)/22/closes[-1]*100
    options = grid_options(low7, high7, cycle_cost)

    reasons = []
    if spread > MAX_SPREAD_PCT:
        reasons.append("широкий спред")
    if funding_day > MAX_FUNDING_DAY_PCT:
        reasons.append("высокий funding")
    if er24 > 0.45 or er7 > 0.25:
        reasons.append("направленное движение")
    if abs(move24) > 5 or abs(move7) > 10:
        reasons.append("сильное изменение цены")
    if shock > 5:
        reasons.append("часовая свеча >5% за неделю")
    if range30 > 40:
        reasons.append("слишком широкий диапазон 30 дней")
    if not 0.15 <= atr <= 1.5:
        reasons.append("неподходящая часовая волатильность")
    if not any(o["passes"] for o in options):
        reasons.append("ни один вариант сетки не прошёл проверку издержек")

    # Объяснимый сравнительный балл, НЕ вероятность заработка.
    score = round(
        45*(1-er7)
        + 25*(1-er24)
        + 15*max(0, 1-spread/MAX_SPREAD_PCT)
        + 15*max(0, 1-funding_day/MAX_FUNDING_DAY_PCT), 1
    )
    return dict(
        symbol=symbol, candidate=not reasons, score=score,
        price=number(ticker["markPrice"]),
        turnover=number(ticker["turnover24h"]),
        spread=spread, atr=atr, range7=range7, range30=range30,
        move24=move24, move7=move7, er7=er7, shock=shock,
        funding_day=funding_day, step_test=step_test,
        cycle_cost=cycle_cost, grid_options=options,
        reference_low=low7, reference_high=high7,
        reason="; ".join(reasons) if reasons else "Фильтры пройдены; требуется PAPER-проверка вариантов",
    )

def scan():
    started = time.time()
    instruments = {}
    cursor = ""
    for _ in range(20):
        params = dict(category="linear", status="Trading", limit=1000)
        if cursor:
            params["cursor"] = cursor
        result, _ = api("instruments-info", **params)
        for item in result["list"]:
            if (
                item.get("status") == "Trading"
                and item.get("contractType") == "LinearPerpetual"
                and item.get("quoteCoin") == "USDT"
                and item.get("settleCoin") == "USDT"
                and not item.get("isPreListing", False)
                and item.get("symbolType", "") not in EXCLUDED_TYPES
                and not item.get("underlyingTicker")
                and item.get("baseCoin") not in EXCLUDED_BASES
                and number(item["launchTime"])/1000 <= started-30*86400
                and not number(item.get("deliveryTime") or 0)
            ):
                instruments[item["symbol"]] = item
        next_cursor = result.get("nextPageCursor", "")
        if not next_cursor:
            break
        if next_cursor == cursor:
            raise RuntimeError("Repeated instruments cursor")
        cursor = next_cursor
    else:
        raise RuntimeError("Incomplete instruments pagination")

    result, quote_time = api("tickers", category="linear")
    eligible = []
    rejected = Counter()
    for ticker in result["list"]:
        if ticker["symbol"] not in instruments:
            continue
        try:
            turnover = number(ticker["turnover24h"])
            bid, ask = number(ticker["bid1Price"]), number(ticker["ask1Price"])
            if not 0 < bid <= ask:
                raise ValueError("Invalid prices")
            if turnover < MIN_TURNOVER:
                rejected["Оборот менее 20 млн USDT"] += 1
            elif (ask-bid)/((ask+bid)/2)*100 > MAX_SPREAD_PCT:
                rejected["Спред более 0.05%"] += 1
            else:
                eligible.append(ticker)
        except (ValueError, KeyError, TypeError):
            rejected["Неполные котировки"] += 1

    eligible.sort(key=lambda t: number(t["turnover24h"]), reverse=True)
    chosen = eligible[:MAX_PAIRS]
    rows, errors = [], []
    for ticker in chosen:
        symbol = ticker["symbol"]
        try:
            rows.append(analyze(ticker, instruments[symbol]))
        except Exception as exc:
            errors.append(symbol + ": " + str(exc)[:160])

    rows.sort(key=lambda r: (not r["candidate"], -r["score"]))
    status = "partial" if errors else "ok"
    if chosen and not rows:
        status = "error"
    output = dict(
        version=2, status=status, started=started, finished=time.time(),
        quote_time=quote_time, universe=len(instruments),
        eligible=len(eligible), selected=len(chosen),
        analyzed=len(rows), candidates=sum(r["candidate"] for r in rows),
        preliminary_rejections=dict(rejected), rows=rows, errors=errors,
    )
    save(output)
    print(
        f"SCAN {status}: contracts={len(instruments)}, "
        f"analyzed={len(rows)}, candidates={output['candidates']}, "
        f"errors={len(errors)}", flush=True
    )

if __name__ == "__main__":
    try:
        scan()
    except Exception as exc:
        save(dict(
            version=1, status="error", finished=time.time(),
            rows=[], errors=[type(exc).__name__ + ": " + str(exc)[:200]]
        ))
        raise
