"""Production Kronos HTTP routes with fake clocks, exchange data and inference.

The actual bounded chart cache and stdlib Kronos client are exercised, without
a listening socket, network request, model runtime or order command.
"""
from copy import deepcopy
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/trading-panel"))
import densities
import exchange_data
import kronos_client
import manual_paper
import market_data
from test_exchange_data import Clock, Fixture, await_idle, await_snapshot
from test_kronos import fixture_forecast

SOURCE = dict(exchange="bybit", symbol="BTCUSDT", interval="5")
FORECAST = "/api/kronos/forecast"
QUERY = "?exchange=bybit&symbol=BTCUSDT&interval=5"
CHART = "/api/exchange-chart" + QUERY


class KronosHTTPTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clock.now = int(self.clock.now // 300) * 300 + 17
        self.fixture = Fixture(self.clock)
        self.adapter = exchange_data.ExchangeData(
            request=self.fixture.request, wall_clock=lambda: self.clock.now,
            clock=lambda: self.clock.mono)
        self.addCleanup(self.adapter.close)
        self.adapter.chart_snapshot = Mock(wraps=self.adapter.chart_snapshot)
        self.adapter.peek_chart_snapshot = Mock(wraps=self.adapter.peek_chart_snapshot)
        self.worker_calls, self.jobs = [], {}

        def transport(method, path, payload):
            self.worker_calls.append((method, path, deepcopy(payload)))
            if method == "POST":
                self.assertEqual(path, "/request")
                self.jobs[payload["job_id"]] = fixture_forecast(payload)
                return deepcopy(self.jobs[payload["job_id"]])
            self.assertEqual(method, "GET")
            if path == "/status":
                return kronos_client.response("idle", enabled=True)
            self.assertTrue(path.startswith("/jobs?job_id="))
            return deepcopy(self.jobs.get(path.split("=", 1)[1],
                                          kronos_client.response("idle", enabled=True)))

        self.client = kronos_client.KronosClient(
            transport=transport, wall_clock=lambda: self.clock.now,
            clock=lambda: self.clock.mono)
        spec = importlib.util.spec_from_file_location(
            "kronos_production_http_fixture", ROOT / "src/trading-panel/server.py")
        self.panel = importlib.util.module_from_spec(spec)
        with patch.object(market_data, "MarketData", return_value=SimpleNamespace()), \
                patch.object(manual_paper, "ManualPaper", return_value=SimpleNamespace()), \
                patch.object(exchange_data, "get_exchange_data", return_value=self.adapter), \
                patch.object(densities, "DensityMonitor", return_value=SimpleNamespace()), \
                patch.object(kronos_client, "KronosClient", return_value=self.client):
            spec.loader.exec_module(self.panel)

    def request(self, path, method="GET"):
        class Capture(self.panel.Handler):
            def send(self, code, body, content_type):
                self.result = code, json.loads(body), content_type

        handler = Capture.__new__(Capture)
        handler.path, handler.headers = path, {"Host": "127.0.0.1:8787"}
        if method == "POST":
            body = json.dumps(SOURCE).encode()
            handler.headers.update({"Content-Type": "application/json",
                                    "Content-Length": str(len(body)),
                                    "X-Lab-Control": self.panel.control_client.TOKEN,
                                    "Sec-Fetch-Site": "same-origin"})
            handler.rfile = BytesIO(body)
            handler.do_POST()
        else:
            handler.do_GET()
        self.assertEqual(handler.result[0], 202 if method == "POST" else 200)
        return handler.result[1]

    def verified_chart(self):
        self.request(CHART)
        await_idle(self.adapter)
        return await_snapshot(lambda: self.request(CHART))

    def model_posts(self):
        return [call for call in self.worker_calls if call[0] == "POST"]

    def test_cold_forecast_get_only_peeks_without_market_or_model_admission(self):
        for _ in range(3):
            packet = self.request(FORECAST + QUERY)
            self.assertEqual(packet["status"], "pending")
            self.assertEqual(packet["forecast"], [])
            self.assertFalse(packet["accepted"])
        self.assertEqual(self.adapter.peek_chart_snapshot.call_count, 3)
        self.adapter.chart_snapshot.assert_not_called()
        self.assertEqual(self.fixture.calls, [])
        self.assertEqual(self.worker_calls, [])

    def test_source_error_is_preserved_without_readmitting_failed_chart(self):
        self.fixture.fail = True
        self.request(CHART)
        await_idle(self.adapter)
        previous_calls = len(self.fixture.calls)
        previous_admissions = self.adapter.chart_snapshot.call_count
        for _ in range(3):
            packet = self.request(FORECAST + QUERY)
            self.assertEqual((packet["status"], packet["enabled"]), ("error", True))
            self.assertEqual(packet["error"], "public market request failed")
            self.assertEqual(packet["forecast"], [])
            self.assertEqual(packet["end_close_samples"], [])
            self.assertFalse(packet["accepted"])
        self.assertEqual(len(self.fixture.calls), previous_calls)
        self.assertEqual(self.adapter.chart_snapshot.call_count, previous_admissions)
        self.assertEqual(self.worker_calls, [])

    def test_publication_wait_recovers_only_after_ordinary_chart_refresh(self):
        self.clock.now = int(self.clock.now // 300) * 300 + 3

        def omit_new_close(exchange, kind, packet):
            if kind == 2:
                end = int((self.clock.now - 2) // 300) * 300
                packet["result"]["list"] = [row for row in packet["result"]["list"]
                                               if int(row[0]) / 1000 + 300 != end]
            return packet

        self.fixture.mutate = omit_new_close
        self.request(CHART)
        await_idle(self.adapter)
        previous_calls = len(self.fixture.calls)
        self.fixture.mutate = None
        self.clock.advance(2)
        waiting = self.request(FORECAST + QUERY)
        self.assertEqual(waiting["status"], "pending")
        self.assertIn("свечи", waiting["error"])
        self.assertEqual(len(self.fixture.calls), previous_calls)
        self.assertEqual(self.worker_calls, [])
        self.assertEqual(self.verified_chart()["status"], "ok")
        self.assertEqual(self.request(FORECAST + QUERY)["status"], "idle")
        self.assertEqual(self.model_posts(), [])
        self.assertEqual(self.request(FORECAST, "POST")["status"], "ready")
        self.assertEqual(len(self.model_posts()), 1)

    def test_expired_rest_receipt_recovers_same_forecast_after_actual_chart_refresh(self):
        self.verified_chart()
        original = self.request(FORECAST, "POST")
        self.assertEqual(original["status"], "ready")
        self.clock.advance(76)
        previous_calls = len(self.fixture.calls)
        waiting = self.request(FORECAST + QUERY)
        self.assertEqual((waiting["status"], waiting["forecast"]), ("pending", []))
        self.assertEqual(len(self.fixture.calls), previous_calls)
        self.verified_chart()
        recovered = self.request(FORECAST + QUERY)
        self.assertEqual(recovered["status"], "ready")
        self.assertEqual(recovered["job_id"], original["job_id"])
        self.assertEqual(recovered["source"], original["source"])
        self.assertGreater(recovered["current_source_updated"], original["current_source_updated"])
        self.assertEqual(recovered["expires_at"], original["expires_at"])
        self.assertEqual(len(self.model_posts()), 1)

    def test_failed_revalidation_hides_ready_forecast_until_new_rest_proof(self):
        self.verified_chart()
        original = self.request(FORECAST, "POST")
        self.clock.advance(31)
        self.fixture.fail = True
        self.request(CHART)
        await_idle(self.adapter)
        failed = self.request(FORECAST + QUERY)
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["error"], "public market request failed")
        self.assertEqual(failed["forecast"], [])
        self.clock.advance(6)
        self.fixture.fail = False
        self.verified_chart()
        recovered = self.request(FORECAST + QUERY)
        self.assertEqual(recovered["status"], "ready")
        self.assertEqual(recovered["job_id"], original["job_id"])
        self.assertEqual(len(self.model_posts()), 1)

    def test_async_chart_revalidation_requires_another_forecast_read_to_receive_new_proof(self):
        initial_chart = self.verified_chart()
        original = self.request(FORECAST, "POST")
        self.clock.advance(28)
        still_current = self.request(CHART)
        self.assertFalse(still_current["refreshing"])
        self.assertEqual(still_current["updated"], initial_chart["updated"])
        previous_rest_calls = len(self.fixture.calls)
        started, release = threading.Event(), threading.Event()
        original_request = self.adapter._request

        def delayed(exchange, path, params):
            if path == exchange_data.PATHS[exchange][2]:
                started.set()
                if not release.wait(timeout=2):
                    raise AssertionError("Fixture chart release missing")
            return original_request(exchange, path, params)

        self.adapter._request = delayed
        try:
            self.clock.advance(30)
            refreshing = self.request(CHART)
            self.assertTrue(started.wait(timeout=1))
            self.assertTrue(refreshing["refreshing"])
            self.assertEqual(refreshing["updated"], initial_chart["updated"])
            held = self.request(FORECAST + QUERY)
            self.assertEqual(held["status"], "ready")
            self.assertEqual(held["current_source_updated"], initial_chart["updated"])
            self.clock.advance(1)
        finally:
            release.set()
        await_idle(self.adapter)
        self.assertEqual(len(self.fixture.calls), previous_rest_calls + 1)
        # The HTTP response already held by a browser does not change when
        # the asynchronous REST job finishes. Its own proof still expires.
        self.clock.advance(17)
        self.assertGreater(self.clock.now - held["current_source_updated"], 75)
        self.assertEqual(self.client.snapshot(initial_chart)["status"], "stale")
        previous_admissions = self.adapter.chart_snapshot.call_count
        current = self.request(FORECAST + QUERY)
        self.assertEqual(current["status"], "ready")
        self.assertGreater(current["current_source_updated"], held["current_source_updated"])
        self.assertEqual(current["source"], original["source"])
        self.assertEqual(current["job_id"], original["job_id"])
        self.assertEqual(self.adapter.chart_snapshot.call_count, previous_admissions)
        self.assertEqual(len(self.model_posts()), 1)

    def test_new_closed_boundary_cannot_reuse_or_resubmit_old_forecast(self):
        self.verified_chart()
        original = self.request(FORECAST, "POST")
        self.clock.advance(300)
        waiting = self.request(FORECAST + QUERY)
        self.assertEqual((waiting["status"], waiting["forecast"]), ("pending", []))
        self.verified_chart()
        current = self.request(FORECAST + QUERY)
        self.assertEqual((current["status"], current["forecast"]), ("idle", []))
        self.assertGreater(current["source"]["candle_end"], original["source"]["candle_end"])
        self.assertNotEqual(current["job_id"], original["job_id"])
        self.assertEqual(len(self.model_posts()), 1)


if __name__ == "__main__":
    unittest.main()
