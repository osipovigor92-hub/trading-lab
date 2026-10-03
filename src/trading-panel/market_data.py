"""Read-only Bybit screener. Bounded background cache; no trading or disk writes."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SYMBOL = re.compile(r"^[A-Z0-9]{2,24}USDT$")
INTERVALS = {"1": 60, "5": 300, "15": 900, "60": 3600}


def number(value):
    if isinstance(value, bool):
        raise ValueError("Invalid number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite number")
    return result


def public_api(endpoint, **params):
    if endpoint not in ("tickers", "kline", "orderbook"):
        raise ValueError("Unsupported public endpoint")
    query = urlencode(dict(category="linear", **params))
    request = Request("https://api.bybit.com/v5/market/" + endpoint + "?" + query,
                      headers={"User-Agent": "trading-lab-screener/1"})
    with urlopen(request, timeout=6) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Public response too large")
    data = json.loads(body)
    if data.get("retCode") != 0:
        raise ValueError("Bybit: " + str(data.get("retMsg", "API error"))[:120])
    stamp = number(data["time"]) / 1000
    if not -2 <= time.time() - stamp <= 15:
        raise ValueError("Exchange timestamp is stale or clock differs")
    return data["result"], stamp


def optional(value):
    try:
        return number(value)
    except (ValueError, TypeError):
        return None


def ticker_rows(result, stamp):
    rows, rejected = [], 0
    seen = set()
    for row in result["list"]:
        symbol = row.get("symbol", "")
        # Expiry futures and pre-listing contracts are not part of this universe.
        if not SYMBOL.fullmatch(symbol) or row.get("deliveryTime") not in (None, "", "0", 0):
            continue
        if row.get("curPreListingPhase") not in (None, "", "Finished"):
            continue
        try:
            price, high, low, bid, ask, turnover = map(number, (
                row["lastPrice"], row["highPrice24h"], row["lowPrice24h"],
                row["bid1Price"], row["ask1Price"], row["turnover24h"]))
            if not (0 < low <= price <= high and 0 < bid < ask and turnover > 0):
                raise ValueError("Invalid ticker")
            if symbol in seen:
                raise ValueError("Duplicate ticker")
            seen.add(symbol)
            rows.append(dict(symbol=symbol, price=price, turnover=turnover,
                             change=number(row["price24hPcnt"]) * 100,
                             range24=(high / low - 1) * 100,
                             spread=(ask - bid) / ((ask + bid) / 2) * 100,
                             open_interest=optional(row.get("openInterestValue")),
                             funding=optional(row.get("fundingRate"))))
        except (ValueError, KeyError, TypeError):
            rejected += 1
    rows.sort(key=lambda r: (-r["turnover"], r["symbol"]))
    if not rows:
        raise ValueError("No valid USDT tickers")
    return dict(status="ok", updated=stamp, rows=rows[:100], eligible=len(rows),
                rejected=rejected, source="Bybit public REST", limit=100)


def closed_candles(result, stamp, interval):
    step = INTERVALS[interval]
    bars = []
    for row in result["list"]:
        start = number(row[0]) / 1000
        if start % step != 0:
            raise ValueError("Unaligned candle")
        if start + step > stamp:
            continue
        o, h, l, c, v, turnover = map(number, row[1:7])
        if not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0 and turnover >= 0):
            raise ValueError("Invalid OHLC or volume")
        bars.append(dict(time=start, open=o, high=h, low=l, close=c,
                         volume=v, turnover=turnover))
    bars.sort(key=lambda b: b["time"])
    bars = bars[-180:]
    if len(bars) < 60:
        raise ValueError("Need at least 60 closed candles")
    if any(b["time"] - a["time"] != step for a, b in zip(bars, bars[1:])):
        raise ValueError("Candle gap or duplicate")
    if not 0 <= stamp - (bars[-1]["time"] + step) < step:
        raise ValueError("Last closed candle is stale")
    return bars


def chart_analysis(symbol, interval, bars, stamp):
    """Confirmed 2+2 swings grouped into price zones. Descriptive, not a forecast."""
    price = bars[-1]["close"]
    trs = [max(b["high"] - b["low"], abs(b["high"] - a["close"]),
               abs(b["low"] - a["close"])) for a, b in zip(bars, bars[1:])]
    atr = sum(trs[-14:]) / 14
    tolerance = max(price * .0005, atr * .25)
    pivots = []
    for i in range(2, len(bars) - 2):
        center = bars[i]
        others = bars[i-2:i] + bars[i+1:i+3]
        if all(center["low"] < b["low"] for b in others):
            pivots.append((center["low"], center["time"], "low"))
        if all(center["high"] > b["high"] for b in others):
            pivots.append((center["high"], center["time"], "high"))
    clusters = []
    for p, t, kind in sorted(pivots):
        if not clusters or p - clusters[-1]["low"] > tolerance:
            clusters.append(dict(low=p, high=p, values=[], times=[], kinds=[]))
        cluster = clusters[-1]
        cluster["high"] = p
        cluster["values"].append(p)
        cluster["times"].append(t)
        cluster["kinds"].append(kind)
    levels = []
    for cluster in clusters:
        p = sum(cluster["values"]) / len(cluster["values"])
        # Zones straddling the latest close are unresolved and not labeled support.
        side = "support" if cluster["high"] < price else "resistance" if cluster["low"] > price else None
        if side is None or (side == "support" and "low" not in cluster["kinds"]) or (
                side == "resistance" and "high" not in cluster["kinds"]):
            continue
        levels.append(dict(side=side, price=p, low=cluster["low"], high=cluster["high"],
                           pivots=len(set(cluster["times"])), last_pivot=max(cluster["times"]),
                           distance_pct=abs(p / price - 1) * 100))
    chosen = []
    for side in ("support", "resistance"):
        candidates = sorted((r for r in levels if r["side"] == side), key=lambda r: r["distance_pct"])
        chosen.extend(candidates[:3])
    base = sum(b["turnover"] for b in bars[-25:-5]) / 20
    recent = sum(b["turnover"] for b in bars[-5:]) / 5
    volume = sum(b["volume"] for b in bars[-60:])
    vwap = sum(b["turnover"] for b in bars[-60:]) / volume if volume > 0 else None
    return dict(status="ok", updated=stamp, symbol=symbol, interval=interval,
                candle_end=bars[-1]["time"] + INTERVALS[interval], candles=bars, levels=chosen,
                price=price, atr_pct=atr / price * 100, vwap=vwap,
                rvol=recent / base if base > 0 else None, zone_width=tolerance,
                turnover_window=sum(b["turnover"] for b in bars[-60:]))


def orderbook_analysis(symbol, result, stamp):
    if result.get("s") != symbol:
        raise ValueError("Wrong orderbook symbol")
    ts = number(result["ts"]) / 1000
    if not -1 <= stamp - ts <= 5:
        raise ValueError("Stale orderbook")
    bids = [(number(p), number(q)) for p, q in result["b"]]
    asks = [(number(p), number(q)) for p, q in result["a"]]
    if not bids or not asks or any(p <= 0 or q <= 0 for p, q in bids + asks):
        raise ValueError("Empty or invalid orderbook")
    if (any(a[0] <= b[0] for a, b in zip(bids, bids[1:])) or
            any(a[0] >= b[0] for a, b in zip(asks, asks[1:])) or bids[0][0] >= asks[0][0]):
        raise ValueError("Unsorted or crossed orderbook")
    mid = (bids[0][0] + asks[0][0]) / 2
    bands = {}
    for width in (.0002, .0005, .001):
        bid = sum(p * q for p, q in bids if p >= mid * (1 - width))
        ask = sum(p * q for p, q in asks if p <= mid * (1 + width))
        bands[str(width)] = dict(bid=bid, ask=ask,
                                imbalance=(bid - ask) / (bid + ask) if bid + ask else 0,
                                covered=bids[-1][0] <= mid * (1 - width) and asks[-1][0] >= mid * (1 + width))
    walls = {}
    for name, levels in (("bid", bids), ("ask", asks)):
        near = [(p, q) for p, q in levels if abs(p / mid - 1) <= .001]
        walls[name] = [dict(price=p, notional=p*q, distance_pct=abs(p/mid-1)*100)
                       for p, q in sorted(near, key=lambda x: -x[0]*x[1])[:3]]
    return dict(status="ok", symbol=symbol, updated=ts, fetched=stamp,
                mid=mid, spread=(asks[0][0] - bids[0][0]) / mid * 100,
                bands=bands, walls=walls, levels=len(bids)+len(asks))


class MarketData:
    """Two workers, two outstanding requests, 24 entries, failure backoff."""
    def __init__(self, api=public_api, clock=time.monotonic):
        self.api, self.clock = api, clock
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="public-market")

    def _load(self, kind, symbol, interval):
        if kind == "screener":
            result, stamp = self.api("tickers")
            return ticker_rows(result, stamp)
        if kind == "chart":
            result, stamp = self.api("kline", symbol=symbol, interval=interval, limit=185)
            return chart_analysis(symbol, interval, closed_candles(result, stamp, interval), stamp)
        result, stamp = self.api("orderbook", symbol=symbol, limit=200)
        return orderbook_analysis(symbol, result, stamp)

    def get(self, kind, symbol="", interval="5"):
        if kind not in ("screener", "chart", "book"):
            raise ValueError("Unknown analysis")
        if kind != "screener" and (not SYMBOL.fullmatch(symbol) or interval not in INTERVALS):
            raise ValueError("Invalid symbol or timeframe")
        key = (kind, symbol, interval if kind == "chart" else "")
        with self.lock:
            now = self.clock()
            # Harvest completed jobs globally so another key cannot starve the list.
            for cache_key, cached in self.entries.items():
                job = cached["future"]
                if job is None or not job.done():
                    continue
                try:
                    cached["data"] = job.result()
                    cached["error"] = ""
                    cached["until"] = now + {"screener": 15, "chart": 25, "book": 2}[cache_key[0]]
                except Exception as exc:
                    cached["error"] = type(exc).__name__ + ": " + str(exc)[:160]
                    cached["until"] = now + 20
                cached["future"] = None
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= 24:
                    victim = next((k for k, v in self.entries.items() if not v.get("future")), None)
                    if victim is None:
                        return dict(status="pending", updated=0, error="Очередь анализа заполнена")
                    del self.entries[victim]
                entry = dict(data=None, until=0, future=None, error="")
                self.entries[key] = entry
            self.entries.move_to_end(key)
            if entry["until"] <= now and entry["future"] is None:
                pending = sum(v["future"] is not None for v in self.entries.values())
                if pending < 2:
                    entry["future"] = self.pool.submit(self._load, kind, symbol, interval)
            data = dict(entry["data"] or dict(status="pending", updated=0))
            data["refreshing"] = entry["future"] is not None
            if entry["error"]:
                data.update(status="error", error=entry["error"])
            return data

    def close(self):
        self.pool.shutdown(wait=True)
