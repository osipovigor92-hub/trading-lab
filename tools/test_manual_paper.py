import concurrent.futures
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from manual_paper import ManualPaper, prepare, quote


class Market:
    def __init__(self):
        self.now, self.price, self.stale = 100001., 100., False

    def get(self, kind, symbol='', interval='5'):
        stamp = self.now-40 if self.stale else self.now
        if kind == 'screener':
            return dict(status='ok', updated=stamp, rows=[dict(symbol='BTCUSDT', price=self.price, funding=.0001, next_funding=100000+3600)])
        return dict(status='ok', symbol=symbol, updated=stamp, fetched=stamp, mid=self.price,
                    top={name:[dict(price=self.price*(1+(1 if name == 'ask' else -1)*.0001), quantity=100)] for name in ('bid', 'ask')})


def plan(side=1):
    return dict(symbol='BTCUSDT', side=side, low=99.8, high=100.2, stop=99 if side == 1 else 101,
                target=103 if side == 1 else 97, stamp=100000., interval='5',
                reason='Ручной тест', settings=dict(capital=600, risk_pct=.5, max_notional=100, fee_pct=.055, slippage_pct=.05, min_rr=1.5))


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market = Market()
        self.paper = ManualPaper(self.market, self.tmp.name, clock=lambda:self.market.now)

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, action, uid=None, **kwargs):
        return self.paper.command(dict(id=uid or action+'-test-123', action=action, generation=self.paper.snapshot()['generation'], **kwargs))

    def test_costs_long_short_and_balance_caps(self):
        for side in (1, -1):
            p = prepare(plan(side), self.market, 600, self.market.now)
            self.assertLessEqual(p['risk'], p['budget'])
            self.assertLessEqual(p['entry']*p['quantity'], 100)
            self.assertGreater(p['side']*(p['entry']-100), 0)
            self.assertGreater(p['entry_fee'], 0)
        p = prepare(plan(), self.market, 20, self.market.now)
        self.assertLessEqual(p['entry']*p['quantity']+p['entry_fee'], 20)
        self.assertLessEqual(p['risk'], .1)

    def test_idempotent_atomic_entry_and_close(self):
        c = dict(id='open-command-123', action='open', generation=0, plan=plan())
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.paper.command, [c]*4))
        self.assertTrue(all(r == results[0] for r in results))
        s = self.paper.snapshot()
        self.assertAlmostEqual(s['balance'], 600-s['position']['entry_fee'])
        with self.assertRaises(ValueError):
            self.paper.command(dict(c, plan=plan(-1)))
        with self.assertRaises(ValueError):
            self.command('open', uid='different-open', plan=plan())
        self.market.price = 100.5
        marked = self.paper.snapshot()['position']['mark']
        c = dict(id='close-command-123', action='close', generation=1)
        self.paper.command(c)
        self.paper.command(c)
        s = self.paper.snapshot()
        self.assertIsNone(s['position'])
        self.assertEqual(len(s['trades']), 1)
        self.assertAlmostEqual(s['balance']-600, marked['net'])
        self.assertAlmostEqual(s['trades'][0]['net'], s['trades'][0]['gross']-s['trades'][0]['entry_fee']-s['trades'][0]['exit_fee'])

    def test_pause_does_not_stop_existing_exit(self):
        self.command('open', plan=plan())
        self.command('pause')
        self.market.price = 103.1
        self.market.now += 1
        self.paper.cycle()
        s = self.paper.snapshot()
        self.assertTrue(s['paused'])
        self.assertIsNone(s['position'])
        self.assertEqual(s['trades'][0]['exit_reason'], 'Цель 1')
        with self.assertRaises(ValueError):
            self.command('open', uid='blocked-entry-1', plan=plan())

    def test_observed_stop_short_target_and_time(self):
        for side, price, reason in ((1, 98.9, 'Стоп'), (-1, 96.9, 'Цель 1')):
            self.command('open', uid='open-'+str(side)+'-1234', plan=plan(side))
            self.market.price = price
            self.market.now += 1
            self.paper.cycle()
            self.assertEqual(self.paper.snapshot()['trades'][0]['exit_reason'], reason)
            self.market.price = 100
        self.command('open', uid='time-open-1234', plan=plan())
        for _ in range(180):
            self.market.now += 1
            self.paper.cycle()
        self.assertEqual(self.paper.snapshot()['trades'][0]['exit_reason'], 'Лимит 180 секунд')

    def test_restart_preserves_position_and_never_fabricates_exit(self):
        self.command('open', plan=plan())
        before = self.paper.snapshot()
        other = ManualPaper(self.market, self.tmp.name, clock=lambda:self.market.now)
        after = other.snapshot()
        self.assertEqual(after['balance'], before['balance'])
        self.assertEqual(after['position']['id'], before['position']['id'])
        self.assertIn('Перезапуск', after['position']['blocked'])
        self.market.price = 104
        other.cycle()
        self.assertEqual(other.snapshot()['trades'], [])
        other.command(dict(id='close-restart-123', action='close', generation=after['generation']))
        self.assertIn('observation_gap', other.snapshot()['trades'][0])

    def test_stale_and_gap_do_not_create_profit_or_exit(self):
        self.command('open', plan=plan())
        self.market.stale = True
        self.market.now += 9
        self.paper.cycle()
        s = self.paper.snapshot()
        self.assertIsNone(s['position']['mark'])
        self.assertTrue(s['position']['blocked'])
        self.assertEqual(s['trades'], [])
        with self.assertRaises(ValueError):
            self.command('close')
        self.market.stale = False
        self.command('close', uid='fresh-close-123')
        self.assertIsNotNone(self.paper.snapshot()['trades'][0]['net'])

    def test_funding_gap_is_not_zero_funding(self):
        self.command('open', plan=plan())
        self.market.now = 103601
        self.command('close')
        s = self.paper.snapshot()
        self.assertIsNone(s['trades'][0]['net'])
        self.assertTrue(s['incomplete'])
        with self.assertRaises(ValueError):
            self.command('open', uid='funding-open-123', plan=plan())

    def test_plan_rejection_is_read_only(self):
        invalid = []
        for key, value in [('side', True), ('symbol', '../BTCUSDT'), ('target', 99), ('stop', 101), ('stamp', 90000), ('reason', '')]:
            invalid.append(dict(plan(), **{key:value}))
        for key, value in [('risk_pct', float('nan')), ('max_notional', 1000), ('fee_pct', -1)]:
            p = plan();p['settings'][key] = value;invalid.append(p)
        for p in invalid:
            with self.assertRaises((ValueError, TypeError)):
                self.command('open', plan=p)
        self.assertEqual(self.paper.snapshot()['balance'], 600)
        self.assertIsNone(self.paper.snapshot()['position'])
        self.market.price = 101
        with self.assertRaisesRegex(ValueError, 'зоны'):
            prepare(plan(), self.market, 600, self.market.now)

    def test_impact_depth_and_near_funding_cannot_be_bypassed(self):
        original = self.market.get
        for mode in ('shallow', 'impact', 'crossed', 'future', 'funding'):
            def altered(kind, symbol='', interval='5'):
                value = original(kind, symbol, interval)
                if kind == 'book':
                    if mode == 'shallow':
                        value['top']['ask'][0]['quantity'] = .00001
                    if mode == 'impact':
                        value['top']['ask'] = [dict(price=100.01, quantity=.00001), dict(price=101, quantity=100)]
                    if mode == 'crossed':
                        value['top']['bid'][0]['price'] = 101
                    if mode == 'future':
                        value['updated'] = self.market.now+20
                elif mode == 'funding':
                    value['rows'][0]['next_funding'] = self.market.now+250
                return value
            self.market.get = altered
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                prepare(plan(), self.market, 600, self.market.now)
        self.market.get = original
        self.assertEqual(self.paper.snapshot()['balance'], 600)

    def test_actual_impact_and_short_notional_stay_within_caps(self):
        original = self.market.get
        def sloped(kind, symbol='', interval='5'):
            value = original(kind, symbol, interval)
            if kind == 'book':
                for name, side in (('ask', 1), ('bid', -1)):
                    value['top'][name] = [dict(price=100*(1+side*.0001), quantity=.1), dict(price=100*(1+side*.0004), quantity=100)]
            return value
        self.market.get = sloped
        for side in (1, -1):
            p = prepare(plan(side), self.market, 600, self.market.now)
            self.assertLessEqual(p['entry']*p['quantity'], 100)
            self.assertLessEqual(p['risk'], p['budget'])

    def test_stale_generation_and_extra_fields_do_not_change_ledger(self):
        with self.assertRaises(ValueError):
            self.paper.command(dict(id='stale-command-123', action='pause', generation=-1))
        with self.assertRaises(ValueError):
            self.paper.command(dict(id='extra-command-123', action='open', generation=0, plan=plan(), quantity=10000))
        self.assertEqual(self.paper.snapshot()['generation'], 0)

    def test_no_silent_reset_or_implicit_directory_creation(self):
        missing = Path(self.tmp.name)/'missing'
        engine = ManualPaper(self.market, missing)
        self.assertEqual(engine.snapshot()['status'], 'unavailable')
        self.assertFalse(missing.exists())
        self.paper.path.write_bytes(b'not sqlite')
        broken = ManualPaper(self.market, self.tmp.name)
        self.assertEqual(broken.snapshot()['status'], 'unavailable')
        self.assertEqual(self.paper.path.read_bytes(), b'not sqlite')


if __name__ == '__main__':
    unittest.main()
