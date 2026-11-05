import copy
from concurrent.futures import Future
import importlib.util
import math
import json
from pathlib import Path
import threading
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))

spec = importlib.util.spec_from_file_location('market_data', Path(__file__).resolve().parents[1]/'src/trading-panel/market_data.py')
market = importlib.util.module_from_spec(spec)
spec.loader.exec_module(market)


def kline_fixture():
    stamp = 300000 + 40
    rows = []
    for i in range(181):
        start = 300000 - (180-i)*300
        price = 100 + math.sin(i*.7)
        rows.append([str(start*1000),str(price),str(price+.2),str(price-.2),str(price),"10",str(price*10)])
    return dict(list=rows[::-1]), stamp


def ticker(symbol='BTCUSDT', turnover='123000000'):
    return dict(symbol=symbol,lastPrice='100',highPrice24h='110',lowPrice24h='90',
                bid1Price='99.99',ask1Price='100.01',turnover24h=turnover,
                price24hPcnt='.05',openInterestValue='50000000',fundingRate='.0001',deliveryTime='0')


class MarketTests(unittest.TestCase):
    def test_owned_public_transport_reuses_tls_and_retains_source_and_body_bounds(self):
        connections = []
        class Response:
            status = 200
            will_close = False
            def read(self, limit):
                self.limit = limit
                return json.dumps(dict(retCode=0, time=1_000_000,
                                       result=dict(list=[ticker()]))).encode()
        class Connection:
            def __init__(self, host, timeout):
                self.host, self.timeout, self.sock = host, timeout, object()
                self.requests, self.responses, self.closed = [], [], False
                connections.append(self)
            def request(self, method, target, headers):
                self.requests.append((method, target, headers))
            def getresponse(self):
                response = Response(); self.responses.append(response); return response
            def close(self):
                self.closed = True; self.sock = None
        with patch('exchange_data.getproxies', return_value={}), \
                patch('exchange_data.HTTPSConnection', Connection), \
                patch('exchange_data.select', return_value=([], [], [])), \
                patch.object(market.time, 'time', return_value=1000):
            cache = market.MarketData()
            try:
                for endpoint in ('tickers', 'kline', 'orderbook'):
                    _, stamp = cache.api(endpoint, symbol='BTCUSDT')
                    self.assertEqual(stamp, 1000, 'source time is never replaced by receipt time')
                self.assertEqual(len(connections), 1, 'three reads reuse one verified TLS connection')
                self.assertEqual(len(connections[0].requests), 3)
                self.assertEqual((connections[0].host, connections[0].timeout), ('api.bybit.com', 6))
                self.assertTrue(all(response.limit == 2_000_001 for response in connections[0].responses))
                self.assertTrue(all(method == 'GET' and target.startswith('/v5/market/')
                                    for method, target, _ in connections[0].requests))
                for bad in ('../private', 'https://example.org', 'order/create'):
                    with self.assertRaises(ValueError): cache.api(bad)
                self.assertEqual(len(connections[0].requests), 3)
            finally:
                cache.close()
            self.assertTrue(connections[0].closed)
            with self.assertRaises(ValueError): cache.api('tickers')

    def test_publication_retry_only_single_newest_missing_bar_never_malformed_or_long_stale(self):
        result, _ = kline_fixture()
        # Retain 180 old closed 5m bars; the new 300300 close has not published yet.
        result['list'] = result['list'][1:]
        for delay in (0, 1, 2, 10):
            with self.assertRaises(market._CandlePublicationPending) as pending:
                market.closed_candles(result, 300300 + delay, '5')
            self.assertEqual(pending.exception.candle_end, 300300)
        for mutation in ('gap', 'duplicate', 'invalid', 'older', 'late'):
            bad = copy.deepcopy(result); stamp = 300302
            if mutation == 'gap': bad['list'].pop(10)
            if mutation == 'duplicate': bad['list'][10] = bad['list'][11]
            if mutation == 'invalid': bad['list'][10][2] = '-1'
            if mutation == 'older': bad['list'].pop(0)
            if mutation == 'late': stamp = 300311
            with self.assertRaises(ValueError) as error:
                market.closed_candles(bad, stamp, '5')
            self.assertNotIsInstance(error.exception, market._CandlePublicationPending, mutation)

    def test_chart_revalidates_at_next_close_then_one_second_publication_retry(self):
        clock, wall = [0], [300298]
        release = threading.Event(); calls = []
        result, _ = kline_fixture()
        def api(endpoint, **params):
            calls.append((endpoint, params)); release.wait(2)
            packet = copy.deepcopy(result)
            # The new closed candle is absent only on the second request.
            if len(calls) == 2: packet['list'] = packet['list'][1:]
            return packet, wall[0]
        cache = market.MarketData(api=api, clock=lambda:clock[0], wall_clock=lambda:wall[0])
        try:
            release.set(); cache.get('chart', 'BTCUSDT', '5')
            cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
            first = cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(cache.entries[('chart', 'BTCUSDT', '5')]['until'], 4,
                             '25s TTL clips to the boundary + 2s, four seconds away')
            release.clear(); clock[0] = 4; wall[0] = 300302
            waiting = cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(waiting['updated'], first['updated'])
            self.assertEqual(waiting['candles'], first['candles'])
            self.assertIn('refresh_error', waiting, 'prior close cannot issue a new directional alert')
            self.assertIn('refresh_error', cache._alert_cache()[('chart', 'BTCUSDT', '5')])
            release.set()
            with self.assertRaises(market._CandlePublicationPending):
                cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
            waiting = cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(waiting['refresh_reason'], 'awaiting_close')
            self.assertEqual(cache.entries[('chart', 'BTCUSDT', '5')]['until'], 5)
            for _ in range(10): cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(len(calls), 2, 'polls coalesce and never retry sooner than one second')
            clock[0] = 5; wall[0] = 300303
            cache.get('chart', 'BTCUSDT', '5')
            cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
            fresh = cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(fresh['candle_end'], 300300)
            self.assertEqual(fresh['updated'], 300303)
            self.assertNotIn('refresh_error', fresh)
        finally:
            release.set(); cache.close()

    def test_chart_boundary_admission_does_not_bypass_an_error_backoff_or_close(self):
        clock, wall = [0], [300040]
        result, _ = kline_fixture(); calls = []
        def api(*args, **kwargs):
            calls.append(args)
            if len(calls) > 1: raise ValueError('outage')
            return result, wall[0]
        cache = market.MarketData(api=api, clock=lambda:clock[0], wall_clock=lambda:wall[0])
        cache.get('chart', 'BTCUSDT', '5')
        cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
        cache.get('chart', 'BTCUSDT', '5')
        clock[0] = 25; cache.get('chart', 'BTCUSDT', '5')
        with self.assertRaises(ValueError): cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
        cache.get('chart', 'BTCUSDT', '5')
        wall[0] = 300302
        for _ in range(5): cache.get('chart', 'BTCUSDT', '5')
        self.assertEqual(len(calls), 2, 'new boundary cannot bypass genuine outage backoff')
        cache.close()
        self.assertEqual(cache.get('chart', 'BTCUSDT', '5')['status'], 'error')
        self.assertEqual(len(calls), 2, 'closed service cannot submit work')

    def test_publication_retry_stops_by_local_window_when_exchange_clock_lags(self):
        result, _ = kline_fixture(); result['list'] = result['list'][1:]
        cache = market.MarketData(api=lambda *args, **kwargs:(result, 300309),
                                  clock=lambda:0, wall_clock=lambda:300320)
        try:
            cache.get('chart', 'BTCUSDT', '5')
            with self.assertRaises(market._CandlePublicationPending):
                cache.entries[('chart', 'BTCUSDT', '5')]['future'].result(timeout=2)
            packet = cache.get('chart', 'BTCUSDT', '5')
            self.assertEqual(packet['status'], 'error')
            self.assertNotIn('refresh_reason', packet)
            self.assertEqual(cache.entries[('chart', 'BTCUSDT', '5')]['until'], 20)
            self.assertIsNone(cache.entries[('chart', 'BTCUSDT', '5')]['publication_end'])
        finally:
            cache.close()

    def test_shortlist_warms_two_charts_per_round_before_books_with_same_job_bound(self):
        release = threading.Event(); calls = []; clock = [0]; wall = [300040]
        symbols = ['COIN' + str(index) + 'USDT' for index in range(8)]
        def api(endpoint, **params):
            calls.append((endpoint, params.get('symbol'))); release.wait(2)
            # Chart fixture is unnecessary here; this isolates admission policy.
            raise ValueError('offline fixture')
        cache = market.MarketData(api=api, clock=lambda:clock[0], wall_clock=lambda:wall[0])
        try:
            cache.selection_watch = symbols; cache.selection_until = 100
            for batch in range(4):
                release.clear(); cache._selection_tick()
                futures = [entry['future'] for entry in cache.entries.values() if entry['future']]
                self.assertEqual(len(futures), 2)
                release.set()
                for future in futures:
                    with self.assertRaises(ValueError): future.result(timeout=2)
                self.assertEqual({symbol for endpoint, symbol in calls if endpoint == 'kline'},
                                 set(symbols[:(batch+1)*2]))
                self.assertFalse(any(endpoint == 'orderbook' for endpoint, _ in calls))
            cache._selection_tick()
            futures = [entry['future'] for entry in cache.entries.values() if entry['future']]
            for future in futures:
                with self.assertRaises(ValueError): future.result(timeout=2)
            self.assertTrue(any(endpoint == 'orderbook' for endpoint, _ in calls),
                            'books get both slots once initial charts have attempted')
            cache.get('screener')
            futures = [entry['future'] for entry in cache.entries.values() if entry['future']]
            for future in futures:
                with self.assertRaises(ValueError): future.result(timeout=2)
            self.assertTrue(any(endpoint == 'tickers' for endpoint, _ in calls))
            self.assertLessEqual(len(cache.entries), 24)
        finally:
            release.set(); cache.close()

    def test_completion_and_changed_shortlist_wake_existing_prefetcher(self):
        clock = [0]; cache = market.MarketData(api=lambda *args, **kwargs: (dict(list=[ticker()]), 1000),
                                               clock=lambda:clock[0], wall_clock=lambda:1000)
        try:
            cache.get('screener')
            cache.entries[('screener', '', '')]['future'].result(timeout=2)
            self.assertTrue(cache.wake_event.is_set(), 'worker completion wakes timer loop')
            cache.wake_event.clear()
            # Volume is required by shortlist; add it to the verified fixture.
            cache.get('screener')
            cache.entries[('screener', '', '')]['data']['rows'][0]['volume24'] = 1000
            cache.selection_snapshot(now=1000)
            self.assertTrue(cache.wake_event.is_set(), 'a new shortlist wakes without a 1s delay')
            cache.wake_event.clear(); cache.selection_snapshot(now=1000)
            self.assertFalse(cache.wake_event.is_set(), 'same snapshot does not make a busy loop')
        finally:
            cache.close()

    def test_slow_successful_refreshes_keep_serving_every_shortlisted_book(self):
        symbols = ['COIN' + str(index) + 'USDT' for index in range(8)]
        for latency in (2, 6):
            with self.subTest(latency=latency):
                clock, calls = [0], []
                base = 300040

                class DelayedPool:
                    def __init__(self):
                        self.jobs = []

                    def submit(self, method, kind, symbol, interval):
                        future = Future()
                        self.jobs.append((clock[0] + latency, future, kind, symbol, interval))
                        calls.append((clock[0], kind, symbol))
                        return future

                    def complete(self):
                        for end, future, kind, symbol, interval in self.jobs:
                            if future.done() or end > clock[0]:
                                continue
                            packet = dict(status='ok', updated=base + end, symbol=symbol, seq=end + 1)
                            if kind == 'chart':
                                packet.update(interval=interval, candle_end=int((base + end) // 60) * 60)
                            elif kind == 'screener':
                                packet['rows'] = []
                            future.set_result(packet)

                    def shutdown(self, wait=True):
                        pass

                pool = DelayedPool()
                with patch.object(market, 'ThreadPoolExecutor', return_value=pool):
                    cache = market.MarketData(api=lambda *args, **kwargs:self.fail('No HTTP'),
                                              clock=lambda:clock[0], wall_clock=lambda:base + clock[0])
                try:
                    cache.selection_watch = symbols
                    cache.selection_until = 10000
                    # Cross four candle boundaries and several successful TTL
                    # renewals; initial warm-up alone cannot reveal starvation.
                    for stamp in range(241):
                        clock[0] = stamp
                        pool.complete()
                        cache.get('screener')
                        cache._selection_tick()
                        self.assertLessEqual(sum(entry['future'] is not None for entry in cache.entries.values()), 2)
                        self.assertLessEqual(len(cache.entries), 24)
                        self.assertLessEqual(len(cache.selection_queue), 16)
                    first_book = next(stamp for stamp, kind, _ in calls if kind == 'book')
                    self.assertTrue(all(any(kind == 'chart' and name == symbol and stamp <= first_book
                                            for stamp, kind, name in calls) for symbol in symbols),
                                    'all initial charts attempt before book rotation begins')
                    for symbol in symbols:
                        attempts = [stamp for stamp, kind, name in calls if kind == 'book' and name == symbol]
                        self.assertGreaterEqual(len(attempts), 3, 'successful chart renewals cannot starve ' + symbol)
                        self.assertLessEqual(240 - attempts[-1], 80, 'book service continues after warm-up')
                    ticker_calls = [stamp for stamp, kind, _ in calls if kind == 'screener']
                    self.assertEqual(calls[0], (0, 'screener', ''))
                    self.assertLessEqual(max(b - a for a, b in zip(ticker_calls, ticker_calls[1:])), latency + 6,
                                         'the prefetcher still admits due tickers first')
                finally:
                    cache.close()

    def test_background_completion_refills_shortlist_without_eight_timer_ticks(self):
        symbols = ['COIN' + str(index) + 'USDT' for index in range(8)]
        completed = threading.Event(); lock = threading.Lock(); calls = []
        clock = [1]; wall = 300040
        def load(kind, symbol, interval):
            with lock:
                calls.append((kind, symbol))
                if len({s for k, s in calls if k == 'chart'}) == 8:
                    completed.set()
            if kind == 'screener':
                return dict(status='ok', updated=wall, rows=[dict(market.ticker_rows(
                    dict(list=[dict(ticker(s), volume24h='1000')]), wall)['rows'][0]) for s in symbols])
            return dict(status='ok', updated=wall, symbol=symbol, interval=interval,
                        candle_end=300000, candles=[], seq=1)
        cache = market.MarketData(api=lambda *args, **kwargs:self.fail('No HTTP'),
                                  clock=lambda:clock[0], wall_clock=lambda:wall)
        try:
            with patch.object(cache, '_load', side_effect=load):
                cache.start_background()
                self.assertTrue(completed.wait(3), 'the existing workers refill on completion, not 8 one-second ticks')
            self.assertEqual({s for k, s in calls if k == 'chart'}, set(symbols))
            self.assertLessEqual(sum(v['future'] is not None for v in cache.entries.values()), 2)
            self.assertLessEqual(len(cache.entries), 24)
        finally:
            cache.close()

    def test_selection_returns_isolated_exact_quote_snapshot_including_error_flags(self):
        raw = dict(ticker(), volume24h='1000')
        tickers = market.ticker_rows(dict(list=[raw]), 1000)
        tickers.update(refreshing=True, refresh_error='outage', metadata={'units':['USDT']})
        cache = market.MarketData(api=lambda *args, **kwargs:self.fail('No HTTP'), wall_clock=lambda:1000)
        try:
            with patch.object(cache, 'get', return_value=tickers) as read:
                packet = cache.assistant_snapshot(now=1000)
            read.assert_called_once_with('screener')
            self.assertEqual(packet['source_time'], packet['quote_snapshot']['updated'])
            self.assertEqual(packet['quote_snapshot']['refresh_error'], 'outage')
            self.assertTrue(packet['quote_snapshot']['refreshing'])
            self.assertIsNone(packet['rows'][0]['assistant']['recommendation'])
            packet['quote_snapshot']['rows'][0]['price'] = -1
            packet['quote_snapshot']['metadata']['units'].append('fake')
            packet['quote_snapshot']['updated'] = 999999
            self.assertEqual(tickers['rows'][0]['price'], 100)
            self.assertEqual(tickers['metadata']['units'], ['USDT'])
            self.assertEqual(tickers['updated'], 1000)
            self.assertEqual(len(cache.entries), 0, 'atomic response creates no extra analysis jobs')
        finally:
            cache.close()
    def test_tickers_units_filters_sort_and_bad_values(self):
        bad=ticker('BADUSDT');bad['bid1Price']='nan'
        future=ticker('FUTUSDT');future['deliveryTime']='1800000000000'
        result=market.ticker_rows(dict(list=[ticker(),ticker('ETHUSDT','200000000'),bad,future,ticker('BTCUSDT')]),1000)
        self.assertEqual([r['symbol'] for r in result['rows']],['ETHUSDT','BTCUSDT'])
        self.assertEqual(result['rows'][1]['turnover'],123000000)
        self.assertEqual(result['rows'][1]['change'],5)
        self.assertAlmostEqual(result['rows'][1]['spread'],.02)
        self.assertEqual(result['rejected'],2)
        with self.assertRaises(ValueError): market.ticker_rows(dict(list=[bad]),1000)

    def test_closed_candles_gap_duplicate_and_stale(self):
        result,stamp=kline_fixture();bars=market.closed_candles(result,stamp,'5')
        self.assertEqual(len(bars),180)
        self.assertEqual(bars[-1]['time']+300,300000)
        gap=copy.deepcopy(result);gap['list'].pop(10)
        duplicate=copy.deepcopy(result);duplicate['list'][10]=duplicate['list'][11]
        invalid=copy.deepcopy(result);invalid['list'][10][2]='-1'
        for value in (gap,duplicate,invalid):
            with self.assertRaises(ValueError): market.closed_candles(value,stamp,'5')
        with self.assertRaises(ValueError): market.closed_candles(result,stamp+600,'5')

    def test_confirmed_zones_rvol_vwap_and_no_last_two_pivots(self):
        result,stamp=kline_fixture();bars=market.closed_candles(result,stamp,'5')
        data=market.chart_analysis('BTCUSDT','5',bars,stamp)
        self.assertGreater(len(data['levels']),0)
        self.assertLessEqual(len(data['levels']),6)
        for level in data['levels']:
            self.assertLessEqual(level['last_pivot'],bars[-3]['time'])
            self.assertLessEqual(level['high']-level['low'],data['zone_width']+1e-9)
            self.assertTrue(level['high']<data['price'] if level['side']=='support' else level['low']>data['price'])
        expected=sum(b['turnover'] for b in bars[-60:])/sum(b['volume'] for b in bars[-60:])
        self.assertAlmostEqual(data['vwap'],expected)
        self.assertEqual(data['volume_window'],600,'volume remains base quantity rather than USDT turnover')
        self.assertAlmostEqual(data['atr']/data['price']*100,data['atr_pct'])
        self.assertAlmostEqual(data['turnover_window'],sum(b['turnover'] for b in bars[-60:]))
        bars[-1]['low']=1
        changed=market.chart_analysis('BTCUSDT','5',bars,stamp)
        self.assertTrue(all(l['low']>1 for l in changed['levels']))

    def test_flat_candles_no_manufactured_levels(self):
        bars=[dict(time=i*60,open=100,high=100,low=100,close=100,volume=0,turnover=0) for i in range(60)]
        data=market.chart_analysis('BTCUSDT','1',bars,3600)
        self.assertEqual(data['levels'],[])
        self.assertIsNone(data['rvol']);self.assertIsNone(data['vwap'])
        self.assertEqual(data['volume_window'],0);self.assertEqual(data['atr'],0)

    def test_orderbook_notional_nested_zones_walls_validation(self):
        result=dict(s='BTCUSDT',ts=1000000,b=[['99.99','10'],['99.95','20'],['99.8','30']],a=[['100.01','15'],['100.05','25'],['100.2','35']])
        data=market.orderbook_analysis('BTCUSDT',result,1000)
        self.assertAlmostEqual(data['bands']['0.0002']['bid'],999.9)
        self.assertAlmostEqual(data['bands']['0.001']['bid'],2998.9)
        self.assertTrue(data['bands']['0.001']['covered'])
        self.assertAlmostEqual(data['walls']['bid'][0]['notional'],1999)
        # Compact ladder shows the best prices, not the largest walls.
        self.assertEqual([v['price'] for v in data['top']['bid']], [99.99,99.95,99.8])
        self.assertEqual([v['price'] for v in data['top']['ask']], [100.01,100.05,100.2])
        self.assertEqual(data['top']['ask'][0]['quantity'],15)
        self.assertAlmostEqual(data['top']['ask'][0]['notional'],1500.15)
        deep=copy.deepcopy(result)
        deep['b']=[[str(99.99-i*.01),'10'] for i in range(10)]
        self.assertEqual(len(market.orderbook_analysis('BTCUSDT',deep,1000)['top']['bid']),5)
        for mutation in ('crossed','sorted','stale','symbol'):
            bad=copy.deepcopy(result)
            if mutation=='crossed':bad['b'][0][0]='100.1'
            if mutation=='sorted':bad['b'].reverse()
            if mutation=='stale':bad['ts']=900000
            if mutation=='symbol':bad['s']='ETHUSDT'
            with self.assertRaises(ValueError):market.orderbook_analysis('BTCUSDT',bad,1000)

    def test_cache_coalesces_bounds_jobs_and_harvests_other_key(self):
        release=threading.Event();calls=[];clock=[0]
        def api(endpoint,**params):
            calls.append(endpoint);release.wait(2)
            return dict(list=[ticker()]),1000
        cache=market.MarketData(api=api,clock=lambda:clock[0])
        try:
            for _ in range(10):self.assertEqual(cache.get('screener')['status'],'pending')
            future=cache.entries[('screener','','')]['future']
            cache.get('chart','BTCUSDT')
            cache.get('book','BTCUSDT')
            self.assertIsNone(cache.entries[('book','BTCUSDT','')]['future'])
            release.set();future.result(timeout=2)
            cache.get('book','BTCUSDT')
            self.assertEqual(cache.get('screener')['status'],'ok')
            self.assertEqual(calls.count('tickers'),1)
            self.assertLessEqual(sum(v['future'] is not None for v in cache.entries.values()),2)
        finally:release.set();cache.close()

    def test_failed_refresh_not_relabelled_fresh_and_retry_backoff(self):
        clock=[0];calls=[]
        def api(endpoint,**params):
            calls.append(endpoint)
            if len(calls)>1:raise ValueError('outage')
            return dict(list=[ticker()]),1000
        cache=market.MarketData(api=api,clock=lambda:clock[0])
        try:
            cache.get('screener');cache.entries[('screener','','')]['future'].result(timeout=2)
            self.assertEqual(cache.get('screener')['updated'],1000)
            clock[0]=16;cache.get('screener')
            try:cache.entries[('screener','','')]['future'].result(timeout=2)
            except ValueError:pass
            data=cache.get('screener');self.assertEqual(data['status'],'ok');self.assertEqual(data['updated'],1000)
            self.assertIn('refresh_error',data)
            for _ in range(10):cache.get('screener')
            self.assertEqual(len(calls),2)
            for symbol in ('../passwd','https://example.org','BTCUSDT&x=1','BTCUSDT;id'):
                with self.assertRaises(ValueError):cache.get('book',symbol)
            with self.assertRaises(ValueError):cache.get('chart','BTCUSDT','D')
        finally:cache.close()

    def test_background_prefetch_warms_only_shared_screener_snapshot(self):
        called = threading.Event(); calls = []
        def api(endpoint, **params):
            calls.append((endpoint, params)); called.set()
            return dict(list=[ticker()]), 1000
        cache = market.MarketData(api=api, background=True)
        try:
            self.assertTrue(called.wait(1), 'background prefetch should start without a browser request')
            self.assertEqual(calls[0], ('tickers', {}))
        finally:
            cache.close()


if __name__=='__main__':unittest.main()
