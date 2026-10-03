"""Offline checks; does not start any market services."""
import ast
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT/'src').rglob('*.py'):
    ast.parse(path.read_text(), filename=str(path))
for path in (ROOT/'src/trading-panel').glob('*.js'):
    subprocess.run(['node', '--check', str(path)], check=True)
for component in ('scalp-model-b', 'trading-report'):
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT/'src'/component), '-v'], check=True)
env = dict(os.environ, PYTHONPATH=str(ROOT/'src/trading-scanner'))
for component, script in [('scalp-paper','paper.py'),('trading-live','live.py'),('trading-signals','signals.py')]:
    subprocess.run([sys.executable, str(ROOT/'src'/component/script), '--selftest'], env=env, check=True)
print('Offline checks passed')
subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT/'tools'), '-p', 'test_*.py', '-v'], check=True)
subprocess.run(['node', '--test', str(ROOT/'tools/test_alerts.cjs'), str(ROOT/'tools/test_client.cjs'), str(ROOT/'tools/test_workspace.cjs'), str(ROOT/'tools/test_research.cjs'), str(ROOT/'tools/test_screener.cjs'), str(ROOT/'tools/test_models.cjs')], check=True)

subprocess.run([sys.executable, '-B', str(ROOT/'integrations/research/test_engine.py')],check=True)
subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT/'integrations/control'), '-v'],check=True)
subprocess.run([sys.executable, '-B', str(ROOT/'integrations/platforms/test_runner.py')],check=True)
