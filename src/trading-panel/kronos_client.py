"""Bounded, stdlib-only client for the separate, optional Kronos CPU worker.

Only request() submits work. status()/snapshot() never fetch market data or
admit a forecast; the caller supplies ExchangeData's current closed-chart proof.
"""
from collections import OrderedDict
from copy import deepcopy
import hashlib
from http.client import HTTPConnection
import json
import math
import os
from pathlib import Path
import re
import threading
import time

MODEL = "NeoQuasar/Kronos-mini"
MODEL_REVISION = "f4e68697d9d5aed55cef5c96aabc3376bcad9f81"
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-2k"
TOKENIZER_REVISION = "26966d0035065a0cae0ebad7af8ece35bc1fb51c"
CODE_REVISION = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
HORIZON, SCENARIOS, LOOKBACK = 6, 5, 120
PORT = 8790
STATUSES = {"unavailable", "idle", "loading", "queued", "ready", "error", "stale"}
EXCHANGES = {"binance", "bybit", "okx", "gate", "bitget"}
INTERVALS = {"1", "5", "15", "60", "240", "1440"}
SYMBOL = re.compile(r"[A-Z0-9]{1,28}USDT\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
NOTE = "Минимум, медиана и максимум 5 сценариев модели; это не вероятность и не торговый сигнал."


def response(status="idle", *, enabled=False, source=None, error=None, **extra):
    result = dict(status=status, enabled=enabled, model=MODEL, device="cpu",
                  model_revision=MODEL_REVISION, tokenizer_revision=TOKENIZER_REVISION,
                  code_revision=CODE_REVISION, source=source, forecast=[],
                  horizon=HORIZON, scenarios=SCENARIOS, seed=None,
                  inference_ms=None, completed_at=None, job_id=None, end_close_samples=[],
                  input_last_close=None, lookback=None, current_source_updated=None,
                  expires_at=None, accepted=False, note=NOTE, error=error)
    result.update(extra)
    return result


def number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Некорректное число свечи")
    value = float(value)
    if not math.isfinite(value) or value < 0 or positive and value == 0:
        raise ValueError("Некорректное число свечи")
    return value


def packet_request(packet, wall=None):
    """Validate and canonically bind a verified chart; no quote/book dependency."""
    wall = time.time() if wall is None else wall
    if (not isinstance(packet, dict) or packet.get("status") != "ok" or
            packet.get("stale") is not False or packet.get("demo") or
            packet.get("timestamp_origin") != "closed_candle"):
        raise ValueError("Нужны свежие проверенные закрытые свечи биржи")
    exchange, symbol, interval = (packet.get(k) for k in ("exchange", "symbol", "interval"))
    if exchange not in EXCHANGES or not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or interval not in INTERVALS:
        raise ValueError("Некорректный источник свечей")
    native = {"okx": symbol[:-4] + "-USDT-SWAP", "gate": symbol[:-4] + "_USDT"}.get(exchange, symbol)
    if packet.get("native_symbol") != native:
        raise ValueError("Инструмент не соответствует бирже")
    updated, end = number(packet.get("updated")), number(packet.get("candle_end"), positive=True)
    step = int(interval) * 60
    if not end.is_integer() or end != int((wall - 2) // step) * step or not -2 <= wall - updated <= 75:
        raise ValueError("Подтверждение закрытых свечей устарело")
    if packet.get("source_ts") != end:
        raise ValueError("Время источника не соответствует закрытию свечи")
    raw = packet.get("candles")
    if not isinstance(raw, list) or not 60 <= len(raw) <= 180:
        raise ValueError("Нужно от 60 до 180 закрытых свечей")
    candles = []
    for row in raw[-LOOKBACK:]:
        if not isinstance(row, dict):
            raise ValueError("Некорректная свеча")
        stamp = number(row.get("t"), positive=True)
        if not stamp.is_integer() or int(stamp) % step:
            raise ValueError("Некорректное время свечи")
        candle = dict(t=int(stamp))
        for name in ("open", "high", "low", "close", "volume", "turnover"):
            candle[name] = number(row.get(name), positive=name in ("open", "high", "low", "close"))
        if (candle["low"] > min(candle["open"], candle["close"]) or
                candle["high"] < max(candle["open"], candle["close"]) or
                candle["high"] < candle["low"]):
            raise ValueError("Некорректные OHLC свечи")
        candles.append(candle)
    if candles[-1]["t"] + step != end or any(b["t"] - a["t"] != step for a, b in zip(candles, candles[1:])):
        raise ValueError("Свечи имеют пропуски или незакрытую последнюю свечу")
    source = dict(exchange=exchange, symbol=symbol, native_symbol=native,
                  interval=interval, candle_end=int(end), updated=updated)
    binding = dict(source={k: v for k, v in source.items() if k != "updated"}, candles=candles)
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    source["input_hash"] = digest
    identity = dict(input_hash=digest, model=MODEL_REVISION, tokenizer=TOKENIZER_REVISION,
                    code=CODE_REVISION, horizon=HORIZON, scenarios=SCENARIOS)
    job_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return dict(source=source, candles=candles, job_id=job_id, seed=int(job_id[:8], 16) & 0x7fffffff)


def validate_submission(payload, wall=None):
    if not isinstance(payload, dict) or set(payload) != {"source", "candles", "job_id", "seed"}:
        raise ValueError("Некорректный запрос Kronos")
    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {"exchange", "symbol", "native_symbol", "interval", "candle_end", "updated", "input_hash"}:
        raise ValueError("Некорректная привязка источника")
    request = packet_request(dict(source, candles=payload["candles"], status="ok", stale=False,
                                  timestamp_origin="closed_candle", source_ts=source["candle_end"]), wall)
    if request != payload:
        raise ValueError("Хэш или параметры источника не совпадают")
    return request


def validate_forecast(value, source):
    if not isinstance(value, list) or len(value) != HORIZON:
        raise ValueError("Некорректная длина прогноза")
    step = int(source["interval"]) * 60
    for i, row in enumerate(value):
        if not isinstance(row, dict) or set(row) != {"time", "median", "low", "high"}:
            raise ValueError("Некорректный прогноз")
        if isinstance(row["time"], bool) or row["time"] != source["candle_end"] + i * step:
            raise ValueError("Прогноз относится к другому времени")
        low, median, high = (number(row[k], positive=True) for k in ("low", "median", "high"))
        if not low <= median <= high:
            raise ValueError("Некорректный разброс сценариев")
    return value


class KronosClient:
    def __init__(self, runtime=None, *, transport=None, wall_clock=None, clock=None):
        self.runtime = Path(runtime or os.environ.get("KRONOS_RUNTIME_DIR", "/opt/trading-kronos"))
        self.transport = transport
        self.wall = wall_clock or time.time
        self.clock = clock or time.monotonic
        self.cache, self.lock = OrderedDict(), threading.Lock()

    def _call(self, method, path, payload=None):
        if self.transport:
            return self.transport(method, path, payload)
        token = (self.runtime / "token").read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
            raise ValueError("Некорректная конфигурация worker")
        # HTTPConnection goes directly to loopback and does not consult proxies.
        connection = HTTPConnection("127.0.0.1", PORT, timeout=0.25)
        try:
            body = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode() if payload is not None else None
            connection.request(method, path, body=body,
                               headers={"X-Kronos-Token": token, "Content-Type": "application/json", "Connection": "close"})
            result = connection.getresponse()
            raw = result.read(32769)
            if len(raw) > 32768 or result.status != 200 or result.getheader("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Некорректный ответ worker")
            value = json.loads(raw)
            return value
        finally:
            connection.close()

    def _read(self, path):
        with self.lock:
            cached = self.cache.get(path)
            if cached and self.clock() - cached[0] < 1:
                return deepcopy(cached[1])
        try:
            result = self._call("GET", path)
        except (OSError, ValueError, TypeError):
            result = response("unavailable", error="Kronos worker не установлен или недоступен")
        with self.lock:
            self.cache[path] = (self.clock(), deepcopy(result))
            while len(self.cache) > 9:
                self.cache.popitem(last=False)
        return result

    def _checked(self, value, request=None):
        try:
            if (not isinstance(value, dict) or value.get("status") not in STATUSES or
                    type(value.get("enabled")) is not bool or
                    any(value.get(k) != v for k, v in (("model", MODEL), ("device", "cpu"),
                         ("model_revision", MODEL_REVISION), ("tokenizer_revision", TOKENIZER_REVISION),
                         ("code_revision", CODE_REVISION), ("horizon", HORIZON), ("scenarios", SCENARIOS)))):
                raise ValueError("Версия или формат worker не совпадает")
            value = deepcopy(value)
            if request:
                source = value.get("source")
                if source is not None:
                    if not isinstance(source, dict) or any(source.get(k) != v for k, v in request["source"].items() if k != "updated"):
                        raise ValueError("Прогноз относится к другому источнику")
                    number(source.get("updated"))
                if value.get("status") in ("queued", "ready") or value.get("status") == "loading" and source is not None:
                    if value.get("job_id") != request["job_id"] or value.get("seed") != request["seed"] or source is None:
                        raise ValueError("Задача прогноза не совпадает")
                if value.get("status") == "ready":
                    if not value["enabled"]:
                        raise ValueError("Модель не готова")
                    validate_forecast(value.get("forecast"), request["source"])
                    samples = value.get("end_close_samples")
                    if not isinstance(samples, list) or len(samples) != SCENARIOS:
                        raise ValueError("Отсутствуют отдельные сценарии модели")
                    ordered = sorted(number(x, positive=True) for x in samples)
                    last = value["forecast"][-1]
                    if (ordered[0], ordered[2], ordered[-1]) != (last["low"], last["median"], last["high"]):
                        raise ValueError("Сценарии не совпадают с последним шагом прогноза")
                    if (value.get("input_last_close") != request["candles"][-1]["close"] or
                            value.get("lookback") != len(request["candles"])):
                        raise ValueError("Исходная цена или длина истории не совпадает")
                    number(value.get("inference_ms"))
                    number(value.get("completed_at"), positive=True)
                else:
                    value["forecast"] = []
                    value["end_close_samples"] = []
                # Original market timestamp remains visible; a current chart
                # independently proves the exact same input hash is still usable.
                value["source"] = source or request["source"]
                value["job_id"] = value.get("job_id") or request["job_id"]
                step = int(request["source"]["interval"]) * 60
                value["current_source_updated"] = request["source"]["updated"]
                value["expires_at"] = request["source"]["candle_end"] + step + 2
                if (request["source"]["candle_end"] != int((self.wall() - 2) // step) * step or
                        not -2 <= self.wall() - request["source"]["updated"] <= 75):
                    return response("stale", enabled=value["enabled"], source=request["source"],
                                    error="Подтверждение закрытых свечей устарело")
            elif value.get("forecast"):
                raise ValueError("Статус worker содержит непривязанный прогноз")
            return value
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return response("error", error=str(exc), source=request["source"] if request else None)

    def status(self):
        return self._checked(self._read("/status"))

    def request(self, packet):
        try:
            request = packet_request(packet, self.wall())
        except (ValueError, TypeError) as exc:
            return response("stale", error=str(exc))
        try:
            result = self._call("POST", "/request", request)
        except (OSError, ValueError, TypeError):
            return response("unavailable", source=request["source"], error="Kronos worker не установлен или недоступен")
        with self.lock:
            self.cache.pop("/jobs?job_id=" + request["job_id"], None)
            self.cache.pop("/status", None)
        return self._checked(result, request)

    def snapshot(self, packet):
        try:
            request = packet_request(packet, self.wall())
        except (ValueError, TypeError) as exc:
            return response("stale", error=str(exc))
        return self._checked(self._read("/jobs?job_id=" + request["job_id"]), request)
