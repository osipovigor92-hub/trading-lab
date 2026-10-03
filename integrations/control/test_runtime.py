import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import runtime
from runtime import Runtime, blocked_cycle
from launcher import load, patch_a

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src/trading-scanner'))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patch = patch.object(runtime, 'COMMANDS', self.folder); self.patch.start()
        self.s = dict(config=dict(capital=600, max_loss=18), phase='running', reason='',
                      equity=598, balance=598, position=None, fees=1, trades=[{'net': -2}],
                      cooldown_until=90)
        self.ctl = Runtime('B', 12)
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def request(self, action, generation=1, model='B'):
        (self.folder / (model+'.json')).write_text(json.dumps(dict(action=action, generation=generation)))
    def test_pause_preserves_balance_journal_and_cooldown(self):
        old = copy.deepcopy(self.s); self.request('stop')
        calls=[]
        blocked_cycle(self.ctl, self.s, lambda: calls.append(self.s['cooldown_until']), 100)
        self.assertGreater(calls[0], 100)
        self.assertEqual(self.s['phase'], 'paused')
        for key in ('equity', 'balance', 'trades', 'fees', 'cooldown_until'):
            self.assertEqual(old[key], self.s[key])
    def test_drain_does_not_fabricate_exit_and_native_close_is_kept(self):
        self.s['position'] = dict(symbol='TEST', entry=10)
        self.request('stop')
        blocked_cycle(self.ctl, self.s, lambda: None, 100)
        self.assertEqual(self.s['phase'], 'draining'); self.assertIsNotNone(self.s['position'])
        def close():
            self.s.update(position=None, balance=597.8, equity=597.8, cooldown_until=240)
            self.s['trades'].append(dict(net=-.2))
        blocked_cycle(self.ctl, self.s, close, 120)
        self.assertEqual(self.s['phase'], 'paused'); self.assertEqual(self.s['cooldown_until'], 240)
        self.assertEqual(len(self.s['trades']), 2)
    def test_restart_waits_for_close_then_warms_and_clears_entry_cache(self):
        self.s['position'] = {'symbol':'TEST'}; self.request('restart')
        self.assertFalse(self.ctl.entries(self.s, now=100))
        self.s['position']=None; cache={'armed': True}
        self.assertFalse(self.ctl.entries(self.s, cache, now=110)); self.assertEqual(cache, {})
        self.assertTrue(self.ctl.entries(self.s, now=122))
        self.assertEqual(self.s['balance'], 598)
    def test_corrupt_control_fails_closed_and_limits_survive_restart(self):
        (self.folder/'B.json').write_text('broken')
        self.assertFalse(self.ctl.entries(self.s, now=100))
        self.s.update(equity=581, phase='halted'); self.request('restart')
        self.assertFalse(self.ctl.entries(self.s, now=100))
        self.assertEqual(self.s['phase'],'halted'); self.assertIn('Лимит',self.s['control']['error'])
    def test_start_cannot_remove_halt_and_restart_cannot_remove_position(self):
        self.s.update(phase='halted',position={'symbol':'TEST'}); self.request('restart')
        self.assertFalse(self.ctl.entries(self.s, now=100)); self.assertIsNotNone(self.s['position'])
        self.s['position']=None; self.request('start',2)
        self.assertFalse(self.ctl.entries(self.s,now=100)); self.assertEqual(self.s['phase'],'halted')
    def test_unknown_a_source_refused(self):
        with self.assertRaises((RuntimeError, StopIteration)):
            patch_a('def main(): pass')
    def test_imported_models_wrap_without_changing_original_source(self):
        for kind, file in [('A','src/scalp-paper/paper.py'),('B','src/scalp-model-b/model_b.py'),('CD','integrations/research/engine.py')]:
            p=REPO/file; before=p.read_bytes(); model=load(kind,p)
            self.assertTrue(callable(model['main'])); self.assertEqual(before,p.read_bytes())
    def test_cd_pause_is_independent_and_b_feed_can_be_paused(self):
        cd=load('CD',REPO/'integrations/research/engine.py'); s=cd['initial'](100)
        self.request('stop',model='C'); self.request('start',model='D')
        cd['cycle'](s,dict(phase='paused',feed_phase='running',updated=100,observations=[]),100)
        self.assertEqual(s['models']['C']['phase'],'paused')
        cd['cycle'](s,dict(phase='paused',feed_phase='running',updated=115,observations=[]),115)
        self.assertEqual(s['models']['D']['phase'],'running')
        self.assertEqual(s['models']['C']['balance'],600)

    def test_native_b_exit_and_market_feed_continue_after_stop(self):
        bmod=load('B',REPO/'src/scalp-model-b/model_b.py');now=time.time()
        book=bmod['Book']('TESTUSDT')
        book.book(dict(type='snapshot',ts=now*1000,data=dict(s='TESTUSDT',u=10,seq=10,
            b=[['99.99','200'],['99.9','200']],a=[['100.01','200'],['100.1','200']])))
        book.started=now-80;book.trade_ts=now
        chart=dict(end=now-40,side=1,atr=1,ema20=100,atr_pct=1,rvol5=2,next_funding=now+3600)
        class Charts:
            def get(self,symbol):return chart,''
        s=bmod['initial']()
        with patch.dict(bmod,signal=lambda *args:(1,[])):
            bmod['cycle'](s,{'TESTUSDT':book},Charts(),now)
            self.assertIsNotNone(s['position'])
            self.request('stop');book.ts=now+1
            bmod['cycle'](s,{'TESTUSDT':book},Charts(),now+1)
            self.assertEqual(s['phase'],'draining');self.assertIsNotNone(s['position'])
            book.b={k+2:v for k,v in book.b.items()};book.a={k+2:v for k,v in book.a.items()};book.ts=now+2
            bmod['cycle'](s,{'TESTUSDT':book},Charts(),now+2)
            self.assertEqual(s['phase'],'paused');self.assertIsNone(s['position'])
            self.assertEqual(len(s['trades']),1);self.assertGreater(s['trades'][0]['net'],0)
            self.assertEqual(s['feed_phase'],'running')
        bmod['STATE']=self.folder/'state.json'
        s['updated']=s['feed_updated'];bmod['atomic'](bmod['STATE'],s)
        self.assertEqual(s['feed_phase'],'running')
        s.update(phase='waiting',updated=now+3,reason='Feed timeout')
        bmod['atomic'](bmod['STATE'],s)
        self.assertEqual(s['feed_phase'],'waiting','a fresh report must not masquerade as a fresh feed')

    def test_native_cd_closes_draining_position_and_emits_original_journal(self):
        cd=load('CD',REPO/'integrations/research/engine.py');s=cd['initial'](100)
        model=s['models']['C'];entry=100.060005;quantity=100/entry
        model.update(phase='running',last_tick=100,balance=599.945,
            position=dict(id='native',symbol='TESTUSDT',side=1,entry=entry,quantity=quantity,
                entry_fee=.055,opened=100,quote_time=100,funding_time=1000,mfe_net=0,mae_net=0))
        self.request('stop',model='C')
        quote=dict(symbol='TESTUSDT',price=102,spread=.02,time=101,
            bands={'0.0005':dict(bid=5000,ask=5000,covered=True)})
        records=cd['cycle'](s,dict(phase='paused',feed_phase='running',updated=101,observations=[quote]),101)
        self.assertEqual(len(records),1);self.assertGreater(records[0]['net'],0)
        self.assertEqual(model['closed'],1);self.assertIsNone(model['position'])
        self.assertEqual(model['phase'],'paused');self.assertGreater(model['cooldown_until'],101)


if __name__=='__main__': unittest.main()
