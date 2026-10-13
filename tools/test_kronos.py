"""Offline contract fixtures. No real model, weights, exchange data or accuracy claims."""
from copy import deepcopy
from email.message import Message
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/trading-panel"))
import kronos_client as client_module
from kronos_client import KronosClient, packet_request, response, HORIZON, SCENARIOS
spec = importlib.util.spec_from_file_location("kronos_contract_worker", ROOT / "integrations/kronos/worker.py")
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Clock:
    now = 1_800_000_017.0
    mono = 100.0

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds


def fixture_packet(clock, symbol="BTCUSDT", count=130):
    end = int((clock.now - 2) // 300) * 300
    bars = [dict(t=end - (count - i) * 300, open=100 + i / 1000,
                 close=100.5 + i / 1000, high=102 + i / 1000,
                 low=99 + i / 1000, volume=10 + i, turnover=1000 + i * 100)
            for i in range(count)]
    return dict(status="ok", stale=False, exchange="bybit", symbol=symbol,
                native_symbol=symbol, interval="5", updated=clock.now,
                source_ts=end, candle_end=end, timestamp_origin="closed_candle", candles=bars)


def fixture_forecast(request):
    last = request["candles"][-1]["close"]
    samples = [last + i / 10 for i in range(SCENARIOS)]
    return response("ready", enabled=True, source=request["source"], job_id=request["job_id"],
                    seed=request["seed"], input_last_close=last, lookback=len(request["candles"]),
                    inference_ms=12.5, completed_at=request["source"]["updated"] + 1,
                    end_close_samples=samples,
                    forecast=[dict(time=request["source"]["candle_end"] + i * 300,
                                   low=samples[0], median=samples[2], high=samples[-1]) for i in range(HORIZON)])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.packet = fixture_packet(self.clock)
        self.request = packet_request(self.packet, self.clock.now)
        self.calls = []
        self.result = fixture_forecast(self.request)

        def transport(method, path, payload):
            self.calls.append((method, path, deepcopy(payload)))
            if path == "/status":
                return response("idle", enabled=True)
            return deepcopy(self.result)
        self.client = KronosClient(transport=transport, wall_clock=lambda: self.clock.now, clock=lambda: self.clock.mono)

    def test_get_only_reads_and_repeated_get_is_cached(self):
        self.assertEqual(self.client.status()["status"], "idle")
        self.assertEqual(self.client.snapshot(self.packet)["status"], "ready")
        self.client.snapshot(self.packet)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(method == "GET" for method, _, _ in self.calls))

    def test_explicit_request_is_the_only_post(self):
        result = self.client.request(self.packet)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(self.calls[0][0:2], ("POST", "/request"))
        self.assertEqual(len(self.calls[0][2]["candles"]), 120)
        self.assertEqual(result["source"]["updated"], self.packet["updated"])
        self.assertEqual(result["current_source_updated"], self.packet["updated"])
        self.assertEqual(result["expires_at"], self.packet["candle_end"] + 302)

    def test_fresh_identical_rest_proof_admits_original_input_after_100s(self):
        self.clock.advance(100)
        self.packet["updated"] = self.clock.now
        result = self.client.snapshot(self.packet)
        self.assertEqual(result["status"], "ready")
        self.assertLess(result["source"]["updated"], result["current_source_updated"])

    def test_stale_candle_boundary_and_receipt_block_even_cached_result(self):
        self.client.snapshot(self.packet)
        self.clock.advance(80)
        self.assertEqual(self.client.snapshot(self.packet)["status"], "stale")
        self.packet["updated"] = self.clock.now
        self.clock.advance(230)
        self.assertEqual(self.client.snapshot(self.packet)["status"], "stale")
        self.assertEqual(len(self.calls), 1)

    def test_changed_prices_same_end_and_other_source_cannot_reuse_result(self):
        for mutation in (lambda p: p["candles"][-1].update(close=100.8),
                         lambda p: p.update(exchange="binance")):
            packet = deepcopy(self.packet)
            mutation(packet)
            result = self.client.snapshot(packet)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["forecast"], [])

    def test_bad_versions_disagreement_samples_and_nonfinite_price_hidden(self):
        for mutation in (lambda p: p.update(model_revision="different"),
                         lambda p: p["end_close_samples"].__setitem__(0, 999.0),
                         lambda p: p["forecast"][0].update(median=float("nan")),
                         lambda p: p.update(input_last_close=99.0)):
            self.result = fixture_forecast(self.request)
            mutation(self.result)
            self.client.cache.clear()
            result = self.client.snapshot(self.packet)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["forecast"], [])

    def test_demo_unconfirmed_discontinuous_or_wrong_native_not_submitted(self):
        mutations = (lambda p: p.update(demo=True), lambda p: p.update(stale=True),
                     lambda p: p.update(native_symbol="ETHUSDT"),
                     lambda p: p["candles"][-2].update(t=p["candles"][-1]["t"]),
                     lambda p: p["candles"][-1].update(volume=-1),
                     lambda p: p.update(updated=self.clock.now + 10))
        for mutation in mutations:
            packet = deepcopy(self.packet)
            mutation(packet)
            self.assertEqual(self.client.request(packet)["status"], "stale")
        self.assertEqual(self.calls, [])

    def test_hash_ignores_revalidation_timestamp_and_older_unselected_bars(self):
        packet = deepcopy(self.packet)
        packet["updated"] += 1
        packet["candles"][0]["close"] += 0.1
        self.assertEqual(packet_request(packet, self.clock.now)["job_id"], self.request["job_id"])
        packet["candles"][-1]["turnover"] += 1
        self.assertNotEqual(packet_request(packet, self.clock.now)["job_id"], self.request["job_id"])


class ContractFixtureEngine:
    """Deliberately fake engine for queue/lifecycle tests, never a model forecast."""
    def __init__(self, runtime):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.closed = False

    def predict(self, request):
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("fixture release missing")
        result = fixture_forecast(request)
        return {k: result[k] for k in ("status", "job_id", "forecast", "end_close_samples", "inference_ms")}

    def close(self):
        self.closed = True
        self.release.set()


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.engine = ContractFixtureEngine(None)
        self.jobs = worker.ForecastJobs("unused-fixture", engine_factory=lambda runtime: self.engine,
                                        wall_clock=lambda: self.clock.now)
        with self.jobs.condition:
            self.assertTrue(self.jobs.condition.wait_for(lambda: self.jobs.phase == "idle", timeout=1))

    def tearDown(self):
        self.jobs.close()

    def request(self, symbol):
        return packet_request(fixture_packet(self.clock, symbol), self.clock.now)

    def test_one_active_two_queued_and_cache_eight(self):
        first = self.request("BTCUSDT")
        self.jobs.request(first)
        self.assertTrue(self.engine.started.wait(1))
        self.assertEqual(self.jobs.get(first["job_id"])["status"], "loading")
        for symbol in ("ETHUSDT", "SOLUSDT"):
            self.assertEqual(self.jobs.request(self.request(symbol))["status"], "queued")
        self.assertEqual(self.jobs.request(self.request("XRPUSDT"))["status"], "error")
        self.assertEqual(self.engine.calls, 1)
        self.assertEqual(self.jobs.status()["queued_jobs"], 2)
        self.engine.release.set()
        with self.jobs.condition:
            self.assertTrue(self.jobs.condition.wait_for(lambda: self.jobs.active is None and not self.jobs.waiting, timeout=1))
        for i in range(12):
            request = self.request("C" + str(i) + "USDT")
            self.jobs.request(request)
            deadline = time.monotonic() + 1
            while self.jobs.get(request["job_id"])["status"] != "ready" and time.monotonic() < deadline:
                time.sleep(0.005)
        self.assertEqual(len(self.jobs.jobs), 8)
        self.assertEqual(self.jobs.get(first["job_id"])["status"], "idle")

    def test_unknown_get_does_not_start_work_and_duplicate_post_deduplicates(self):
        request = self.request("BTCUSDT")
        self.assertEqual(self.jobs.get(request["job_id"])["status"], "idle")
        self.assertEqual(self.engine.calls, 0)
        self.jobs.request(request)
        self.assertTrue(self.engine.started.wait(1))
        self.jobs.request(request)
        self.assertEqual(len(self.jobs.waiting), 0)
        self.assertEqual(self.engine.calls, 1)

    def test_new_closed_boundary_discards_completion(self):
        request = self.request("BTCUSDT")
        self.jobs.request(request)
        self.assertTrue(self.engine.started.wait(1))
        self.clock.advance(300)
        self.engine.release.set()
        deadline = time.monotonic() + 1
        while self.jobs.active and time.monotonic() < deadline:
            time.sleep(0.005)
        result = self.jobs.get(request["job_id"])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["forecast"], [])

    def test_http_token_origin_host_paths_and_no_job_admission_by_get(self):
        # Offline handler contract, with parsed HTTP headers; no local listener.
        server = SimpleNamespace(jobs=self.jobs, token="a" * 43)

        def get(path, headers):
            handler = worker.Handler.__new__(worker.Handler)
            handler.server, handler.path, handler.headers = server, path, Message()
            for key, value in headers.items():
                handler.headers[key] = value
            sent = []
            handler.send = lambda code, value: sent.append((code, value))
            handler.do_GET()
            return sent[0]
        allowed = {"Host": "127.0.0.1:8790", "X-Kronos-Token": server.token}
        self.assertEqual(get("/status", allowed)[0], 200)
        self.assertEqual(get("/status", dict(allowed, Origin="https://example.com"))[0], 403)
        self.assertEqual(get("/status", dict(allowed, Host="evil.example"))[0], 403)
        self.assertEqual(get("/status", {"Host": "127.0.0.1:8790"})[0], 403)
        self.assertEqual(get("/jobs?job_id=" + "f" * 64, allowed)[1]["status"], "idle")
        self.assertEqual(get("/jobs?job_id=" + "f" * 64 + "&job_id=" + "f" * 64, allowed)[0], 400)
        self.assertEqual(get("/unknown", allowed)[0], 404)
        self.assertEqual(get("http://example.com/status", allowed)[0], 400)
        self.assertEqual(self.engine.calls, 0)

    def test_startup_timeout_kills_model_child(self):
        class BlockingOutput:
            def __init__(self):
                self.release = threading.Event()
            def readline(self, limit):
                self.release.wait(1)
                return ""
            def close(self):
                self.release.set()

        class FakeProcess:
            def __init__(self):
                self.stdin, self.stdout = io.StringIO(), BlockingOutput()
                self.killed = False
            def poll(self):
                return 0 if self.killed else None
            def kill(self):
                self.killed = True
                self.stdout.release.set()
            def wait(self, timeout):
                return 0
        process = FakeProcess()
        with patch.object(worker, "TIMEOUT", 0.02), patch.object(worker.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "120"):
                worker.ModelProcess("unused-fixture")
        self.assertTrue(process.killed)


if __name__ == "__main__":
    unittest.main()
