# Development workflow

This repository contains the current PAPER-only server source, including trading-signals. No production balances, credentials or history databases are stored here.

Work on feature branches. Run `python tools/check.py` with Python 3.12, Node.js and requirements-dev.txt installed. Start the synthetic localhost dashboard with `python tools/preview.py`. Synthetic data tests rendering and transport only; it is not a backtest.

GitHub Actions checks each push and pull request. Browser visual verification is still pending because the local browser download failed.

For updates, see [deployment.md](deployment.md). The initial updater supports only panel/report/signals code, with version checks, backup and error rollback. Model/LIVE/scanner/unit changes require a separate migration. Never reset state or restart a model with an open PAPER position. VPN services are outside this repository's scope.

GitHub access does not provide SSH access to the server. Production deployment remains an explicit command run by the user.
