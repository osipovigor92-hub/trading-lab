"""Public-density observations: units, coverage, interruption and bounded scans."""
import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trading-panel'))
from densities import DensityMonitor, EXCHANGES, HISTORY_LIMIT, MAX_ROWS, SCAN_LIMIT, density_id


def book(stamp, bids=None, asks=None, exchange='bybit', symbol='BTCUSDT'):
    bids = bids if bids is not None else [['100.02', 10], ['100', 1000], ['98', 10]]
    asks = asks if asks is not None else [['100.1', 1000], ['102', 10]]
    return dict(exchange=exchange, symbol=symbol, status='ok', source_ts=stamp, updated=stamp,
                timestamp_origin='exchange', bids=bids, asks=asks,
                coverage=dict(bid_min=bids[-1][0], ask_max=asks[-1][0]))


class Adapter:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
    def exchange_snapshot(self, exchange):
        return dict(status='ok', updated=self.clock(), eligible=100,
                    rows=[dict(symbol='COIN'+str(index)+'USDT', turnover24=100-index) for index in range(10)])
    def book_snapshot(self, exchange, symbol):
        self.calls.append((exchange, symbol))
        return book(self.clock(), exchange=exchange, symbol=symbol)


class DensityTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.adapter = Adapter(lambda:self.now)
        self.monitor = DensityMonitor(self.adapter, clock=lambda:self.now)
        self.identity = density_id('bybit', 'BTCUSDT', 'bid', '100')
    def observe(self, packet=None):
        return self.monitor.observe('bybit', 'BTCUSDT', book(self.now) if packet is None else packet)
    def row(self):
        return next(row for row in self.monitor.snapshot()['rows'] if row['id'] == self.identity)

    def test_catalogs_cannot_starve_books_and_completed_books_are_harvested(self):
        calls=[]
        class BudgetAdapter:
            ready=False
            def exchange_snapshot(adapter, exchange):
                calls.append(('catalog',exchange))
                return dict(status='pending', updated=0)
            def book_snapshot(adapter, exchange, symbol):
                calls.append(('book',symbol))
                return dict(status='pending', updated=0)
            def peek_book(adapter, exchange, symbol):
                return book(self.now, exchange=exchange, symbol=symbol) if adapter.ready else dict(status='pending', updated=0)
        adapter=BudgetAdapter();monitor=DensityMonitor(adapter,clock=lambda:self.now)
        monitor.request(watch='bybit:BTCUSDT,bybit:ETHUSDT,bybit:SOLUSDT')
        first=[]
        for tick in range(10):
            self.now=tick;calls.clear();monitor.tick();first.append(calls[0])
        self.assertEqual({v for kind,v in first if kind=='catalog'},set(EXCHANGES))
        self.assertTrue(all(first[i][0]=='book' for i in range(1,10,2)))
        adapter.ready=True;self.now=10;monitor.tick()
        self.assertEqual(monitor.snapshot()['coverage']['scanned'],3)

    def test_relative_wall_below_absolute_floor_and_side_baseline(self):
        bids=[[str(100-i*.01), 1] for i in range(21)]
        bids[0][1]=12
        asks=[[str(101+i*.01), 1000] for i in range(21)]
        self.observe(book(0,bids,asks))
        row=self.row()
        self.assertLess(row['notional'],50000)
        self.assertGreaterEqual(row['size_multiple'],10)
        self.assertEqual(row['baseline_levels'],20)
        self.assertAlmostEqual(row['baseline_notional'],sum(float(p)*q for p,q in bids[1:])/20)

    def test_chart_overlay_adds_bounded_targets_without_replacing_monitor_scope(self):
        self.monitor.request(exchanges='bybit', symbols='BTCUSDT', watch='bybit:BTCUSDT')
        packet = self.monitor.request(exchanges='binance', symbols='ETHUSDT', watch='binance:ETHUSDT', overlay=True)
        self.assertEqual(self.monitor.selected, ['bybit'])
        self.assertEqual(self.monitor.watch, [('bybit', 'BTCUSDT')])
        self.assertIn(('binance', 'ETHUSDT'), self.monitor.targets)
        self.assertIn(('bybit', 'BTCUSDT'), self.monitor.targets)
        self.monitor.tick()
        self.assertTrue(all(row['exchange']=='binance' for row in self.monitor.snapshot({'exchanges':['binance']})['rows']))
        self.assertTrue(all(row['exchange']=='bybit' for row in self.monitor.snapshot()['rows']))
        self.now=16;self.monitor.tick()
        self.assertNotIn(('binance', 'ETHUSDT'), self.monitor.targets)
        self.assertEqual(self.monitor.selected, ['bybit'])
        self.assertLessEqual(len(self.monitor.targets), SCAN_LIMIT)

    def test_base_quantity_notional_exact_price_identity_and_exchange_side(self):
        self.observe()
        self.assertEqual(self.row()['notional'], 100_000)
        self.assertEqual(self.row()['age_seconds'], 0)
        self.assertAlmostEqual(self.row()['distance_pct'], abs(100/100.06-1)*100)
        self.assertEqual(density_id('bybit','BTCUSDT','bid','100.0'), self.identity)
        self.assertNotEqual(density_id('binance','BTCUSDT','bid','100'), self.identity)
        self.assertNotEqual(density_id('bybit','BTCUSDT','ask','100'), self.identity)
        self.now = 10
        precise = book(self.now, bids=[['100.0000000000000002', 1000], ['100.0000000000000001', 1000], ['99', 10]])
        self.observe(precise)
        ids = [density_id('bybit','BTCUSDT','bid',price) for price in ('100.0000000000000002','100.0000000000000001')]
        self.assertNotEqual(*ids)
        self.assertTrue(all(identity in self.monitor.rows for identity in ids))

    def test_hour_requires_consecutive_fresh_observations_and_outage_resets_age(self):
        for stamp in range(0, 3601, 10):
            self.now = stamp
            self.observe()
        self.assertEqual(self.row()['age_seconds'], 3600)
        self.assertTrue(self.row()['stable'])
        self.now = 3601
        self.observe(dict(status='error', error='outage'))
        self.assertEqual(self.row()['status'], 'unavailable')
        self.assertFalse(self.row()['stable'])
        self.assertEqual(self.row()['age_seconds'], 0)
        self.now = 3610
        self.observe()
        self.assertEqual(self.row()['first_seen'], 0)
        self.assertEqual(self.row()['age_seconds'], 0)
        self.assertFalse(self.row()['stable'])
        self.assertTrue(any(event['status']=='unavailable' for event in self.monitor.snapshot()['history']))

    def test_two_fresh_covered_misses_confirm_disappearance_and_reappearance(self):
        self.observe()
        missing = [['100.02', 10], ['98', 10]]
        self.now = 10
        self.observe(book(self.now, bids=missing))
        self.assertEqual(self.row()['status'], 'unobserved')
        self.assertFalse(self.row()['stable'])
        self.assertFalse(self.observe(book(self.now, bids=missing)), 'replayed snapshot is not a second miss')
        self.assertEqual(self.row()['status'], 'unobserved')
        self.now = 20
        self.observe(book(self.now, bids=missing))
        self.assertEqual(self.row()['status'], 'missing')
        self.assertTrue(any(event['id']==self.identity and event['status']=='missing' for event in self.monitor.history))
        self.now = 30
        self.observe()
        self.assertEqual(self.row()['status'], 'active')
        self.assertEqual(self.row()['age_seconds'], 0)

    def test_missing_history_retains_last_verified_hour_without_current_qualification(self):
        for stamp in range(0, 3601, 10):
            self.now = stamp
            self.observe()
        self.assertTrue(self.row()['stable'])
        for stamp in (3610,3620):
            self.now = stamp
            self.observe(book(stamp,bids=[['100.02',10],['98',10]]))
            self.assertEqual(self.row()['age_seconds'], 0)
            self.assertFalse(self.row()['stable'])
        historical = next(row for row in self.monitor.snapshot()['history'] if row['id']==self.identity and row['status']=='missing')
        self.assertEqual(historical['age_seconds'], 3600)
        self.assertFalse(historical['stable'])
        self.now = 3630
        self.observe()
        self.now = 3640
        self.observe()
        for stamp in (3650,3660):
            self.now = stamp
            self.observe(book(stamp,bids=[['100.02',10],['98',10]]))
        historical = next(row for row in self.monitor.snapshot()['history'] if row['id']==self.identity and row['status']=='missing')
        self.assertEqual(historical['age_seconds'], 10, 'new short episode does not inherit historical hour')

    def test_outside_depth_is_unobserved_and_interrupts_consecutive_misses(self):
        self.observe()
        shallow = [['100.02', 10], ['100.01', 10]]
        for stamp in (10, 20, 30):
            self.now = stamp
            self.observe(book(stamp, bids=shallow))
            self.assertEqual(self.row()['status'], 'unobserved')
        self.now = 40
        self.observe(book(40, bids=[['100.02',10],['98',10]]))
        self.assertEqual(self.row()['status'], 'unobserved')
        self.now = 50
        self.observe(book(50, bids=shallow))
        self.now = 60
        self.observe(book(60, bids=[['100.02',10],['98',10]]))
        self.assertEqual(self.row()['status'], 'unobserved', 'only one fresh covered miss after depth gap')

    def test_lower_notional_is_density_missing_not_fabricated_order_removal(self):
        self.observe()
        for stamp in (10, 20):
            self.now = stamp
            self.observe(book(stamp, bids=[['100.02',10],['100',400],['98',10]]))
        self.assertEqual(self.row()['status'], 'missing')
        self.assertEqual(self.row()['notional'], 100_000, 'last observed density is retained historically')

    def test_stale_error_future_replay_backward_and_large_gap_do_not_extend(self):
        self.observe()
        self.now = 10
        self.observe()
        self.now = 20
        self.assertFalse(self.observe(book(10)))
        self.assertEqual(self.row()['age_seconds'], 10)
        self.assertFalse(self.observe(book(9)))
        self.assertEqual(self.row()['status'], 'unavailable')
        self.now = 30
        self.observe()
        self.assertEqual(self.row()['age_seconds'], 0)
        for changes in ({'source_ts':0}, {'updated':0}, {'source_ts':self.now+3},
                        {'stale':True}, {'status':'error'}, {'refresh_error':'outage'}):
            self.observe(dict(book(self.now+1), **changes))
            self.assertEqual(self.row()['status'], 'unavailable', str(changes))
        self.now = 40
        self.observe()
        self.now = 80
        self.observe()
        self.assertEqual(self.row()['age_seconds'], 0, 'gap cannot be bridged without snapshots')
        self.now = 106
        self.assertEqual(self.row()['status'], 'unavailable', 'snapshot expiry works without a new HTTP response')

    def test_five_second_cache_ttl_with_ten_second_visits_preserves_verified_observation(self):
        self.observe()
        for stamp in range(10, 3620, 10):
            self.now = stamp
            source = stamp-5
            self.observe(dict(book(source),status='pending',stale=True,error=None,refreshing=True))
            self.assertEqual(self.row()['status'], 'active')
        self.assertTrue(self.row()['stable'])
        self.assertEqual(self.row()['age_seconds'], 3605)
        age = self.row()['age_seconds']
        self.now += 5
        self.observe(dict(book(3605),status='pending',stale=True,error=None,refreshing=True))
        self.assertEqual(self.row()['age_seconds'], age, 'cache poll time never replaces actual source time')
        self.now += 1
        self.observe(dict(book(3605),status='error',stale=True,error='API outage'))
        self.assertEqual(self.row()['status'], 'unavailable')
        self.assertEqual(self.row()['age_seconds'], 0)
        self.assertFalse(self.row()['stable'])

    def test_catalog_refresh_keeps_verified_scan_targets_and_source_book_history(self):
        self.monitor.tick()
        targets = list(self.monitor.targets)
        old_catalog = self.adapter.exchange_snapshot('bybit')
        self.now = 65
        self.adapter.exchange_snapshot = lambda exchange:dict(old_catalog,status='pending',stale=True,error=None,refreshing=True)
        self.monitor.tick()
        self.assertEqual(self.monitor.targets, targets, 'catalog TTL refresh does not empty the watched queue')
        self.now = 91
        self.monitor.tick()
        self.assertEqual(self.monitor.targets, [], 'unbounded old catalog is not used for discovery')

    def test_malformed_books_never_confirm_fresh_density(self):
        self.observe()
        for packet in (dict(book(1), exchange='binance'), dict(book(1), symbol='ETHUSDT'),
                       dict(book(1), bids=[['100','nan']]), dict(book(1), bids=[['100',-5]]),
                       dict(book(1), asks=[['99',1000]]), dict(book(1), coverage={'bid_min':'97','ask_max':'102'}),
                       ['malformed']):
            self.now = 1
            self.assertFalse(self.observe(packet))
            self.assertFalse(self.row()['stable'])

    def test_restart_preserves_identity_history_but_resets_continuous_qualification(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'density-state.json'
            monitor = DensityMonitor(self.adapter, clock=lambda:self.now, state_path=path)
            for stamp in range(0, 3601, 10):
                self.now = stamp
                monitor.observe('bybit','BTCUSDT',book(stamp))
            monitor.close()
            self.assertTrue(path.exists())
            self.assertFalse(path.with_name(path.name+'.tmp').exists())
            restarted = DensityMonitor(self.adapter, clock=lambda:self.now, state_path=path)
            row = next(row for row in restarted.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['first_seen'], 0)
            self.assertEqual(row['age_seconds'], 0)
            self.assertFalse(row['stable'])
            self.assertEqual(row['status'], 'unavailable')
            self.now = 3610
            restarted.observe('bybit','BTCUSDT',book(3600))
            row = next(row for row in restarted.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['age_seconds'], 0)
            self.assertEqual(row['status'], 'unavailable', 'pre-restart source replay cannot revive observation')
            self.now = 3620
            restarted.observe('bybit','BTCUSDT',book(self.now))
            row = next(row for row in restarted.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['age_seconds'], 0, 'new source begins a new episode after restart')
            restarted.close()
            self.assertLess(path.stat().st_size, 1_000_000)

    def test_scan_shared_cache_budget_watch_priority_and_coverage_are_explicit(self):
        self.monitor.tick()
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(len(self.monitor.targets), 10)
        packet = self.monitor.snapshot()
        self.assertEqual(packet['coverage']['total'], 500)
        self.assertEqual(packet['coverage']['scanned'], 2)
        watched = ['bybit:WATCH'+str(index)+'USDT' for index in range(20)]
        self.monitor.request(watch=','.join(watched))
        self.assertEqual(len(self.monitor.targets), SCAN_LIMIT)
        self.assertEqual(self.monitor.targets[0], ('bybit','WATCH0USDT'))
        self.now = 10
        self.monitor.tick()
        self.assertEqual(len(self.adapter.calls), 4, 'still only two cache requests per scheduler step')
        for bad in ('binance,binance', 'unknown'):
            with self.assertRaises(ValueError): self.monitor.request(exchanges=bad)
        for bad in ('../passwd', 'BTC', 'bybit:btcusdt', ','.join(watched+['bybit:LASTUSDT'])):
            with self.assertRaises(ValueError): self.monitor.request(watch=bad)
        self.assertFalse(hasattr(self.monitor,'pool'), 'no extra network worker pool is created')
        self.monitor.request(watch='bybit:XUSDT')
        self.assertEqual(self.monitor.targets[0], ('bybit','XUSDT'))

    def test_rows_history_and_book_cache_are_bounded(self):
        for index in range(MAX_ROWS+20):
            self.now += 1
            self.monitor.observe('bybit','COIN'+str(index)+'USDT',book(self.now,symbol='COIN'+str(index)+'USDT'))
        self.assertLessEqual(len(self.monitor.rows), MAX_ROWS)
        self.assertLessEqual(len(self.monitor.books), SCAN_LIMIT)
        self.assertLessEqual(len(self.monitor.history), HISTORY_LIMIT)

    def test_corrupt_persistence_never_restores_nonfinite_or_stable_live_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'density-state.json'
            bad = dict(id=self.identity,exchange='bybit',symbol='BTCUSDT',side='bid',price=100,
                       price_text='100',notional=float('nan'),distance_pct=.1,
                       first_seen=0,last_seen=0,stable=True,age_seconds=9000,status='active')
            path.write_text(json.dumps(dict(version=1,rows=[bad],history=[bad],sequence=1)),encoding='utf-8')
            monitor = DensityMonitor(self.adapter,clock=lambda:self.now,state_path=path)
            self.assertEqual(monitor.snapshot()['rows'], [])
            self.assertEqual(monitor.snapshot()['history'], [])
            monitor.close()

    @unittest.skipIf(os.name=='nt', 'Preview imports Linux fcntl; Windows browser harness supplies its preview-only shim')
    def test_preview_exchange_chart_has_normalized_closed_contiguous_timestamps(self):
        path = Path(__file__).with_name('preview.py')
        spec = importlib.util.spec_from_file_location('density_preview_contract',path)
        preview = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preview)
        try:
            for interval in ('1','5','15','60'):
                packet = preview.exchange_fixture('/api/exchange-chart',dict(exchange=['bybit'],symbol=['BTCUSDT'],interval=[interval]))
                candles = packet['candles']
                step = int(interval)*60
                self.assertTrue(packet['demo'])
                self.assertEqual(packet['status'], 'ok')
                self.assertEqual(len(candles), 180)
                self.assertTrue(all(row['t']==row['time'] and row['t']%step==0 for row in candles))
                self.assertTrue(all(b['t']-a['t']==step for a,b in zip(candles,candles[1:])))
                self.assertEqual(candles[-1]['t']+step,packet['candle_end'])
                self.assertLessEqual(packet['candle_end'],packet['updated'])
            legacy = preview.market_fixture('/api/market-chart',dict(symbol=['BTCUSDT'],interval=['1']))
            self.assertTrue(all('time' in row and 't' not in row for row in legacy['candles']))
        finally:
            preview.MANUAL.stop.set()


if __name__ == '__main__':
    unittest.main()

