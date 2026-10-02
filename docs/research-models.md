# Free open-source tools and research screeners C/D

Verified 2026-10-02. The user replaced the paid-platform request with free well-known tools. The visible catalog now contains Freqtrade, Hummingbot and the free research core of Jesse. These are frameworks, not certified profitable strategies. No external engine is installed by this panel-only update; no subscriptions or API keys are connected.

## Official comparison sources

- Freqtrade: free/open-source Python bot with backtesting, dry-run and web UI. https://www.freqtrade.io/en/stable/ and https://github.com/freqtrade/freqtrade
- Strategy verification: https://www.freqtrade.io/en/stable/strategy-101/ and https://www.freqtrade.io/en/stable/lookahead-analysis/
- Public example strategies, not endorsed profitable: https://github.com/freqtrade/freqtrade-strategies
- Hummingbot: Apache2.0 open-source framework for market making/algorithmic execution. https://github.com/hummingbot/hummingbot and https://hummingbot.org/strategies/
- Paper support is connector/strategy-specific; do not infer Bybit paper support from generic descriptions: https://hummingbot.org/client/global-configs/paper-trade/
- Jesse: MIT core for research/backtests, with CPU limits on free optimization; live-trading plugin is paid and clearly excluded from a fully free live recommendation. https://github.com/jesse-ai/jesse and https://jesse.trade/pricing and https://jesse.trade/help/faq/why-do-i-have-to-pay-for-live-i-thought-its-open-source

Engineering priority: evaluate Freqtrade for candle-based backtesting and bias checks, Hummingbot for order execution research, Jesse as an optional research alternative. This is an engineering fit assessment, not a profitability ranking. Infrastructure, market data and exchange costs remain. Original C/D code copies none of these projects' implementations.

## Research sources and limits

- VWAP definition: https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/
- ATR definition: https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/
- Relative volume definitions: https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/
- Cont, Kukanov, Stoikov, order flow imbalance: https://arxiv.org/abs/1011.6402 (equity data; does not validate this crypto implementation).
- Bailey et al., backtest overfitting: https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf

Our features come from the existing B feed. VWAP60 is turnover/base volume over60closed minutes; RVOL5 is average turnover over5closed minutes divided by average over the preceding60. These are explicitly different from session VWAP and TradingView RVOL10. ATR14 uses the existing B Wilder-style smoothing. No new candles are fetched by the browser.

## Fixed version 2026-10-02.1

Common gates: source running, state<=8s, book<=3s, closed candles<=120s; finite positive prices/ATR; ready and trade age<=10s; spread<=0.025%; positive known modeled roundtrip cost; fully covered +/-0.05% band with each side>=5000USDT; flow15>=1500USDT and>=10trades; funding more than300s away. Depth imbalance is recomputed from notional amounts; tape ratios from executed buy/sell amounts, not trusted supplied ratios.

C trend impulse: existing EMA/VWAP side plus current price on the same side of VWAP; RVOL>=1.5; current move from last closed minute price in trend direction between0.15 and1ATR; ATR/current price>=1.5times modeled cost.

D VWAP reversion: EMA gap<=0.25ATR, RVOL<=1.2; current VWAP distance between0.75 and2ATR; price has moved toward VWAP relative to last closed minute; VWAP distance/current price>=2times modeled cost. The EMA-gap proxy does not prove a stable sideways regime.

Both: +/-0.05% imbalance>=15% in hypothetical direction, OFI5 sign agreement, tape5>=30% and tape15>=20% directional imbalance. Three distinct ordered book snapshots spanning>=4s are required. Duplicate snapshots cannot increase confirmation; direction change, failed gate, a gap>6s or stale data resets it. These constants are initial research settings, not optimized or literature-derived profit thresholds. ATR or VWAP distance is not expected profit.

## Not an executor or backtest

C/D run only while the browser is open. There is no persistent C/D trade journal, equity or P&L. Purple means an observed condition match, not an entry order. Current B selection limits the observable universe; results cannot be generalized to all Bybit coins. Reloading resets confirmations. Real B alerts remain in their separate tab.

Next validation requires a separate server-side PAPER executor with versioned state, entry/exit and fill definitions, execution costs, funding/gap handling and an immutable trade journal. Freeze rules before subsequent data; compare common-period net returns, drawdown, expectation, sample count and regime coverage with A/B; report all tried variants and uncertainty. Neither two losses nor a short winning streak establishes superiority.

## Validation

Unit tests cover both directions, regime and cost gates, malformed/stale/future inputs, missing book coverage, funding exclusion, distinct-snapshot confirmation and resets. Browser tests cover the new tab at390/1280px, all6 research cards, catalog links, preserved expanded details, expiry and no entry-alert styles for research.
