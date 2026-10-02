# Market terminal · 2026-10-01

## Research and interpretation

Primary sources reviewed:
- TradingView Advanced Chart embed: https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/
- Bybit snapshot/delta reconstruction: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
- Cont, Kukanov, Stoikov, *The Price Impact of Order Book Events*: https://arxiv.org/abs/1011.6402
- Gould, Bonart, *Queue Imbalance as a One-Tick-Ahead Price Predictor*: https://arxiv.org/abs/1512.03492
- Bailey et al., *The Probability of Backtest Overfitting*: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

OFI and queue imbalance have empirical relationships with short-horizon price changes in the stock-market datasets studied. This does not establish a profitable crypto strategy after costs. Market depth and executed trade flow describe different events. Cancellation cannot be identified as spoofing from these aggregates. No indicator always works.

The interface therefore exposes context (EMA/VWAP trend, ATR, RVOL), execution costs, nested depth bands, and separate rolling trade-flow windows. Model B remains the existing trend/pullback/resumption hypothesis with confirmation and cost filters. Breakout/relative-volume and range/VWAP-reversion approaches are research candidates described in the help panel, NOT newly implemented strategies. Future variants require frozen rules, chronological forward evaluation after costs, and separate versioned journals. A/B sample size and costs must remain visible.

## Features and data contracts

- Redesigned visual system on all six tabs. Overview contains A/B total P&L, selected B contract, TradingView, decision reasons, liquidity, comparison and journal curves. Previous A detail remains expandable.
- TradingView loads only after the user clicks. BYBIT:<SYMBOL>.P perpetual contract; 1/5/15/60 minute views. Invalid symbols fall back to LINKUSDT. Attribution and external chart link remain visible. No trade integration or data feed to the model.
- A sandboxed same-origin `/chart.html` loads the official TradingView embed. The trusted local wrapper creates a cross-origin provider iframe with scripts, same-origin storage and popups enabled. No third-party JavaScript executes in the local wrapper; browser origin isolation separates the provider from authenticated APIs. Third-party scripts do not run in the authenticated dashboard document. Parent CSP permits only same-origin frames and scripts. Widget document CSP permits only local scripts and two known provider frame origins. Widget is external and may be unavailable by region/network; opening the external link is always possible.
- Book rows are separate cumulative ±0.02%, ±0.05%, ±0.1% bands, NEVER summed. Incomplete bands are labeled. No fabricated full-depth ladder or historical heatmap.
- Trade flow windows are independent rolling 5/15/60 seconds, NOT cumulative CVD. OFI is displayed in contract quantity units. Not-ready flow is labeled.
- Price/spread sparklines retain up to 120 observed B snapshots in browser memory; a gap over six seconds resets the curve. These are not candles. Book age over three seconds or source age over eight seconds suppresses current metrics. Chart metrics also require recent closed candles.
- Journal curves are cumulative net starting at zero for the report's returned records (up to 200), NOT full account equity. Common-period A/B stats remain the server report, with incomplete/stale labels.
- Alerts persist at most 50 transitions for 24 hours in localStorage in this browser, NOT on the server. Initial entries are recorded silently, reversals are separate events, canceled/blocked entries produce neutral events. Repeating the same state does not duplicate events. Page closed means no collection. Storage denial degrades to memory only.
- Audio is opt-in each page load and requires a user gesture; no guarantee in background iOS. No external messaging or browser push. Clear-history control removes stored events.

## Operational scope

Only trading-panel files change in production. Models A/B, scanner, reports, HTTPS gateway, firewall, Xray and runtime ledgers are unchanged. Guarded updater restarts the panel only. The existing gateway's Basic Auth and localhost Host handling remain intact. TradingView loading happens on the user's browser, not a new VPS market-data service.

## Verification

`python3 tools/check.py`: syntax checks, model/report/deployment tests, preview isolation, alert classification/transition tests, aggregate/plot tests, request cache tests, model selftests.

`node tools/visual-check.cjs`: isolated synthetic preview, desktop/mobile tab layout, chart sandbox and interval changes (provider frame transport stubbed for deterministic CI), alert colors/filtering, persisted history, cancellation and stale-state behavior. CI screenshots are synthetic examples, not current trading results. Real third-party chart availability and iOS audio remain dependent on the user's browser/network.
