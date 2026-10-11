"""Bounded, public-only USDT perpetual market adapters.

Snapshot methods never wait for HTTP. Synchronous fetch methods are also useful
for offline fixtures and share the same two-request execution bound.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from functools import wraps
import json
import math
import re
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener


EXCHANGES = ("binance", "bybit", "okx", "gate", "bitget")
INTERVALS = ("1", "5", "15", "60", "240", "1440")
ROOTS = {
    "binance": "https://fapi.binance.com",
    "bybit": "https://api.bybit.com",
    "okx": "https://www.okx.com",
    "gate": "https://api.gateio.ws",
    "bitget": "https://api.bitget.com",
}
PATHS = {
    "binance": ("/fapi/v1/exchangeInfo", "/fapi/v1/ticker/24hr", "/fapi/v1/klines", "/fapi/v1/depth"),
    "bybit": ("/v5/market/instruments-info", "/v5/market/tickers", "/v5/market/kline", "/v5/market/orderbook"),
    "okx": ("/api/v5/public/instruments", "/api/v5/market/tickers", "/api/v5/market/candles", "/api/v5/market/books"),
    "gate": ("/api/v4/futures/usdt/contracts", "/api/v4/futures/usdt/tickers", "/api/v4/futures/usdt/candlesticks", "/api/v4/futures/usdt/order_book"),
    "bitget": ("/api/v2/mix/market/contracts", "/api/v2/mix/market/tickers", "/api/v2/mix/market/candles", "/api/v2/mix/market/merge-depth"),
}
TTLS = {"catalog": 5, "chart": 30, "book": 5}
REFRESH_PROOF_SECONDS = {"catalog": 60, "chart": 75}
CLOSE_PUBLICATION_SECONDS = 10
SYMBOL_RE = re.compile(r"[A-Z0-9]{1,28}USDT\Z")


def _number(value, minimum=None):
    if isinstance(value, bool):
        raise ValueError("invalid numeric value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("invalid numeric value") from None
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError("invalid numeric value")
    return result


def _positive(value):
    result = _number(value, 0)
    if result == 0:
        raise ValueError("zero price or contract size")
    return result


def _list(value, limit=5000):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError("invalid or oversized response list")
    return value


def _exchange(value):
    if value not in EXCHANGES:
        raise ValueError("unsupported exchange")
    return value


def _symbol(value):
    if not isinstance(value, str) or not SYMBOL_RE.fullmatch(value):
        raise ValueError("invalid canonical USDT symbol")
    return value


def _interval(value):
    if not isinstance(value, str) or value not in INTERVALS:
        raise ValueError("unsupported interval")
    return value


def _bounded_fetch(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._fetch_slots:
            return method(self, *args, **kwargs)
    return wrapped


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("market endpoint redirect refused")


class _CandlePublicationPending(ValueError):
    """Only the expected latest close is absent during its short publication window."""
    def __init__(self, candle_end):
        super().__init__("waiting for newly closed candle publication")
        self.candle_end = candle_end


class ExchangeData:
    """A single shared service: two workers, four jobs, 48 entries per kind."""
    def __init__(self, request=None, *, wall_clock=None, clock=None):
        self._request = request
        self._wall = wall_clock or time.time
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._fetch_slots = threading.BoundedSemaphore(2)
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="public-market")
        self._cache = {kind: OrderedDict() for kind in TTLS}
        self._marks = {kind: OrderedDict() for kind in TTLS}
        self._instruments = {}
        self._instrument_locks = {ex: threading.Lock() for ex in EXCHANGES}
        self._outstanding = 0
        self._nonchart_outstanding = 0
        self._closed = False

    def close(self):
        with self._lock:
            self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _json(self, exchange, path, params):
        if path not in PATHS[_exchange(exchange)]:
            raise ValueError("unsupported public endpoint")
        if self._request is not None:
            packet = self._request(exchange, path, dict(params))
        else:
            url = ROOTS[exchange] + path + ("?" + urlencode(params) if params else "")
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "TradingLab/1.0 public-market"})
            with build_opener(_NoRedirect()).open(request, timeout=6) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise ValueError("market response too large")
                packet = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("non-finite JSON")))
        if exchange == "bybit":
            if not isinstance(packet, dict) or str(packet.get("retCode")) != "0":
                raise ValueError("Bybit public API error")
        elif exchange in ("okx", "bitget"):
            if not isinstance(packet, dict) or str(packet.get("code")) != ("0" if exchange == "okx" else "00000"):
                raise ValueError("public API error")
        return packet

    def _stamp(self, value, max_age, milliseconds=True):
        stamp = _positive(value) / (1000 if milliseconds else 1)
        now = self._wall()
        if stamp > now + 3 or now - stamp > max_age:
            raise ValueError("stale or future market source timestamp")
        return stamp

    def _metadata(self, exchange):
        # This lock is only entered by fetch workers, never by snapshot callers.
        with self._instrument_locks[exchange]:
            saved = self._instruments.get(exchange)
            if saved and self._clock() - saved[0] < 300:
                return saved[1]
            rows = []
            if exchange == "binance":
                rows = _list(self._json(exchange, PATHS[exchange][0], {}).get("symbols"))
            elif exchange == "bybit":
                cursor = ""
                seen = set()
                for _ in range(4):
                    params = {"category": "linear", "limit": 1000}
                    if cursor:
                        params["cursor"] = cursor
                    response = self._json(exchange, PATHS[exchange][0], params)["result"]
                    rows.extend(_list(response.get("list"), 1000))
                    cursor = response.get("nextPageCursor", "")
                    if not cursor:
                        break
                    if not isinstance(cursor, str) or len(cursor) > 1024 or cursor in seen:
                        raise ValueError("invalid instrument pagination")
                    seen.add(cursor)
                else:
                    raise ValueError("instrument pagination budget exhausted")
            elif exchange == "okx":
                rows = _list(self._json(exchange, PATHS[exchange][0], {"instType": "SWAP"})["data"])
            elif exchange == "gate":
                rows = _list(self._json(exchange, PATHS[exchange][0], {}))
            else:
                rows = _list(self._json(exchange, PATHS[exchange][0], {"productType": "USDT-FUTURES"})["data"])
            instruments, duplicates = {}, set()
            for row in rows:
                try:
                    if not isinstance(row, dict):
                        raise ValueError("invalid instrument")
                    factor = 1.0
                    if exchange == "binance":
                        if (row.get("status"), row.get("contractType"), row.get("quoteAsset"), row.get("marginAsset")) != ("TRADING", "PERPETUAL", "USDT", "USDT"):
                            continue
                        native = symbol = row["symbol"]
                    elif exchange == "bybit":
                        if (row.get("status"), row.get("contractType"), row.get("quoteCoin"), row.get("settleCoin")) != ("Trading", "LinearPerpetual", "USDT", "USDT"):
                            continue
                        native = symbol = row["symbol"]
                    elif exchange == "okx":
                        if (row.get("instType"), row.get("ctType"), row.get("settleCcy"), row.get("state")) != ("SWAP", "linear", "USDT", "live"):
                            continue
                        native = row["instId"]
                        if not re.fullmatch(r"[A-Z0-9]{1,28}-USDT-SWAP", native):
                            continue
                        base = native.split("-")[0]
                        symbol = base + "USDT"
                        # Contract face quantity is denominated by ctValCcy.
                        # Quote-denominated/inverse conversion is out of scope.
                        if row.get("ctValCcy") != base:
                            continue
                        factor = _positive(_positive(row["ctVal"]) * _positive(row.get("ctMult") or 1))
                    elif exchange == "gate":
                        if row.get("type") != "direct" or row.get("in_delisting") is not False or row.get("status", "trading") != "trading" or row.get("is_pre_market", False):
                            continue
                        native = row["name"]
                        if not re.fullmatch(r"[A-Z0-9]{1,28}_USDT", native):
                            continue
                        symbol = native.replace("_", "")
                        factor = _positive(row["quanto_multiplier"])
                    else:
                        if (row.get("quoteCoin"), row.get("symbolType"), row.get("symbolStatus")) != ("USDT", "perpetual", "normal") or "USDT" not in row.get("supportMarginCoins", []):
                            continue
                        native = symbol = row["symbol"]
                    _symbol(symbol)
                    if symbol in duplicates:
                        continue
                    if symbol in instruments:
                        del instruments[symbol]
                        duplicates.add(symbol)
                        continue
                    instruments[symbol] = {"native": native, "factor": factor}
                except (ValueError, KeyError, TypeError):
                    continue
            if not instruments:
                raise ValueError("no verified active USDT perpetual instruments")
            self._instruments[exchange] = (self._clock(), instruments)
            return instruments

    def _instrument(self, exchange, symbol):
        instruments = self._metadata(exchange)
        if symbol not in instruments:
            raise ValueError("symbol is not an active USDT perpetual on this exchange")
        return instruments[symbol]

    def _accept(self, kind, key, packet, mark):
        # Equal source times are valid: an unchanged book or closed series may
        # be fetched twice. Older responses cannot replace verified data.
        json.dumps(packet, allow_nan=False)
        with self._lock:
            previous = self._marks[kind].get(key)
            cached = self._cache[kind].get(key)
            if cached and cached["data"]:
                saved_mark = cached["data"].get("candle_end") if kind == "chart" else cached["data"].get("source_ts")
                previous = max(previous or 0, saved_mark or 0)
            if previous is not None and mark < previous:
                raise ValueError("market source moved backwards")
            self._marks[kind][key] = mark
            self._marks[kind].move_to_end(key)
            while len(self._marks[kind]) > 48:
                self._marks[kind].popitem(last=False)
        return packet

    @_bounded_fetch
    def fetch_catalog(self, exchange):
        exchange = _exchange(exchange)
        instruments = self._metadata(exchange)
        params = {"bybit": {"category": "linear"}, "okx": {"instType": "SWAP"}, "bitget": {"productType": "USDT-FUTURES"}}.get(exchange, {})
        raw = self._json(exchange, PATHS[exchange][1], params)
        receipt = self._wall()
        source = receipt
        origin = "receipt"
        if exchange == "bybit":
            source = self._stamp(raw["time"], 90)
            origin = "exchange"
            raw = raw["result"]["list"]
        elif exchange in ("okx", "bitget"):
            if exchange == "bitget":
                source = self._stamp(raw["requestTime"], 90)
                origin = "exchange"
            raw = raw["data"]
        rows, rejected, stamps, seen = [], 0, [], set()
        native_map = {item["native"]: symbol for symbol, item in instruments.items()}
        for row in _list(raw):
            try:
                native = row.get("instId") if exchange == "okx" else row.get("contract") if exchange == "gate" else row.get("symbol")
                if native not in native_map:
                    continue
                symbol = native_map[native]
                if symbol in seen:
                    raise ValueError("duplicate ticker")
                seen.add(symbol)
                estimated, count = False, None
                if exchange == "binance":
                    price, change = _positive(row["lastPrice"]), _number(row["priceChangePercent"])
                    volume, turnover = _number(row["volume"], 0), _number(row["quoteVolume"], 0)
                    count = _number(row["count"], 0)
                    if not count.is_integer():
                        raise ValueError("invalid trade count")
                    count = int(count)
                    stamps.append(self._stamp(row["closeTime"], 90))
                elif exchange == "bybit":
                    price, change = _positive(row["lastPrice"]), _number(row["price24hPcnt"]) * 100
                    volume, turnover = _number(row["volume24h"], 0), _number(row["turnover24h"], 0)
                elif exchange == "okx":
                    price, opening = _positive(row["last"]), _positive(row["open24h"])
                    change = (price / opening - 1) * 100
                    volume = _number(row["volCcy24h"], 0)
                    turnover, estimated = volume * price, True
                    stamps.append(self._stamp(row["ts"], 90))
                elif exchange == "gate":
                    price, change = _positive(row["last"]), _number(row["change_percentage"])
                    volume, turnover = _number(row["volume_24h_base"], 0), _number(row["volume_24h_quote"], 0)
                else:
                    price, change = _positive(row["lastPr"]), _number(row["change24h"]) * 100
                    volume, turnover = _number(row["baseVolume"], 0), _number(row["quoteVolume"], 0)
                    self._stamp(row["ts"], 90)
                result = {"symbol": symbol, "price": price, "change24": change, "turnover24": turnover, "volume24": volume, "trades24": count,
                          "turnover": turnover, "change": change, "turnover_estimated": estimated}
                json.dumps(result, allow_nan=False)
                rows.append(result)
            except (KeyError, TypeError, ValueError, OverflowError):
                rejected += 1
        if not rows:
            raise ValueError("no fresh valid market tickers")
        if stamps:
            source, origin = max(stamps), "exchange"
        rows.sort(key=lambda row: (-row["turnover24"], row["symbol"]))
        packet = {"exchange": exchange, "status": "ok", "updated": self._wall(), "source_ts": source, "timestamp_origin": origin,
                  "rows": rows, "error": None, "stale": False, "refreshing": False, "rejected_rows": rejected, "market": "USDT linear perpetual"}
        return self._accept("catalog", (exchange,), packet, source)

    @_bounded_fetch
    def fetch_chart(self, exchange, symbol, interval):
        exchange, symbol, interval = _exchange(exchange), _symbol(symbol), _interval(interval)
        instrument = self._instrument(exchange, symbol)
        native, factor = instrument["native"], instrument["factor"]
        step = int(interval) * 60
        unit = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "240": "4h", "1440": "1d"}[interval]
        # UTC daily bars keep every venue aligned to the same 86,400-second boundary.
        uppercase_unit = {"60": "1H", "240": "4H", "1440": "1Dutc"}.get(interval, unit)
        if exchange == "binance":
            raw = self._json(exchange, PATHS[exchange][2], {"symbol": native, "interval": unit, "limit": 181})
        elif exchange == "bybit":
            response = self._json(exchange, PATHS[exchange][2], {"category": "linear", "symbol": native, "interval": "D" if interval == "1440" else interval, "limit": 181})
            self._stamp(response["time"], 90)
            raw = response["result"]["list"]
        elif exchange == "okx":
            raw = self._json(exchange, PATHS[exchange][2], {"instId": native, "bar": uppercase_unit, "limit": 181})["data"]
        elif exchange == "gate":
            raw = self._json(exchange, PATHS[exchange][2], {"contract": native, "interval": unit, "limit": 181})
        else:
            response = self._json(exchange, PATHS[exchange][2], {"symbol": native, "productType": "USDT-FUTURES", "granularity": uppercase_unit, "limit": 181, "kLineType": "MARKET"})
            self._stamp(response["requestTime"], 90)
            raw = response["data"]
        now = self._wall()
        expected_end = int((now - 2) // step) * step
        publication_window = 2 <= now - expected_end <= CLOSE_PUBLICATION_SECONDS
        candles, seen = [], set()
        for row in _list(raw, 300):
            if exchange == "gate":
                t = _positive(row["t"])
                values = [row[name] for name in ("o", "h", "l", "c")]
                volume, turnover = _number(row["v"], 0) * factor, _number(row["sum"], 0)
            else:
                if not isinstance(row, list) or len(row) < (9 if exchange == "okx" else 8 if exchange == "binance" else 7):
                    raise ValueError("invalid candle row")
                t = _positive(row[0]) / 1000
                values = row[1:5]
                if exchange == "okx":
                    if row[8] not in ("0", "1"):
                        raise ValueError("invalid candle confirmation")
                    if row[8] == "0":
                        # An old unconfirmed candle is a broken series, not a
                        # reason to silently stitch its neighbours together.
                        if t + step <= now - 2 and not (publication_window and t + step == expected_end):
                            raise ValueError("historical candle is unconfirmed")
                        continue
                    volume, turnover = _number(row[6], 0), _number(row[7], 0)
                else:
                    volume = _number(row[5], 0)
                    turnover = _number(row[7 if exchange == "binance" else 6], 0)
            if not t.is_integer() or int(t) % step:
                raise ValueError("unaligned candle timestamp")
            t = int(t)
            if t > now + 3:
                raise ValueError("future candle")
            if t + step > now - 2:
                continue
            if t in seen:
                raise ValueError("duplicate candle timestamp")
            seen.add(t)
            opening, high, low, close = map(_positive, values)
            if low > min(opening, close) or high < max(opening, close) or high < low:
                raise ValueError("inconsistent candle OHLC")
            candles.append({"t": t, "open": opening, "high": high, "low": low, "close": close, "volume": volume, "turnover": turnover})
        candles.sort(key=lambda row: row["t"])
        candles = candles[-180:]
        if len(candles) < 60 or any(b["t"] - a["t"] != step for a, b in zip(candles, candles[1:])):
            raise ValueError("insufficient or discontinuous closed candles")
        end = candles[-1]["t"] + step
        if end != expected_end:
            if publication_window and end == expected_end - step:
                with self._lock:
                    saved = self._marks["chart"].get((exchange, symbol, interval))
                    cached = self._cache["chart"].get((exchange, symbol, interval))
                    cached_end = cached["data"].get("candle_end") if cached and cached["data"] else None
                    if max(saved or 0, cached_end or 0) > end:
                        raise ValueError("market source moved backwards")
                raise _CandlePublicationPending(expected_end)
            raise ValueError("closed candle series is stale")
        metrics = {"natr5_14": None, "natr1_30": None, "change5": None}
        if interval in ("1", "5"):
            period = 30 if interval == "1" else 14
            tr = [max(b["high"] - b["low"], abs(b["high"] - a["close"]), abs(b["low"] - a["close"])) for a, b in zip(candles, candles[1:])]
            atr = sum(tr[:period]) / period
            for value in tr[period:]:
                atr = (atr * (period - 1) + value) / period
            metrics["natr1_30" if interval == "1" else "natr5_14"] = atr / candles[-1]["close"] * 100
            previous = candles[-6]["close"] if interval == "1" else candles[-2]["close"]
            metrics["change5"] = (candles[-1]["close"] / previous - 1) * 100
        packet = {"exchange": exchange, "symbol": symbol, "native_symbol": native, "interval": interval, "status": "ok", "updated": now,
                  "source_ts": end, "timestamp_origin": "closed_candle", "candle_end": end, "candles": candles, "metrics": metrics,
                  "metrics_interval": interval, "error": None, "stale": False, "refreshing": False,
                  "next_refresh_at": min(now + TTLS["chart"], end + step + 2)}
        return self._accept("chart", (exchange, symbol, interval), packet, end)

    @_bounded_fetch
    def fetch_book(self, exchange, symbol):
        exchange, symbol = _exchange(exchange), _symbol(symbol)
        instrument = self._instrument(exchange, symbol)
        native, factor = instrument["native"], instrument["factor"]
        if exchange == "binance":
            raw = self._json(exchange, PATHS[exchange][3], {"symbol": native, "limit": 500})
            source = self._stamp(raw["E"], 15)
            bids, asks = raw["bids"], raw["asks"]
        elif exchange == "bybit":
            response = self._json(exchange, PATHS[exchange][3], {"category": "linear", "symbol": native, "limit": 200})
            self._stamp(response["time"], 15)
            raw = response["result"]
            if raw.get("s") != native:
                raise ValueError("order book symbol mismatch")
            source = self._stamp(raw["ts"], 15)
            bids, asks = raw["b"], raw["a"]
        elif exchange == "okx":
            raw = self._json(exchange, PATHS[exchange][3], {"instId": native, "sz": 400})["data"]
            if len(_list(raw, 1)) != 1:
                raise ValueError("missing order book")
            raw = raw[0]
            source = self._stamp(raw["ts"], 15)
            bids, asks = raw["bids"], raw["asks"]
        elif exchange == "gate":
            raw = self._json(exchange, PATHS[exchange][3], {"contract": native, "limit": 100, "with_id": "true"})
            source = self._stamp(raw["current"], 15, milliseconds=False)
            bids, asks = raw["bids"], raw["asks"]
        else:
            response = self._json(exchange, PATHS[exchange][3], {"symbol": native, "productType": "USDT-FUTURES", "precision": "scale0"})
            self._stamp(response["requestTime"], 15)
            raw = response["data"]
            if raw.get("precision") != "scale0":
                raise ValueError("merged book precision refused")
            source = self._stamp(raw["ts"], 15)
            bids, asks = raw["bids"], raw["asks"]

        def levels(raw_levels, descending):
            output, seen = [], set()
            for level in _list(raw_levels, 1000):
                if exchange == "gate":
                    price_value, size_value = level["p"], level["s"]
                else:
                    if not isinstance(level, list) or len(level) < 2:
                        raise ValueError("malformed order book level")
                    price_value, size_value = level[:2]
                price = _positive(price_value)
                quantity = _positive(size_value) * factor
                _positive(quantity)
                # Preserve source decimal strings for matching density levels.
                price_text = str(price_value) if isinstance(price_value, str) else format(Decimal(str(price_value)), "f")
                if len(price_text) > 64 or not re.fullmatch(r"\d+(?:\.\d+)?", price_text):
                    raise ValueError("invalid order book price text")
                identity = Decimal(price_text)
                if identity in seen:
                    raise ValueError("duplicate book price")
                seen.add(identity)
                output.append([price_text, quantity])
            output.sort(key=lambda row: Decimal(row[0]), reverse=descending)
            if not output:
                raise ValueError("empty order book side")
            return output

        bids, asks = levels(bids, True), levels(asks, False)
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if Decimal(bids[0][0]) >= Decimal(asks[0][0]):
            raise ValueError("crossed or locked order book")
        packet = {"exchange": exchange, "symbol": symbol, "native_symbol": native, "status": "ok", "updated": self._wall(), "source_ts": source,
                  "timestamp_origin": "exchange", "bids": bids, "asks": asks, "price": bid / 2 + ask / 2,
                  "coverage": {"bid_min": bids[-1][0], "ask_max": asks[-1][0]}, "error": None, "stale": False, "refreshing": False}
        return self._accept("book", (exchange, symbol), packet, source)

    def _empty(self, kind, key):
        packet = {"exchange": key[0], "status": "pending", "updated": None, "source_ts": None, "error": None, "stale": True, "refreshing": False}
        if kind == "catalog":
            packet["rows"] = []
        else:
            packet["symbol"] = key[1]
            if kind == "chart":
                packet.update(interval=key[2], candle_end=None, candles=[], metrics={"natr5_14": None, "natr1_30": None, "change5": None})
            else:
                packet.update(bids=[], asks=[], price=None, coverage={"bid_min": None, "ask_max": None})
        return packet

    def _run(self, kind, key, entry):
        try:
            method = {"catalog": self.fetch_catalog, "chart": self.fetch_chart, "book": self.fetch_book}[kind]
            packet = method(*key)
            with self._lock:
                entry.update(data=packet, expires=self._clock() + TTLS[kind], retry=0, error=None, publication_end=None)
        except _CandlePublicationPending as exc:
            with self._lock:
                # No worker sleeps or retries internally. Snapshot admission
                # reuses a single job and enforces at least 1s between attempts.
                entry.update(error=None, retry=self._clock() + 1, publication_end=exc.candle_end)
        except Exception as exc:
            # Never echo upstream bodies, URLs or local configuration to clients.
            message = str(exc) if isinstance(exc, ValueError) else "public market request failed"
            with self._lock:
                entry.update(error=message[:160], retry=self._clock() + 5, publication_end=None)
        finally:
            with self._lock:
                entry["pending"] = False
                self._outstanding -= 1
                if kind != "chart":
                    self._nonchart_outstanding -= 1

    def _snapshot(self, kind, key):
        with self._lock:
            now = self._clock()
            entries = self._cache[kind]
            entry = entries.get(key)
            if entry is None:
                if len(entries) >= 48:
                    # Pending entries cannot be evicted while their worker owns
                    # them. Return a bounded busy response if all are pending.
                    victim = next((k for k, value in entries.items() if not value["pending"]), None)
                    if victim is None:
                        return dict(self._empty(kind, key), error="market cache busy")
                    del entries[victim]
                entry = {"data": None, "expires": 0, "retry": 0, "error": None, "pending": False, "publication_end": None}
                entries[key] = entry
            entries.move_to_end(key)
            data = entry["data"]
            if (entry.get("publication_end") is not None and not entry["pending"] and
                    self._wall() > entry["publication_end"] + CLOSE_PUBLICATION_SECONDS):
                # Stop presenting this as ordinary publication delay, but let
                # an already-due request verify recovery. If it is still old,
                # the fetch fails and applies the normal 5s error backoff.
                entry.update(error="closed candle series is stale", publication_end=None)
            fresh = data is not None and now < entry["expires"] and not entry["error"]
            if kind == "chart" and fresh:
                step = int(key[2]) * 60
                fresh = data["candle_end"] == int((self._wall() - 2) // step) * step
            # Density scans share these workers. Reserve two of the existing
            # four admission slots for visible charts, without increasing HTTP
            # concurrency or allowing an unbounded queue.
            admitted = self._outstanding < 4 and (kind == "chart" or self._nonchart_outstanding < 2)
            if not fresh and not entry["pending"] and now >= entry["retry"] and admitted and not self._closed:
                entry["pending"] = True
                self._outstanding += 1
                if kind != "chart":
                    self._nonchart_outstanding += 1
                try:
                    self._pool.submit(self._run, kind, key, entry)
                except RuntimeError:
                    entry["pending"] = False
                    self._outstanding -= 1
                    if kind != "chart":
                        self._nonchart_outstanding -= 1
                    entry["error"] = "market service closed"
            # A TTL starts revalidation; it does not erase still-current proof.
            # Keep its original timestamps, and stop immediately on a failed
            # refresh, a new closed-candle boundary or the bounded receipt age.
            usable = False
            if data is not None and kind in REFRESH_PROOF_SECONDS and not entry["error"] and not self._closed:
                wall = self._wall()
                limit = REFRESH_PROOF_SECONDS[kind]
                usable = -2 <= wall - data["updated"] <= limit
                if kind == "chart":
                    step = int(key[2]) * 60
                    usable = usable and data["candle_end"] == int((wall - 2) // step) * step
                else:
                    usable = usable and -2 <= wall - data["source_ts"] <= limit
            if (fresh or usable) and not self._closed:
                packet = deepcopy(data)
                packet["refreshing"] = entry["pending"]
                if kind == "chart":
                    packet["refresh_reason"] = "revalidation" if entry["pending"] else None
                return packet
            packet = deepcopy(data) if data is not None else self._empty(kind, key)
            packet.update(status="error" if entry["error"] else "pending", stale=True, error=entry["error"],
                          refreshing=data is not None and entry["pending"] and entry["error"] is None)
            if kind == "chart":
                wall, step = self._wall(), int(key[2]) * 60
                expected_end = int((wall - 2) // step) * step
                awaiting_close = (not entry["error"] and 2 <= wall - expected_end <= CLOSE_PUBLICATION_SECONDS and
                                  (entry.get("publication_end") == expected_end or
                                   data is not None and data["candle_end"] == expected_end - step))
                packet["refresh_reason"] = "awaiting_close" if awaiting_close else None
                packet["retry_after_seconds"] = max(0, entry["retry"] - now)
            if self._closed:
                packet.update(status="error", error="market service closed")
            return packet

    def exchange_snapshot(self, exchange):
        return self._snapshot("catalog", (_exchange(exchange),))

    def chart_snapshot(self, exchange, symbol, interval):
        return self._snapshot("chart", (_exchange(exchange), _symbol(symbol), _interval(interval)))

    def book_snapshot(self, exchange, symbol):
        return self._snapshot("book", (_exchange(exchange), _symbol(symbol)))


_shared = None
_shared_lock = threading.Lock()


def get_exchange_data():
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ExchangeData()
        return _shared
