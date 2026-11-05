"""Local assistant HTTP contract, using explicitly fake collaborators only.

These tests start an ephemeral loopback listener. They never construct a market
pool, download candles or weights, run inference, or issue an order command.
"""
from copy import deepcopy
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/trading-panel"))
from exchange_data import _exchange, _interval, _symbol
from kronos_client import response

spec = importlib.util.spec_from_file_location("public_assistant_contract", ROOT / "tools/serve_public.py")
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)

SOURCE = dict(exchange="bybit", symbol="BTCUSDT", interval="5")
FORECAST_PATH = "/api/kronos/forecast"
QUERY_PATH = FORECAST_PATH + "?exchange=bybit&symbol=BTCUSDT&interval=5"


class FakeExchange:
    """An in-memory routing fixture; neither method creates a fetch job."""
    def __init__(self):
        self.peeks, self.charts = [], []
        self.packet = dict(status="pending", queued=True, fixture_only=True)
        self.admission_available = True

    def _source(self, exchange, symbol, interval):
        return (_exchange(exchange), _symbol(symbol), _interval(interval))

    def peek_chart_snapshot(self, exchange, symbol, interval):
        self.peeks.append(self._source(exchange, symbol, interval))
        return deepcopy(self.packet)

    def chart_snapshot(self, exchange, symbol, interval):
        self.charts.append(self._source(exchange, symbol, interval))
        packet = deepcopy(self.packet)
        if packet.get("status") == "pending":
            packet["queued"] = self.admission_available
        return packet


class FakeKronos:
    """Only records routing; returns no fabricated prices or model forecast."""
    def __init__(self):
        self.snapshots, self.requests = [], []
        self.status_reads = 0
        self.state = response("idle", enabled=True, fixture_only=True)

    def status(self):
        self.status_reads += 1
        return deepcopy(self.state)

    def snapshot(self, packet):
        self.snapshots.append(deepcopy(packet))
        return response("idle", enabled=True, fixture_only=True)

    def request(self, packet):
        self.requests.append(deepcopy(packet))
        return response("queued", enabled=True, accepted=True, fixture_only=True)


class UnusedFixture:
    def __getattr__(self, name):
        raise AssertionError("Unexpected public data dispatch: " + name)


class PublicAssistantHTTPTests(unittest.TestCase):
    def setUp(self):
        self.exchange, self.kronos = FakeExchange(), FakeKronos()
        try:
            self.server = public.PublicHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        except PermissionError:
            self.skipTest("Local sockets unavailable; runs in CI")
        self.port = self.server.server_port
        self.server.RequestHandlerClass = public.build_handler(
            self.exchange, UnusedFixture(), UnusedFixture(), self.kronos, self.port)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        code, _, status = self.request("GET", "/api/kronos/status")
        self.assertEqual(code, 200)
        self.token = status["token"]

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, payload=None, *, headers=None, raw=None):
        given = {"Host": f"127.0.0.1:{self.port}"}
        if method == "POST":
            given.update({"Content-Type": "application/json", "X-Lab-Control": self.token,
                          "Sec-Fetch-Site": "same-origin"})
        given.update(headers or {})
        body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        connection = HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=given)
            result = connection.getresponse()
            content = result.read()
            data = json.loads(content) if result.getheader("Content-Type", "").startswith("application/json") else content.decode()
            return result.status, dict(result.getheaders()), data
        finally:
            connection.close()

    def assert_no_jobs(self):
        self.assertEqual(self.exchange.charts, [])
        self.assertEqual(self.kronos.requests, [])

    def test_forecast_get_only_peeks_even_when_verified_chart_is_present(self):
        code, _, data = self.request("GET", QUERY_PATH)
        self.assertEqual((code, data["status"], data["forecast"]), (200, "pending", []))
        self.assertEqual(self.kronos.snapshots, [])
        self.exchange.packet = dict(status="ok", fixture_only=True)
        code, _, data = self.request("GET", QUERY_PATH)
        self.assertEqual((code, data["status"]), (200, "idle"))
        self.assertEqual(self.exchange.peeks, [("bybit", "BTCUSDT", "5")] * 2)
        self.assertEqual(self.kronos.snapshots, [self.exchange.packet])
        self.assert_no_jobs()

    def test_explicit_authenticated_post_warms_pending_chart_without_forecast(self):
        code, _, data = self.request("POST", FORECAST_PATH, SOURCE)
        self.assertEqual((code, data["status"]), (202, "pending"))
        self.assertEqual(self.exchange.charts, [("bybit", "BTCUSDT", "5")])
        self.assertEqual(self.exchange.peeks, [])
        self.assertEqual(self.kronos.requests, [])
        self.assertEqual(data["forecast"], [])
        self.assertEqual(data["end_close_samples"], [])
        self.assertFalse(data["accepted"])

    def test_forecast_get_preserves_source_error_without_warming_or_submitting(self):
        for reason in ("closed candle series is stale", None):
            with self.subTest(reason=reason):
                self.exchange.packet = dict(status="error", queued=False, error=reason, fixture_only=True)
                code, _, data = self.request("GET", QUERY_PATH)
                self.assertEqual((code, data["status"], data["enabled"]), (200, "error", True))
                self.assertEqual(data["error"], reason or "Источник свечей недоступен")
                self.assertEqual(data["forecast"], [])
                self.assertEqual(data["end_close_samples"], [])
                self.assertFalse(data["accepted"])
                self.assertEqual(self.kronos.snapshots, [])
                self.assert_no_jobs()

    def test_refused_chart_admission_errors_and_get_never_retries_even_after_slots_free(self):
        for source_error in (None, "Fixture chart queue refused"):
            with self.subTest(source_error=source_error):
                self.exchange.packet = dict(status="pending", queued=False,
                                            error=source_error, fixture_only=True)
                self.exchange.admission_available = False
                previous_charts = len(self.exchange.charts)
                code, _, data = self.request("POST", FORECAST_PATH, SOURCE)
                self.assertEqual((code, data["status"], data["enabled"]), (202, "error", True))
                self.assertEqual(data["error"], source_error or "Очередь свечей занята. Повторите отбор.")
                self.assertEqual(data["forecast"], [])
                self.assertEqual(data["end_close_samples"], [])
                self.assertFalse(data["accepted"])
                self.assertEqual(len(self.exchange.charts), previous_charts + 1)
                previous_peeks = len(self.exchange.peeks)
                for available in (False, True):
                    self.exchange.admission_available = available
                    code, _, data = self.request("GET", QUERY_PATH)
                    self.assertEqual((code, data["status"], data["forecast"]), (200, "pending", []))
                    self.assertEqual(len(self.exchange.charts), previous_charts + 1)
                    self.assertEqual(self.kronos.requests, [])
                self.assertEqual(len(self.exchange.peeks), previous_peeks + 2)
                self.assertEqual(self.kronos.snapshots, [])

    def test_verified_chart_post_admits_model_exactly_once(self):
        self.exchange.packet = dict(status="ok", fixture_only=True)
        code, _, data = self.request("POST", FORECAST_PATH, SOURCE)
        self.assertEqual((code, data["status"], data["accepted"]), (202, "queued", True))
        self.assertEqual(self.exchange.charts, [("bybit", "BTCUSDT", "5")])
        self.assertEqual(self.kronos.requests, [self.exchange.packet])
        self.assertEqual(self.kronos.snapshots, [])
        self.assertEqual(data["forecast"], [])

    def test_unavailable_model_does_not_warm_chart(self):
        self.kronos.state = response("unavailable", enabled=False, fixture_only=True)
        code, _, data = self.request("POST", FORECAST_PATH, SOURCE)
        self.assertEqual((code, data["status"]), (202, "unavailable"))
        self.assert_no_jobs()

    def test_invalid_host_and_forecast_query_reject_before_source_dispatch(self):
        invalid = (QUERY_PATH + "&symbol=ETHUSDT", QUERY_PATH + "&source=demo",
                   FORECAST_PATH + "?exchange=bybit&symbol=BTCUSDT",
                   FORECAST_PATH + "?exchange=bybit&symbol=BTCUSDT&interval=5&extra=" + "x" * 3001)
        for path in invalid:
            with self.subTest(path=path[:90]):
                self.assertEqual(self.request("GET", path)[0], 400)
        self.assertEqual(self.request("GET", QUERY_PATH, headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/api/kronos/status?extra=1")[0], 400)
        self.assertEqual(self.exchange.peeks, [])
        self.assert_no_jobs()

    def test_rejected_auth_origin_size_and_source_never_admit_jobs(self):
        before_status_reads = self.kronos.status_reads
        for change in ({"X-Lab-Control": "invalid"}, {"X-Lab-Control": ""},
                       {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                       {"Origin": "null"}, {"Content-Type": "text/plain"},
                       {"Host": "attacker.invalid"}):
            with self.subTest(headers=list(change)):
                self.assertEqual(self.request("POST", FORECAST_PATH, SOURCE, headers=change)[0], 403)
        for payload in (dict(SOURCE, source="demo"), {"symbol": "BTCUSDT"}, [], "BTCUSDT"):
            with self.subTest(payload_type=type(payload).__name__):
                self.assertEqual(self.request("POST", FORECAST_PATH, payload)[0], 400)
        for body in (b"", b"{", b"x" * 4097):
            with self.subTest(body_length=len(body)):
                self.assertEqual(self.request("POST", FORECAST_PATH, raw=body)[0], 400)
        self.assertEqual(self.request("POST", FORECAST_PATH, SOURCE,
                                      headers={"Transfer-Encoding": "chunked"})[0], 400)
        self.assertEqual(self.request("POST", FORECAST_PATH + "?exchange=bybit", SOURCE)[0], 403)
        self.assertEqual(self.kronos.status_reads, before_status_reads)
        self.assert_no_jobs()

    def test_manual_paper_is_unavailable_and_all_order_posts_are_rejected(self):
        code, _, data = self.request("GET", "/api/manual-paper")
        self.assertEqual((code, data["status"]), (200, "unavailable"))
        self.assertNotIn("position", data)
        for path in ("/api/manual-paper", "/api/models-control", "/api/worker", "/api/orders"):
            with self.subTest(path=path):
                self.assertEqual(self.request("POST", path, {"action": "open"})[0], 403)
        self.assert_no_jobs()

    def test_static_assets_are_available_without_demo_and_csp_has_only_public_hosts(self):
        code, headers, html = self.request("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn('src="/density-signals.js"', html)
        self.assertIn('src="/kronos.js"', html)
        self.assertIn('href="/kronos.css"', html)
        self.assertNotIn('data-demo="true"', html)
        self.assertNotIn("СИНТЕТИЧЕСКИЕ ДАННЫЕ", html)
        for path in ("/density-signals.js", "/kronos.js", "/kronos.css"):
            with self.subTest(path=path):
                code, asset_headers, body = self.request("GET", path)
                self.assertEqual(code, 200)
                self.assertTrue(body)
                self.assertEqual(asset_headers["Cache-Control"], "no-store")
        policy = headers["Content-Security-Policy"]
        connect = next(part.strip().split()[1:] for part in policy.split(";")
                       if part.strip().startswith("connect-src "))
        self.assertEqual(set(connect), {"'self'", "wss://stream.bybit.com", "wss://fstream.binance.com",
                                        "wss://ws.okx.com", "wss://fx-ws.gateio.ws", "wss://ws.bitget.com"})
        self.assertNotIn("*", policy)
        self.assertNotIn("unsafe-eval", policy)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assert_no_jobs()


if __name__ == "__main__":
    unittest.main()
