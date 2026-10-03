# Trading Lab dashboard layout

The screener is the initial page for a first visit. An existing session returns to its last section. Desktop uses a left sidebar; phones use five bottom actions and a native “Ещё” menu for graph, LIVE, journals, Grid, tests and presentation preferences.

The screener groups real market rows, closed-candle analysis, shared B/orderbook alert classifications, the selected REST ladder and PAPER states A/B/C/D on one page. Search, preset chips, sorting, turnover thresholds and locally saved favorites filter the actual results. Settings affect presentation only. The existing TradingView iframe moves to the graph page; A/B and C/D journal downloads and the common-period report move to the journal page.

Numbers are not taken from the design image. Five best prices per side are returned alongside existing depth bands and largest levels. Ladder volume is price × quantity in USDT; ±0.1% totals remain conservative if the received book does not cover the band. All price miniatures use either actual closed candles or observed ticker snapshots; no invented curves. Support and resistance preserve the confirmed-pivot calculation. Unavailable data render an empty/loading state.

Compact alerts call the same `collectAlerts`/classifiers as the alert page. A watch card is yellow and never becomes a confirmed entry just because a liquidity condition passed. Open position and cooldown continue to block B entries. Stale prices, candles and volumes are hidden and stale alerts lose directional color. Model state stays separate from market liquidity.

This revision changes the panel only. It does not change model rules, reset balances, alter existing journals, or modify VPN/network services. It is applied through the existing guarded, pinned updater.

Validation: existing offline engine/client checks plus browser scenarios for 320/390/1280 px, all ten sections, favorites and preferences across reloads, preserved disclosures, journal/CSV locations, iframe isolation, duplicate alert history and simulated expiration. Preview screenshots use a clearly labelled isolated synthetic fixture, not production observations.
