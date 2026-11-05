"""Loopback-only supervisor. One isolated CPU inference process, bounded jobs.

No model imports in this HTTP process. A hung model process is killed at 120s;
GET endpoints only read state. It never fetches exchange data or creates orders.
"""
from collections import OrderedDict, deque
from copy import deepcopy
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

try:
    from kronos_client import PORT, HEX64, response, validate_submission, validate_forecast
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/trading-panel"))
    from kronos_client import PORT, HEX64, response, validate_submission, validate_forecast

TIMEOUT = 120


class ModelProcess:
    def __init__(self, runtime):
        self.messages = queue.Queue(maxsize=4)
        env = dict(os.environ, HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                   OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        self.process = subprocess.Popen([sys.executable, "-u", str(Path(__file__).with_name("infer.py")),
                                         "--runtime", str(runtime)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env, **options)

        def read():
            try:
                while True:
                    line = self.process.stdout.readline(32769)
                    if not line:
                        self.messages.put(None)
                        return
                    if len(line) > 32768 or not line.endswith("\n"):
                        self.messages.put(None)
                        return
                    self.messages.put(json.loads(line))
            except (ValueError, OSError):
                self.messages.put(None)
        threading.Thread(target=read, daemon=True, name="kronos-model-output").start()
        try:
            initial = self.messages.get(timeout=TIMEOUT)
        except queue.Empty:
            self.close()
            raise RuntimeError("Загрузка модели превысила 120 секунд") from None
        if not isinstance(initial, dict) or initial.get("status") != "loaded":
            self.close()
            raise RuntimeError(initial.get("error", "Модель не загрузилась") if isinstance(initial, dict) else "Модель завершилась при загрузке")

    def predict(self, request):
        self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
        self.process.stdin.flush()
        result = self.messages.get(timeout=TIMEOUT)
        if not isinstance(result, dict):
            raise OSError("Процесс модели завершился")
        return result

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        try:
            self.process.wait(timeout=5)
        finally:
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()


class ForecastJobs:
    def __init__(self, runtime, *, engine_factory=ModelProcess, wall_clock=None, start=True):
        self.runtime, self.factory = Path(runtime), engine_factory
        self.wall = wall_clock or time.time
        self.condition = threading.Condition(threading.RLock())
        self.jobs, self.waiting = OrderedDict(), deque()
        self.active = None
        self.phase, self.error = "loading", None
        self.stopping, self.engine = False, None
        self.thread = None
        if start:
            self.thread = threading.Thread(target=self._loop, daemon=True, name="kronos-forecast")
            self.thread.start()

    def status(self):
        with self.condition:
            return response(self.phase, enabled=self.phase in ("idle", "loading"), error=self.error,
                            active_jobs=int(self.active is not None), queued_jobs=len(self.waiting),
                            queue_limit=2, cache_limit=8)

    def get(self, job_id):
        if not isinstance(job_id, str) or not HEX64.fullmatch(job_id):
            raise ValueError("Некорректный идентификатор задачи")
        with self.condition:
            entry = self.jobs.get(job_id)
            if entry:
                return self._visible(entry)
            return response("idle", enabled=self.phase == "idle", job_id=job_id,
                            error=self.error if self.phase in ("unavailable", "error") else None)

    def _visible(self, entry):
        result = deepcopy(entry["result"])
        source = result["source"]
        step = int(source["interval"]) * 60
        if source["candle_end"] != int((self.wall() - 2) // step) * step:
            result.update(status="stale", forecast=[], end_close_samples=[], error="Закрылась новая свеча; нужен новый явный расчёт")
        return result

    def request(self, payload):
        request = validate_submission(payload, self.wall())
        job_id = request["job_id"]
        with self.condition:
            if job_id in self.jobs and self.jobs[job_id]["result"]["status"] not in ("error", "stale"):
                self.jobs.move_to_end(job_id)
                return self._visible(self.jobs[job_id])
            if self.phase != "idle":
                return response(self.phase, enabled=self.phase == "loading", source=request["source"],
                                job_id=job_id, seed=request["seed"], error=self.error)
            if len(self.waiting) >= 2:
                return response("error", enabled=True, source=request["source"], job_id=job_id,
                                seed=request["seed"], error="Очередь Kronos занята; повторите явный запрос после завершения расчёта")
            if job_id in self.jobs:
                del self.jobs[job_id]
            while len(self.jobs) >= 8:
                victim = next((key for key, value in self.jobs.items() if value["result"]["status"] not in ("loading", "queued")), None)
                if victim is None:
                    raise RuntimeError("Кэш Kronos занят")
                del self.jobs[victim]
            entry = dict(request=request, result=response("queued", enabled=True, source=request["source"],
                         job_id=job_id, seed=request["seed"], lookback=len(request["candles"]),
                         input_last_close=request["candles"][-1]["close"], accepted=True))
            self.jobs[job_id] = entry
            self.waiting.append(job_id)
            self.condition.notify()
            return deepcopy(entry["result"])

    def _start_engine(self):
        engine = self.factory(self.runtime)
        with self.condition:
            if self.stopping:
                engine.close()
                return False
            self.engine, self.phase, self.error = engine, "idle", None
            self.condition.notify_all()
        return True

    def _loop(self):
        try:
            if not self._start_engine():
                return
        except Exception as exc:
            with self.condition:
                self.phase, self.error = "unavailable", str(exc)[:180]
            return
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.stopping or self.waiting)
                if self.stopping:
                    break
                job_id = self.waiting.popleft()
                self.active = job_id
                entry = self.jobs[job_id]
                entry["result"]["status"] = "loading"
            restart = False
            try:
                request = validate_submission(entry["request"], self.wall())
                result = self.engine.predict(request)
                if result.get("job_id") != job_id or result.get("status") != "ready":
                    raise ValueError(result.get("error") or "Некорректный результат модели")
                validate_forecast(result.get("forecast"), request["source"])
                # The client repeats all binding/sample checks. The engine has
                # no source-selection authority; merge only allowed result fields.
                completed = self.wall()
                with self.condition:
                    entry["result"].update(status="ready", completed_at=completed,
                          **{k: result[k] for k in ("forecast", "end_close_samples", "inference_ms")})
                    entry["result"] = self._visible(entry)
            except (queue.Empty, BrokenPipeError, OSError) as exc:
                restart = True
                with self.condition:
                    entry["result"].update(status="error", forecast=[], end_close_samples=[],
                                          error="Расчёт превысил 120 секунд или процесс модели недоступен")
                    self.phase, self.error = "loading", str(exc)[:180]
            except Exception as exc:
                with self.condition:
                    entry["result"].update(status="error", forecast=[], end_close_samples=[], error=str(exc)[:180])
            finally:
                with self.condition:
                    self.active = None
                    self.condition.notify_all()
            if restart:
                self.engine.close()
                self.engine = None
                if self.stopping:
                    break
                try:
                    if not self._start_engine():
                        break
                except Exception as exc:
                    with self.condition:
                        self.phase, self.error = "unavailable", str(exc)[:180]
                        for queued_id in self.waiting:
                            self.jobs[queued_id]["result"].update(status="error", error="Модель недоступна", forecast=[])
                        self.waiting.clear()
                    break
        if self.engine:
            self.engine.close()

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify_all()
        if self.engine:
            self.engine.close()
        if self.thread:
            self.thread.join(timeout=2)


class WorkerServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8
    allow_reuse_address = True

    def __init__(self, jobs, token):
        self.jobs, self.token = jobs, token
        super().__init__(("127.0.0.1", PORT), Handler)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(1)

    def log_message(self, *args):
        pass

    def send(self, code, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        token = self.headers.get("X-Kronos-Token", "")
        return (self.headers.get("Host") in ("127.0.0.1:8790", "localhost:8790") and
                self.headers.get("Origin") is None and self.headers.get("Sec-Fetch-Site") in (None, "none") and
                len(self.headers.get_all("Host", [])) == 1 and len(self.headers.get_all("X-Kronos-Token", [])) == 1 and
                isinstance(token, str) and token.isascii() and hmac.compare_digest(token, self.server.token))

    def do_GET(self):
        if not self.authorized():
            self.send(403, response("error", error="Запрос worker не разрешён"))
            return
        try:
            target = urlsplit(self.path)
            if not self.path.startswith("/") or target.scheme or target.netloc or target.fragment:
                raise ValueError("Некорректный путь")
            if target.path == "/status" and not target.query:
                result = self.server.jobs.status()
            elif target.path == "/jobs":
                query = parse_qs(target.query, keep_blank_values=True)
                if set(query) != {"job_id"} or len(query["job_id"]) != 1 or len(target.query) > 80:
                    raise ValueError("Некорректный запрос задачи")
                result = self.server.jobs.get(query["job_id"][0])
            else:
                self.send(404, response("error", error="Неизвестный путь"))
                return
            self.send(200, result)
        except (ValueError, TypeError):
            self.send(400, response("error", error="Некорректный запрос worker"))

    def do_POST(self):
        if not self.authorized():
            self.send(403, response("error", error="Запрос worker не разрешён"))
            return
        try:
            length = self.headers.get_all("Content-Length", [])
            if (self.path != "/request" or len(length) != 1 or not length[0].isdigit() or
                    not 0 < int(length[0]) <= 65536 or self.headers.get("Transfer-Encoding") or
                    self.headers.get("Content-Type") != "application/json"):
                raise ValueError("Некорректный запрос worker")
            raw = self.rfile.read(int(length[0]))
            if len(raw) != int(length[0]):
                raise ValueError("Неполный запрос")
            self.send(200, self.server.jobs.request(json.loads(raw)))
        except (ValueError, TypeError, KeyError, OverflowError):
            self.send(400, response("error", error="Некорректные свечи или привязка источника"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=Path(os.environ.get("KRONOS_RUNTIME_DIR", "/opt/trading-kronos")))
    args = parser.parse_args()
    token = (args.runtime / "token").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise SystemExit("Invalid local worker token")
    jobs = ForecastJobs(args.runtime)
    server = WorkerServer(jobs, token)
    print("Kronos worker: http://127.0.0.1:8790 (CPU, local token required)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        jobs.close()


if __name__ == "__main__":
    main()
