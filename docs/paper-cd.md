# Server PAPER models C/D

C/D are original strategies from the Models tab, now executed continuously by `trading-research.service`. Freqtrade/Hummingbot/Jesse are external frameworks in the catalog, not installed or represented as running strategies. Existing A/B remain separate services.

## Install

After updating the panel to the matching immutable revision:

```sh
python3 -B /opt/trading-lab-repo/tools/install_research.py
```

This is a separate first-install migration, not an expansion of the generic panel updater's allowlist. Sources live in `integrations/research`; installed engine is `/opt/trading-research/engine.py`, state is `/var/lib/trading-research/journal.sqlite`, public report is `report.json`. The installer verifies the panel manifest/revision, existing paths, symlinks and untracked state, runs engine tests, and starts only the new service. A/B, Xray, firewall, HTTPS and their systemd files are not changed. Repeating an identical installation with an active service is a no-op. Later engine changes require a separate migration; do not reset state. On first-install failure code/unit are removed and any newly created runtime state is retained for diagnosis.

## Execution contract: 2026-10-02.paper1

The engine reads local B `state.json` once per second and has no exchange/network client. This deliberately shares the selected B universe and its availability. C/D do not add WS connections. Both have independent virtual capital600USDT, nominal100USDT, one position each, target net+0.6, stop net-0.4, maximum hold180seconds, cooldown120seconds and experiment loss threshold18USDT. Thresholds are observed at sample times; they are not guaranteed exact loss limits.

Entry gates match research version2026-10-02.1: C trend/volume/impulse, D EMA-range/VWAP-return plus freshness, liquidity, cost, funding and flow gates. Three distinct ordered book snapshots spanning at least4seconds confirm. Repeated snapshots do not increment; >6second gaps reset. Confirmations are reset on restart, failed gates, cooldown and open position. Candidate selection is deterministic by minimum two-sided depth then symbol.

Modeled fill = mid * (1 + side * spread_pct /200) * (1 + side *0.0005). Fee0.00055 per side. Quantity100 / entry. This is a quote-based execution model with fixed residual slippage, not full-book VWAP execution used by B. The depth coverage check is a guard, not a measured execution price. Changes in slippage/fees require a new version and cannot be presented as improved signals. Exits require a fresh quote and covered +/-0.05% depth with at least200USDT on each side. No maker queue or partial fills are modeled.

Funding must be >300seconds away at entry; maximum hold180seconds. A crossed funding boundary halts accounting with position preserved instead of assuming zero funding. Ordinary closes before that boundary record funding0. Quote/stream loss, missing liquidity, clock reversal, restart with a position, or funding-boundary loss halts the affected model. A halt is persistent; no automatic resets. The other model can continue if its own state/feed is usable. The service remains active to publish stopped states.

## Durable accounting

SQLite WAL with FULL synchronization stores both updated model state and closed trade records in the same transaction. Unique trade IDs prevent duplicate closing records. JSON is a replace-atomic projection of committed state. A crash after commit and before JSON export recovers from SQLite. A crash with an unclosed position halts on recovery. Reports include last100trades per model; all closes stay in SQLite and CSV. CSV updates at close and at least every30seconds. CSV strings are escaped against formula interpretation.

Balances deduct entry fees at open, then add gross minus exit fee at close; net includes both fees. Equity includes an estimated exit fee. Peak drawdown is sampled net-equity drawdown in USDT. Journal net excludes open positions; equity does not. Last valuation time is separate from report heartbeat. Different start times and fill assumptions prevent treating the C/D table as a controlled A/B superiority test.

## Verification

11engine tests cover C/D long/short, simultaneous independent positions, freshness/coverage/funding/cost gates, confirmation deduplication/gaps, roundtrip fees, stop, target, timeout/cooldown, restart/funding/data gaps, per-model risk limit, atomic state+close transaction, duplicate rollback and CSV/JSON export. Installer tests verify refusal of unknown/drifted paths, no-op repeats and failed-health cleanup limited to its own new code/service. Browser tests cover4model statuses,2server summaries,2CSVlinks and per-symbol server checks at390/1280px, plus stale-report behavior.
