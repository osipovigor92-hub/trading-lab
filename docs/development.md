# Trading lab: development workflow

This repository is for the PAPER-only trading laboratory, separate from VPN services.

## Initial import

Import the current server source before implementing further updates. Local historical installers are not authoritative copies of deployed files. Review the source for secrets before committing. Do not import runtime state, trading history, SQLite databases, environment files, SSH keys or backups.

## Development

- Work on feature branches; keep main as the reviewed baseline.
- Run accounting, market feed, stale-data, journal and report tests offline.
- Preview the dashboard against synthetic fixtures on localhost; do not connect a preview to production state.
- Keep model A and B results and journals separate.

## Releases

The deployment command and rollback mechanism are not implemented yet. They must be built against the imported current services and tested before use.

Deploy a reviewed immutable commit with a source backup and rollback. Never reset balances, journals or open positions. A model restart must be deferred while that model has an open PAPER position. Panel/report changes should not restart trading models. Do not restart or modify VPN services.

GitHub access does not provide SSH access to the running server.
