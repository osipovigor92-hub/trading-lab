"""Actual, offline Kronos-mini inference. Launched only by the worker supervisor."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time

try:
    from kronos_client import (CODE_REVISION, MODEL, MODEL_REVISION, TOKENIZER,
                               TOKENIZER_REVISION, HORIZON, SCENARIOS)
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/trading-panel"))
    from kronos_client import (CODE_REVISION, MODEL, MODEL_REVISION, TOKENIZER,
                               TOKENIZER_REVISION, HORIZON, SCENARIOS)

MODEL_SHA256 = "a7d5f37e2e9fbd9891f7d7d4f72574512dd1f704fee14223e0a8cd0fbf54197c"
TOKENIZER_SHA256 = "b97ec46b3b72160509e289183eaf7bdf5f0dac5bb9b49522f6d46638a99a8717"


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_runtime(runtime):
    manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
    pins = dict(code_revision=CODE_REVISION, model=MODEL, model_revision=MODEL_REVISION,
                tokenizer=TOKENIZER, tokenizer_revision=TOKENIZER_REVISION)
    if any(manifest.get(key) != value for key, value in pins.items()):
        raise ValueError("Пины установленной модели не совпадают")
    expected = {"vendor/model/__init__.py", "vendor/model/kronos.py", "vendor/model/module.py", "vendor/LICENSE",
                "weights/model/config.json", "weights/model/model.safetensors",
                "weights/tokenizer/config.json", "weights/tokenizer/model.safetensors"}
    hashes = manifest.get("files")
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise ValueError("Манифест установленной модели неполон")
    for name in expected:
        path = runtime / name
        if path.is_symlink() or not path.is_file() or file_hash(path) != hashes[name]:
            raise ValueError("Файл установленной модели изменён: " + name)
    if (hashes["weights/model/model.safetensors"] != MODEL_SHA256 or
            hashes["weights/tokenizer/model.safetensors"] != TOKENIZER_SHA256):
        raise ValueError("Веса отличаются от официальных .safetensors")


class Predictor:
    def __init__(self, runtime):
        verify_runtime(runtime)
        os.environ.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                          OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        sys.path.insert(0, str(runtime / "vendor"))
        import numpy as np
        import pandas as pd
        import torch
        from model import Kronos, KronosTokenizer, KronosPredictor
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        tokenizer = KronosTokenizer.from_pretrained(str(runtime / "weights/tokenizer"), local_files_only=True)
        model = Kronos.from_pretrained(str(runtime / "weights/model"), local_files_only=True)
        tokenizer.eval()
        model.eval()
        self.predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=2048)
        self.np, self.pd, self.torch = np, pd, torch

    def forecast(self, request):
        started = time.monotonic()
        candles, source = request["candles"], request["source"]
        frame = self.pd.DataFrame(candles).rename(columns={"turnover": "amount"})
        frame = frame[["open", "high", "low", "close", "volume", "amount"]]
        x_timestamp = self.pd.Series(self.pd.to_datetime([row["t"] for row in candles], unit="s", utc=True))
        step = int(source["interval"]) * 60
        times = [source["candle_end"] + i * step for i in range(HORIZON)]
        y_timestamp = self.pd.Series(self.pd.to_datetime(times, unit="s", utc=True))
        self.torch.manual_seed(request["seed"])
        # sample_count=1 preserves each independent path in predict_batch.
        # Upstream sample_count>1 averages internally and cannot yield a band.
        with self.torch.inference_mode():
            paths = self.predictor.predict_batch([frame] * SCENARIOS, [x_timestamp] * SCENARIOS,
                      [y_timestamp] * SCENARIOS, pred_len=HORIZON, T=0.6, top_p=0.9,
                      sample_count=1, verbose=False)
        closes = self.np.stack([path["close"].to_numpy() for path in paths])
        if closes.shape != (SCENARIOS, HORIZON) or not self.np.isfinite(closes).all() or (closes <= 0).any():
            raise ValueError("Модель вернула недопустимые цены; прогноз скрыт")
        result = []
        for i, stamp in enumerate(times):
            values = closes[:, i]
            result.append(dict(time=stamp, median=float(self.np.median(values)),
                               low=float(values.min()), high=float(values.max())))
        return dict(status="ready", job_id=request["job_id"], forecast=result,
                    end_close_samples=[float(value) for value in closes[:, -1]],
                    inference_ms=round((time.monotonic() - started) * 1000, 2))


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            predictor = Predictor(args.runtime)
        emit(dict(status="loaded"))
    except Exception as exc:
        emit(dict(status="error", error=str(exc)[:180]))
        return
    while True:
        line = sys.stdin.readline(65537)
        if not line:
            return
        if len(line) > 65536 or not line.endswith("\n"):
            return
        request = {}
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                result = predictor.forecast(request)
            emit(result)
        except Exception as exc:
            emit(dict(status="error", job_id=request.get("job_id"), error=str(exc)[:180]))


if __name__ == "__main__":
    main()
