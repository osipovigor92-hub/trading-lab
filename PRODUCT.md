# Product: Trading Lab

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

The existing panel uses HTML, CSS, browser JavaScript and a Python HTTP server. Exchange charts use the locally served official TradingView Lightweight Charts 5.2.1 bundle; no chart service or CDN receives the selected symbols. Public market requests share a bounded Python background cache. This documents the current stack; it does not introduce a framework or deployment change.

## Users

The project owner follows crypto coins for manual trading. Their stated problems are alerts that disappear and a screener whose changing rank moves coins away from the place they were watching.

## Product Purpose

Find observable market activity, keep chosen coins easy to follow, explain the current setup, and let the user check risk before making a manual decision. The activity index measures observations; it is not a probability of profit.

## Operating Context

The website has five pages: **Скринер**, **Плотности**, **Алерты**, **Позиции**, and **Настройки**. The user's later request for a screenercrypto.ru-style chart screener and densities expands the earlier four-page assistant. Tests, models, journals, an independent orderbook page and Live remain removed from the website. The observation event feed remains part of the table screener and alerts workflow.

The chart screener and density monitor use public REST adapters for Binance, Bybit, OKX, Gate and Bitget USDT perpetual contracts. Exchange and symbol together identify a source; the same coin on two exchanges is not a shared quote. The existing detailed activity table continues to use Bybit public REST data for linear USDT perpetual contracts. Tickers cover the top 100 valid contracts by 24-hour turnover; expiry and pre-listing contracts are excluded. A watched symbol still has to be present in this bounded universe.

`tools/preview.py` uses isolated synthetic fixtures and an isolated temporary PAPER ledger. Its visible demo banner and screenshots must not be presented as live exchange evidence. Observation timestamps use the browser's locale; exchange-chart candle readouts and time axes use UTC. Freshness checks use source timestamps.

## Capabilities and Constraints

- **Chart screener:** the default view is a grid of 4/6/9/12 charts, with exchange, timeframe, search, watch and metric controls. Metrics include 24h turnover/change/trades, closed-candle NATR 5m/14 and 1m/30, and 5m change. Missing provider trade counts remain unavailable. Only verified loaded candle packets contribute derived metrics; sorting is explicit and tile order stays pinned. A dialog expands a source-specific chart; the Bybit dialog can open the existing activity table and risk calculator.
- **Interactive candles:** grid and expanded exchange charts share one native candlestick renderer, right price scale, time axis, crosshair and OHLCV candle readout. Periods are 1m, 5m, 15m, 1h, 4h and 1d. Mouse drag, wheel/pinch zoom and focused keyboard controls (`+`, `−`, arrows and `Home`) change the local viewport without fetching more history. A historical viewport preserves its UTC anchors as the bounded window rolls; a latest viewport follows new closed candles. The dialog can show a separate base-volume pane and EMA20/50 plus VWAP60 lines. These operate on the loaded closed candles; no older-history loading or unclosed live candle is implied. Source switches clear the previous source. Stale candles remain readable with explicit unconfirmed status and contribute no current metric.
- **Densities:** display public bid/ask levels, default size at least 100,000 USDT and distance 0–5%, exchange/include/exclude/side/size/distance filters, per-contract level limits and size/distance/age sorting. A table and distance radar share the real row data. Backend tracking starts at 50,000 USDT, scans at most 20 contracts with watch priority and exposes actual coverage. The browser polls only the visible density page every five seconds; the monitor visits a full bounded shortlist periodically, normally in ten seconds. Watched pairs preserve exchange identities and are capped at 20.
- **Density continuity:** one-hour cards require the backend's active stable flag and at least 3,600 seconds of sequential fresh observations. The browser never advances that age. Source gaps, outages, restart and levels outside fetched depth interrupt confirmation; two new covered misses confirm disappearance. Confirmed missing episodes remain separately visible, including repeated episodes at the same price. Periodic snapshots cannot prove a level stayed present between checks. Failed reads retain prior levels as unavailable. No density control sends a trading command.
- **Activity table:** search, scenario filters, minimum activity, turnover and spread controls, three sort choices, up to eight watched coins, a selected-coin chart, indicator groups, setup reasons, activity breakdown and a manual risk calculator.
- **Stable order:** the default keeps existing visible symbols in their remembered order while values update. New symbols append. The user can explicitly re-sort or enable automatic ordering. Selection and watch entries persist in the browser when storage is available.
- **Bounded analysis:** watch entries get priority. Remaining slots use a ticker discovery proxy, `min(|change24_pct|,20)/20 + min(range24_pct,30)/30`, then turnover and symbol as tie-breakers. This proxy is distinct from the confirmed activity index. The worker shortlist remains at most eight pairs, with two workers, at most two outstanding upstream jobs and 24 cached packets; selected-chart requests reuse the same cache. Multiple browser requests share the latest shortlist for 30 seconds.
- **Closed-candle evidence:** assistant setups use 1-minute closed candles from a verified contiguous window of 60–180 bars. EMA20/50 use an SMA seed; RSI14 and ATR14 use Wilder smoothing. VWAP60 is exchange quote turnover divided by base volume over 60 bars, not a session VWAP. RVOL5/20 is mean base quantity over the last five bars divided by mean quantity over the preceding 20 bars. A displayed 5m/15m/1h chart does not change the assistant's 1m signal timeframe.
- **Activity index:** four independently rounded components sum to 0–100. Each component is `floor(clamp(value/cap,0,1) × maximum + 0.5)`: RVOL5/20 has cap 3 and maximum 40; 5m range has cap 1.5% and maximum 30; absolute 5m change has cap 1% and maximum 20; 24h turnover has cap 100 million USDT and maximum 10. Direction is separate from the score. Thresholds are explicit heuristics, not a performance claim.
- **Setup gates:** momentum requires the EMA/VWAP directional condition, RVOL at least 1.5, 5m range at least 0.2%, and signed 5m change of at least 0.1%. Breakout uses a first closed crossing beyond the previous 20-bar range with a 0.1 ATR buffer and sufficient relative volume. Extension beyond 1.5 ATR from the original breakout boundary blocks the continuing impulse until the close re-enters that boundary; this context is derived from the bounded candle window. Momentum episode memory is independent of the displayed breakout label. RSI is context and a late-entry warning, not an instruction to reverse a trend.
- **Freshness:** quote age is at most 45 seconds, chart age 75 seconds and closed-candle age 120 seconds, with a two-second future-clock tolerance. Missing, incomplete, misaligned, stale or failed-refresh sources produce pending analysis with no current score or positive assistant signal. Source-time rollback does not create a new transition. Pending values are shown as dashes and an explanation.
- **Alerts:** a current event is short lived, with source-dependent validity and a maximum 30-second lifetime. The browser retains up to 50 captured events for 24 hours; expiry changes the current/history label instead of deleting the observation. Clearing history does not hide still-current events or re-arm their notifications. Initial connection, source gaps and repeated polls do not replay the same episode notification. Sound and browser notifications require explicit browser controls; they require the browser to remain open.
- **Risk calculator:** LONG/SHORT, capital, risk percentage, entry, stop, target, fee and slippage are manual inputs. The estimate includes costs on both sides, limits notional to the entered capital and explains that funding and actual orderbook execution are excluded. Defaults are editable assumptions, not a statement of the user's actual exchange tariff. Preparing a PAPER draft requires a valid estimate, reward/risk of at least 1.5, a fresh chart and quote, and current price within 0.02% of the entered price; risk must be at least 0.01% and slippage must be nonnegative. Preparation transfers a zone of entry ±0.02%, the manual stop/target and cost assumptions to the Positions page, with a maximum notional of 100 USDT. It does not open a position.
- **Positions:** the existing manual PAPER account is separate from real trading: one position, initial capital 600 USDT, no leverage. The user reviews the prepared draft and explicitly confirms a virtual entry. The server checks current price, orderbook and risk against its current balance before virtual entry. A missing or unavailable PAPER installation is displayed explicitly. No real orders are sent by this workflow.
- **Settings:** density and starting page are browser preferences. Market filters and observation controls remain in their respective pages.

Removing a website section does not delete its backend service, ledger or historical data. Orderbook data remains an internal execution guard for manual PAPER even though there is no orderbook page.

## Brand Commitments

The existing name is **Trading Lab**. The user pinned the generated dark graphite screener concept, with watchlist, central table and selected-coin chart/detail columns. Russian interface copy describes observations, reasons, freshness and manual action. The later chart-screener and densities request expands the assistant while keeping models and real order execution outside its user flow.

## Evidence on Hand

Product facts above come from the user brief and current `src/trading-panel` implementation. The approved concept is an AI-generated interface reference; its example prices, scores and claims are illustrative. It is not a shipping asset.

The final bounded batch contains 18 synthetic captures: `artifacts/assistant-{market,table,densities,alerts,positions,settings}-{1280,390,320}.png`. Root inspected the chart grid and densities at desktop/mobile widths and representative retained-page captures. One grouped fix batch and one confirmation batch established the visual verdict; all captures passed overflow and browser-error checks. A navigation color transition found during confirmation was corrected and verified through focused functional assertions. Browser tests cover five-page navigation, table/PAPER continuity, chart exchange isolation, explicit ordering, density filters, source-preserving watch/chart actions, radar, stale/outage retention, malformed preferences and visible-only polling. Captures establish interface evidence, not live market availability. No generated raster is shipped by this redesign.

## Product Principles

Keep a coin trackable while values change. Keep an observation readable after its freshness expires. Explain why a measurement is unavailable. Keep score, direction, historical observation and current execution checks distinct. Preserve manual choice and the PAPER boundary.

The subsequent native-chart update passed its own bounded review: 21 synthetic captures cover the five pages, table and expanded chart at 1280/390/320px. Root inspected the default grid and expanded charts at desktop/mobile widths, corrected the hidden-dialog initial width and selected-period accessibility in one grouped fix batch, then completed one confirmation batch. No page/dialog overflow or browser errors remained. Functional browser checks passed for historical OHLCV crosshair, zoom/pan/reset without market requests, the separate volume pane, six periods, source/watch isolation, stale history and UTC viewport preservation across rolling candle windows. No further visual polish loop was run; captures remain synthetic evidence. No raster ships.
