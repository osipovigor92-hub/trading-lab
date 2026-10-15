#!/usr/bin/env bash
# Explicit Linux installation of the optional model unit only. No checkout chmod.
set -Eeuo pipefail
[[ $(uname -s) == Linux && $(id -u) == 0 ]] || { echo 'Run this installer as root on Linux.' >&2; exit 1; }
umask 077
for tool in install mktemp tee getent systemctl timeout; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done
[[ ! -L /var/log ]] || { echo 'Refusing symlink: /var/log' >&2; exit 1; }
log=$(mktemp /var/log/trading-kronos-install.XXXXXX)
exec > >(tee "$log") 2>&1
trap 'rc=$?; printf "\nKronos installation failed (exit %s). Worker may remain stopped. Log: %s\n" "$rc" "$log" >&2; exit "$rc"' ERR
die() { echo "$*" >&2; return 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
runtime=/opt/trading-kronos
stage_root=/var/lib/trading-kronos-install
unit=/etc/systemd/system/trading-kronos.service
python=${KRONOS_SETUP_PYTHON:-python3}
python=$(command -v "$python") || die 'Set KRONOS_SETUP_PYTHON to an accessible Python 3.10-3.12 executable.'
getent passwd tradingbot >/dev/null || die 'User tradingbot does not exist.'
getent group tradingbot >/dev/null || die 'Group tradingbot does not exist.'
if command -v runuser >/dev/null; then
  as_bot=(runuser -u tradingbot --)
elif command -v sudo >/dev/null; then
  as_bot=(sudo -u tradingbot --)
else
  die 'Required command missing: runuser or sudo'
fi
# Reject fixed path redirection before any privileged install/chown operation.
for path in /opt /var/lib /etc/systemd /etc/systemd/system "$stage_root" "$runtime" "$unit"; do
  [[ ! -L "$path" ]] || die "Refusing symlink: $path"
done
for relative in token manifest.json .venv vendor vendor/model weights weights/model weights/tokenizer app; do
  [[ ! -L "$runtime/$relative" ]] || die "Refusing symlink: $runtime/$relative"
done
sources=(integrations/kronos/setup.py integrations/kronos/requirements.txt
         integrations/kronos/worker.py integrations/kronos/infer.py
         integrations/kronos/smoke.py src/trading-panel/kronos_client.py)
template="$repo/integrations/kronos/trading-kronos.service.example"
for source in "${sources[@]}"; do
  [[ -f "$repo/$source" && -r "$repo/$source" && ! -L "$repo/$source" ]] || die "Missing regular source: $source"
done
[[ -f "$template" && -r "$template" && ! -L "$template" ]] || die 'Missing regular Kronos unit template.'
# Run preflight from an accessible cwd, even when the checkout is root-only.
(cd /; "${as_bot[@]}" "$python" -B -c '
import sys
if not (3, 10) <= sys.version_info[:2] <= (3, 12):
    raise SystemExit("Use Python 3.10-3.12; set KRONOS_SETUP_PYTHON if needed.")
try:
    import venv, ensurepip
except ImportError:
    raise SystemExit("Python venv/ensurepip unavailable; install the matching venv package first.")
print("Python preflight:", sys.version.split()[0])')
install -d -o root -g tradingbot -m 0750 "$stage_root"
stage=$(mktemp -d "$stage_root/source.XXXXXX")
install -d -o root -g tradingbot -m 0750 "$stage" "$stage/integrations" \
  "$stage/integrations/kronos" "$stage/src" "$stage/src/trading-panel"
for source in "${sources[@]}"; do
  install -o root -g tradingbot -m 0640 "$repo/$source" "$stage/$source"
done
printf 'Private log: %s\nRetained installation source: %s\n' "$log" "$stage"
if systemctl cat trading-kronos.service >/dev/null 2>&1; then
  echo 'Stopping only trading-kronos.service before updating its runtime.'
  systemctl stop trading-kronos.service
fi
install -d -o tradingbot -g tradingbot -m 0750 "$runtime"
# The installer never runs pip as root. Its original token is preserved by setup.
cd -- "$runtime"
"${as_bot[@]}" env PYTHONDONTWRITEBYTECODE=1 "$python" -B \
  "$stage/integrations/kronos/setup.py" --runtime "$runtime"
# Install the unit only after the complete setup succeeds.
install -o root -g root -m 0644 "$template" "$unit"
systemctl daemon-reload
systemctl enable trading-kronos.service
systemctl restart trading-kronos.service
# Read only stdlib status as the service user. Never disclose the local token.
timeout 5s "${as_bot[@]}" "$python" -B -c '
import json, sys, time
sys.path.insert(0, sys.argv[1])
from kronos_client import KronosClient
client = KronosClient(sys.argv[2])
deadline = time.monotonic() + 4
while True:
    state = client.status()
    if (state.get("status") != "unavailable" or
            state.get("error") != "Kronos worker не установлен или недоступен" or
            time.monotonic() >= deadline):
        break
    time.sleep(0.15)
keys = ("status", "enabled", "model", "device", "model_revision", "tokenizer_revision", "error")
print(json.dumps({key: state.get(key) for key in keys}, ensure_ascii=False), flush=True)
if state.get("status") not in ("idle", "loading") or not state.get("enabled"):
    raise SystemExit(1)
if state["status"] == "loading":
    print("Service started; model is still loading. No forecast readiness claimed.")
' "$stage/src/trading-panel" "$runtime"
printf 'Kronos installation command completed. Log: %s\n' "$log"
