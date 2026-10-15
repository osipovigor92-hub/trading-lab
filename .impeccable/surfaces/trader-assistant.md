# Surface brief: Trader assistant

## Scope

Primary target: `src/trading-panel/index.html`.

Related targets: `src/trading-panel/screener.js`, `src/trading-panel/screener.css`, `src/trading-panel/fresh-alerts.js`, `src/trading-panel/positions.js`, `src/trading-panel/layout.js`, `src/trading-panel/layout.css`, `src/trading-panel/chart-grid.js`, `src/trading-panel/chart-grid.css`, `src/trading-panel/exchange-chart.js`, `src/trading-panel/densities.js`, `src/trading-panel/densities.css`.

Current bounded extension: public forming candles and current-price display (`chart-stream.js`, `exchange-chart.js`, `chart-grid.js`, `chart-grid.css`), with incremental native rendering and bounded server HTTPS reuse. Prior directional captions, evidence and filtering remain in the existing alerts page and compact screener feed, backed by the Bybit assistant. Closed-candle proof remains independent of the display stream. These additions retain the current page composition and visual tokens.

Visitor mode: **Operate**. This brief is development documentation and is not served by the panel. The runtime context launcher was unavailable; the brief is authored directly rather than claimed to be registered by its helper.

## Task and evidence

The user finds activity, pins coins, examines a selected coin and checks a manual decision. Their explicit continuity requirements are stable row order and alerts that remain trackable after freshness expires. PRODUCT.md owns source, formula and operating constraints; DESIGN.md owns the shared visual tokens.

The later request asks alerts to show a LONG or SHORT recommendation. Confirmed Bybit 1m breakout/momentum direction now has a written caption, observed price, source, reason and invalidation. The recommendation derives from the existing setup gates; it does not change calculations or thresholds. Watch/pending, rollback and illiquid sources retain no recommendation. Entry, stop, target and position size remain manual.

Five pages now remain: Скринер, Плотности, Алерты, Позиции, Настройки. The later screenercrypto.ru reference authorizes a chart grid within the screener and public density observations. Tests, models, journals, an independent orderbook page and Live remain absent. The compact observation feed is retained as part of following signals.

## Direction contract

**THESIS:** Follow a coin through changing measurements and retained observations. The user-pinned graphite identity remains binding. The later screenercrypto.ru request adds a chart-first screener and a density workspace without changing the manual decision boundary.

**OWN-WORLD:** Graphite fields, flat bordered panels, compact sans typography, cyan actions and explicit green/rose direction labels. Identity follows the approved concept and the extracted DESIGN.md cascade.

**STORY:** Scan activity or a fresh directional setup, select or watch a symbol, inspect its source evidence, reason and invalidation, then enter manual risk assumptions. History shows what happened; current labels show what remains verified.

**FIRST VIEWPORT:** Header and exchange/search/metric controls precede the default chart grid. The Table view retains the watch/table/detail arrangement and compact observations. The density page places persisted filters above confirmed hour-old levels at left and newer/unconfirmed levels or a distance radar at right. Search, watch and refresh actions remain visible; risk is a deliberate disclosure within the activity table.

The alerts viewport retains its existing heading, event/direction filters and feed. A current directional caption appears with its scenario; source and observed price precede reason and invalidation in the same row. Current conditions remain separate from captured events. The compact table feed uses the same direction, and enabled browser-notification titles include direction and coin.

**CHART DETAIL:** The later reference specifies native interactive candles: dark plotting field, green/red candles, dotted horizontal grid, right price scale with last-price tag, UTC timeline, symbol watermark and crosshair OHLCV. Grid and dialog share a self-hosted Lightweight Charts 5.2.1 renderer. The dialog exposes six periods from 1m to 1d, local zoom/pan/reset, an optional separate volume pane and EMA20/50 plus VWAP60. Historical viewport anchors survive refresh; unconfirmed sources remain explicitly historical. This extends the chart form while preserving the approved shell and manual PAPER boundary.

**FORM:** User-pinned generated concept, implemented directly in the existing panel. No random direction selection was used; no seed key exists. The concept's illustrative Models tab and example rating claims yield to the user's explainable-activity and later chart-screener/density instructions.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Approved visual reference

AI-generated concept: `C:/Users/ПК/.codex/generated_images/01a10d8f-9ffe-7c92-9701-5bce7646e9dd/exec-6c97f90a-3b31-4e0d-b319-f1b29e6018c2.png`.

Its visual composition is binding; prices, example scores and status wording are illustrative. It is not copied into shipped site assets. The current chart is drawn from candle data, and interface icons are code assets; no generated raster ships with this change.

## Responsive and state contract

The activity table preserves the three reading columns. The chart view uses a responsive multi-chart grid; the density view separates confirmed long observations from newer and unconfirmed levels. Intermediate widths move the detail below the left workspace. Mobile uses stacked panels, a locally scrollable table and five fixed bottom navigation items. Selected/watch states remain explicit.

Pending, stale, source-error, empty-watch and absent-PAPER states explain the next available action. Missing score and indicator values remain dashes. Historical events keep their coin action and time. The user decides when to re-sort; watch order does not follow score movement.

Directional events remain current for at most their original 30-second event lifetime and source expiry. Continuing current-row recommendations independently require the original quote/chart/closed-candle proof to remain within 45/75/120 seconds, with matching coin, source, candle and signal identity. Archived copies immediately carry a muted history label and neutral saved-observation proof; they do not assert that a still-current event ended. Expiry or an outage removes current confirmation while preserving the observation.

Chart refresh checks the catalog every five seconds and advances toward the next closed boundary with a two-second grace. During the bounded seconds 2–10 publication wait, a continuous series exactly one bar behind is checked at most once per second per source and described as updating the closed candle. The old bars remain historical for metrics. Actual failures retain explicit error wording and a five-second retry. A separate public stream can display the current forming candle and last price, with independent original timestamps and visible forming-state disclosure; it cannot renew closed proof.

## Verification record

Final synthetic preview captures: `artifacts/assistant-{market,alerts,positions,settings}-{1280,390,320}.png`. The documenter inspected the final market captures at 1280 and 390 and the pinned concept. Root inspected all four pages and three widths, fixed the desktop observation-feed gap and added the calculator-to-PAPER preparation action in one grouped batch, then completed one confirmation batch. Root reported no page overflow or browser errors. The handoff was also reconciled with the final source: preparation opens the Positions review, and virtual entry still requires the user's confirmation.

**Previous finish verdict: passed** for the bounded visual review of these desktop/mobile preview surfaces. The watch/table/events remain grouped at left, the selected detail remains at right on desktop, and the four-page mobile navigation remains visible. This verdict predates the chart-grid/densities extension and does not cover its new surfaces. Product and design documentation record the final implementation; the schemaVersion 2 sidecar contains its component snippets and metadata.

**Raster provenance:** every named capture is generated by the isolated synthetic preview. The approved reference is an AI-generated concept, retained outside shipping assets. No generated raster is shipped. These visuals do not prove live API availability or trading performance.

## Chart and density extension verification

Functional checks passed at 1280, 390 and 320px for the five-page navigation, existing manual PAPER flow, chart exchange isolation and explicit ordering, density filtering, sorting, persisted watch pairs, source-specific chart events, radar, retained outage/stale state and missing history. The browser never creates continuous age or execution commands. Invalid include scopes are bounded to 20 contracts and do not fall back to the entire market.

**Extension finish verdict: passed.** The bounded batch produced 18 synthetic captures for the chart grid, activity table, densities and the three retained pages at those widths. Root inspected the new surfaces at desktop/mobile widths and representative retained pages, completed one grouped fix batch and one confirmation batch, and found no page overflow or browser errors. A navigation color transition noticed in confirmation was corrected and verified with focused functional assertions. No further visual polish loop was run. All captures retain synthetic-demo provenance and do not establish live market availability.

## Native-chart verification

The new native renderer receives functional browser checks for source-bound historical OHLCV, local keyboard zoom/pan/reset, optional native volume pane, all six periods, bounded-window timestamp preservation and stale labels. Its bounded visual batch adds `artifacts/assistant-expanded-chart-{1280,390,320}.png` with volume and EMA/VWAP enabled, alongside default-grid captures taken before the table view. Root inspected the default grid and expanded charts at desktop/mobile widths, applied one grouped correction for the hidden-dialog initial width and period accessibility, then completed one confirmation batch. All 21 captures passed page/dialog overflow and browser-error checks. All listed functional checks passed at three widths. **Native-chart finish verdict: passed.** No further visual polish loop was run. All new captures use the same isolated synthetic preview provenance; no raster enters shipping assets.

## Freshness and chart-level verification

The expanded chart now includes selected-source density overlays and browser-local support/resistance annotations, entered by price or native plot click. Functional checks passed at 1280/390/320px for request deduplication, visible-chart priority, independent candle proof, annotation source isolation, storage/reload/deletion, native price lines and fit, expired-density labels, confirmed removal, and modal/table polling coordination. The same synthetic 1.2-second response delay produced six visible plots in 6,233ms before the scheduling change and 3,732ms after it. This is a local scheduling comparison, not a live upstream benchmark.

**Chart-level finish verdict: passed.** Root reviewed `artifacts/chart-levels-{1280,390,320}.png`, completed one grouped correction and one confirmation batch, and found no page/dialog overflow or browser errors. Gold resistance and violet support use the existing graphite control hierarchy; density freshness is written beside the color cue. No further visual polish loop was run. The captures are isolated synthetic evidence and no raster ships.

## Directional-alert and adaptive-refresh verification

The initial directional-alert functional batch passed at 1280/390/320px, including the new direction/evidence controls and the retained alerts workflow. The independent finish review requested one bounded correction: the immediate archive copy said that a recommendation had ended while its event could still be current. Its proof now says “история — сохранённое наблюдение”; the muted history badge and absent current recommendation remain. One confirmation batch completed at all three widths; it resumed at 320px after an intermittent navigation interruption using the unchanged locator and timeout. All functional checks passed, with no browser errors or POST commands.

**Directional-alert finish verdict: passed; disposition: ship for the scoped archive-copy fix.** The independent final review found neutral archived LONG/SHORT counterparts while the current event stayed active, no regression in current labels, reasons, invalidation or responsive layout, and no remaining issue. This verdict is scoped to the reviewed correction and is not inherited from earlier extension verdicts. No further visual polish loop was run.

Adaptive automatic boundary refresh, bounded publication retry and recovery passed browser checks at 1280/390/320px, as did the existing chart-level regression suite. The exchange-data backend suite passed 27 tests and the chart scheduler suite passed eight. These functional checks cover the refresh extension separately; they do not expand the independent visual verdict beyond its scored copy fix.

The current captures are `artifacts/recommendation-alerts-{1280,390,320}.png`, generated from isolated synthetic fixtures. They establish interface/state evidence only. No raster ships. The DESIGN.md frontmatter and incumbent identity are preserved; the schemaVersion 2 sidecar is retained unchanged. Its older four-page narrative and navigation sample are pre-existing documentation drift, outside this bounded extension.

## Live-chart performance and disclosure verification

The chart grid and dialog now show native public forming candles and a separate “Цена сейчас” readout/price line. A compact tile explicitly shows “формируется”, or “закрылась · проверяем” for a native closing sample awaiting REST. Historical cursor OHLC never receives that live caption. The dialog keeps its source/timeframe caption and wraps the quote, UTC timestamp and OHLCV on narrow widths. Connecting and unavailable streams have explicit text; closed history and alert/metric proof remain separate. Stale quotes disappear after ten seconds, candles require the current bucket and their own receipt/source age, and unknown Gate live base volume is a dash. Source switches, disconnects, hidden views and historical pan retain their tested isolation.

Measured native work with the shipped Lightweight Charts in Chromium: 100 unchanged packets previously invoked 100 resize and 400 full setData calls; the new path invokes none. Two forming ticks use two candle updates without auxiliary-series replacement. The deterministic transport model for eight HTTPS GETs fell from 1.28s to 0.44s by avoiding repeated 120ms handshakes, with 40ms responses; this is a synthetic comparison. A separate twenty-second read-only public probe received BTC 5m candles and quotes from all five venues, but neither measurement guarantees browser or VDS latency.

The bounded review inspected `artifacts/chart-live-{1280,390,320}.png` and `artifacts/chart-live-expanded-{1280,390,320}.png`. Root grouped the detail wrapping and stream-status corrections. The independent review then held the change for one truth issue: the tile's hidden source caption also hid its forming-state wording. A compact visible label and real visibility/clipping assertions corrected it. A focused confirmation updated only the three grid captures; the expanded captures were retained and their original visible caption was asserted again. The reviewer gave **pass; ship** for this scoped live-state disclosure correction, with no remaining blocker. No further polish or full-site review was run.

Functional checks passed at 1280/390/320px for live OHLC/current price, unchanged closed REST/NATR proof, historical viewport/cursor, modal period and venue isolation, quote expiry, disconnect, table and visibility lifecycle, manual chart levels and densities. The stream suite passed 40 cases, renderer eight, exchange backend 36 and public HTTP five; all 141 listed pure browser-JavaScript cases passed. The complete Linux and native-engine checks belong to exact-head CI, recorded in the PR after publication. No browser errors, external fixture HTTP requests or POST commands were observed. Captures use synthetic REST and fake WebSocket messages with a visible demo banner; no raster ships and no whole-site or trading-performance verdict is implied.

## Column filters, grid densities and cache latency

The latest scoped extension adds explicit header sorts and browser-persisted inclusive per-column ranges, with null-last sorting, invalid-range explanation and pinned live updates. Each native tile can enable densities for its own venue/pair; only enabled visible tiles share one bounded two-second scope, paused for dialog/table/hidden states. Grey stale lines retain written unconfirmed status.

Root inspected initial artifacts/screener-columns-{1280,390,320}.png, artifacts/grid-density-{1280,390,320}.png and representative speed-table/speed-densities captures. One grouped column evidence correction restored ordinary demo price and scroll origin; the confirmation was inspected at desktop/mobile sizes. No further visual polish loop was run. Scoped disposition: pass for the reviewed column/grid-density controls and speed display states, with synthetic evidence only. Functional browser checks cover three widths, native expiry/removal/reappearance, scope/source isolation, persistence and absence of commands. Backend scheduling/cache tests preserve source proof and bounds. Complete Linux/native-engine/exact-head CI is recorded in the PR after publication. No raster ships and no whole-site or exchange-latency guarantee is implied.

A final read-only contract review held one data issue: bounded backend pruning can omit a watched density without a missing tombstone. A shared grid/dialog merger now retains at most six previously displayed omitted levels in grey, preserving original source age and rejecting older source/tombstone replacements. Current fresh missing rows remove lines; history cannot erase reappearance. Three new pure checks passed; functional confirmation uses the existing native grid/dialog tests, without new captures or visual polish. Exact-head CI must be renewed for this correction; the preceding commit's green checks do not certify it.

## Significant liquidity and Kronos comparison (2026-10-13)

The user clarified that Kronos should assess and select several screener coins. The scoped extension adds a collapsed inline ≤8-candidate panel and hides ordinary book noise from the density table/radar/native overlays. Existing graphite tokens, five-page navigation, manual risk/PAPER boundary and closed-candle alerts remain. Pattern evidence is labelled observed repricing with unknown ownership; no calibrated probability, spoof/absorption or price-causality claim is made.

Root inspected the initial Kronos comparison captures at 1280/390/320. No visual correction was needed. Root then inspected the initial significant-density captures at the same widths and held the explanation column, which was clipped on desktop and initially outside the mobile table viewport. One grouped correction places the reason under the source name and narrows the desktop stable section. One confirmation batch was inspected at all three widths; the reason is readable without horizontal scrolling, while other numeric columns retain contained table scrolling. Scoped disposition: pass for these reviewed controls, explanation and source states; no further polish or whole-site verdict. Native density controls/history and Kronos batch/source/hash/boundary/cancellation/error/demo contracts passed browser checks at all three widths. Synthetic captures are marked demo; no raster ships.

Separate installed, pinned official CPU weights generated real BTC and ETH scenarios from fresh public Bybit candles (985/953 ms inference only). The opt-in live desktop UI check then completed BTC/ETH/SOL/NEAR with four explicit model commands, no order commands, no browser errors or page overflow. artifacts/kronos-live-1280.png is genuine point-in-time integration evidence, not a model-quality or VDS-speed result. Read-only finish review found false new-candle expiry wording and cold-chart refused admission; both were corrected, with 9 focused loopback HTTP contracts passed. Complete Linux/native/visual checks still require exact-head CI after publication. VDS installation was not performed.

## Kronos request errors (2026-10-14)

The scoped correction preserves HTTP codes and bounded JSON reasons when the HTTPS service rejects an assessment or status check. HTML responses are ignored; network errors and request timeout have distinct text. Existing graphite styling, progress wrapping, explicit batch admission and source proof remain. Pure parser checks and the functional browser pass at 1280/390/320px cover initial status JSON 401/HTML 502/invalid JSON, forecast JSON 403/HTML 405/502/invalid JSON, network failure, abort, rejected warmup continuation and typed stale/unavailable reasons. A fresh background status updates readiness without erasing a completed batch failure or retired-data reason; deterministic reopen checks preserve the text without new POST. No automatic retries, order commands, new raster, layout change or whole-site visual verdict is claimed. The user confirmed the VDS model now reports idle without error. Diagnosis identified the private HTTPS service's GET-only root location; application of the separate exact-route fix on VDS remained pending at this review.

## Table-source confirmation (2026-10-15)

The user applied the gateway fix with existing request/connection limits preserved; an unauthenticated POST now requests Basic Auth, and the user observed real completed forecasts. A separate source issue was reproduced: table-only coins never re-admitted candle refresh after publication delay or REST receipt expiry. The visible, explicitly started comparison now reads the existing bounded chart API sequentially before active/result forecast reads. The model GET remains read-only; no TTL, concurrency, batch size, source binding, model admission or layout was changed. Production/helper source errors retain their reason. Six actual production-handler/cache/client fixtures and the existing helper contracts passed. A focused 1280px browser check passed recovery, real chart-only proof renewal beyond 75s with original input receipt retained, hash/new-close rejection, HTTP error reasons and aborting held chart continuations. Required exact-head CI will exercise all three existing widths after publication; no redundant local three-width rerun, new raster, visual polish or whole-site verdict is claimed.

## Fifteen-coin groups (2026-10-15)

The user requested groups of 15 and explicit assessment of the next group. The existing inline panel now shows the current range, an explicit next-group assessment action and previous-group selection. Completion does not advance. Source/filter/list/order changes reset to the first group; ordinary quote updates preserve the group. The chart grid and network concurrency remain bounded as before. Existing graphite tokens and approved page concept are retained; no launcher rerun or unrelated design-sidecar repair was performed.

Root inspected one combined initial capture batch: group-15 results at 1280/390/320px, running controls at 320px and the last partial group at 390px (artifacts/kronos-groups-{15,running,partial}-{width}.png). Captures retain the synthetic-data banner. Ranges and action labels are readable, mobile pager targets are at least 44px and table overflow stays contained. Scoped visual disposition: pass, no grouped correction or further polish needed. No raster ships and no whole-site verdict is implied.

Panel retention is separately bounded to 16 previously validated completed responses, without input candles; the model worker remains at eight tasks and two queued. Twenty-three client/worker checks cover actual fake-engine worker eviction across 15 jobs, source/pins/hash/bar/expiry, isolation, failure rejection and parallel readers. Seven production HTTP/cache checks include a reproduced TTL30/async REST phase where a browser-held proof can expire before a 30-second row revisit despite a completed REST refresh. The retained-row cadence therefore reads at most two rows strictly sequentially per existing cycle, during both idle display and active inference, with unchanged chart TTL and 75-second proof requirement and no additional model admission. A deterministic browser-clock fixture passed 96 seconds within the same close with 15 frozen model results, chart TTL30 and REST completion delayed one second, retaining every row with original admission timestamps and exactly 15 explicit POSTs. Final focused functional confirmation and exact-head CI are recorded with the published change.
