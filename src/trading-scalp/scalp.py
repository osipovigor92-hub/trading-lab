import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/trading-scanner")
from scanner import api, number

SOURCE = Path("/var/lib/trading-scanner/market.json")
DEST = Path("/var/lib/trading-scalp/scalp.json")
NOTIONAL = 100.0
SAMPLES = 5
MAX_BOOKS = 10

def save(data):
    tmp = DEST.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DEST)

def minute_stats(symbol):
    result, stamp = api(
        "kline", category="linear", symbol=symbol, interval="1", limit=65
    )
    bars = []
    for row in result["list"]:
        start = int(row[0])/1000
        if start+60 > stamp:
            continue
        o, h, l, c = map(number, row[1:5])
        if not 0 < l <= min(o,c) <= max(o,c) <= h:
            raise ValueError("Invalid minute OHLC")
        bars.append((start,o,h,l,c))
    bars.sort()
    bars = bars[-60:]
    if len(bars) != 60:
        raise ValueError("Need 60 closed minute candles")
    if any(b[0]-a[0] != 60 for a,b in zip(bars,bars[1:])):
        raise ValueError("Minute candle gap")
    if not 0 <= stamp-(bars[-1][0]+60) < 60:
        raise ValueError("Stale minute candles")

    trs = [
        max(
            bars[i][2]-bars[i][3],
            abs(bars[i][2]-bars[i-1][4]),
            abs(bars[i][3]-bars[i-1][4]),
        )
        for i in range(len(bars)-14,len(bars))
    ]
    recent = bars[-15:]
    return dict(
        symbol=symbol,
        candle_end=bars[-1][0]+60,
        atr=sum(trs)/14/bars[-1][4]*100,
        range15=(max(b[2] for b in recent)/min(b[3] for b in recent)-1)*100,
        move15=(bars[-1][4]/bars[-16][4]-1)*100,
    )

def impact(levels, quantity, buying):
    left, value = quantity, 0.0
    for price,size in levels:
        take = min(left,size)
        value += take*price
        left -= take
        if left <= quantity*1e-10:
            vwap = value/quantity
            best = levels[0][0]
            return max(0, (vwap/best-1 if buying else 1-vwap/best)*100)
    return None

def snapshot(symbol):
    result, stamp = api(
        "orderbook", category="linear", symbol=symbol, limit=200
    )
    if result["s"] != symbol:
        raise ValueError("Wrong orderbook symbol")
    ts = number(result["ts"])/1000
    if not -1 <= stamp-ts <= 5:
        raise ValueError("Stale orderbook")

    bids = [(number(p),number(q)) for p,q in result["b"]]
    asks = [(number(p),number(q)) for p,q in result["a"]]
    if not bids or not asks:
        raise ValueError("Empty orderbook")
    if any(p <= 0 or q <= 0 for p,q in bids+asks):
        raise ValueError("Invalid orderbook levels")
    if any(a[0] <= b[0] for a,b in zip(bids,bids[1:])):
        raise ValueError("Unsorted bids")
    if any(a[0] >= b[0] for a,b in zip(asks,asks[1:])):
        raise ValueError("Unsorted asks")
    if bids[0][0] >= asks[0][0]:
        raise ValueError("Crossed orderbook")

    mid = (bids[0][0]+asks[0][0])/2
    near_b = [(p,q) for p,q in bids if p >= mid*0.999]
    near_a = [(p,q) for p,q in asks if p <= mid*1.001]
    depth_b = sum(p*q for p,q in near_b)
    depth_a = sum(p*q for p,q in near_a)

    def wall(levels):
        if not levels:
            return None
        p,q = max(levels,key=lambda x:x[0]*x[1])
        return dict(price=p,notional=p*q)

    return dict(
        time=ts, seq=int(result["seq"]), mid=mid,
        spread=(asks[0][0]-bids[0][0])/mid*100,
        bid_depth=depth_b, ask_depth=depth_a,
        bid_wall=wall(near_b), ask_wall=wall(near_a),
        imbalance=(depth_b-depth_a)/(depth_b+depth_a)
            if depth_b+depth_a else 0,
        buy_impact=impact(asks,NOTIONAL/mid,True),
        sell_impact=impact(bids,NOTIONAL/mid,False),
        covered=bids[-1][0] <= mid*0.999 and asks[-1][0] >= mid*1.001,
    )

def summarize(stats, books):
    reasons = []
    if len(books) != SAMPLES:
        raise ValueError("Not enough distinct orderbook snapshots")
    last = books[-1]
    spread = max(b["spread"] for b in books)
    depth_b = min(b["bid_depth"] for b in books)
    depth_a = min(b["ask_depth"] for b in books)
    impacts = [
        b[key] for b in books for key in ("buy_impact","sell_impact")
    ]
    worst = max(impacts) if all(x is not None for x in impacts) else None

    if not 0.08 <= stats["atr"] <= 0.8:
        reasons.append("минутная волатильность вне 0.08–0.8%")
    if not 0.4 <= stats["range15"] <= 5:
        reasons.append("диапазон 15 минут вне 0.4–5%")
    if abs(stats["move15"]) > 3:
        reasons.append("движение за 15 минут больше 3%")
    if spread > 0.03:
        reasons.append("спред превышал 0.03%")
    if min(depth_b,depth_a) < 5000:
        reasons.append("видимая глубина одной стороны менее 5000 USDT")
    if worst is None or worst > 0.05:
        reasons.append("недостаточная глубина либо impact больше 0.05%")
    if time.time()-stats["candle_end"] > 180:
        reasons.append("минутный анализ устарел")
    if time.time()-last["time"] > 60:
        reasons.append("стакан устарел")

    return dict(
        **stats, candidate=not reasons,
        reason="; ".join(reasons) if reasons else "Первичные фильтры пройдены",
        sampled_at=last["time"],
        window=last["time"]-books[0]["time"],
        samples=len(books), price=last["mid"],
        max_spread=spread,
        min_bid=depth_b,min_ask=depth_a,
        last_bid=last["bid_depth"],last_ask=last["ask_depth"],
        imbalance=last["imbalance"],
        bid_wall=last["bid_wall"],ask_wall=last["ask_wall"],
        impact=worst, covered=all(b["covered"] for b in books),
    )

def run():
    source = json.loads(SOURCE.read_text())
    age = time.time()-source.get("quote_time",0)
    if source.get("status") not in ("ok","partial") or not 0 <= age <= 1800:
        raise RuntimeError("Общий сканер не предоставил свежий список пар")
    universe = source.get("rows",[])
    if not universe:
        raise RuntimeError("Список пар пуст")

    stats, errors = [], []
    for row in universe:
        symbol = row["symbol"]
        try:
            stats.append(minute_stats(symbol))
        except Exception as exc:
            errors.append(symbol+": "+str(exc)[:140])

    # Отбираем по текущему минутному ATR, не по grid-статусу.
    stats.sort(key=lambda r:r["atr"],reverse=True)
    chosen = [r for r in stats if 0.08 <= r["atr"] <= 0.8][:MAX_BOOKS]
    books = {r["symbol"]:[] for r in chosen}
    for sample in range(SAMPLES):
        if sample:
            time.sleep(2)
        for row in chosen:
            symbol = row["symbol"]
            try:
                b = snapshot(symbol)
                previous = books[symbol]
                if previous and (
                    b["time"] <= previous[-1]["time"] or
                    b["seq"] <= previous[-1]["seq"]
                ):
                    raise ValueError("Repeated or out-of-order snapshot")
                previous.append(b)
            except Exception as exc:
                errors.append(symbol+": "+str(exc)[:140])

    rows = []
    for row in chosen:
        try:
            rows.append(summarize(row,books[row["symbol"]]))
        except Exception as exc:
            errors.append(row["symbol"]+": "+str(exc)[:140])

    rows.sort(key=lambda r:(
        not r["candidate"], -min(r["min_bid"],r["min_ask"])
    ))
    data = dict(
        status="partial" if errors else "ok",
        finished=time.time(), source_time=source["quote_time"],
        universe=len(universe), minute_checked=len(stats),
        selected=len(chosen), rows=rows, errors=errors,
        candidates=sum(r["candidate"] for r in rows),
        notional=NOTIONAL,
    )
    if chosen and not rows:
        data["status"] = "error"
    save(data)
    print(
        f"SCALP {data['status']}: minutes={len(stats)}, "
        f"books={len(rows)}, candidates={data['candidates']}, "
        f"errors={len(errors)}",flush=True
    )

if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        save(dict(
            status="error",finished=time.time(),rows=[],
            errors=[type(exc).__name__+": "+str(exc)[:200]]
        ))
        raise
