# Crypto screener and levels

See [stable tracking](stable-tracking.md) for pinned row order, historical rating
labels, priority watchlists and the retained alert feed added after these stages.

The **Скринер** tab lists the top 100 valid Bybit linear USDT perpetual tickers by 24-hour turnover. Search, minimum turnover, sorting and presets run locally. Expiry futures, pre-listing rows, malformed and duplicate tickers are excluded. This does not change the symbol selection or entry rules of trading models.

- Price, 24-hour change, turnover in USDT, daily high/low range and quoted bid/ask spread.
- A transparent **«Рейтинг»** score (0–100): four integer parts for liquidity,
  spread, relative volume and the order book, with measured values and explanations.
  It describes observed market conditions; see Stage 2 below for the fixed formula.
- Presets: all, active/liquid (range ≥3%, turnover ≥20M USDT, spread ≤0.03%), tight spread (turnover ≥50M, spread ≤0.02%), gainers, losers, and observed/open-position bot symbols.
- Selecting a coin requests up to 180 closed 1/5/15/60-minute candles and a 200-level REST book. A chart starts with 90 candles (45 on small screens), turnover bars and VWAP of the last 60 candles. `− / % / +` changes the visible candle range and therefore the price scale; the chosen scale is saved separately for each timeframe and is not reset by a quote update or an internal panel switch. TradingView links and the overview chart support any selected screener symbol. Mobile rows show turnover, range and spread under each coin without horizontal scrolling.
- The chart supports time zoom around the pointer, price zoom over the right axis, drag panning, pinch zoom and double-click reset. Views are stored per symbol and timeframe; previously saved per-timeframe scale is used as a starting point. Desktop column headings sort 24-hour change, turnover, spread or rating in either direction; a changed price briefly highlights up/down with reduced-motion support.
- Support/resistance: strict 2-left/2-right confirmed swing lows/highs, clustered within max(0.05% close, 0.25 ATR14) total width; up to three nearest zones below/above the last closed price. Zones crossing the price are omitted. Pivot counts describe history, not independent tests or probabilities. Lines beyond the visible candle price scale are shown in the level list only. This is a descriptive heuristic, not a validated trading strategy.
- Book volume: price × base quantity in USDT, separated by ±0.02/0.05/0.10% nested bands. Three largest visible price levels per side within ±0.10%. Partial depth is marked as a lower bound. Changes between distinct snapshots no more than 12 seconds apart also include cancellations and changing band membership. They are not a reconstruction of all book events or proof of execution. Snapshot age is shown.
- The selected coin card exposes price, OI, contract funding, VWAP, ATR and
  base-quantity volume without expanding details. Quotes, candles and the book
  have independent age/status indicators; see Stage 3 below.
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

### Stage 1: smart coin selection

The **«Умный отбор · фильтры и проверка»** section adds adjustable eligibility
thresholds. Each row exposes every check, its value and threshold, and one of
**«прошёл»**, **«проверяется»**, **«отсев»**. Use **«Показать»** to show passed,
pending or rejected rows. Defaults are heuristics for screening, not validated
trading parameters. They can be changed and reset; preferences are saved in the
browser. Selection thresholds determine eligibility separately from the rating.

| Check | Default | Unit / calculation |
| --- | --- | --- |
| 24h turnover | ≥20 million | USDT |
| Spread | ≤0.03% | Quoted spread and worst spread across 5 books |
| 24h range | 1–30% | Existing daily high/low range |
| ATR(14) | 0.08–0.8% | Closed 1-minute candles |
| Relative volume | ≥1× | Mean base quantity of last 5 closed minutes / previous 20 |
| Open interest | ≥1 million | `openInterestValue`, USDT |
| Absolute funding | ≤0.05% | `fundingRate` ×100, per contract interval; interval shown when available |
| Depth | ≥5,000 | Minimum Bid and Ask USDT inside ±0.1% over 5 books |
| Impact | ≤0.05% | Worst VWAP movement from best quote for quantity equal to ~100 USDT at mid, both sides, 5 books |

The base 24h volume must be positive. Missing OI, funding or quantity means
**«проверяется»**, never an assumed zero. Any known failed threshold gives
**«отсев»**. Passing requires all checks and five distinct exchange book sequences
at least 1.5 seconds apart within 60 seconds; the latest must be at most 12 seconds
old. The entire ±0.1% band must be covered. Candles expire after 75 seconds,
their last closed minute after 120 seconds, and tickers after 45 seconds.
The browser also expires passed results and rejects a verification from a
different ticker snapshot. A failed refresh cannot preserve a passed label.

`GET /api/market-selection` accepts the 11 named numeric thresholds in
`selection.DEFAULT_FILTERS` and optional uppercase alphanumeric `search` (≤24
characters). Unknown, repeated, empty, nonfinite, out-of-bounds and inverted
range/ATR parameters return 400. This endpoint reads only public market data.

To fit the small VDS, ticker checks cover the top 100, but candles and order
books warm for only **up to 8 pairs**, prioritised by turnover after ticker
thresholds and the current search. Other pairs remain pending until analysed;
there is no claim that all 100 books have been checked. Use search to prioritise
a specific pair. Initial collection can take about a minute when eight pairs
are eligible, longer if the exchange is unavailable. Several browsers share the
same cache; the most recent request sets the shortlist for 30 seconds. Without
browser requests the default shortlist is warmed. Memory remains bounded:
24 cached responses, histories for 24 symbols with 5 summaries each, and the
existing 2 workers / 2 outstanding upstream calls. No new service is required.

Offline checks: `python tools/check.py`. Browser checks additionally run
`node tools/test_selection_ui.cjs` for threshold changes, reset/persistence,
explanations retained across refresh, pending/stale/error data, and widths
1280/390/320. The preview uses explicitly synthetic data.

### Stage 2: candidate rating and explanations

The old turnover/quoted-spread-only score is replaced by a server-calculated
rating. Click the desktop score or expand the selection line under the symbol
on any screen to see four parts, their observed values and labels such as
**«Ликвидность высокая»**, **«Спред узкий»**, **«Объём растёт»** and
**«Стакан подтверждает»**. The method can be expanded above the list.

Each part is clamped to 0–25 and rounded to the nearest integer (half up).
The final 0–100 score is exactly the sum of the displayed parts.
Let `clamp(x)` bound x to 0–1. Percent values below use percentage points,
so a 0.01% spread is the number `0.01`.

| Part | Raw points before rounding | Explanation / input |
| --- | --- | --- |
| Liquidity | `25 × clamp((log10(T) − log10(2,000,000)) / 2)`; zero when T=0 | T is 24h turnover in USDT: 2M gives 0, 20M gives 13, 200M gives 25; «высокая» at ≥100M |
| Spread | `25 × clamp(1 − S / 0.05)` | S is the larger of the quoted spread and worst spread of five books; «узкий» at ≤0.02% |
| Volume | `25 × clamp(R / 2)` | R is mean base quantity per minute over the last five closed minutes / the previous twenty; 1× gives 13, 2× gives 25; «растёт» means ≥1.2× that baseline |
| Book | `15 × clamp(D / 20,000) + 10 × clamp(1 − I / 0.05)` | D is the lowest Bid/Ask depth in USDT inside ±0.1% across five books; I is their worst estimated impact in %, for ~100 USDT; «подтверждает» requires all current book checks to pass |

These anchors are explicit screening heuristics, not a trained predictor or
a probability of profit. Changing eligibility thresholds does not rescale the
four components. A fully observed coin that fails a threshold can retain a
numeric rating and its **«отсев»** state. Rating sorting groups passed coins
first, pending coins second, rejected coins last in both directions; known
scores precede unavailable ones inside a group. Equal ratings use turnover,
then symbol for stable ordering.

The final score requires all 12 selection checks to have known finite values
(coverage must be true), five complete books, and the same source freshness
limits as Stage 1. Missing OI/funding or an incomplete book cannot produce a
complete score. Known component points remain visible but are neither replaced
by zero nor renormalised; the total shows **«проверяется»** / **«—»**.
The browser checks freshness and that all four parts add up to the total;
a stale source, different ticker snapshot, malformed total or failed API
refresh removes the complete rating. There is no ticker-only fallback.

Rating is calculated from the existing selection data, with no added upstream
requests, caches, workers or services. It does not change model entry rules,
positions or journals. Tests cover exact sums, rounding and anchors, monotonic
responses, worst-book measurements, invalid/missing/stale inputs, threshold
independence, sort grouping and desktop/mobile expansion with live refresh.

### Stage 3: selected coin card

Selecting a coin updates the **«Карточка выбранной монеты»** section and its
adjacent book. Existing 1m/5m/15m/1h charts, confirmed levels, zoom/pan, overlays
and turnover bars are retained. The four timeframe controls remain visible on
small screens and use 44px touch targets. Views remain saved per symbol/timeframe.

Six always-visible measurements use the selected symbol and timeframe:

| Measurement | Unit and meaning |
| --- | --- |
| Price | Latest ticker price in USDT; 24h change and turnover below it |
| OI | `openInterestValue` in USDT from the shared ticker snapshot; unknown OI stays unavailable |
| Funding | `fundingRate × 100`, signed %, per contract interval; e.g. −0.0002 becomes −0.02%. Interval is shown only when supplied; it is never assumed to be eight hours |
| VWAP | Sum of turnover in USDT / sum of base quantity over the latest 60 closed candles, in USDT; unavailable for zero total quantity |
| ATR(14) | Mean of the last 14 true ranges, in USDT and % of the last closed price, for the selected timeframe |
| Volume | Sum of base quantity over the latest 60 closed candles, labelled with the selected base asset; turnover in USDT is shown separately |

The detailed levels section retains the last closed price and **RVOL by
turnover over 5 / previous 20 candles**. This chart measure is explicitly
labelled and is distinct from the base-quantity minute RVOL used by selection
and ranking. Both volume and turnover can be valid measured zeros. Missing OI,
funding or VWAP is shown as **«—»**, without substituting zero. Main price
measurements use compact precision; exceptionally small nonzero prices use
scientific notation rather than becoming a displayed zero.

The card shows each source's original timestamp and age:

- Quotes expire after 45 seconds. OI/funding use this same observed snapshot
  time; no separate exchange update time for those fields is claimed.
- Candles expire after 75 seconds since their fetch and when the latest closed
  candle end exceeds one selected period plus 75 seconds. Stale candles hide
  the chart, zones and candle-based measurements, while fresh quote values remain.
- The book expires after 8 seconds. Expired book depth is hidden while fresh
  chart and quote values remain. Incomplete ±0.1% coverage is marked as a lower
  estimate, independently of timestamp freshness.

Loading, unavailable, stale and missing-symbol states are explicit. A failed
refresh can retain a previously verified response only within its original
freshness window and displays **«повторяем обновление»**. An old response is
never stamped with the browser's current time. Responses for another symbol
or timeframe cannot populate the card; request generation prevents a slow
previous selection from overwriting the currently selected coin. Native open
details and metric DOM nodes survive updates.

The backend exposes existing calculated ATR and base-quantity volume as
`atr` and `volume_window` in `/api/market-chart`. No additional upstream API
calls, services, workers, cache entries, dependencies or model changes are
introduced. Offline tests cover the units, zeros, funding conversion and
independent expiry. `node tools/test_coin_card_ui.cjs` checks all four
timeframes at 1280/390/320, missing/negative/zero/partial/wrong/stale/error
responses, delayed coin switching, persistence and recovery; it also runs in CI.

### Stage 4: selected coin PAPER trade plan

The **«План сделки · PAPER»** section follows the selected coin card. It shows
direction, entry zone, stop, up to two confirmed-zone targets, base quantity,
virtual entry notional, planned stop loss, risk budget and net reward/risk.
It uses the selected 1/5/15/60 minute chart plus the existing minute selection
packet and selected book. There are no additional upstream requests or services.
It is a planning calculation; model actions, balances, positions and journals
are unchanged. No trading or control POST request is sent.

The fixed hypothesis is a pullback to a confirmed zone:

- LONG requires EMA20 > EMA50, the latest closed price above VWAP, and a
  positive close-to-close move over five bars; SHORT requires all opposites.
  EMAs use a first-period SMA seed followed by the standard 2/(period+1) update.
- The nearest support behind the closed price is the LONG entry zone, expanded
  upward by 0.25 ATR; the nearest resistance is the SHORT zone, expanded downward.
  The stop sits 0.5 ATR beyond the far edge of that zone.
- Targets sit 0.1 ATR before the nearest and next opposite confirmed zones.
  The second assumes a break through the first zone; it is absent when no
  second zone exists. Targets are evaluated for the whole quantity separately,
  and their reported profits must not be added. A nearer unfavorable target
  cannot be skipped in order to manufacture a higher reward/risk.

Defaults, editable in **«Капитал и расчёт риска»**:

| Setting | Default | Allowed values |
|---|---|---|
| Virtual capital | 600 USDT | 10–1,000,000 USDT |
| Risk budget | 0.5% | 0.01–5% of virtual capital |
| Entry notional cap | 100 USDT | 1 USDT up to virtual capital |
| Fee per side | 0.055% | 0–1% |
| Residual slippage allowance per side | 0.05% | 0–5% |
| Minimum net reward/risk to first target | 1.5 | 1–10 |

The fee default matches the existing PAPER simulator and Bybit's published
base VIP-0 perpetual/futures taker rate, verified 2026-10-05. The account's
actual rate can differ by region, tier and special trading zone; this setting
is a simulation assumption, not a lookup of the user's account.
Sources: [Bybit fee structure](https://www.bybit.com/en/help-center/article/Trading-Fee-Structure),
[fee calculation](https://www.bybit.com/en/help-center/article/Futures-Contracts-Fees-Explained),
[funding calculation](https://www.bybit.com/en/help-center/article/Funding-fee-calculation).

Sizing uses the entry edge farthest from the stop. Let `d` be +1 for LONG or
−1 for SHORT, `E` the entry edge, `S` the stop, `T_i` a target, `f` the fee rate,
and `a = slippage_pct/100 + max(ticker_spread, book_spread)/200`.

```text
E' = E × (1 + d × a)
S' = S × (1 − d × a)
T_i' = T_i × (1 − d × a)
F = max(E', S', all T_i') × max(0, d × current_funding_rate)
L = d × (E' − S') + f × (E' + S') + F
B = capital × risk_pct / 100
Q = min(B / L, max_notional / E', capital / (E' × (1 + f)))
planned_loss = Q × L
net_profit_i = Q × [d × (T_i' − E') − f × (E' + T_i') − F]
net_RR_i = net_profit_i / planned_loss
```

`Q` is reduced by one relative machine epsilon to keep rounded arithmetic on
the conservative side of the caps. Prices and rates are dimensionally separate;
`Q` is in base coins and costs/profits are in USDT. The one adverse funding
payment is an explicit reserve using the largest modeled price and the current
rate, not a claim about the future settlement mark or holding duration.
Receiving funding gives no profit credit. Future rates and slippage can change.
The virtual fractional quantity is not exchange lot-size validation.

Readiness requires all three card sources to be **fresh**, without a transport
or retained refresh error, a complete matching **passed** selection and rating,
continuous closed bars, valid confirmed zones, full ±0.1% book coverage and
agreement between ticker, book mid and best levels. The calculated quantity
must fit the five verified visible levels on each side, with their actual
impact no greater than the configured slippage allowance; the 100-USDT
selection impact is not extrapolated to another position size.

**«Готов для PAPER»** also requires the live price inside the entry zone and
first-target net RR at least the chosen minimum. Otherwise the panel distinguishes
waiting for a return, a missing scenario, a rejected plan, missing/stale/error
inputs, a crossed stop or already reached target, and an existing fresh model
position on the same coin. A retained halted position is historical and does
not create a false active-position block. States recompute with new data;
this stage does not persist a signal lifecycle or implement stage-6 alerts.

Settings are validated and stored locally under `lab-paper-plan-v1` after
applying them. Editing immediately clears the displayed size/risk until the
new calculation is applied; invalid or partial settings never produce a ready
plan. Native expanded settings/method details and metric nodes survive refresh.
The hypothesis and thresholds require chronological PAPER evaluation before
any claim of profitability.

`node --test tools/test_paper_plan.cjs` verifies long/short geometry, net costs,
funding direction, caps, boundaries, identity/expiry/selection gates and actual
quantity depth. `node tools/test_paper_plan_ui.cjs` checks 1280/390/320 widths,
all four timeframes, input validation and persistence, waiting/cancellation,
missing/partial/stale/error data, delayed coin changes and absence of POSTs.
Both are included in CI.

This update changes the panel only. Existing `tools/update.sh <full SHA>` installs it; no service, VPN, firewall, account or model configuration changes. New endpoints are read-only `/api/screener`, `/api/market-chart?symbol=BTCUSDT&interval=5`, and `/api/market-book?symbol=BTCUSDT`. A fixed hostname and allowlisted public endpoints prevent arbitrary URL requests. Query symbols/timeframes are validated. No credentials are used.

Two background workers, at most two outstanding requests, 24 cached results, 6-second upstream timeout, 2 MB response cap. Cached data is shared across browsers. The panel service prefetches the shared top-100 ticker snapshot every 5 seconds even when no browser has opened the screener. The browser continues updating its selected screener symbol and alert/model snapshots while another section of the same dashboard is open; only DOM painting is deferred for the hidden section. Candles refresh after 25 seconds and the selected book after 2 seconds. A transient refresh error retains the last verified response until its actual timestamp expires; it is never relabelled as fresh. Local UI expires tickers at 45 seconds, candles at 75 seconds since fetch (also checks last closed candle end), and books at 8 seconds. Source errors hide the corresponding data. The feature works when B is halted, except B's trade flow and bot feed-dependent execution. The browser cannot promise background sound while the whole browser tab is suspended, but server-side snapshots and PAPER models continue independently of the open panel section.

Bybit blocked or unavailable: the UI shows unavailable/queued/stale status. It does not fall back to invented prices or silently label historical results live. Analytics cache is in memory and lost on panel restart; model and journal persistence are unaffected.

Primary API references:

- https://bybit-exchange.github.io/docs/v5/market/tickers
- https://bybit-exchange.github.io/docs/v5/market/kline
- https://bybit-exchange.github.io/docs/v5/market/orderbook

Validation: backend tests cover ticker units/filtering, closed candles/gaps, confirmed swings, flat charts, order-book notional/coverage, request coalescing/backoff and invalid queries. Browser checks cover search, presets, coin/timeframe selection, overlays, volume bars, bots, small-screen overflow and data expiration.
