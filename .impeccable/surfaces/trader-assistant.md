# Surface brief: Trader assistant

## Scope

Primary target: `src/trading-panel/index.html`.

Related targets: `src/trading-panel/screener.js`, `src/trading-panel/screener.css`, `src/trading-panel/fresh-alerts.js`, `src/trading-panel/positions.js`, `src/trading-panel/layout.js`, `src/trading-panel/layout.css`, `src/trading-panel/chart-grid.js`, `src/trading-panel/chart-grid.css`, `src/trading-panel/densities.js`, `src/trading-panel/densities.css`.

Visitor mode: **Operate**. This brief is development documentation and is not served by the panel. The runtime context launcher was unavailable; the brief is authored directly rather than claimed to be registered by its helper.

## Task and evidence

The user finds activity, pins coins, examines a selected coin and checks a manual decision. Their explicit continuity requirements are stable row order and alerts that remain trackable after freshness expires. PRODUCT.md owns source, formula and operating constraints; DESIGN.md owns the shared visual tokens.

Five pages now remain: Скринер, Плотности, Алерты, Позиции, Настройки. The later screenercrypto.ru reference authorizes a chart grid within the screener and public density observations. Tests, models, journals, an independent orderbook page and Live remain absent. The compact observation feed is retained as part of following signals.

## Direction contract

**THESIS:** Follow a coin through changing measurements and retained observations. The user-pinned graphite identity remains binding. The later screenercrypto.ru request adds a chart-first screener and a density workspace without changing the manual decision boundary.

**OWN-WORLD:** Graphite fields, flat bordered panels, compact sans typography, cyan actions and explicit green/rose direction labels. Identity follows the approved concept and the extracted DESIGN.md cascade.

**STORY:** Scan activity, select or watch a symbol, inspect closed-candle evidence and reasons, then enter manual risk assumptions. History shows what happened; current labels show what remains verified.

**FIRST VIEWPORT:** Header and exchange/search/metric controls precede the default chart grid. The Table view retains the watch/table/detail arrangement and compact observations. The density page places persisted filters above confirmed hour-old levels at left and newer/unconfirmed levels or a distance radar at right. Search, watch and refresh actions remain visible; risk is a deliberate disclosure within the activity table.

**FORM:** User-pinned generated concept, implemented directly in the existing panel. No random direction selection was used; no seed key exists. The concept's illustrative Models tab and example rating claims yield to the user's explainable-activity and later chart-screener/density instructions.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Approved visual reference

AI-generated concept: `C:/Users/ПК/.codex/generated_images/01a10d8f-9ffe-7c92-9701-5bce7646e9dd/exec-6c97f90a-3b31-4e0d-b319-f1b29e6018c2.png`.

Its visual composition is binding; prices, example scores and status wording are illustrative. It is not copied into shipped site assets. The current chart is drawn from candle data, and interface icons are code assets; no generated raster ships with this change.

## Responsive and state contract

The activity table preserves the three reading columns. The chart view uses a responsive multi-chart grid; the density view separates confirmed long observations from newer and unconfirmed levels. Intermediate widths move the detail below the left workspace. Mobile uses stacked panels, a locally scrollable table and five fixed bottom navigation items. Selected/watch states remain explicit.

Pending, stale, source-error, empty-watch and absent-PAPER states explain the next available action. Missing score and indicator values remain dashes. Historical events keep their coin action and time. The user decides when to re-sort; watch order does not follow score movement.

## Verification record

Final synthetic preview captures: `artifacts/assistant-{market,alerts,positions,settings}-{1280,390,320}.png`. The documenter inspected the final market captures at 1280 and 390 and the pinned concept. Root inspected all four pages and three widths, fixed the desktop observation-feed gap and added the calculator-to-PAPER preparation action in one grouped batch, then completed one confirmation batch. Root reported no page overflow or browser errors. The handoff was also reconciled with the final source: preparation opens the Positions review, and virtual entry still requires the user's confirmation.

**Previous finish verdict: passed** for the bounded visual review of these desktop/mobile preview surfaces. The watch/table/events remain grouped at left, the selected detail remains at right on desktop, and the four-page mobile navigation remains visible. This verdict predates the chart-grid/densities extension and does not cover its new surfaces. Product and design documentation record the final implementation; the schemaVersion 2 sidecar contains its component snippets and metadata.

**Raster provenance:** every named capture is generated by the isolated synthetic preview. The approved reference is an AI-generated concept, retained outside shipping assets. No generated raster is shipped. These visuals do not prove live API availability or trading performance.

## Chart and density extension verification

Functional checks passed at 1280, 390 and 320px for the five-page navigation, existing manual PAPER flow, chart exchange isolation and explicit ordering, density filtering, sorting, persisted watch pairs, source-specific chart events, radar, retained outage/stale state and missing history. The browser never creates continuous age or execution commands. Invalid include scopes are bounded to 20 contracts and do not fall back to the entire market.

**Extension finish verdict: passed.** The bounded batch produced 18 synthetic captures for the chart grid, activity table, densities and the three retained pages at those widths. Root inspected the new surfaces at desktop/mobile widths and representative retained pages, completed one grouped fix batch and one confirmation batch, and found no page overflow or browser errors. A navigation color transition noticed in confirmation was corrected and verified with focused functional assertions. No further visual polish loop was run. All captures retain synthetic-demo provenance and do not establish live market availability.
