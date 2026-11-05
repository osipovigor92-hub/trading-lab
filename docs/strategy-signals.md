# Strategy signals — revised user scope, 2026-11-05

The user has replaced the bot execution objective with a manual signal assistant.
No automated orders or strategy executor should be enabled as part of this work.
The Bots navigation slot is now labelled Strategies to preserve saved navigation keys.

Target delivery:
- Nine entry-signal families: density bounce/break, horizontal level bounce/break,
  structure break, trendline bounce/break, impulse fade/follow.
- DCA is a bounded position-building plan after an entry signal, not a standalone
  market-entry recommendation.
- Server evaluation independent of selected browser tab; shared subscriptions and
  bounded cache; source timestamps preserved.
- Signal record: source exchange/symbol/timeframe, strategy, direction, closed-bar
  time, reason, confirmation evidence, expiry, invalidation, entry reference,
  stop, targets, and stable event key.
- Persist event deduplication across restarts. Distinguish waiting, confirmed,
  expired and invalidated; don't repeat a sound on each poll or initial load.
- Chart: time-anchored LONG/SHORT marker plus level/entry/stop/targets, bound to the
  selected source. Expired events remain historical, never presented as fresh.
- Integrate into existing Alerts and chart APIs rather than create duplicate feeds.
- Density threshold >=10 times baseline; cancellation alone is not evidence of
  executed volume or a density breakout.

Current status: configuration UI and storage exist, plus isolated level-break
validator. The new strategy rules are NOT connected to alerts or chart markers.
Existing scanner alerts and manual/automatic chart levels remain independent.
The published bf370461 release predates this scope change.

## Increment: chart overlays
The server monitor and read-only strategy feed are now implemented locally for the
preceding 20-minute range breakout with 1.5x prior-bar mean volume. Source is Bybit
1-minute closed candles. Saved pair/favorites scope is supported; market-wide is
explicitly unavailable. Signals and dedup keys persist before publication.

Expanded charts have an opt-in Signals control. It draws three price lines for the
latest matching source event: signal reference, stop and target. Expired events up
to 24 hours old are grey and labelled History. Stale/unavailable packets remove
all overlays. These are horizontal reference lines, not time-anchored arrow markers.
Fifteen level/renderer unit tests pass. Browser visual QA, sound alerts, chart arrow
markers and remaining strategy evaluators are outstanding. No new remote release
has been published for this signal integration yet.

## Increment: candle arrows and optional sound
The expanded 1-minute chart now renders one LONG/SHORT arrow on the confirming
closed candle, when that candle exists in the loaded series. Other timeframes
keep price references only. Marker updates are deduplicated and detached with
the chart. Sixteen level/renderer tests pass, including candle-time calculation.
Strategy alerts now offer an explicit sound toggle. Initial history is silent;
only newly observed, unexpired events created within 30 seconds can sound. The
browser must allow/resume Web Audio from the user's click. Sound is not a server
push service and is not guaranteed when the browser sleeps or closes. Browser
visual/audio verification remains outstanding.

## Monitor status corrections
Coverage now reports the winning LONG/SHORT evaluation, distinguishes no configured
rule, empty scope, stale-data waiting and active monitoring, and includes source
and candle timestamps. Bybit favorites from both screener lists are combined and
bounded to eight. Stale per-symbol coverage no longer marks its alert as current.
The UI disables market-wide selection and saving unsupported strategies. Preview
serves an explicit empty strategy-feed response. Five monitor tests, eight signal
tests and sixteen chart tests passed. Browser validation remains outstanding.

## Signal validity-window outcomes
Signals now record stop/target touches, ambiguous both-touched candles, or expiry
without a touch. The observation window is the existing 60-second signal validity,
not an assumed holding period. Only contiguous closed candles after the signal
candle count. Missing data leaves the outcome unknown. Persist before publication;
terminal outcomes never change on a later poll. Results are observations, not fills,
returns or a strategy win rate. Evaluation currently follows configured symbols;
removing a symbol can leave its historical result unknown. A separate bounded
historical evaluation queue remains future work. Seven new outcome tests pass,
alongside five monitor, eight signal and sixteen chart tests (36 total).
