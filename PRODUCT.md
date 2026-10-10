# Product: Trading Lab

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

The existing panel uses HTML, CSS, browser JavaScript and a Python HTTP server. Public market requests share a bounded Python background cache. This documents the current stack; it does not introduce a framework or deployment change.

## Users

The project owner follows crypto coins for manual trading. Their stated problems are alerts that disappear and a screener whose changing rank moves coins away from the place they were watching.

## Product Purpose

Find observable market activity, keep chosen coins easy to follow, explain the current setup, and let the user check risk before making a manual decision. The activity index measures observations; it is not a probability of profit.

## Operating Context

The website has four pages: **Скринер**, **Алерты**, **Позиции**, and **Настройки**. The user explicitly removed tests, models, grid, journals, orderbook and Live sections from the website. The observation event feed remains part of the screener and alerts workflow.

Production market adapters read Bybit public REST data for linear USDT perpetual contracts. Tickers cover the top 100 valid contracts by 24-hour turnover; expiry and pre-listing contracts are excluded. A watched symbol still has to be present in this bounded universe.

`tools/preview.py` uses isolated synthetic fixtures and an isolated temporary PAPER ledger. Its visible demo banner and screenshots must not be presented as live exchange evidence. Browser timestamps use the browser's locale; freshness checks use source timestamps.

## Capabilities and Constraints

- **Screener:** search, scenario filters, minimum activity, turnover and spread controls, three sort choices, up to eight watched coins, a selected-coin chart, indicator groups, setup reasons, activity breakdown and a manual risk calculator.
- **Stable order:** the default keeps existing visible symbols in their remembered order while values update. New symbols append. The user can explicitly re-sort or enable automatic ordering. Selection and watch entries persist in the browser when storage is available.
- **Bounded analysis:** watch entries get priority. Remaining slots use a ticker discovery proxy, `min(|change24_pct|,20)/20 + min(range24_pct,30)/30`, then turnover and symbol as tie-breakers. This proxy is distinct from the confirmed activity index. The worker shortlist remains at most eight pairs, with two workers, at most two outstanding upstream jobs and 24 cached packets; selected-chart requests reuse the same cache. Multiple browser requests share the latest shortlist for 30 seconds.
- **Closed-candle evidence:** assistant setups use 1-minute closed candles from a verified contiguous window of 60–180 bars. EMA20/50 use an SMA seed; RSI14 and ATR14 use Wilder smoothing. VWAP60 is exchange quote turnover divided by base volume over 60 bars, not a session VWAP. RVOL5/20 is mean base quantity over the last five bars divided by mean quantity over the preceding 20 bars. A displayed 5m/15m/1h chart does not change the assistant's 1m signal timeframe.
- **Activity index:** four independently rounded components sum to 0–100. Each component is `floor(clamp(value/cap,0,1) × maximum + 0.5)`: RVOL5/20 has cap 3 and maximum 40; 5m range has cap 1.5% and maximum 30; absolute 5m change has cap 1% and maximum 20; 24h turnover has cap 100 million USDT and maximum 10. Direction is separate from the score. Thresholds are explicit heuristics, not a performance claim.
- **Setup gates:** momentum requires the EMA/VWAP directional condition, RVOL at least 1.5, 5m range at least 0.2%, and signed 5m change of at least 0.1%. Breakout uses a first closed crossing beyond the previous 20-bar range with a 0.1 ATR buffer and sufficient relative volume. Extension beyond 1.5 ATR from the original breakout boundary blocks the continuing impulse until the close re-enters that boundary; this context is derived from the bounded candle window. Momentum episode memory is independent of the displayed breakout label. RSI is context and a late-entry warning, not an instruction to reverse a trend.
- **Freshness:** quote age is at most 45 seconds, chart age 75 seconds and closed-candle age 120 seconds, with a two-second future-clock tolerance. Missing, incomplete, misaligned, stale or failed-refresh sources produce pending analysis with no current score or positive assistant signal. Source-time rollback does not create a new transition. Pending values are shown as dashes and an explanation.
- **Alerts:** a current event is short lived, with source-dependent validity and a maximum 30-second lifetime. The browser retains up to 50 captured events for 24 hours; expiry changes the current/history label instead of deleting the observation. Clearing history does not hide still-current events or re-arm their notifications. Initial connection, source gaps and repeated polls do not replay the same episode notification. Sound and browser notifications require explicit browser controls; they require the browser to remain open.
- **Risk calculator:** LONG/SHORT, capital, risk percentage, entry, stop, target, fee and slippage are manual inputs. The estimate includes costs on both sides, limits notional to the entered capital and explains that funding and actual orderbook execution are excluded. Defaults are editable assumptions, not a statement of the user's actual exchange tariff. Preparing a PAPER draft requires a valid estimate, reward/risk of at least 1.5, a fresh chart and quote, and current price within 0.02% of the entered price; risk must be at least 0.01% and slippage at least 0.001%. Preparation transfers a zone of entry ±0.02%, the manual stop/target and cost assumptions to the Positions page, with a maximum notional of 100 USDT. It does not open a position.
- **Positions:** the existing manual PAPER account is separate from real trading: one position, initial capital 600 USDT, no leverage. The user reviews the prepared draft and explicitly confirms a virtual entry. The server checks current price, orderbook and risk against its current balance before virtual entry. A missing or unavailable PAPER installation is displayed explicitly. No real orders are sent by this workflow.
- **Settings:** density and starting page are browser preferences. Market filters and observation controls remain in their respective pages.

Removing a website section does not delete its backend service, ledger or historical data. Orderbook data remains an internal execution guard for manual PAPER even though there is no orderbook page.

## Brand Commitments

The existing name is **Trading Lab**. The user pinned the generated dark graphite screener concept, with watchlist, central table and selected-coin chart/detail columns. Russian interface copy describes observations, reasons, freshness and manual action. The later four-page instruction takes precedence over extra sections visible in the illustrative concept.

## Evidence on Hand

Product facts above come from the user brief and current `src/trading-panel` implementation. The approved concept is an AI-generated interface reference; its example prices, scores and claims are illustrative. It is not a shipping asset.

Final captures are `artifacts/assistant-{market,alerts,positions,settings}-{1280,390,320}.png`. They show synthetic preview data. Root inspected all four pages at all three widths and reported a passed visual verdict after one grouped fix batch, with no page overflow or browser errors. The documenter inspected the final market captures at 1280 and 390 and verified the PAPER handoff against source. These captures establish interface evidence, not live market availability. No generated raster is shipped by this redesign.

## Product Principles

Keep a coin trackable while values change. Keep an observation readable after its freshness expires. Explain why a measurement is unavailable. Keep score, direction, historical observation and current execution checks distinct. Preserve manual choice and the PAPER boundary.
