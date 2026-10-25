import tempfile
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from whales import WhaleMonitor,trades


def tape(now=1000, identity='exec1',size='1000'):
    return dict(category='linear',list=[dict(execId=identity,symbol='BTCUSDT',price='100',size=size,side='Buy',time=str(now*1000))])


class WhaleTests(unittest.TestCase):
    def monitor(self, path=None):
        return WhaleMonitor(None,None,clock=lambda:1000,state_path=path)

    def test_trade_threshold_identity_time_and_restart_dedup(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.json';monitor=self.monitor(path)
            monitor.observe_trades('BTCUSDT',tape(),1000,1000)
            monitor.observe_trades('BTCUSDT',tape(),1000,1000)
            self.assertEqual(len(monitor.events),1)
            self.assertEqual(monitor.events[0]['notional'],100000)
            self.assertEqual(monitor.events[0]['execution_id'],'exec1')
            monitor=self.monitor(path);monitor.observe_trades('BTCUSDT',tape(),1000,1000)
            self.assertEqual(monitor.events,[])
            monitor.observe_trades('BTCUSDT',tape(1001,'exec2'),1001,1001)
            self.assertEqual(len(monitor.events),1)
            monitor.observe_trades('BTCUSDT',tape(1002,'small','1'),1002,1002)
            self.assertEqual(len(monitor.events),1)

    def test_stale_future_wrong_symbol_nan_and_no_partial_events(self):
        for change in ({'symbol':'ETHUSDT'},{'price':'nan'},{'size':'-1'},{'time':'999999999'},{'side':'Other'}):
            packet=tape();packet['list'].append(dict(packet['list'][0],**change))
            monitor=self.monitor()
            with self.subTest(change=change),self.assertRaises(ValueError):monitor.observe_trades('BTCUSDT',packet,1000,1000)
            self.assertEqual(monitor.events,[])
        monitor=self.monitor();monitor.observe_trades('BTCUSDT',tape(900),1000,1000)
        self.assertEqual(monitor.events,[])

    def test_wall_requires_age_and_covered_missing_not_outage(self):
        m=self.monitor();row=dict(id='wall',status='active',notional=2000,size_multiple=12,baseline_notional=2000/12,baseline_levels=20,last_seen=1000,age_seconds=0,distance_pct=.1,side='bid',symbol='BTCUSDT',exchange='bybit',price=100)
        m.observe_walls(dict(rows=[row]),1000);self.assertFalse(m.events)
        row['age_seconds']=10;m.observe_walls(dict(rows=[row]),1000);self.assertEqual(len(m.events),1)
        row['status']='unobserved';m.observe_walls(dict(rows=[row]),1001);self.assertEqual(len(m.events),1)
        row['status']='active';m.observe_walls(dict(rows=[row]),1002);self.assertEqual(len(m.events),1)
        row['status']='missing';m.observe_walls(dict(rows=[row]),1003);self.assertEqual(len(m.events),1)
        history=[dict(density_id='wall',status='missing',observed_at=1003)]
        m.observe_walls(dict(rows=[row],history=history),1003);self.assertEqual(m.events[0]['kind'],'wall_missing')
        row.update(status='active',last_seen=1004);m.observe_walls(dict(rows=[row]),1004);self.assertEqual(len(m.events),3)

    def test_tick_uses_bounded_pinned_targets_and_reports_errors(self):
        calls=[]
        market=SimpleNamespace(selection_lock=threading.Lock(),selection_watch=['ETHUSDT']*10,
                               alerts=SimpleNamespace(latest=lambda:dict(watch='BTCUSDT')))
        def api(*args,**kwargs):calls.append(kwargs);raise OSError('offline')
        m=WhaleMonitor(market,SimpleNamespace(snapshot=lambda:dict(rows=[])),api=api,clock=lambda:1000)
        m.tick();self.assertEqual(calls[0]['symbol'],'BTCUSDT');self.assertEqual(m.targets,['BTCUSDT','ETHUSDT'])
        self.assertFalse(m.snapshot()['coverage']['BTCUSDT']['fresh'])

    def test_corrupt_state_is_visible_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'state.json';path.write_text('[]');m=self.monitor(path)
            self.assertTrue(m.storage_error);m.observe_trades('BTCUSDT',tape(),1000,1000)
            self.assertEqual(path.read_text(),'[]')
