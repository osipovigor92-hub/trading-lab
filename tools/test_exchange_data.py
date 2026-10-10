"""Offline public-adapter contract tests; no live exchange requests."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "trading-panel"))
from exchange_data import ExchangeData, EXCHANGES, INTERVALS, PATHS


class Clock:
    def __init__(self):
        self.now = 1_800_000_017.0
        self.mono = 100.0

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


class Fixture:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.mutate = None
        self.fail = False
        self.lock = threading.Lock()

    def request(self, exchange, path, params):
        with self.lock:
            self.calls.append((exchange, path, dict(params)))
        if self.fail:
            raise OSError("transport fixture failure")
        kind = PATHS[exchange].index(path)
        stamp = int(self.clock.now * 1000)
        native = "BTC-USDT-SWAP" if exchange == "okx" else "BTC_USDT" if exchange == "gate" else "BTCUSDT"
        if kind == 0:
            rows = {
                "binance": [{"symbol": native, "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT"}],
                "bybit": [{"symbol": native, "status": "Trading", "contractType": "LinearPerpetual", "quoteCoin": "USDT", "settleCoin": "USDT"}],
                "okx": [{"instId": native, "instType": "SWAP", "ctType": "linear", "settleCcy": "USDT", "state": "live", "ctVal": "0.01", "ctMult": "1", "ctValCcy": "BTC"}],
                "gate": [{"name": native, "type": "direct", "in_delisting": False, "status": "trading", "quanto_multiplier": "0.0001"}],
                "bitget": [{"symbol": native, "quoteCoin": "USDT", "symbolType": "perpetual", "symbolStatus": "normal", "supportMarginCoins": ["USDT"], "sizeMultiplier": "0.01"}],
            }[exchange]
            if exchange == "binance":
                packet = {"symbols": rows}
            elif exchange == "bybit":
                packet = {"retCode": 0, "time": stamp, "result": {"list": rows, "nextPageCursor": ""}}
            elif exchange == "gate":
                packet = rows
            else:
                packet = {"code": "0" if exchange == "okx" else "00000", "requestTime": stamp, "data": rows}
        elif kind == 1:
            rows = {
                "binance": [{"symbol": native, "lastPrice": "100", "priceChangePercent": "25", "volume": "3", "quoteVolume": "270", "count": 123, "closeTime": stamp}],
                "bybit": [{"symbol": native, "lastPrice": "100", "price24hPcnt": "0.25", "volume24h": "3", "turnover24h": "270"}],
                "okx": [{"instId": native, "last": "100", "open24h": "80", "volCcy24h": "3", "vol24h": "300", "ts": str(stamp)}],
                "gate": [{"contract": native, "last": "100", "change_percentage": "25", "volume_24h_base": "3", "volume_24h_quote": "270", "volume_24h": "30000"}],
                "bitget": [{"symbol": native, "lastPr": "100", "change24h": "0.25", "baseVolume": "3", "quoteVolume": "270", "usdtVolume": "270", "ts": str(stamp)}],
            }[exchange]
            if exchange in ("binance", "gate"):
                packet = rows
            elif exchange == "bybit":
                packet = {"retCode": 0, "time": stamp, "result": {"list": rows}}
            else:
                packet = {"code": "0" if exchange == "okx" else "00000", "requestTime": stamp, "data": rows}
        elif kind == 2:
            raw_unit = params.get("interval", params.get("bar", params.get("granularity")))
            minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1H": 60, "1": 1, "5": 5, "15": 15, "60": 60}[raw_unit]
            step = minutes * 60
            boundary = int(self.clock.now // step) * step
            rows = []
            for i in range(181):
                t = boundary - (180 - i) * step
                if exchange == "gate":
                    row = {"t": t, "o": "100", "h": "102", "l": "98", "c": "100", "v": "12300", "sum": "123"}
                elif exchange == "okx":
                    row = [str(t * 1000), "100", "102", "98", "100", "123", "1.23", "123", "0" if i == 180 else "1"]
                elif exchange == "binance":
                    row = [t * 1000, "100", "102", "98", "100", "1.23", (t + step) * 1000 - 1, "123", 10]
                else:
                    row = [str(t * 1000), "100", "102", "98", "100", "1.23", "123"]
                rows.append(row)
            if exchange in ("bybit", "okx"):
                rows.reverse()
            if exchange in ("binance", "gate"):
                packet = rows
            elif exchange == "bybit":
                packet = {"retCode": 0, "time": stamp, "result": {"symbol": native, "category": "linear", "list": rows}}
            else:
                packet = {"code": "0" if exchange == "okx" else "00000", "requestTime": stamp, "data": rows}
        else:
            quantities = ("123", "200", "300", "400") if exchange == "okx" else ("12300", "20000", "30000", "40000") if exchange == "gate" else ("1.23", "2", "3", "4")
            bids = [["98.0", quantities[1]], ["99.0", quantities[0]]]
            asks = [["102.0", quantities[3]], ["101.0", quantities[2]]]
            if exchange == "gate":
                packet = {"current": self.clock.now, "update": self.clock.now - 0.1,
                          "bids": [{"p": p, "s": q} for p, q in bids], "asks": [{"p": p, "s": q} for p, q in asks]}
            elif exchange == "bybit":
                packet = {"retCode": 0, "time": stamp, "result": {"s": native, "ts": stamp, "b": bids, "a": asks}}
            elif exchange == "okx":
                packet = {"code": "0", "data": [{"ts": str(stamp), "bids": [row + ["0", "1"] for row in bids], "asks": [row + ["0", "1"] for row in asks]}]}
            elif exchange == "bitget":
                packet = {"code": "00000", "requestTime": stamp, "data": {"precision": "scale0", "ts": str(stamp), "bids": bids, "asks": asks}}
            else:
                packet = {"E": stamp, "T": stamp - 1, "bids": bids, "asks": asks}
        if self.mutate:
            packet = self.mutate(exchange, kind, deepcopy(packet))
        return packet


def await_snapshot(function, expected="ok"):
    deadline = time.monotonic() + 2
    packet = None
    while time.monotonic() < deadline:
        packet = function()
        if packet["status"] == expected:
            return packet
        time.sleep(0.002)
    raise AssertionError(f"snapshot did not become {expected}: {packet}")


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.fixture = Fixture(self.clock)
        self.adapter = ExchangeData(self.fixture.request, wall_clock=lambda: self.clock.now, clock=lambda: self.clock.mono)

    def tearDown(self):
        self.adapter.close()

    def test_all_catalog_units_percentages_and_unavailable_counts(self):
        for exchange in EXCHANGES:
            with self.subTest(exchange=exchange):
                packet = self.adapter.fetch_catalog(exchange)
                self.assertEqual(packet["status"], "ok")
                row = packet["rows"][0]
                self.assertEqual(row["symbol"], "BTCUSDT")
                self.assertEqual(row["change24"], 25)
                self.assertEqual(row["volume24"], 3)
                self.assertEqual(row["turnover24"], 300 if exchange == "okx" else 270)
                self.assertEqual(row["turnover_estimated"], exchange == "okx")
                self.assertEqual(row["trades24"], 123 if exchange == "binance" else None)
                self.assertEqual(row["turnover"], row["turnover24"])
                json.dumps(packet, allow_nan=False)

    def test_all_books_contract_sizes_and_exact_coverage(self):
        for exchange in EXCHANGES:
            with self.subTest(exchange=exchange):
                packet = self.adapter.fetch_book(exchange, "BTCUSDT")
                self.assertAlmostEqual(packet["bids"][0][1], 1.23)
                self.assertEqual(packet["bids"][0][0], "99.0")
                self.assertAlmostEqual(packet["asks"][0][1], 3)
                self.assertEqual(packet["price"], 100)
                self.assertEqual(packet["coverage"], {"bid_min": "98.0", "ask_max": "102.0"})
                self.assertEqual(packet["source_ts"], self.clock.now)

    def test_all_chart_intervals_normalized_closed_and_single_query(self):
        for exchange in EXCHANGES:
            for interval in INTERVALS:
                with self.subTest(exchange=exchange, interval=interval):
                    before = len([call for call in self.fixture.calls if call[1] == PATHS[exchange][2]])
                    packet = self.adapter.fetch_chart(exchange, "BTCUSDT", interval)
                    after = len([call for call in self.fixture.calls if call[1] == PATHS[exchange][2]])
                    self.assertEqual(after - before, 1)
                    self.assertEqual(len(packet["candles"]), 180)
                    self.assertAlmostEqual(packet["candles"][-1]["volume"], 1.23)
                    self.assertEqual(packet["candles"][-1]["turnover"], 123)
                    self.assertLess(packet["candle_end"], self.clock.now)
                    self.assertEqual(packet["candle_end"], packet["candles"][-1]["t"] + int(interval) * 60)
                    metric = "natr1_30" if interval == "1" else "natr5_14" if interval == "5" else None
                    if metric:
                        self.assertEqual(packet["metrics"][metric], 4)
                        self.assertEqual(packet["metrics"]["change5"], 0)
                    else:
                        self.assertTrue(all(value is None for value in packet["metrics"].values()))
                    json.dumps(packet, allow_nan=False)

    def test_input_and_endpoint_allowlists_before_http(self):
        for method, args in ((self.adapter.fetch_catalog, ("https://evil.test",)),
                             (self.adapter.book_snapshot, ("bybit", "BTCUSDT?secret=x")),
                             (self.adapter.chart_snapshot, ("binance", "BTC/USDT", "1")),
                             (self.adapter.chart_snapshot, ("bybit", "BTCUSDT", "1m")),
                             (self.adapter.chart_snapshot, ("okx", "BTCUSDT", 1)),
                             (self.adapter._json, ("bybit", "/v5/order/create", {}))):
            with self.assertRaises(ValueError):
                method(*args)
        self.assertEqual(self.fixture.calls, [])

    def test_ambiguous_okx_currency_and_invalid_multiplier_or_gate_inverse_rejected(self):
        for field, value in (("ctMult", "NaN"), ("ctValCcy", "USDT"), ("ctVal", "NaN"), ("ctType", "inverse")):
            def mutate(exchange, kind, packet):
                if exchange == "okx" and kind == 0:
                    packet["data"][0][field] = value
                return packet
            self.fixture.mutate = mutate
            self.adapter._instruments.clear()
            with self.assertRaises(ValueError):
                self.adapter.fetch_book("okx", "BTCUSDT")
        self.fixture.mutate = lambda ex, kind, packet: [dict(packet[0], type="inverse")] if ex == "gate" and kind == 0 else packet
        with self.assertRaises(ValueError):
            self.adapter.fetch_book("gate", "BTCUSDT")

    def test_okx_multiplier_only_applies_to_contract_counts(self):
        def mutate(exchange, kind, packet):
            if kind == 0:
                packet["data"][0]["ctMult"] = "2"
            return packet
        self.fixture.mutate = mutate
        self.assertAlmostEqual(self.adapter.fetch_book("okx", "BTCUSDT")["bids"][0][1], 2.46)
        self.assertEqual(self.adapter.fetch_catalog("okx")["rows"][0]["volume24"], 3)
        self.assertAlmostEqual(self.adapter.fetch_chart("okx", "BTCUSDT", "5")["candles"][0]["volume"], 1.23)

    def test_numeric_small_bitget_price_preserves_decimal_boundary(self):
        def mutate(exchange, kind, packet):
            if kind == 3:
                packet["data"]["bids"] = [[0.000012, 3]]
                packet["data"]["asks"] = [[0.000013, 4]]
            return packet
        self.fixture.mutate = mutate
        packet = self.adapter.fetch_book("bitget", "BTCUSDT")
        self.assertEqual(packet["bids"][0][0], "0.000012")
        self.assertEqual(packet["coverage"]["ask_max"], "0.000013")

    def test_invalid_chart_data_never_stitched_or_clamped(self):
        for change in ("gap", "duplicate", "nan", "ohlc", "future", "short", "stale"):
            def mutate(exchange, kind, packet):
                if kind != 2:
                    return packet
                if change == "gap":
                    del packet[90]
                elif change == "duplicate":
                    packet[90] = deepcopy(packet[91])
                elif change == "nan":
                    packet[90][5] = "NaN"
                elif change == "ohlc":
                    packet[90][2] = "90"
                elif change == "future":
                    packet[-1][0] += 600_000
                elif change == "short":
                    packet = packet[-60:]
                elif change == "stale":
                    packet = packet[:-2]
                return packet
            self.fixture.mutate = mutate
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.adapter.fetch_chart("binance", "BTCUSDT", "1")

    def test_okx_historical_unconfirmed_candle_rejected(self):
        def mutate(exchange, kind, packet):
            if kind == 2:
                packet["data"][30][8] = "0"
            return packet
        self.fixture.mutate = mutate
        with self.assertRaises(ValueError):
            self.adapter.fetch_chart("okx", "BTCUSDT", "5")

    def test_invalid_book_quantity_crossing_duplicates_and_stale_time(self):
        for change in ("nan", "zero", "cross", "duplicate", "old", "future"):
            def mutate(exchange, kind, packet):
                if kind != 3:
                    return packet
                if change == "nan":
                    packet["bids"][0][1] = "NaN"
                elif change == "zero":
                    packet["asks"][0][1] = 0
                elif change == "cross":
                    packet["asks"][0][0] = "97"
                elif change == "duplicate":
                    packet["bids"][0][0] = packet["bids"][1][0]
                elif change == "old":
                    packet["E"] -= 16_000
                else:
                    packet["E"] += 4_000
                return packet
            self.fixture.mutate = mutate
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.adapter.fetch_book("binance", "BTCUSDT")

    def test_fresh_source_cannot_go_backwards(self):
        self.adapter.fetch_book("bybit", "BTCUSDT")
        def mutate(exchange, kind, packet):
            if kind == 3:
                packet["result"]["ts"] -= 1000
            return packet
        self.fixture.mutate = mutate
        with self.assertRaisesRegex(ValueError, "backwards"):
            self.adapter.fetch_book("bybit", "BTCUSDT")

    def test_public_api_error_is_not_success(self):
        def mutate(exchange, kind, packet):
            if exchange == "bybit":
                packet["retCode"] = 10006
            else:
                packet["code"] = "50000"
            return packet
        self.fixture.mutate = mutate
        for exchange in ("bybit", "okx", "bitget"):
            with self.subTest(exchange=exchange), self.assertRaises(ValueError):
                self.adapter.fetch_catalog(exchange)

    def test_cache_ttl_failure_retains_history_then_recovers(self):
        call = lambda: self.adapter.book_snapshot("bybit", "BTCUSDT")
        first = await_snapshot(call)
        original_calls = len(self.fixture.calls)
        first["bids"][0][1] = 999  # returned values are detached from the cache
        self.assertAlmostEqual(call()["bids"][0][1], 1.23)
        self.assertEqual(len(self.fixture.calls), original_calls)
        self.clock.advance(6)
        self.fixture.fail = True
        error = await_snapshot(call, "error")
        self.assertTrue(error["stale"])
        self.assertEqual(error["updated"], first["updated"])
        self.assertAlmostEqual(error["bids"][0][1], 1.23)
        self.fixture.fail = False
        self.clock.advance(6)
        recovered = await_snapshot(call)
        self.assertFalse(recovered["stale"])
        self.assertGreater(recovered["updated"], first["updated"])

    def test_normal_refresh_retains_actual_source_time_without_new_proof(self):
        call = lambda: self.adapter.book_snapshot("bybit", "BTCUSDT")
        original = await_snapshot(call)
        release = threading.Event()
        def delayed(exchange, path, params):
            if path == PATHS[exchange][3]:
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed
        self.clock.advance(10)
        pending = call()
        self.assertEqual(pending["status"], "pending")
        self.assertTrue(pending["refreshing"])
        self.assertIsNone(pending["error"])
        self.assertEqual(pending["updated"], original["updated"])
        self.assertEqual(pending["source_ts"], original["source_ts"])
        self.assertEqual(call()["source_ts"], original["source_ts"])
        release.set()
        latest = await_snapshot(call)
        self.assertGreater(latest["source_ts"], original["source_ts"])

    def test_catalog_and_chart_ttls_and_new_close_invalidate_cache(self):
        for kind, ttl, call in (("catalog", 45, lambda: self.adapter.exchange_snapshot("binance")),
                                ("chart", 30, lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1"))):
            packet = await_snapshot(call)
            count = len(self.fixture.calls)
            self.clock.advance(1)
            self.assertEqual(call()["status"], "ok")
            self.assertEqual(len(self.fixture.calls), count)
            self.clock.advance(ttl)
            refreshed = await_snapshot(call)
            self.assertGreater(refreshed["updated"], packet["updated"])
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1")
        packet = await_snapshot(call)
        self.clock.advance(25)  # crosses next minute while chart TTL is fresh
        if int((self.clock.now - 2) // 60) * 60 > packet["candle_end"]:
            self.assertEqual(call()["status"], "pending")
            self.assertGreater(await_snapshot(call)["candle_end"], packet["candle_end"])

    def test_snapshots_return_immediately_and_pool_and_queue_are_bounded(self):
        release, active = threading.Event(), threading.Event()
        def request(exchange, path, params):
            active.set()
            release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = request
        start = time.monotonic()
        packets = [self.adapter.book_snapshot("bybit", f"C{i}USDT") for i in range(20)]
        self.assertLess(time.monotonic() - start, 0.2)
        self.assertTrue(all(packet["status"] == "pending" for packet in packets))
        self.assertTrue(active.wait(1))
        with self.adapter._lock:
            self.assertEqual(self.adapter._outstanding, 4)
            self.assertEqual(sum(entry["pending"] for entry in self.adapter._cache["book"].values()), 4)
        self.assertLessEqual(len(self.adapter._pool._threads), 2)
        release.set()

    def test_each_cache_capacity_is_bounded_under_unique_requests(self):
        # Avoid network work here: exercise admission pressure with a closed
        # service; no worker can mutate these entries during the assertion.
        self.adapter.close()
        for i in range(100):
            self.adapter.book_snapshot("bybit", f"C{i}USDT")
            self.adapter.chart_snapshot("bybit", f"C{i}USDT", "1")
        self.assertEqual(len(self.adapter._cache["book"]), 48)
        self.assertEqual(len(self.adapter._cache["chart"]), 48)


if __name__ == "__main__":
    unittest.main(verbosity=2)
