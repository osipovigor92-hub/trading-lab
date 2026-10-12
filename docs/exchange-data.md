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

Direct HTTPS GETs reuse at most two idle connections per fixed exchange host,
discarding them after 30 idle seconds or when the socket has closed/unexpected
readable data. The global active-HTTP bound remains two. `HTTPSConnection` keeps
normal certificate verification; redirects, non-success responses and oversized
bodies fail the read. The transport does not retry a failed GET internally: the
existing snapshot scheduler owns retry timing and proof invalidation. Configured
HTTPS/all proxies continue through the existing urllib proxy-aware opener rather
than being bypassed. Closing the service closes idle and active connections.

## Packet contract

Every packet includes `exchange`, `status`, `updated`, `source_ts`, `error`,
`stale` and `refreshing`. All timestamps use Unix **seconds**. `updated` records
local fetch completion, while `source_ts` records the upstream timestamp when
available; for chart packets it is the verified closed-candle boundary, not a
live quote timestamp. Catalogs without such a timestamp use receipt time and explicitly
set `timestamp_origin: "receipt"`. There is no fabricated freshness timestamp
when retained data is returned during a refresh.

| Kind | Verified contents |
| --- | --- |
| Catalog | `rows`: symbol, verified native_symbol, price, change24 in percent, turnover24 in USDT, volume24 in base units, trades24; compatibility aliases turnover/change |
| Chart | symbol, native_symbol, interval, candle_end; candles with t/open/high/low/close/volume/turnover; metrics and metrics_interval; next_refresh_at |
| Book | symbol, native_symbol; bids descending and asks ascending, `[decimal price string, base quantity number]`; midpoint price; coverage.bid_min / coverage.ask_max as exact price strings |

Unprovided trade counts are `null`. A successful catalog is ordered by decreasing
24-hour turnover with a symbol tie-break. UI stability is handled by its consumer.
`rejected_rows` reports unusable ticker rows; an entirely invalid catalog fails.
Each row's `native_symbol` comes from the already verified active instrument
mapping, preserving prefixes and the venue's contract spelling. The browser can
use that identity to subscribe before its closed chart history has loaded.

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

## Public browser chart streams

`src/trading-panel/chart-stream.js` supplies display-only native candles and
last-traded quotes. It opens public sockets directly from the browser, with no
API key or login. REST packets remain authoritative for closed history,
EMA20/50, VWAP60, NATR, assistant signals and alerts. A stream never rewrites a
REST timestamp, extends a closed packet's validity, or sends a trading command.

The provider accepts at most 13 validated source keys
`exchange:symbol:interval` (12 grid charts and one expanded chart). Only needed
venue groups connect; the provider's ceiling is six sockets, with separate OKX
candle and ticker sockets. Ticker subscriptions deduplicate across periods of
the same contract. Subscription diffs retain connections, are paced, and obey
the OKX 480/hour and Bitget 240/hour request budgets. `connect-src` allows only
same-origin reads and the five exact public WSS hosts below, without external
scripts or a wildcard WSS permission.

| Venue | Public stream and native channels |
| --- | --- |
| Bybit | `wss://stream.bybit.com/v5/public/linear`; `kline.{interval}.{native_symbol}` and `tickers.{native_symbol}`. Day interval is `D`. Native candle `confirm` identifies closure; ticker snapshot/delta values use `lastPrice`. Missing delta price fields are unchanged, not a new quote. |
| Binance | `wss://fstream.binance.com/market/stream`; `{symbol lowercase}@kline_{interval}` and `@miniTicker`. Combined frames use `{stream,data}`; candle `k.x` identifies closure. The routed `/market` path is required under the current URL split. |
| OKX | `wss://ws.okx.com/ws/v5/business` for `candle{interval}` and `/ws/v5/public` for `tickers`, with the verified `BTC-USDT-SWAP` style instrument ID. Hours use `1H`/`4H`, days `1Dutc`. Candle arrays use base volume at index 6, quote turnover at index 7, and string confirmation at index 8. |
| Gate | `wss://fx-ws.gateio.ws/v4/ws/usdt`; `futures.candlesticks` with `[interval,native_symbol]`, and `futures.tickers`. Periods use `1h`, `4h`, `1d`, not uppercase H or `1Dutc`. Candle `w === true` identifies closure; absence is not closure evidence. Live `v` counts contracts and is deliberately exposed as unknown base volume. |
| Bitget | `wss://ws.bitget.com/v2/ws/public`; `USDT-FUTURES` subscriptions for `candle{interval}` and `ticker`. Hours/days use `1H`, `4H`, `1Dutc`; ticker price is `lastPr`. Candle arrays supply base and quote volume without a closing flag. |

Frames validate the selected native identity, period, aligned opening time,
finite OHLC, positive prices and valid supplied volumes. Non-text or oversized
frames above 262,144 characters are ignored. Older source timestamps cannot
roll a sample back. Application heartbeats follow each provider's protocol;
protocol pong frames on Binance are handled by the browser. Hidden pages close
all streams and restart only needed subscriptions when visible again. A broken
socket immediately drops its samples and reconnects with exponential backoff
from 2 to 30 seconds plus jitter. A stalled handshake or protocol rejection
also retries; repeated failures do not spin a tight connection loop.

Market samples retain `received_at`, `source_ts` and `timestamp_origin` in Unix
seconds. Quotes require both receipt/source age at most 10 seconds. Candles
require receipt/source age at most 75 seconds and either the current open
period or an explicitly closed prior period within its ten-second publication
window, with a two-second future-clock tolerance. OKX candle frames contain
opening time but no generation time: `source_ts` stays null and origin is
`receipt`. Pongs and ordinary renders never refresh market timestamps.

The renderer adds a native current candle only immediately after the matching
last closed history bar. A missing history window cannot be filled by invented
bars. A separate fresh quote line is labelled "Цена сейчас". Native forming or
recently closing candles have explicit display labels and do not enter the
closed volume/indicator series. Historic OHLCV selection, manual annotations,
density source isolation and viewport anchors remain tied to their own data.
Updates are coalesced over 250ms; changed latest candles use `series.update`,
while unchanged snapshots skip native data and resize calls. The local bundled
renderer remains TradingView Lightweight Charts 5.2.1.

Official protocol references:
[Bybit candles](https://bybit-exchange.github.io/docs/v5/websocket/public/kline),
[Bybit tickers](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker),
[Bybit connection](https://bybit-exchange.github.io/docs/v5/ws/connect),
[Binance URL migration](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice),
[Binance stream connection](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect),
[OKX candles](https://app.okx.com/docs-v5/en/#order-book-trading-market-data-ws-candlesticks-channel),
[OKX global services](https://www.okx.com/docs-v5/),
[Gate Futures WebSocket](https://www.gate.com/docs/developers/futures/ws/en/),
[Bitget candles](https://www.bitget.com/docs/classic/websocket/contract/public/Candlesticks-Channel),
[Bitget tickers](https://www.bitget.com/docs/classic/websocket/contract/public/Tickers-Channel),
[Bitget connection](https://www.bitget.com/docs/classic/websocket/intro), and
[Lightweight Charts incremental updates](https://tradingview.github.io/lightweight-charts/tutorials/demos/realtime-updates).

## Checks

Run `python tools/test_exchange_data.py` with Python 3. The 36 offline tests
cover all five venues, six intervals, UTC daily alignment and long-period close
grace, quantity conversions, unavailable counts,
estimated turnover, malformed/stale data, rollback protection, tiny numeric
prices, bounded proof during revalidation, immediate boundary/error invalidation,
cache refresh/failure/recovery, new-boundary scheduling, bounded publication
retry/recovery on all five venues, strict validation during that window, and
chart admission during busy density scans. No test
contacts the internet. Added transport coverage exercises TLS reuse and idle
expiry, global concurrency and pool bounds, closure, response/redirect failures,
no hidden retry, proxy preservation and verified native catalog identities.

Run `node --test tools/test_chart_stream.cjs tools/test_exchange_chart.cjs` for
the 40 protocol/lifecycle and eight renderer regression cases. They use native
exchange fixtures and deterministic fake sockets/timers or chart APIs; they do
not contact exchanges. Coverage includes venue/period isolation, UTC day
mapping, finite data, source/receipt expiry, time-bucket rollover, hourly request
budgets, reconnects, hidden-page shutdown, batching, no-op snapshots and separate
live/closed series. Synthetic preview sets its demo flag and disables external
streams. These suites do not establish current browser finish review or
exact-head CI status.

Focused measurements on 2026-10-11:

- With real Chromium and the shipped Lightweight Charts 5.2.1 bundle, 100
  unchanged snapshots previously caused 100 native resize calls and 400
  `setData` calls. The updated path caused zero of either; two native forming
  ticks caused two candlestick `update` calls. The local loop elapsed time was
  69.7ms before and 56.8ms after. Native call counts explain reduced renderer
  work; elapsed time is a local sample, not exchange latency or a universal FPS
  claim.
- Eight synthetic HTTPS GETs with a 120ms connection/TLS cost and 40ms response
  cost used one reused connection: the deterministic model fell from 1.28s to
  0.44s. It still performed eight validated reads. This model isolates avoided
  handshakes and does not predict production network timing.
- A 20-second read-only public WebSocket probe received BTC five-minute candles
  and quotes from all five venues over all six sockets. Observed source-to-
  receipt delays for timestamped frames were 0.04–0.56s. OKX candle frames
  supplied no generation timestamp and were measured only at receipt. This is
  point-in-time availability from the probe environment, not a guarantee for
  every browser, region, connection or VDS.

A separate read-only live public probe on 2026-10-11 returned eligible catalogs
for all five venues (520 Binance, 790 Bybit, 485 OKX, 1,010 Gate, 817 Bitget),
valid BTC order books and 180 closed five-minute candles from each. Counts are
a point-in-time check, not a fixed expected universe. Credentials and full
upstream response bodies were not logged.


## Резервное обновление текущей свечи

Если публичный WebSocket недоступен в браузере или не присылает текущую свечу, видимые графики запрашивают свой источник через `/api/exchange-chart?live=1` примерно каждые две секунды. Общий серверный кэш повторно проверяет такой источник после трёх секунд; каждый источник имеет только одну незавершённую загрузку. Скорость зависит от ответа биржи и числа видимых графиков. Данные отображаются с подписью «API» и исходным временем получения, без обещания непрерывного тикового потока.

Поле `current_candle` содержит только текущую незакрытую свечу своей биржи, монеты и периода. Оно не входит в закрытую историю, NATR, EMA, VWAP или сигналы. Резервное наблюдение истекает через десять секунд или при смене периода; ошибка источника снимает его подтверждение. При восстановлении WebSocket его свеча и цена имеют приоритет.

Запросы каталога и плотностей занимают не более одного рабочего места; второй из двух рабочих потоков остаётся доступен графикам. Общая очередь по-прежнему ограничена четырьмя заданиями, а внешние HTTP-запросы — двумя.

Эта версия продолжает `24a5a04`, сохраняя новую панель. Обновление также допускает восстановление кода прежнего фонового наблюдателя `trading-live` после ошибочной версии `878f057`: перезапускается только уже активный наблюдатель; остановленный не включается. Торговые модели и их данные не изменяются.
