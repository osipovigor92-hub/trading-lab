"""Explicit live-data smoke test. Never a synthetic fixture or a trading action."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

try:
    from kronos_client import KronosClient
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/trading-panel"))
    from kronos_client import KronosClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path(os.environ.get("KRONOS_RUNTIME_DIR", "/opt/trading-kronos")))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--exchange", choices=("bybit", "binance", "okx", "gate", "bitget"), default="bybit")
    parser.add_argument("--symbols", default="BTCUSDT")
    parser.add_argument("--interval", choices=("1", "5", "15", "60", "240", "1440"), default="5")
    args = parser.parse_args()
    symbols = args.symbols.split(",")
    if not 1 <= len(symbols) <= 2 or len(set(symbols)) != len(symbols):
        raise SystemExit("Smoke test accepts one or two distinct symbols")
    sys.path.insert(0, str(args.repo / "src/trading-panel"))
    from exchange_data import ExchangeData
    client, market = KronosClient(args.runtime), ExchangeData()
    try:
        deadline = time.monotonic() + 120
        while client.status()["status"] == "loading" and time.monotonic() < deadline:
            time.sleep(0.5)
        state = client.status()
        if state["status"] != "idle":
            raise RuntimeError(state.get("error") or "Worker not ready")
        for symbol in symbols:
            packet = market.fetch_chart(args.exchange, symbol, args.interval)
            result = client.request(packet)
            if result["status"] not in ("queued", "loading", "ready"):
                raise RuntimeError(result.get("error") or result["status"])
            deadline, next_refresh = time.monotonic() + 125, time.monotonic() + 30
            while result["status"] in ("queued", "loading") and time.monotonic() < deadline:
                time.sleep(0.25)
                if time.monotonic() >= next_refresh:
                    packet = market.fetch_chart(args.exchange, symbol, args.interval)
                    next_refresh = time.monotonic() + 30
                result = client.snapshot(packet)
            if result["status"] != "ready":
                raise RuntimeError(result.get("error") or result["status"])
            # Fresh REST verification of the actual inputs before reporting.
            packet = market.fetch_chart(args.exchange, symbol, args.interval)
            result = client.snapshot(packet)
            if result["status"] != "ready":
                raise RuntimeError("Input candles changed during verification; repeat explicit test")
            print(json.dumps(dict(real_model=True, real_exchange_data=True, **result), ensure_ascii=False), flush=True)
    finally:
        market.close()


if __name__ == "__main__":
    main()
