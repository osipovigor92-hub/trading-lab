"""Public-density observations: units, coverage, interruption and bounded scans."""
import json
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trading-panel'))
from densities import (DensityMonitor, EVIDENCE_LIMIT, EXCHANGES, HISTORY_LIMIT, MAX_ROWS,
                       SCAN_LIMIT, density_id)


def book(stamp, bids=None, asks=None, exchange='bybit', symbol='BTCUSDT'):
    bids = bids if bids is not None else [['100.02', 10], ['100', 1000], ['98', 10]]
    asks = asks if asks is not None else [['100.1', 1000], ['102', 10]]
    return dict(exchange=exchange, symbol=symbol, status='ok', source_ts=stamp, updated=stamp,
                timestamp_origin='exchange', bids=bids, asks=asks,
                coverage=dict(bid_min=bids[-1][0], ask_max=asks[-1][0]))


def wall_book(stamp, walls=None, exchange='bybit', symbol='BTCUSDT', best='100.05'):
    """A dense covered ladder makes outliers and repricings observable."""
    quantities = {price:10 for price in ('100.04','100','99.95','99.9','99.85','99.8','99.75','99.7','99.5')}
    quantities[best] = 10
    quantities.update(walls if walls is not None else {'99.8':2000})
    bids = [[price, quantity] for price, quantity in sorted(quantities.items(), key=lambda value:-float(value[0]))]
    asks = [[price,10] for price in ('100.3','100.35','100.4','100.45','100.5')]
    return book(stamp, bids=bids, asks=asks, exchange=exchange, symbol=symbol)


class Adapter:
    def __init__(self, clock):
        self.clock, self.calls, self.catalog_calls = clock, [], []
    def exchange_snapshot(self, exchange):
        self.catalog_calls.append(exchange)
        return dict(status='ok', updated=self.clock(), eligible=100,
                    rows=[dict(symbol='COIN'+str(index)+'USDT', turnover24=100-index) for index in range(10)])
    def book_snapshot(self, exchange, symbol):
        self.calls.append((exchange, symbol))
        return book(self.clock(), exchange=exchange, symbol=symbol)


class CacheAdapter(Adapter):
    """Deterministic worker completion; peek never admits an upstream read."""
    def __init__(self, clock):
        super().__init__(clock)
        self.cache, self.peeks = {}, []
    def peek_book_snapshot(self, exchange, symbol):
        self.peeks.append((exchange, symbol))
        packet = self.cache.get((exchange, symbol))
        if packet is None:
            return dict(status='pending', updated=None, source_ts=None, error=None)
        if packet['status'] == 'ok' and self.clock()-packet['updated'] >= 5:
            return dict(packet, status='pending', stale=True, refreshing=True)
        return dict(packet)
    def book_snapshot(self, exchange, symbol):
        self.calls.append((exchange, symbol))
        return self.peek_book_snapshot(exchange, symbol)
    def complete(self, exchange, symbol, stamp, **changes):
        self.cache[(exchange, symbol)] = dict(book(stamp, exchange=exchange, symbol=symbol), **changes)


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

    def wall_row(self, price='99.8', exchange='bybit', symbol='BTCUSDT'):
        identity = density_id(exchange, symbol, 'bid', price)
        return next(row for row in self.monitor.snapshot()['rows'] if row['id'] == identity)

    def repricing(self):
        for stamp, price in ((0,'99.8'),(5,'99.85'),(10,'99.9')):
            self.now = stamp
            self.observe(wall_book(stamp, walls={price:2000}))
        return self.wall_row('99.9')

    def test_significance_keeps_raw_levels_but_only_selects_large_near_outlier(self):
        self.observe(wall_book(0, walls={'99.8':2000,'99.95':800,'98':5000}))
        rows = self.monitor.snapshot()['rows']
        self.assertEqual(len(rows), 3, 'the raw 50K observation contract is retained')
        significant = [row for row in rows if row['significance']['status']=='significant']
        self.assertEqual([row['price_text'] for row in significant], ['99.8'])
        evidence = significant[0]['significance']
        self.assertEqual(evidence['kind'], 'large_wall')
        self.assertEqual(evidence['confidence'], 'single_snapshot')
        self.assertGreaterEqual(evidence['relative_size'], 5)
        self.assertGreaterEqual(evidence['neighbor_count'], 3)
        self.assertNotIn('repeated_repricing', evidence['reasons'])
        self.assertAlmostEqual(evidence['visible_depth_share'], significant[0]['notional']/evidence['side_depth_notional'])
        self.assertEqual(evidence['source_stamps'], [0])
        self.assertEqual(evidence['last_source_ts'], significant[0]['last_seen'])
        settings = self.monitor.snapshot()['coverage']['significance']
        self.assertEqual(settings['min_notional'], 100_000)
        self.assertEqual(settings['score_kind'], 'rule_priority')

    def test_absolute_threshold_uniform_large_levels_and_sparse_book_are_not_outliers(self):
        self.observe(wall_book(0, walls={'100':1000}))
        self.assertEqual(self.wall_row('100')['significance']['status'], 'significant', '100K is inclusive')
        self.now = 1
        self.observe(wall_book(1, walls={'100':999}))
        self.assertEqual(self.wall_row('100')['significance']['status'], 'ordinary', '99.9K is below the candidate threshold')
        self.now = 2
        uniform = {price:1200 for price in ('100.05','100.04','100','99.95','99.9','99.85','99.8','99.75','99.7','99.5')}
        self.observe(wall_book(2, walls=uniform))
        current = [row for row in self.monitor.snapshot()['rows'] if row['last_seen']==2]
        self.assertTrue(current)
        self.assertTrue(all(row['notional'] >= 100_000 for row in current))
        self.assertTrue(all(row['significance']['status']=='ordinary' for row in current), 'ordinary deep liquidity is not every wall')
        self.now = 3
        self.observe(book(3,bids=[['100',2000],['99.9',10]], asks=[['100.1',10]]))
        evidence = self.wall_row('100')['significance']
        self.assertIsNone(evidence['relative_size'])
        self.assertIsNone(evidence['local_median_notional'])
        self.assertEqual(evidence['neighbor_count'], 1)
        self.assertEqual(evidence['status'], 'ordinary', 'a shallow denominator does not qualify a lone wall')

    def test_three_distinct_sources_two_actual_moves_make_only_current_wall_pattern(self):
        row = self.repricing()
        evidence = row['significance']
        self.assertEqual(evidence['kind'], 'machine_pattern_suspect')
        self.assertEqual(evidence['confidence'], 'repeated_pattern')
        self.assertEqual(evidence['observations'], 1, 'same-price observations are separate from the moving chain')
        self.assertEqual(evidence['source_stamps'], [10])
        self.assertEqual(evidence['pattern']['samples'], 3)
        self.assertEqual(evidence['pattern']['repricings'], 2)
        self.assertEqual(evidence['pattern']['side_pressure_observations'], 3)
        self.assertEqual([item['source_ts'] for item in evidence['pattern']['price_path']], [0,5,10])
        self.assertEqual([item['price_text'] for item in evidence['pattern']['price_path']], ['99.8','99.85','99.9'])
        self.assertLessEqual(evidence['score'], 100)
        inactive = self.wall_row('99.85')['significance']
        self.assertIsNone(inactive['kind'])
        self.assertEqual(inactive['observed_kind'], 'large_wall')
        for stamp in (15,20,25):
            self.now = stamp
            self.observe(wall_book(stamp,walls={'99.9':2000}))
        evidence = self.wall_row('99.9')['significance']
        self.assertEqual(evidence['last_source_ts'], 25)
        self.assertEqual([item['price_text'] for item in evidence['pattern']['price_path']], ['99.8','99.85','99.9'],
                         'bounded proof retains the actual moves when later samples stay at the same price')

    def test_replay_rollback_error_and_expiry_cannot_supply_pattern_proof(self):
        self.observe(wall_book(0))
        self.now = 1
        self.assertFalse(self.observe(wall_book(0,walls={'99.85':2000})))
        self.assertEqual(self.wall_row()['significance']['observations'], 1)
        self.assertNotIn(density_id('bybit','BTCUSDT','bid','99.85'), self.monitor.rows)
        row = self.repricing()
        self.assertEqual(row['significance']['pattern']['samples'], 3)
        self.assertFalse(self.observe(wall_book(9,walls={'99.95':2000})))
        inactive = self.wall_row('99.9')['significance']
        self.assertEqual(inactive['status'], 'inactive')
        self.assertIsNone(inactive['kind'])
        self.assertEqual(inactive['observed_kind'], 'machine_pattern_suspect')
        self.assertEqual(inactive['last_source_ts'], 10)
        self.assertNotIn(('bybit','BTCUSDT'), self.monitor.evidence)
        self.now = 15
        self.observe(wall_book(15,walls={'99.95':2000}))
        self.assertEqual(self.wall_row('99.95')['significance']['pattern']['samples'], 1)
        self.observe(dict(status='error',error='upstream failure'))
        self.assertNotIn(('bybit','BTCUSDT'), self.monitor.evidence)
        self.now = 20
        self.observe(wall_book(20,walls={'100':2000}))
        self.assertEqual(self.wall_row('100')['significance']['kind'], 'large_wall')
        self.assertEqual(self.wall_row('100')['significance']['observations'], 1)
        self.now = 46
        expired = self.wall_row('100')['significance']
        self.assertEqual(expired['status'], 'inactive')
        self.assertIsNone(expired['kind'])
        self.assertEqual(expired['last_source_ts'], 20)
        self.assertNotIn(('bybit','BTCUSDT'), self.monitor.evidence)

    def test_static_wall_mid_motion_and_long_counts_never_become_moving_pattern(self):
        for stamp in range(25):
            self.now = stamp
            packet = wall_book(stamp)
            packet['asks'][0][0] = str(100.3-stamp*.001)
            self.observe(packet)
        evidence = self.wall_row()['significance']
        self.assertEqual(evidence['kind'], 'large_wall')
        self.assertEqual(evidence['confidence'], 'repeated_observations')
        self.assertEqual(evidence['observations'], EVIDENCE_LIMIT)
        self.assertEqual(evidence['source_stamps'], list(range(13,25)))
        self.assertEqual(evidence['pattern']['samples'], EVIDENCE_LIMIT)
        self.assertEqual(evidence['pattern']['repricings'], 0)
        self.now = 60
        self.observe(wall_book(60))
        self.assertEqual(self.wall_row()['significance']['observations'], 1, 'large source gaps start new evidence')
        self.assertEqual(self.wall_row()['significance']['pattern']['samples'], 1)

    def test_pattern_never_combines_other_symbols_venues_or_sides(self):
        for stamp, exchange, symbol, price in ((0,'bybit','BTCUSDT','99.8'),
                                               (5,'binance','BTCUSDT','99.85'),
                                               (10,'bybit','ETHUSDT','99.9')):
            self.now = stamp
            self.monitor.observe(exchange,symbol,wall_book(stamp,walls={price:2000},exchange=exchange,symbol=symbol))
        self.assertTrue(all(row['significance']['kind']=='large_wall' for row in self.monitor.snapshot()['rows']))
        self.assertEqual(len(self.monitor.evidence), 3)
        for stamp, price in ((15,'99.85'),(20,'99.9')):
            self.now = stamp
            self.observe(wall_book(stamp,walls={price:2000}))
        self.assertEqual(self.wall_row('99.9')['significance']['kind'], 'machine_pattern_suspect')
        self.assertEqual(self.wall_row('99.85','binance')['significance']['kind'], 'large_wall')
        self.assertEqual(self.wall_row('99.9',symbol='ETHUSDT')['significance']['kind'], 'large_wall')
        self.assertEqual(self.monitor.evidence[('bybit','BTCUSDT')]['sides']['ask']['candidates'], [])

    def test_ask_repricing_is_symmetric_and_pressure_context_is_required(self):
        for stamp, price in ((0,'100.5'),(5,'100.45'),(10,'100.4')):
            self.now = stamp
            packet = wall_book(stamp,walls={})
            amounts = {level:10 for level in ('100.3','100.35','100.4','100.45','100.5','100.55','100.6','100.7')}
            amounts[price] = 2000
            packet['asks'] = [[level, quantity] for level, quantity in sorted(amounts.items(),key=lambda value:float(value[0]))]
            packet['coverage']['ask_max'] = '100.7'
            self.observe(packet)
        identity = density_id('bybit','BTCUSDT','ask','100.4')
        evidence = self.monitor.rows[identity]['significance']
        self.assertEqual(evidence['kind'], 'machine_pattern_suspect')
        self.assertEqual(evidence['pattern']['repricings'], 2)
        self.assertGreaterEqual(evidence['near_pressure_share'], .6)
        self.monitor = DensityMonitor(self.adapter,clock=lambda:self.now)
        for stamp, price in ((15,'99.8'),(20,'99.85'),(25,'99.9')):
            self.now = stamp
            packet = wall_book(stamp,walls={price:2000})
            packet['asks'] = [[level,1000] for level in ('100.3','100.35','100.4','100.45','100.5')]
            self.observe(packet)
        evidence = self.wall_row('99.9')['significance']
        self.assertEqual(evidence['kind'], 'large_wall')
        self.assertLess(evidence['near_pressure_share'], .6)
        self.assertEqual(evidence['pattern']['samples'], 1, 'repricings do not manufacture same-side pressure')

    def test_ambiguous_replacements_added_walls_and_outside_coverage_are_not_repricing(self):
        self.observe(wall_book(0,walls={'99.75':2000,'99.8':2000}))
        self.now = 5
        self.observe(wall_book(5,walls={'99.85':2000}))
        evidence = self.wall_row('99.85')['significance']
        self.assertTrue(evidence['pattern']['ambiguous'])
        self.assertEqual(evidence['kind'], 'large_wall')
        self.assertEqual(evidence['pattern']['samples'], 1)
        self.monitor = DensityMonitor(self.adapter,clock=lambda:self.now)
        for stamp, walls in ((10,{'99.8':2000}), (15,{'99.8':2000,'99.85':2000}),
                              (20,{'99.8':2000,'99.85':2000,'99.9':2000})):
            self.now = stamp
            self.observe(wall_book(stamp,walls=walls))
        self.assertTrue(all(row['significance']['kind']=='large_wall' for row in self.monitor.snapshot()['rows']))
        self.assertEqual(self.wall_row('99.8')['significance']['pattern']['repricings'], 0)
        self.monitor = DensityMonitor(self.adapter,clock=lambda:self.now)
        for stamp, price, best in ((25,'99.8','100.05'),(30,'100.1','100.15'),(35,'100.2','100.25')):
            self.now = stamp
            self.observe(wall_book(stamp,walls={price:2000},best=best))
        self.assertEqual(self.wall_row('100.2')['significance']['kind'], 'large_wall')
        self.assertEqual(self.wall_row('100.2')['significance']['pattern']['samples'], 1,
                         'a new level beyond the earlier returned ladder cannot be linked')

    def test_significance_history_persistence_and_all_evidence_limits_remain_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'density-state.json'
            monitor = DensityMonitor(self.adapter,clock=lambda:self.now,state_path=path)
            for index in range(175):
                symbol = 'COIN'+str(index)+'USDT'
                for price in ('99.8','99.85','99.9'):
                    self.now += 1
                    monitor.observe('bybit',symbol,wall_book(self.now,walls={price:2000},symbol=symbol))
            self.assertLessEqual(len(monitor.rows), MAX_ROWS)
            self.assertLessEqual(len(monitor.history), HISTORY_LIMIT)
            self.assertLessEqual(len(monitor.evidence), SCAN_LIMIT)
            self.assertTrue(all(len(pair['source_stamps'])<=EVIDENCE_LIMIT for pair in monitor.evidence.values()))
            self.assertTrue(all(len(wall['chain'])<=EVIDENCE_LIMIT for pair in monitor.evidence.values()
                                for side in pair['sides'].values() for wall in side['candidates']))
            monitor.close()
            self.assertLess(path.stat().st_size, 1_000_000, 'new evidence still fits the existing archive bound')
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['version'], 1)
            restarted = DensityMonitor(self.adapter,clock=lambda:self.now,state_path=path)
            patterns = [row for row in restarted.snapshot()['rows']
                        if row['significance']['observed_kind']=='machine_pattern_suspect']
            self.assertTrue(patterns)
            self.assertTrue(all(row['significance']['status']=='inactive' and row['significance']['kind'] is None
                                for row in patterns), 'restart retains observed evidence without live qualification')
            self.assertTrue(all(row['significance']['last_source_ts']==row['last_seen'] for row in patterns))
            self.assertEqual(restarted.evidence, {})
            self.assertTrue(restarted.snapshot()['history'])
            restarted.close()

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

    def test_completed_book_is_observed_next_second_instead_of_next_ten_second_visit(self):
        watched = ['bybit:WATCH'+str(index)+'USDT' for index in range(20)]
        fast_adapter, rotation_adapter = CacheAdapter(lambda:self.now), CacheAdapter(lambda:self.now)
        # Remove only the read-only drain from the control; both runs have the
        # same two-per-second request queue and the same completed source data.
        rotation_peek = rotation_adapter.peek_book_snapshot
        rotation_adapter.peek_book_snapshot = None
        rotation_adapter.book_snapshot = lambda exchange, symbol: (
            rotation_adapter.calls.append((exchange, symbol)) or rotation_peek(exchange, symbol))
        fast = DensityMonitor(fast_adapter, clock=lambda:self.now)
        rotation = DensityMonitor(rotation_adapter, clock=lambda:self.now)
        for monitor in (fast, rotation):
            monitor.request(exchanges='bybit', watch=watched)
            monitor.tick()
        self.now = .2
        for adapter in (fast_adapter, rotation_adapter):
            adapter.complete('bybit', 'WATCH0USDT', self.now)
        observed = {}
        for stamp in range(1, 11):
            self.now = stamp
            for label, monitor in (('drained', fast), ('rotation', rotation)):
                monitor.tick()
                if any(row['symbol']=='WATCH0USDT' for row in monitor.rows.values()):
                    observed.setdefault(label, stamp)
        self.assertEqual(observed, {'drained':1, 'rotation':10})
        self.assertEqual(len(fast_adapter.calls), len(rotation_adapter.calls))
        self.assertEqual(len(fast_adapter.calls), 22, 'completion draining adds no refresh requests')
        row = next(row for row in fast.snapshot()['rows'] if row['symbol']=='WATCH0USDT')
        self.assertEqual(row['last_seen'], .2, 'observing completion does not renew source time')
        self.assertEqual(row['age_seconds'], 0, 'repeated cached reads do not age a density')
        self.assertEqual(fast.snapshot()['coverage']['observe_seconds'], 1)

    def test_http_snapshot_drains_completed_book_without_fetching_or_waiting_for_tick(self):
        adapter = CacheAdapter(lambda:self.now)
        monitor = DensityMonitor(adapter, clock=lambda:self.now)
        monitor.request(exchanges='bybit', watch='bybit:BTCUSDT')
        monitor.tick()
        self.now = .2
        adapter.complete('bybit', 'BTCUSDT', .2)
        calls = list(adapter.calls)
        self.now = .25
        response = monitor.request(exchanges='bybit', watch='bybit:BTCUSDT')
        row = next(row for row in response['rows'] if row['symbol']=='BTCUSDT' and row['side']=='bid')
        self.assertEqual(row['last_seen'], .2)
        self.assertEqual(row['age_seconds'], 0)
        self.assertEqual(adapter.calls, calls, 'HTTP inspection creates no network work')

    def test_real_shared_adapter_completion_is_drained_without_another_admission(self):
        from exchange_data import ExchangeData
        calls, entered, release = [], threading.Event(), threading.Event()
        def forbidden_request(*args):
            raise AssertionError('Integration test must not read the network')
        adapter = ExchangeData(forbidden_request, wall_clock=lambda:self.now, clock=lambda:self.now)
        adapter.fetch_catalog = lambda exchange:dict(exchange=exchange, status='ok', updated=self.now,
            source_ts=self.now, stale=False, error=None, eligible=1,
            rows=[dict(symbol='BTCUSDT', turnover24=100)])
        def fetch(exchange, symbol):
            calls.append((exchange, symbol))
            entered.set()
            if not release.wait(2):
                raise AssertionError('Book worker was not released')
            return book(self.now, exchange=exchange, symbol=symbol)
        adapter.fetch_book = fetch
        monitor = DensityMonitor(adapter, clock=lambda:self.now)
        try:
            monitor.request(exchanges='bybit', watch='bybit:BTCUSDT')
            self.assertEqual(len(adapter._cache['book']), 0, 'peek of a cold watch allocates no entry')
            monitor.tick()
            self.assertTrue(entered.wait(2))
            self.assertTrue(adapter.peek_book_snapshot('bybit','BTCUSDT')['queued'])
            self.now = .2
            release.set()
            deadline = time.monotonic()+2
            while adapter._outstanding and time.monotonic() < deadline:
                time.sleep(.001)
            self.assertEqual(adapter._outstanding, 0)
            self.now = .25
            row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['last_seen'], .2)
            self.assertEqual(row['age_seconds'], 0)
            self.now = 7
            row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['status'], 'active', 'pending TTL revalidation still retains original proof')
            self.assertEqual(calls, [('bybit','BTCUSDT')])
            self.assertEqual(adapter._outstanding, 0, 'peeks never restart the expired cache fetch')
            self.now = 26
            row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['status'], 'unavailable')
            self.assertEqual(row['last_seen'], .2)
        finally:
            release.set()
            monitor.close()
            adapter.close()

    def test_cache_drains_preserve_ttl_proof_and_require_distinct_covered_misses(self):
        adapter = CacheAdapter(lambda:self.now)
        monitor = DensityMonitor(adapter, clock=lambda:self.now)
        monitor.request(exchanges='bybit', watch='bybit:BTCUSDT')
        adapter.complete('bybit', 'BTCUSDT', 0)
        monitor.snapshot()
        self.now = 10
        adapter.complete('bybit', 'BTCUSDT', 10)
        monitor.snapshot()
        self.now = 16
        row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
        self.assertEqual(row['status'], 'active', 'normal TTL refresh keeps original verified proof')
        self.assertEqual(row['age_seconds'], 10)
        self.assertEqual(row['last_seen'], 10)
        self.now = 20
        missing = [['100.02', 10], ['98', 10]]
        adapter.complete('bybit', 'BTCUSDT', 20, bids=missing,
                         coverage=dict(bid_min='98', ask_max='102'))
        for _ in range(10):
            row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
            self.assertEqual(row['status'], 'unobserved', 'ten peeks remain one covered miss')
        self.now = 21
        adapter.complete('bybit', 'BTCUSDT', 21, bids=missing,
                         coverage=dict(bid_min='98', ask_max='102'))
        row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
        self.assertEqual(row['status'], 'missing')
        self.now = 22
        adapter.complete('bybit', 'BTCUSDT', 22)
        row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
        self.assertEqual(row['age_seconds'], 0, 'new episode does not inherit the earlier duration')
        adapter.complete('bybit', 'BTCUSDT', 22, status='error', error='upstream unavailable')
        row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
        self.assertEqual(row['status'], 'unavailable', 'an actual refresh failure invalidates immediately')
        self.now = 50
        adapter.complete('bybit', 'BTCUSDT', 22)
        row = next(row for row in monitor.snapshot()['rows'] if row['id']==self.identity)
        self.assertEqual(row['status'], 'unavailable', 'an old completed sample cannot revive expired proof')
        self.assertEqual(row['last_seen'], 22)

    def test_new_explicit_scope_has_priority_without_resetting_rotation_on_each_poll(self):
        self.monitor.tick()
        self.now = 1
        self.monitor.tick()
        self.monitor.request(watch='bybit:WATCHUSDT')
        self.assertTrue(self.monitor.wake_event.is_set())
        # Rapid wakeups/filter reads do not expand the admission budget.
        for index in range(1, 10):
            self.now = 1 + index/10
            self.monitor.request(watch='bybit:WATCHUSDT')
            self.monitor.tick()
        self.assertEqual(len(self.adapter.calls), 4)
        self.now = 2
        self.monitor.tick()
        self.assertEqual(self.adapter.calls[4], ('bybit', 'WATCHUSDT'))
        for stamp in range(3, 8):
            self.now = stamp
            self.monitor.request(watch='bybit:WATCHUSDT')
            self.monitor.tick()
        visited = set(self.adapter.calls[4:])
        self.assertTrue(set(self.monitor.targets).issubset(visited), 'repeated same scope does not starve other pairs')
        self.assertLessEqual(len(self.monitor.scan_queue), SCAN_LIMIT)

    def test_density_discovery_reuses_thirty_second_universe_and_frees_book_slots(self):
        for stamp in range(30):
            self.now = stamp
            self.monitor.tick()
        self.assertEqual(len(self.adapter.catalog_calls), 5, 'previous loop made 150 catalog cache reads')
        self.assertEqual(len(self.adapter.calls), 60, 'two books per second remains the ceiling')
        self.assertEqual(len(self.monitor.targets), 10)
        self.now = 30
        self.monitor.tick()
        self.assertEqual(len(self.adapter.catalog_calls), 10)
        self.assertEqual(len(self.adapter.calls), 62)

    def test_cold_explicit_books_retry_nonadmission_before_waiting_for_full_rotation(self):
        adapter = Adapter(lambda:self.now)
        original = adapter.book_snapshot
        def read(exchange, symbol):
            if self.now < 3:
                adapter.calls.append((exchange, symbol))
                return dict(status='pending', source_ts=None, updated=None, error=None, queued=False)
            return original(exchange, symbol)
        adapter.book_snapshot = read
        monitor = DensityMonitor(adapter, clock=lambda:self.now)
        watched = ['bybit:WATCH'+str(index)+'USDT' for index in range(20)]
        monitor.request(exchanges='bybit', watch=watched)
        for stamp in range(4):
            self.now = stamp
            monitor.request(exchanges='bybit', watch=watched)
            monitor.tick()
        self.assertEqual(adapter.calls, [('bybit','WATCH0USDT'), ('bybit','WATCH1USDT')]*4)
        row = next(row for row in monitor.snapshot()['rows'] if row['symbol']=='WATCH0USDT')
        self.assertEqual(row['last_seen'], 3)
        self.assertEqual(row['age_seconds'], 0)
        self.now = 4
        monitor.tick()
        self.assertEqual(adapter.calls[-2:], [('bybit','WATCH2USDT'), ('bybit','WATCH3USDT')])

    def test_permanently_refused_priority_rotates_after_bounded_retries_and_deadline(self):
        adapter = Adapter(lambda:self.now)
        def read(exchange, symbol):
            adapter.calls.append((exchange, symbol))
            return dict(status='pending', source_ts=None, updated=None, error=None, queued=False)
        adapter.book_snapshot = read
        monitor = DensityMonitor(adapter, clock=lambda:self.now)
        watched = ['bybit:WATCH'+str(index)+'USDT' for index in range(20)]
        for stamp in range(14):
            self.now = stamp
            monitor.request(exchanges='bybit', watch=watched)
            monitor.tick()
        self.assertEqual(len(adapter.calls), 28)
        self.assertEqual(adapter.calls[:8], [('bybit','WATCH0USDT'), ('bybit','WATCH1USDT')]*4)
        self.assertEqual(adapter.calls[8:10], [('bybit','WATCH2USDT'), ('bybit','WATCH3USDT')])
        self.assertTrue(set(monitor.targets).issubset(set(adapter.calls)), 'busy preferred pairs cannot starve remaining contracts')
        self.assertEqual(monitor.snapshot()['rows'], [], 'queue admission supplies no density proof')
        self.assertLessEqual(len(monitor.priority_retries), SCAN_LIMIT)

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
