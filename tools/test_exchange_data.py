"""Offline public-adapter contract tests; no live exchange requests."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "trading-panel"))
from exchange_data import ExchangeData, EXCHANGES, INTERVALS, PATHS
import exchange_data


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
            minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1H": 60, "4h": 240, "4H": 240,
                       "1d": 1440, "1Dutc": 1440, "1": 1, "5": 5, "15": 15, "60": 60, "240": 240, "D": 1440}[raw_unit]
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


def await_snapshot(function, expected="ok", *, updated_after=None):
    deadline = time.monotonic() + 2
    packet = None
    while time.monotonic() < deadline:
        packet = function()
        if packet["status"] == expected and (updated_after is None or packet["updated"] > updated_after):
            return packet
        time.sleep(0.002)
    raise AssertionError(f"snapshot did not become {expected}: {packet}")


def await_idle(adapter):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with adapter._lock:
            if not adapter._outstanding:
                return
        time.sleep(0.002)
    raise AssertionError("adapter worker did not finish")


class HTTPResponseFixture:
    def __init__(self, raw=b'{"symbols": []}', *, status=200, will_close=False, failure=None):
        self.raw, self.status, self.will_close, self.failure = raw, status, will_close, failure

    def read(self, limit):
        if self.failure:
            raise self.failure
        return self.raw[:limit]


class HTTPSFixture:
    """Deterministic latency model: 120ms TLS setup and 40ms per GET."""
    def __init__(self):
        self.connections, self.responses, self.requests = [], [], []
        self.cost = 0
        self.lock = threading.Lock()

    def connection(self, host, timeout):
        owner = self
        class Connection:
            def __init__(self):
                self.host, self.timeout, self.closed = host, timeout, False
                self.sock = object()
                self.connected = False

            def request(self, method, target, headers):
                with owner.lock:
                    if not self.connected:
                        owner.cost += .120
                        self.connected = True
                    owner.cost += .040
                    owner.requests.append((self, method, target, headers))

            def getresponse(self):
                with owner.lock:
                    return owner.responses.pop(0) if owner.responses else HTTPResponseFixture()

            def close(self):
                self.closed = True
                self.sock = None
        connection = Connection()
        self.connections.append(connection)
        return connection


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.http = HTTPSFixture()
        self.clock = Clock()
        self.proxies = patch.object(exchange_data, "getproxies", return_value={})
        self.transport = patch.object(exchange_data, "HTTPSConnection", side_effect=self.http.connection)
        self.socket_readiness = patch.object(exchange_data, "select", return_value=([], [], []))
        self.proxies.start()
        self.transport.start()
        self.socket_readiness.start()
        self.adapter = ExchangeData(wall_clock=lambda: self.clock.now, clock=lambda: self.clock.mono)

    def tearDown(self):
        self.adapter.close()
        self.transport.stop()
        self.proxies.stop()
        self.socket_readiness.stop()

    def test_chart_batch_reuses_tls_connection_with_bounded_latency_model(self):
        for path in (PATHS["binance"][0], PATHS["binance"][1], *([PATHS["binance"][2]] * 6)):
            self.adapter._json("binance", path, {"symbol": "BTCUSDT"} if path == PATHS["binance"][2] else {})
        self.assertEqual(len(self.http.requests), 8)
        self.assertEqual(len(self.http.connections), 1)
        self.assertAlmostEqual(self.http.cost, .120 + 8 * .040)
        old_cost = 8 * (.120 + .040)
        self.assertLess(self.http.cost, old_cost / 2, "model removes repeated TLS setup, without fewer validated HTTP reads")
        connection = self.http.connections[0]
        self.assertEqual((connection.host, connection.timeout), ("fapi.binance.com", 6))
        self.assertTrue(all(method == "GET" and target.startswith("/fapi/v1/") for _, method, target, _ in self.http.requests))
        self.adapter.close()
        self.assertTrue(connection.closed)
        self.assertTrue(all(not idle for idle in self.adapter._connections.values()))

    def test_caller_can_preserve_stricter_public_response_limit(self):
        self.http.responses.append(HTTPResponseFixture(b'x' * 101))
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.adapter._json('binance', PATHS['binance'][1], {}, max_bytes=100)
        self.assertTrue(self.http.connections[-1].closed)
        for limit in (0, -1, True, 4 * 1024 * 1024 + 1):
            with self.assertRaisesRegex(ValueError, 'response limit'):
                self.adapter._json('binance', PATHS['binance'][1], {}, max_bytes=limit)

    def test_upstream_close_and_failed_read_discard_without_duplicate_retry(self):
        self.http.responses.append(HTTPResponseFixture(will_close=True))
        self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertTrue(self.http.connections[0].closed)
        self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertEqual(len(self.http.connections), 2)
        self.http.responses.append(HTTPResponseFixture(failure=OSError("socket fixture failure")))
        with self.assertRaises(OSError):
            self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertEqual(len(self.http.requests), 3, "transport cannot internally retry a failed GET")
        self.assertTrue(self.http.connections[1].closed)
        self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertEqual(len(self.http.connections), 3)

    def test_expired_or_peer_closed_idle_socket_reconnects_before_get(self):
        self.adapter._json("binance", PATHS["binance"][0], {})
        self.clock.advance(31)
        self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertTrue(self.http.connections[0].closed)
        with patch.object(exchange_data, "select", return_value=([self.http.connections[-1].sock], [], [])):
            self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertTrue(self.http.connections[1].closed)
        self.assertEqual(len(self.http.connections), 3)
        self.assertEqual(len(self.http.requests), 3, "idle reconnection adds no duplicate HTTP request")

    def test_redirect_http_error_and_oversize_are_closed(self):
        for response, reason in ((HTTPResponseFixture(status=302), "redirect"),
                                 (HTTPResponseFixture(status=429), "request failed"),
                                 (HTTPResponseFixture(b"x" * (4*1024*1024+1)), "too large")):
            self.http.responses.append(response)
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.adapter._json("binance", PATHS["binance"][0], {})
            self.assertTrue(self.http.connections[-1].closed)
            self.assertEqual(self.adapter._connections["binance"], [])
        self.assertEqual(len(self.http.requests), 3)

    def test_connection_pool_stays_bounded_under_concurrent_direct_calls_and_shutdown(self):
        entered, release = threading.Barrier(3), threading.Event()
        responses = []
        for _ in range(2):
            response = HTTPResponseFixture()
            def blocked_read(limit, original=response.read):
                entered.wait(timeout=2)
                release.wait(2)
                return original(limit)
            response.read = blocked_read
            responses.append(response)
        self.http.responses.extend(responses)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self.adapter._json, "binance", PATHS["binance"][0], {}) for _ in range(8)]
            entered.wait(timeout=2)
            self.assertEqual(len(self.http.connections), 2)
            self.assertEqual(len(self.adapter._active_connections), 2)
            release.set()
            for future in futures:
                future.result(timeout=2)
        self.assertEqual(len(self.http.connections), 2)
        self.assertEqual(len(self.adapter._connections["binance"]), 2)
        self.adapter.close()
        self.assertTrue(all(connection.closed for connection in self.http.connections))
        with self.assertRaisesRegex(ValueError, "closed"):
            self.adapter._json("binance", PATHS["binance"][0], {})
        self.assertEqual(len(self.http.requests), 8)

    def test_shutdown_during_active_response_does_not_return_connection_to_pool(self):
        entered, release = threading.Event(), threading.Event()
        response = HTTPResponseFixture()
        def blocked_read(limit):
            entered.set()
            release.wait(2)
            return response.raw
        response.read = blocked_read
        self.http.responses.append(response)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.adapter._json, "binance", PATHS["binance"][0], {})
            self.assertTrue(entered.wait(1))
            self.adapter.close()
            self.assertTrue(self.http.connections[0].closed)
            release.set()
            future.result(timeout=2)
        self.assertEqual(self.adapter._connections["binance"], [])
        self.assertEqual(self.adapter._active_connections, set())

    def test_configured_proxy_keeps_urllib_transport_and_request_limits(self):
        with patch.object(exchange_data, "getproxies", return_value={"https": "http://proxy.example:3128"}), \
                patch.object(exchange_data, "build_opener") as create_opener:
            proxy_adapter = ExchangeData()
        try:
            response = create_opener.return_value.open.return_value.__enter__.return_value
            response.read.return_value = b'{"symbols": []}'
            self.assertEqual(proxy_adapter._json("binance", PATHS["binance"][0], {}), {"symbols": []})
            request = create_opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://fapi.binance.com/fapi/v1/exchangeInfo")
            self.assertEqual(create_opener.return_value.open.call_args.kwargs, {"timeout": 6})
            response.read.assert_called_once_with(4*1024*1024+1)
            self.assertEqual(self.http.connections, [])
        finally:
            proxy_adapter.close()

    def test_no_proxy_exclusions_alone_do_not_disable_connection_reuse(self):
        with patch.object(exchange_data, "getproxies", return_value={"no": "localhost,127.0.0.1"}):
            adapter = ExchangeData()
        try:
            adapter._json("binance", PATHS["binance"][0], {})
            adapter._json("binance", PATHS["binance"][0], {})
            self.assertEqual(len(self.http.connections), 1)
            self.assertIsNone(adapter._proxy_opener)
        finally:
            adapter.close()


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.fixture = Fixture(self.clock)
        self.adapter = ExchangeData(self.fixture.request, wall_clock=lambda: self.clock.now, clock=lambda: self.clock.mono)

    def tearDown(self):
        self.adapter.close()

    def test_book_peek_does_not_allocate_admit_or_renew_cached_proof(self):
        cold = self.adapter.peek_book_snapshot('bybit', 'BTCUSDT')
        self.assertEqual(cold['status'], 'pending')
        self.assertFalse(cold['queued'])
        self.assertEqual(len(self.adapter._cache['book']), 0)
        self.assertEqual(self.fixture.calls, [])
        packet = await_snapshot(lambda: self.adapter.book_snapshot('bybit', 'BTCUSDT'))
        calls = len(self.fixture.calls)
        peek = self.adapter.peek_book_snapshot('bybit', 'BTCUSDT')
        self.assertEqual(peek['updated'], packet['updated'])
        self.assertEqual(peek['source_ts'], packet['source_ts'])
        peek['bids'].clear()
        self.assertTrue(self.adapter.peek_book_snapshot('bybit', 'BTCUSDT')['bids'])
        self.clock.advance(6)
        expired = self.adapter.peek_book_snapshot('bybit', 'BTCUSDT')
        self.assertEqual(expired['status'], 'pending')
        self.assertEqual(expired['updated'], packet['updated'])
        self.assertFalse(expired['queued'])
        self.assertEqual(len(self.fixture.calls), calls)
        self.assertEqual(self.adapter._outstanding, 0)

    def test_all_catalog_units_percentages_and_unavailable_counts(self):
        for exchange in EXCHANGES:
            with self.subTest(exchange=exchange):
                packet = self.adapter.fetch_catalog(exchange)
                self.assertEqual(packet["status"], "ok")
                row = packet["rows"][0]
                self.assertEqual(row["symbol"], "BTCUSDT")
                self.assertEqual(row["native_symbol"], "BTC-USDT-SWAP" if exchange == "okx" else "BTC_USDT" if exchange == "gate" else "BTCUSDT")
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
                    self.assertEqual(packet["next_refresh_at"],
                                     min(self.clock.now+30, packet["candle_end"]+int(interval)*60+2))
                    query = [call[2] for call in self.fixture.calls if call[1] == PATHS[exchange][2]][-1]
                    native = query.get("interval", query.get("bar", query.get("granularity")))
                    if interval in ("240", "1440"):
                        expected = {"binance": ("4h", "1d"), "gate": ("4h", "1d"),
                                    "bybit": ("240", "D"), "okx": ("4H", "1Dutc"), "bitget": ("4H", "1Dutc")}
                        self.assertEqual(native, expected[exchange][interval == "1440"])
                    metric = "natr1_30" if interval == "1" else "natr5_14" if interval == "5" else None
                    if metric:
                        self.assertEqual(packet["metrics"][metric], 4)
                        self.assertEqual(packet["metrics"]["change5"], 0)
                    else:
                        self.assertTrue(all(value is None for value in packet["metrics"].values()))
                    json.dumps(packet, allow_nan=False)

    def test_parallel_cold_charts_share_one_verified_instrument_request(self):
        entered, release = threading.Event(), threading.Event()
        def delayed_metadata(exchange, path, params):
            if path == PATHS[exchange][0]:
                entered.set()
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed_metadata
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.adapter.fetch_chart, "bybit", "BTCUSDT", interval) for interval in ("1", "5")]
            self.assertTrue(entered.wait(1))
            release.set()
            for future in futures:
                self.assertEqual(future.result(timeout=2)["status"], "ok")
        self.adapter.fetch_catalog("bybit")
        self.adapter.fetch_book("bybit", "BTCUSDT")
        reads = [call for call in self.fixture.calls if call[1] == PATHS["bybit"][0]]
        self.assertEqual(len(reads), 1, "cold charts, catalog and density book reuse the same verified metadata")

    def test_long_interval_freshness_uses_closed_utc_boundary_and_close_grace(self):
        for exchange in EXCHANGES:
            for interval in ("240", "1440"):
                with self.subTest(exchange=exchange, interval=interval):
                    step = int(interval)*60
                    boundary = int(self.clock.now//step)*step
                    self.clock.now = boundary+step-1
                    before = self.adapter.fetch_chart(exchange, "BTCUSDT", interval)
                    self.assertEqual(before["candle_end"], boundary)
                    # A current daily series can have a day-old last closed bar.
                    # Freshness follows its expected boundary, not quote age.
                    self.assertGreater(self.clock.now-before["source_ts"], 90)
                    self.clock.now = boundary+step+1
                    grace = self.adapter.fetch_chart(exchange, "BTCUSDT", interval)
                    self.assertEqual(grace["candle_end"], boundary)
                    self.clock.now += 2
                    closed = self.adapter.fetch_chart(exchange, "BTCUSDT", interval)
                    self.assertEqual(closed["candle_end"], boundary+step)

                    def old_series(venue, kind, packet):
                        if kind != 2:
                            return packet
                        rows = packet if venue in ("binance", "gate") else packet["result"]["list"] if venue == "bybit" else packet["data"]
                        for row in rows:
                            if venue == "gate":
                                row["t"] -= 2*step
                            else:
                                row[0] = str(int(row[0])-2*step*1000)
                        return packet
                    self.fixture.mutate = old_series
                    try:
                        with self.assertRaises(ValueError):
                            self.adapter.fetch_chart(exchange, "BTCUSDT", interval)
                    finally:
                        self.fixture.mutate = None

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
        for kind, ttl, call in (("catalog", 5, lambda: self.adapter.exchange_snapshot("binance")),
                                ("chart", 30, lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1"))):
            packet = await_snapshot(call)
            count = len(self.fixture.calls)
            self.clock.advance(1)
            self.assertEqual(call()["status"], "ok")
            self.assertEqual(len(self.fixture.calls), count)
            self.clock.advance(ttl)
            refreshed = await_snapshot(call, updated_after=packet["updated"])
            self.assertGreater(refreshed["updated"], packet["updated"])
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1")
        packet = await_snapshot(call)
        self.clock.advance(25)  # crosses next minute while chart TTL is fresh
        if int((self.clock.now - 2) // 60) * 60 > packet["candle_end"]:
            self.assertEqual(call()["status"], "pending")
            self.assertGreater(await_snapshot(call)["candle_end"], packet["candle_end"])

    def test_next_boundary_refreshes_before_chart_ttl_and_preserves_original_pending_stamps(self):
        boundary = int(self.clock.now//60)*60
        self.clock.now = boundary+59
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1")
        original = await_snapshot(call)
        self.assertEqual(original["next_refresh_at"], boundary+62)
        release = threading.Event()
        def delayed(exchange, path, params):
            if path == PATHS[exchange][2]:
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed
        try:
            self.clock.advance(4)
            pending = call()
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["refresh_reason"], "awaiting_close")
            self.assertEqual(pending["updated"], original["updated"])
            self.assertEqual(pending["source_ts"], original["source_ts"])
            self.assertEqual(pending["candle_end"], original["candle_end"])
        finally:
            release.set()
        current = await_snapshot(call)
        self.assertEqual(current["candle_end"], original["candle_end"]+60)

    def test_all_venues_short_publication_delay_retries_only_once_per_second_then_recovers(self):
        for exchange in EXCHANGES:
            with self.subTest(exchange=exchange):
                boundary = int(self.clock.now//60)*60
                self.clock.now = boundary+59
                call = lambda: self.adapter.chart_snapshot(exchange, "BTCUSDT", "1")
                original = await_snapshot(call)
                def unpublished(venue, kind, packet):
                    if kind != 2:
                        return packet
                    rows = packet if venue in ("binance", "gate") else packet["result"]["list"] if venue == "bybit" else packet["data"]
                    for index, row in enumerate(rows):
                        opening = row['t'] if venue == "gate" else float(row[0])/1000
                        if opening == boundary:
                            if venue == "okx":
                                row[8] = "0"  # newest expected close still unconfirmed
                            else:
                                del rows[index]
                            break
                    return packet
                self.fixture.mutate = unpublished
                self.clock.advance(4)
                call()
                await_idle(self.adapter)
                pending = call()
                self.assertEqual(pending["status"], "pending")
                self.assertTrue(pending["stale"])
                self.assertIsNone(pending["error"])
                self.assertEqual(pending["refresh_reason"], "awaiting_close")
                self.assertEqual(pending["retry_after_seconds"], 1)
                self.assertEqual(pending["updated"], original["updated"])
                self.assertEqual(pending["candle_end"], original["candle_end"])
                reads = lambda: len([c for c in self.fixture.calls if c[0] == exchange and c[1] == PATHS[exchange][2]])
                count = reads()
                for _ in range(20):
                    call()
                self.clock.advance(.5)
                call()
                self.assertEqual(reads(), count, 'polls cannot bypass the publication retry bound')
                self.clock.advance(.5)
                call()
                await_idle(self.adapter)
                self.assertEqual(reads(), count+1)
                self.fixture.mutate = None
                self.clock.advance(1)
                latest = await_snapshot(call)
                self.assertEqual(latest["candle_end"], original["candle_end"]+60)
                self.assertTrue(all(c["t"]+60 <= latest["candle_end"] for c in latest["candles"]))

    def test_publication_delay_does_not_hide_older_gaps_rollbacks_or_prolonged_missing_close(self):
        boundary = int(self.clock.now//60)*60
        self.clock.now = boundary+59
        call = lambda: self.adapter.chart_snapshot("binance", "BTCUSDT", "1")
        original = await_snapshot(call)
        self.fixture.mutate = lambda ex, kind, packet: packet[:-2] if kind == 2 else packet
        self.clock.advance(4)
        call()
        await_idle(self.adapter)
        self.assertEqual(call()["refresh_reason"], "awaiting_close")
        self.clock.advance(8)
        call()
        await_idle(self.adapter)
        stale = call()
        self.assertEqual(stale["status"], "error")
        self.assertIsNone(stale["refresh_reason"])
        self.assertEqual(stale["retry_after_seconds"], 5)
        self.assertEqual(stale["updated"], original["updated"])

        self.fixture.mutate = None
        self.clock.now = boundary+63
        current = self.adapter.fetch_chart("bybit", "BTCUSDT", "1")
        def older(ex, kind, packet):
            if kind == 2:
                packet['result']['list'] = packet['result']['list'][2:]
            return packet
        self.fixture.mutate = older
        with self.assertRaisesRegex(ValueError, "backwards"):
            self.adapter.fetch_chart("bybit", "BTCUSDT", "1")
        self.assertEqual(current["candle_end"], boundary+60)
        self.fixture.mutate = lambda ex, kind, packet: packet[:-3] if kind == 2 else packet
        with self.assertRaisesRegex(ValueError, "stale"):
            self.adapter.fetch_chart("binance", "BTCUSDT", "1")

    def test_close_published_after_short_window_is_verified_without_extra_artificial_backoff(self):
        boundary = int(self.clock.now//60)*60
        self.clock.now = boundary+59
        call = lambda: self.adapter.chart_snapshot('binance', 'BTCUSDT', '1')
        original = await_snapshot(call)
        self.fixture.mutate = lambda ex, kind, packet: packet[:-2] if kind == 2 else packet
        self.clock.advance(4)
        call()
        await_idle(self.adapter)
        self.assertEqual(call()['refresh_reason'], 'awaiting_close')
        self.fixture.mutate = None
        self.clock.advance(8)
        latest = await_snapshot(call)
        self.assertEqual(latest['candle_end'], original['candle_end']+60)
        self.assertGreater(latest['updated'], original['updated'])

    def test_new_close_publication_window_does_not_relax_other_series_validation(self):
        self.clock.now = int(self.clock.now//60)*60+3
        for mutation in ('gap', 'duplicate', 'nan', 'future'):
            self.clock.now = int(self.clock.now//60)*60+3
            def broken(ex, kind, packet):
                if kind != 2:
                    return packet
                del packet[-2]  # expected newest close missing, within grace
                if mutation == 'gap':
                    del packet[30]
                elif mutation == 'duplicate':
                    packet[30] = deepcopy(packet[31])
                elif mutation == 'nan':
                    packet[30][5] = 'NaN'
                else:
                    packet[-1][0] += 600_000
                return packet
            self.fixture.mutate = broken
            call = lambda: self.adapter.chart_snapshot('binance', 'BTCUSDT', '1')
            with self.subTest(mutation=mutation):
                call()
                await_idle(self.adapter)
                failed = call()
                self.assertEqual(failed['status'], 'error')
                self.assertIsNone(failed['refresh_reason'])
                self.assertGreater(failed['retry_after_seconds'], 1)
                self.clock.advance(6)
        self.clock.now = int(self.clock.now//60)*60+3
        def old_unconfirmed(ex, kind, packet):
            if kind == 2:
                packet['data'][30][8] = '0'
            return packet
        self.fixture.mutate = old_unconfirmed
        with self.assertRaisesRegex(ValueError, 'historical candle is unconfirmed'):
            self.adapter.fetch_chart('okx', 'BTCUSDT', '1')

    def test_current_chart_refresh_retains_proof_but_receipt_age_is_bounded(self):
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "5")
        original = await_snapshot(call)
        release = threading.Event()
        def delayed(exchange, path, params):
            if path == PATHS[exchange][2]:
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed
        try:
            self.clock.advance(31)
            current = call()
            self.assertEqual(current["status"], "ok")
            self.assertFalse(current["stale"])
            self.assertTrue(current["refreshing"])
            self.assertEqual(current["updated"], original["updated"])
            self.assertEqual(current["candle_end"], original["candle_end"])
            self.assertEqual(current["source_ts"], original["source_ts"])
            self.clock.advance(45)
            expired = call()
            self.assertEqual(expired["status"], "pending")
            self.assertTrue(expired["stale"])
            self.assertEqual(expired["updated"], original["updated"])
        finally:
            release.set()

    def test_refresh_proof_never_survives_next_close_or_failed_revalidation(self):
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "1")
        original = await_snapshot(call)
        release = threading.Event()
        def delayed(exchange, path, params):
            if path == PATHS[exchange][2]:
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed
        try:
            self.clock.advance(31)
            self.assertEqual(call()["status"], "ok")
            self.clock.advance(15)  # receipt <75s, but a new bar must be proved
            pending = call()
            self.assertEqual(pending["status"], "pending")
            self.assertTrue(pending["stale"])
            self.assertEqual(pending["candle_end"], original["candle_end"])
            self.fixture.fail = True
        finally:
            release.set()
        failed = await_snapshot(call, "error")
        self.assertTrue(failed["stale"])
        self.assertFalse(failed["refreshing"])
        self.assertEqual(failed["updated"], original["updated"])
        self.fixture.fail = False
        self.clock.advance(6)
        recovered = await_snapshot(call)
        self.assertGreater(recovered["candle_end"], original["candle_end"])

    def test_catalog_refresh_keeps_original_proof_with_short_source_age_guard(self):
        call = lambda: self.adapter.exchange_snapshot("bybit")
        original = await_snapshot(call)
        release = threading.Event()
        def delayed(exchange, path, params):
            if path == PATHS[exchange][1]:
                release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = delayed
        try:
            self.clock.advance(46)
            refreshing = call()
            self.assertEqual(refreshing["status"], "ok")
            self.assertTrue(refreshing["refreshing"])
            self.assertFalse(refreshing["stale"])
            self.assertEqual(refreshing["source_ts"], original["source_ts"])
            self.assertEqual(refreshing["updated"], original["updated"])
            self.clock.advance(15)
            self.assertEqual(call()["status"], "pending")
        finally:
            release.set()

    def test_failed_chart_refresh_rejects_even_same_boundary_recent_proof(self):
        call = lambda: self.adapter.chart_snapshot("bybit", "BTCUSDT", "5")
        original = await_snapshot(call)
        self.clock.advance(31)
        self.fixture.fail = True
        failed = await_snapshot(call, "error")
        self.assertTrue(failed["stale"])
        self.assertEqual(failed["candle_end"], original["candle_end"])
        self.assertEqual(failed["updated"], original["updated"])
        self.assertLess(self.clock.now - failed["updated"], 75)
        # Repeated polling cannot clear a failure before new verification.
        self.assertEqual(call()["status"], "error")
        self.fixture.fail = False
        self.clock.advance(6)
        recovered = await_snapshot(call)
        self.assertGreater(recovered["updated"], original["updated"])
        self.assertEqual(recovered["candle_end"], original["candle_end"])

    def test_snapshots_return_immediately_and_pool_and_queue_are_bounded(self):
        release, active = threading.Event(), threading.Event()
        def request(exchange, path, params):
            active.set()
            release.wait(2)
            return self.fixture.request(exchange, path, params)
        self.adapter._request = request
        start = time.monotonic()
        packets = [self.adapter.book_snapshot("bybit", f"C{i}USDT") for i in range(20)]
        # A density scan cannot fill the chart admission slots. Requests for
        # visible candles are admitted while both HTTP workers are occupied.
        packets += [self.adapter.chart_snapshot("bybit", "BTCUSDT", interval) for interval in ("1", "5")]
        self.assertLess(time.monotonic() - start, 0.2)
        self.assertTrue(all(packet["status"] == "pending" for packet in packets))
        self.assertTrue(active.wait(1))
        with self.adapter._lock:
            self.assertEqual(self.adapter._outstanding, 4)
            self.assertEqual(self.adapter._nonchart_outstanding, 2)
            self.assertEqual(sum(entry["pending"] for entry in self.adapter._cache["book"].values()), 2)
            self.assertEqual(sum(entry["pending"] for entry in self.adapter._cache["chart"].values()), 2)
        self.adapter.book_snapshot("bybit", "C0USDT")
        self.adapter.chart_snapshot("bybit", "BTCUSDT", "1")
        self.assertEqual(self.adapter._outstanding, 4)  # pending jobs are reused
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
