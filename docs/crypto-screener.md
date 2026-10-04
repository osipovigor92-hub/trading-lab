# Crypto screener and levels

The **Скринер** tab lists the top 100 valid Bybit linear USDT perpetual tickers by 24-hour turnover. Search, minimum turnover, sorting and presets run locally. Expiry futures, pre-listing rows, malformed and duplicate tickers are excluded. This does not change the symbol selection or entry rules of trading models.

- Price, 24-hour change, turnover in USDT, daily high/low range and quoted bid/ask spread.
- A transparent **«Качество»** score (0–100): 24-hour turnover plus the current
  quoted spread. It is an execution/liquidity ordering aid, not a price forecast,
  buy recommendation or replacement for the model conditions.
- Presets: all, active/liquid (range ≥3%, turnover ≥20M USDT, spread ≤0.03%), tight spread (turnover ≥50M, spread ≤0.02%), gainers, losers, and observed/open-position bot symbols.
- Selecting a coin requests up to 180 closed 1/5/15/60-minute candles and a 200-level REST book. A chart starts with 90 candles (45 on small screens), turnover bars and VWAP of the last 60 candles. `− / % / +` changes the visible candle range and therefore the price scale; the chosen scale is saved separately for each timeframe and is not reset by a quote update or an internal panel switch. TradingView links and the overview chart support any selected screener symbol. Mobile rows show turnover, range and spread under each coin without horizontal scrolling.
- The chart supports time zoom around the pointer, price zoom over the right axis, drag panning, pinch zoom and double-click reset. Views are stored per symbol and timeframe; previously saved per-timeframe scale is used as a starting point. Desktop column headings sort 24-hour change, turnover, spread or quality in either direction; a changed price briefly highlights up/down with reduced-motion support.
- Support/resistance: strict 2-left/2-right confirmed swing lows/highs, clustered within max(0.05% close, 0.25 ATR14) total width; up to three nearest zones below/above the last closed price. Zones crossing the price are omitted. Pivot counts describe history, not independent tests or probabilities. Lines beyond the visible candle price scale are shown in the level list only. This is a descriptive heuristic, not a validated trading strategy.
- Book volume: price × base quantity in USDT, separated by ±0.02/0.05/0.10% nested bands. Three largest visible price levels per side within ±0.10%. Partial depth is marked as a lower bound. Changes between distinct snapshots no more than 12 seconds apart also include cancellations and changing band membership. They are not a reconstruction of all book events or proof of execution. Snapshot age is shown.
- Bot activity: actual saved A/B/C/D phases and positions, entry notional and last close. Stale or halted positions are explicitly historical. Grid stays in its existing tab. C/D still require their separate `install_research.py` installation.
- Alerts combine the existing B conditions, book-only watch state, and fresh C/D
  research checks. Green/red means a fresh model condition; yellow means only
  observation. A position, cooldown or stale feed blocks the entry label. The
  list patches existing cards rather than recreating them on every refresh, so
  open details and scroll context do not blink away.
- Browser notification permission is requested only on a user click. When enabled,
  a newly confirmed entry or new PAPER position can notify while the tab is hidden
  and the browser remains active. Notifications are not push delivery and are
  unreliable if the browser or phone suspends the page. Sound uses distinct tones
  for LONG and SHORT and works only on a visible page after a user gesture.

## Deployment and resource use

This update changes the panel only. Existing `tools/update.sh <full SHA>` installs it; no service, VPN, firewall, account or model configuration changes. New endpoints are read-only `/api/screener`, `/api/market-chart?symbol=BTCUSDT&interval=5`, and `/api/market-book?symbol=BTCUSDT`. A fixed hostname and allowlisted public endpoints prevent arbitrary URL requests. Query symbols/timeframes are validated. No credentials are used.

Two background workers, at most two outstanding requests, 24 cached results, 6-second upstream timeout, 2 MB response cap. Cached data is shared across browsers. The panel service prefetches the shared top-100 ticker snapshot every 5 seconds even when no browser has opened the screener. The browser continues updating its selected screener symbol and alert/model snapshots while another section of the same dashboard is open; only DOM painting is deferred for the hidden section. Candles refresh after 25 seconds and the selected book after 2 seconds. A transient refresh error retains the last verified response until its actual timestamp expires; it is never relabelled as fresh. Local UI expires tickers at 45 seconds, candles at 75 seconds since fetch (also checks last closed candle end), and books at 8 seconds. Source errors hide the corresponding data. The feature works when B is halted, except B's trade flow and bot feed-dependent execution. The browser cannot promise background sound while the whole browser tab is suspended, but server-side snapshots and PAPER models continue independently of the open panel section.

Bybit blocked or unavailable: the UI shows unavailable/queued/stale status. It does not fall back to invented prices or silently label historical results live. Analytics cache is in memory and lost on panel restart; model and journal persistence are unaffected.

Primary API references:

- https://bybit-exchange.github.io/docs/v5/market/tickers
- https://bybit-exchange.github.io/docs/v5/market/kline
- https://bybit-exchange.github.io/docs/v5/market/orderbook

Validation: backend tests cover ticker units/filtering, closed candles/gaps, confirmed swings, flat charts, order-book notional/coverage, request coalescing/backoff and invalid queries. Browser checks cover search, presets, coin/timeframe selection, overlays, volume bars, bots, small-screen overflow and data expiration.
