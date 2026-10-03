"""Fixed native test entry point on Linux/WSL. No remote Python or shell payloads."""
import argparse
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine', choices=('freqtrade', 'jesse', 'hummingbot'), required=True)
    p.add_argument('--id', required=True)
    p.add_argument('--data', type=Path, required=True)
    args = p.parse_args()
    if str(uuid.UUID(args.id)) != args.id or not args.data.is_absolute():
        raise ValueError('Invalid fixed job')
    folder = Path(__file__).resolve().parents[1] / 'platforms'
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location('pc_native_runner', folder/'runner.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    runner.ROOT = args.data
    # The journal identifier is the server lease, including after delivery retries.
    runner.uuid = SimpleNamespace(uuid4=lambda: args.id, UUID=uuid.UUID)
    (args.data/args.engine).mkdir(parents=True, exist_ok=True)
    sys.argv = [str(folder/'runner.py'), args.engine]
    runner.main()


if __name__ == '__main__':
    main()
