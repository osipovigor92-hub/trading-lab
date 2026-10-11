# Public exchange data

`src/trading-panel/exchange_data.py` normalizes public USDT linear perpetual
market data for `binance`, `bybit`, `okx`, `gate`, and `bitget`. It uses fixed
HTTPS hosts and a fixed list of public GET paths. It reads no API keys and sends
no account, order, position or execution requests. HTTP redirects are refused.

## Integration

Use the shared `get_exchange_data()` instance. Its immediate, nonblocking methods
are `exchange_snapshot(exchange)`, `chart_snapshot(exchange, symbol, interval)`
and `book_snapshot(exchange, symbol)`. Symbols are canonical uppercase names such
as `BTCUSDT`; `1000` prefixes are retained as part of the exchange instrument
name. Only string intervals `1`, `5`, `15`, `60`, `240`, `1440` are accepted
(1 minute, 5 minutes, 15 minutes, 1 hour, 4 hours, 1 day). A syntactically
valid symbol must also occur in the verified active instrument metadata before
HTTP is sent to its chart or book endpoint.

The instance also exposes synchronous `fetch_catalog`, `fetch_chart` and
`fetch_book` with the same arguments. These perform HTTP, return verified `ok`
packets or raise. They are for workers, diagnostics and fixtures; request handlers
must use the snapshot methods. Direct fetches share the two-fetch semaphore.

The service has two worker threads, at most four outstanding jobs and 48 cache
entries per kind. Catalog TTL is 5 seconds, chart TTL 30 seconds and book TTL
5 seconds. At most two outstanding jobs may be catalogs/books, reserving two
admission slots for charts during a density scan. HTTP concurrency remains two.
Instrument metadata is cached for 300 seconds; Bybit pagination is
limited to four pages of 1,000 instruments. A chart job fetches only its requested
interval. Each HTTP request has a six-second timeout and a 4 MiB response limit.

## Packet contract

Every packet includes `exchange`, `status`, `updated`, `source_ts`, `error`,
`stale` and `refreshing`. All timestamps use Unix **seconds**. `updated` records
local fetch completion, while `source_ts` records exchange generation time when
available. Catalogs without such a timestamp use receipt time and explicitly
set `timestamp_origin: "receipt"`. There is no fabricated freshness timestamp
when retained data is returned during a refresh.

| Kind | Verified contents |
| --- | --- |
| Catalog | `rows`: symbol, price, change24 in percent, turnover24 in USDT, volume24 in base units, trades24; compatibility aliases turnover/change |
| Chart | symbol, native_symbol, interval, candle_end; candles with t/open/high/low/close/volume/turnover; metrics and metrics_interval; next_refresh_at |
| Book | symbol, native_symbol; bids descending and asks ascending, `[decimal price string, base quantity number]`; midpoint price; coverage.bid_min / coverage.ask_max as exact price strings |

Unprovided trade counts are `null`. A successful catalog is ordered by decreasing
24-hour turnover with a symbol tie-break. UI stability is handled by its consumer.
`rejected_rows` reports unusable ticker rows; an entirely invalid catalog fails.

`status: "pending"` initially contains empty data and null timestamps. TTL expiry
starts background revalidation. A chart keeps `status: "ok"`, `stale: false`
while its latest closed boundary is still the expected one and the original
HTTP receipt is at most 75 seconds old. A catalog does the same for at most
60 seconds of original receipt and source age. `refreshing: true` indicates an
outstanding refresh; returned timestamps are never replaced by polling time.
This avoids treating an unchanged closed series as unavailable every 30 seconds.
Crossing the next closed boundary immediately invalidates chart proof, including
when the receipt is recent. Failed revalidation also invalidates it immediately.

Outside these guards, a retained packet has `stale: true`; `refreshing: true`
identifies an ordinary refresh in progress with no prior error. A failed refresh returns
`status: "error"`, preserves the last verified packet and retries after five
seconds. Consumers can show that history, but must not treat it as new evidence.
The density observer may inspect retained data during an ordinary refresh only
within its own actual-source-age guard; repeated source timestamps never provide
a second observation. Closing the service stops new work.

Chart `next_refresh_at` is the earlier of receipt + 30 seconds and the next
closed boundary + the two-second grace. It is a suggested verification time,
not an exchange timestamp or proof of a new candle. On every snapshot a new
expected boundary immediately triggers revalidation even before the TTL.

A continuous response exactly one closed bar behind during seconds 2–10 of a
new boundary is a bounded publication wait. For OKX, only the expected newest
close may still have `confirm=0` in that window; it is excluded, never promoted
to a completed candle. The snapshot stays `pending`, `stale: true`, and reports
`refresh_reason: "awaiting_close"` and `retry_after_seconds`. Retry admission is
at most once per second per key, only when a consumer requests a snapshot;
workers do not loop or sleep. Existing timestamps and candles remain unchanged.
After the ten-second window the absent close is an error; an already-due
request may verify recovery immediately. A continued absence applies the usual
five-second retry. Missing older bars, invalid values, source rollback and HTTP
failures never receive this publication-wait exemption.

## Units and upstream endpoints

- **Binance:** `/fapi/v1/exchangeInfo`, `/ticker/24hr`, `/klines`, `/depth`
  under the `/fapi/v1` prefix. Metadata must identify a trading USDT perpetual.
  Native volume and quantity are base units; quoteVolume and kline quote asset
  volume are USDT. `count` supplies the available trade count.
  [Official USD-M market API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
- **Bybit:** `/v5/market/instruments-info`, `/tickers`, `/kline`, `/orderbook`
  with `category=linear`. Only Trading / LinearPerpetual instruments quoted and
  settled in USDT are admitted. Volume and book quantity are base units and
  turnover is USDT; price24hPcnt is converted from a ratio to percent.
  [Instruments](https://bybit-exchange.github.io/docs/v5/market/instrument),
  [tickers](https://bybit-exchange.github.io/docs/v5/market/tickers),
  [candles](https://bybit-exchange.github.io/docs/v5/market/kline),
  [books](https://bybit-exchange.github.io/docs/v5/market/orderbook).
- **OKX:** `/api/v5/public/instruments`, `/api/v5/market/tickers`, `/candles`,
  `/books`; only live linear USDT-settled SWAP instruments. Book counts are
  converted with `ctVal × ctMult`, and `ctValCcy` must equal the base currency.
  Explicit base candle/ticker volume fields are already converted. Candle quote
  volume is exact USDT. Tickers lack exact USDT turnover: `turnover24` is base
  volume × latest price, marked `turnover_estimated: true`. It is a liquidity
  proxy, not a reconstructed trading total.
  [Official API](https://app.okx.com/docs-v5/en/),
  [contract face-value guide](https://www.okx.com/en-ar/help/how-can-i-do-derivatives-trading-with-the-jupyter-notebook).
- **Gate:** `/api/v4/futures/usdt/contracts`, `/tickers`, `/candlesticks`,
  `/order_book`; only trading direct contracts outside delisting and premarket.
  Contract quantities and candle `v` are multiplied by `quanto_multiplier`.
  The explicit base/quote ticker volumes and candle `sum` are not multiplied
  again. Book `current` supplies generation time in seconds.
  [Official futures API](https://www.gate.com/docs/developers/apiv4/en/futures/).
- **Bitget:** `/api/v2/mix/market/contracts`, `/tickers`, `/candles`,
  `/merge-depth` with `productType=USDT-FUTURES`. Only normal perpetual symbols
  supporting USDT margin are admitted. Volume and quantities are base units;
  `sizeMultiplier` is an order-quantity step, not a contract conversion factor.
  Unmerged `precision=scale0` is required. Numeric depth prices are formatted as
  decimal strings, including very small prices.
  [Official classic contract market API](https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market).

## Validation and indicators

Charts contain 60–180 continuous closed candles, ordered by opening time. The
current candle is excluded with a two-second close grace; OKX additionally
requires confirm=1. Missing, duplicate or unaligned bars, invalid OHLC, negative
volumes and non-finite numbers fail the packet. The latest candle must end at
the most recent interval boundary outside the grace window; crossing a new
boundary invalidates the cache even before its TTL. Charts are trade-price
candles rather than mark/index candles.

Daily candles use UTC boundaries on every venue. Binance/Gate receive `1d`,
Bybit receives `D`, and OKX/Bitget receive `1Dutc` (rather than their local-day
variant). Four-hour requests use `4h`, `240`, or `4H` according to the venue.
The two-second grace and expected-boundary check apply to every period; a
current daily series may have a last closed candle nearly one day old, while
its HTTP completion is recent. This is different from quote/book freshness.
See the official [Bybit intervals](https://bybit-exchange.github.io/docs/v5/market/kline),
[OKX candle periods](https://app.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks),
and [Bitget contract candles](https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market).

Book source time must be no more than 15 seconds old; timestamped catalogs have
a 90-second source guard. Future timestamps beyond three seconds are rejected.
Older source timestamps cannot replace a previously verified packet. Equal
timestamps are allowed for unchanged snapshots, without being new observations.
Empty, crossed, locked, duplicate-price or nonpositive-quantity books fail. Book
coverage describes only the returned depth; absence beyond that boundary is not
proof that an order disappeared. REST snapshots cannot establish ownership or
prove continuous presence between observations, and can omit special liquidity
such as RPI orders.

Metrics never fetch another timeframe implicitly. `natr1_30` is available only
on 1-minute packets; `natr5_14` only on 5-minute packets. NATR is Wilder ATR
divided by the final close, times 100, seeded from the first period of true
ranges in the returned window. `change5` uses five 1-minute close intervals or
one 5-minute close interval. Metrics for an unavailable timeframe are null; the
consumer explicitly requests the required timeframe. These are descriptive
measurements, not entry recommendations or return predictions.

## Checks

Run `python tools/test_exchange_data.py` with Python 3. The 27 offline tests
cover all five venues, six intervals, UTC daily alignment and long-period close
grace, quantity conversions, unavailable counts,
estimated turnover, malformed/stale data, rollback protection, tiny numeric
prices, bounded proof during revalidation, immediate boundary/error invalidation,
cache refresh/failure/recovery, new-boundary scheduling, bounded publication
retry/recovery on all five venues, strict validation during that window, and
chart admission during busy density scans. No test
contacts the internet.

A separate read-only live public probe on 2026-10-11 returned eligible catalogs
for all five venues (520 Binance, 790 Bybit, 485 OKX, 1,010 Gate, 817 Bitget),
valid BTC order books and 180 closed five-minute candles from each. Counts are
a point-in-time check, not a fixed expected universe. Credentials and full
upstream response bodies were not logged.
