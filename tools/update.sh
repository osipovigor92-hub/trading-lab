#!/usr/bin/env bash
set -euo pipefail
revision=${1:?Usage: bash tools/update.sh FULL_COMMIT_SHA}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || { echo 'Use a full immutable commit SHA'; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ -z "$(git -C "$repo" status --porcelain)" ]] || { echo 'Checkout has local changes'; exit 1; }
git -C "$repo" fetch origin "$revision"
[[ "$(git -C "$repo" rev-parse 'FETCH_HEAD^{commit}')" == "$revision" ]] || exit 1
git -C "$repo" checkout --detach "$revision"
exec python3 "$repo/tools/deploy.py" --apply
