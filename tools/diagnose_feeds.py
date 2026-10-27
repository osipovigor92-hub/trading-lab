"""Read-only source diagnostics; no scope changes, tokens or trading commands."""
import json
import subprocess
from urllib.request import urlopen


def main():
    report = {}
    try:
        with urlopen('http://127.0.0.1:8787/api/monitor-health', timeout=10) as response:
            report['monitor'] = json.load(response)
    except (OSError, ValueError) as exc:
        report['error'] = str(exc)
    try:
        result = subprocess.run(['systemctl', 'show', 'trading-panel.service',
                                 '-p', 'MemoryCurrent', '-p', 'MemoryMax', '-p', 'TasksCurrent',
                                 '-p', 'TasksMax', '-p', 'NRestarts', '-p', 'CPUQuotaPerSecUSec'],
                                capture_output=True, text=True, timeout=5)
        report['service'] = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    except (OSError, subprocess.TimeoutExpired):
        report['service'] = {'status': 'unavailable'}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
