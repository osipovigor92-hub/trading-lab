"""Offline contract fixtures. No real model, weights, exchange data or accuracy claims."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
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
        self.assertEqual(list(self.client.completed), [self.request["job_id"]])

    def test_completed_retention_excludes_input_candles_and_unrelated_worker_fields(self):
        self.result.update(candles=[dict(private_fixture=True)] * 120, request=dict(private_fixture=True))
        self.result["source"] = dict(self.result["source"], unrelated_fixture=[dict(private_fixture=True)] * 120)
        self.client.request(self.packet)
        retained = self.client.completed[self.request["job_id"]]
        self.assertEqual(set(retained), set(response()))
        self.assertEqual(set(retained["source"]), set(self.request["source"]))
        self.assertNotIn("candles", retained)
        self.assertNotIn("request", retained)

    def test_demo_worker_result_is_never_retained_as_an_actual_completed_forecast(self):
        self.result["demo"] = True
        self.assertTrue(self.client.request(self.packet)["demo"])
        self.assertEqual(self.client.completed, {})

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


class CompletedRetentionTests(unittest.TestCase):
    """Real bounded worker/client lifecycle with an explicitly fake engine."""
    def setUp(self):
        self.clock = Clock()
        self.clock.now = int(self.clock.now // 300) * 300 + 17
        self.engine = ContractFixtureEngine(None)
        self.engine.release.set()
        self.jobs = worker.ForecastJobs(
            "unused-fixture", engine_factory=lambda runtime: self.engine,
            wall_clock=lambda: self.clock.now)
        self.addCleanup(self.jobs.close)
        with self.jobs.condition:
            self.assertTrue(self.jobs.condition.wait_for(lambda: self.jobs.phase == "idle", timeout=1))
        self.calls, self.override, self.worker_reads = [], None, []

        def transport(method, path, payload):
            self.calls.append((method, path, deepcopy(payload)))
            if method == "POST":
                self.assertEqual(path, "/request")
                return self.jobs.request(payload)
            self.assertEqual(method, "GET")
            if path == "/status":
                return self.jobs.status()
            self.assertTrue(path.startswith("/jobs?job_id="))
            result = (deepcopy(self.override) if self.override is not None else
                      self.jobs.get(path.split("=", 1)[1]))
            self.worker_reads.append(deepcopy(result))
            return result

        self.client = KronosClient(transport=transport,
                                   wall_clock=lambda: self.clock.now,
                                   clock=lambda: self.clock.mono)

    def posts(self):
        return [call for call in self.calls if call[0] == "POST"]

    def admit(self, symbol):
        packet = fixture_packet(self.clock, symbol)
        queued = self.client.request(packet)
        self.assertIn(queued["status"], ("queued", "ready"))
        with self.jobs.condition:
            self.assertTrue(self.jobs.condition.wait_for(
                lambda: self.jobs.jobs[queued["job_id"]]["result"]["status"] == "ready", timeout=1))
        ready = self.client.snapshot(packet)
        self.assertEqual(ready["status"], "ready")
        self.clock.advance(1.1)
        return ready

    def test_fifteen_results_survive_worker_eight_cache_without_any_get_admission(self):
        originals = {"C" + str(i) + "USDT": self.admit("C" + str(i) + "USDT") for i in range(15)}
        self.assertEqual(len(self.jobs.jobs), 8)
        self.assertEqual(self.jobs.status()["queue_limit"], 2)
        self.assertEqual(len(self.client.completed), 15)
        self.assertLessEqual(len(self.client.cache), 9)
        self.assertEqual(self.engine.calls, 15)
        first = originals["C0USDT"]
        self.assertEqual(self.jobs.get(first["job_id"])["status"], "idle")
        for symbol, original in originals.items():
            current = self.client.snapshot(fixture_packet(self.clock, symbol))
            self.assertEqual(current["status"], "ready")
            for key in ("job_id", "source", "forecast", "completed_at", "inference_ms", "expires_at"):
                self.assertEqual(current[key], original[key], (symbol, key))
            self.assertGreater(current["current_source_updated"], original["current_source_updated"])
        self.assertTrue(any(value["status"] == "idle" for value in self.worker_reads))
        self.assertEqual(len(self.posts()), 15)
        self.assertEqual(self.engine.calls, 15)

    def test_retention_is_bounded_to_sixteen_and_unknown_idle_never_creates_result(self):
        first = self.admit("C0USDT")
        for i in range(1, 17):
            self.admit("C" + str(i) + "USDT")
        self.assertEqual(len(self.client.completed), 16)
        self.assertNotIn(first["job_id"], self.client.completed)
        self.assertEqual(len(self.jobs.jobs), 8)
        for symbol in ("C0USDT", "UNKNOWNUSDT"):
            idle = self.client.snapshot(fixture_packet(self.clock, symbol))
            self.assertEqual((idle["status"], idle["forecast"]), ("idle", []))
        self.assertEqual(len(self.posts()), 17)
        self.assertEqual(self.engine.calls, 17)

    def test_retained_packets_are_deep_copies_and_keep_original_receipt(self):
        returned = self.admit("C0USDT")
        original = deepcopy(returned)
        returned["forecast"][0]["median"] = 999
        returned["source"]["updated"] = 0
        returned["end_close_samples"][0] = 999
        for i in range(1, 9):
            self.admit("C" + str(i) + "USDT")
        restored = self.client.snapshot(fixture_packet(self.clock, "C0USDT"))
        self.assertEqual(restored["status"], "ready")
        for key in ("forecast", "source", "end_close_samples", "completed_at", "expires_at"):
            self.assertEqual(restored[key], original[key])
        restored["forecast"][0]["median"] = 998
        self.assertEqual(self.client.snapshot(fixture_packet(self.clock, "C0USDT"))["forecast"], original["forecast"])
        self.assertEqual(len(self.posts()), 9)

    def test_worker_failures_busy_states_and_mismatched_binding_never_use_retained_ready(self):
        original = self.admit("C0USDT")
        request = packet_request(fixture_packet(self.clock, "C0USDT"), self.clock.now)
        base = dict(enabled=True, source=original["source"], job_id=request["job_id"], seed=request["seed"])
        cases = [response(status, **base) for status in ("unavailable", "error", "stale", "loading", "queued")]
        cases += [response("idle", **dict(base, enabled=False)),
                  response("idle", error="fixture failure", **base),
                  dict(response("idle", **base), demo=True),
                  response("idle", **dict(base, job_id="f" * 64)),
                  response("idle", **dict(base, source=dict(original["source"], symbol="ETHUSDT"))),
                  dict(response("idle", **base), model_revision="different-fixture-revision"),
                  dict(response("idle", **base), tokenizer_revision="different-fixture-tokenizer"),
                  dict(response("idle", **base), code_revision="different-fixture-code")]
        for value in cases:
            with self.subTest(status=value["status"], error=value.get("error")):
                self.override = value
                self.client.cache.clear()
                result = self.client.snapshot(fixture_packet(self.clock, "C0USDT"))
                self.assertNotEqual(result["status"], "ready")
                self.assertEqual(result["forecast"], [])
                self.assertEqual(result["end_close_samples"], [])
        self.assertEqual(len(self.posts()), 1)

    def test_worker_transport_outage_never_falls_back_to_retained_ready(self):
        self.admit("C0USDT")
        self.client.cache.clear()
        with patch.object(self.client, "_call", side_effect=OSError("fixture unavailable")):
            result = self.client.snapshot(fixture_packet(self.clock, "C0USDT"))
        self.assertEqual((result["status"], result["enabled"], result["forecast"]),
                         ("unavailable", False, []))
        self.assertEqual(len(self.posts()), 1)

    def test_changed_input_hash_or_source_never_reuses_previous_retained_result(self):
        original = self.admit("C0USDT")
        for packet in (fixture_packet(self.clock, "OTHERUSDT"), fixture_packet(self.clock, "C0USDT")):
            if packet["symbol"] == "C0USDT":
                packet["candles"][-1]["turnover"] += 1
            result = self.client.snapshot(packet)
            self.assertEqual((result["status"], result["forecast"]), ("idle", []))
            self.assertNotEqual(result["job_id"], original["job_id"])
        self.assertEqual(len(self.posts()), 1)

    def test_fresh_same_input_proof_never_extends_original_candle_expiry(self):
        original = self.admit("C0USDT")
        for i in range(1, 9):
            self.admit("C" + str(i) + "USDT")
        self.clock.advance(original["expires_at"] - self.clock.now - 0.1)
        renewed = self.client.snapshot(fixture_packet(self.clock, "C0USDT"))
        self.assertEqual(renewed["status"], "ready")
        self.assertEqual(renewed["expires_at"], original["expires_at"])
        self.assertEqual(renewed["source"], original["source"])
        self.assertEqual(renewed["completed_at"], original["completed_at"])
        self.clock.advance(0.2)
        current = self.client.snapshot(fixture_packet(self.clock, "C0USDT"))
        self.assertEqual((current["status"], current["forecast"]), ("idle", []))
        self.assertNotEqual(current["job_id"], original["job_id"])
        self.assertEqual(len(self.client.completed), 0)
        self.assertEqual(len(self.posts()), 9)

    def test_parallel_readers_preserve_cached_packet_and_never_submit_model_work(self):
        original = self.admit("C0USDT")
        for i in range(1, 9):
            self.admit("C" + str(i) + "USDT")
        packet = fixture_packet(self.clock, "C0USDT")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.client.snapshot(packet), range(32)))
        self.assertTrue(all(value["status"] == "ready" and value["forecast"] == original["forecast"] for value in results))
        results[0]["forecast"][0]["median"] = 999
        self.assertEqual(results[1]["forecast"], original["forecast"])
        self.assertEqual(len(self.client.completed), 9)
        self.assertEqual(len(self.posts()), 9)


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
