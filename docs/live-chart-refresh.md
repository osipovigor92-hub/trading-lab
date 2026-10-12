# Graph and LIVE refresh

Based on the version confirmed on VM-392550 on 10 October 2026:
`ead940bb5c4847d9194885a3ac10a0925b1a6ed7`.

The old cache had two slots shared by background selection and foreground
charts. Two blocked background requests left an opened contract unscheduled.
Charts also discarded the current candle, and LIVE waited indefinitely for
approved candidates from the old scanner. The graph/LIVE workspace derived
its market price and depth from model B, so an intentionally halted B hid them.

The cache keeps its 24-entry limit and two background slots, with two reserved
foreground slots for the visible contract. Closed candles still produce the
same levels, ATR, VWAP, ranking and PAPER plans. An independently validated
`current_candle` supplies display updates. Visible charts refresh their cache
after 3 seconds and depth after 1 second; browser requests remain bounded and
coalesced. Network and exchange latency still affect actual delivery times.

The graph tab loads a local Bybit chart when opened. TradingView remains an
explicit optional provider. The local chart and the screener retain their SVG
nodes. A slow depth request no longer delays rendering or polling candles.
`/api/market-view` provides the graph/LIVE workspace with independent cached
quotes, candles and depth. Stale depth hides current market values; it does
not remove independent candle history. Model signals retain their own checks.

The observation service starts with fresh scanner candidates when available,
otherwise BTCUSDT, ETHUSDT and SOLUSDT. This fallback is a watchlist, not a
trading recommendation or an approved candidate. Fresh books display before
the 60-second trade window is complete. Aggregation windows remain separate.
The service publishes once per second and reconnects with 1–15-second backoff.
Trade tape is shown only for a freshly observed contract; REST depth works
for other selected contracts. The UI never substitutes zero trades for an
unavailable tape. Inactive chart/LIVE views stop their dedicated requests.

The deployment transaction can update/start `trading-live.service` alongside
the panel. It checks the observer dependency before changing files and preserves
the observer's previous inactive state on rollback. Model services and their
positions, budgets and journals are outside this update. Diagnostics include
the observation service and public feed freshness.

Validation covers an open candle leaving closed analytics unchanged, reserved
foreground capacity with two blocked background requests, observation without
scanner candidates, separate trade windows, observer rollback, and browser
behavior at 1280/390/320 pixels. The browser scenario changes an open candle
while a depth response is delayed, halts B, switches coins/timeframes, expires
and restores depth, retains the frame, and verifies paused/resumed polling.
The previous model-budget regression remains in CI.
