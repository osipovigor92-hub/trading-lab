import copy
import json
from pathlib import Path
import tempfile
import unittest
import engine as e


def row(now=1000,side=1,kind='C',symbol='TESTUSDT'):
    r=dict(symbol=symbol,time=now,price=100.,spread=.01,roundtrip_pct=.2,ready=True,trade_age=.2,ofi5=side*50,
           bands={'0.0005':dict(bid=12000 if side==1 else 6000,ask=6000 if side==1 else 12000,covered=True)},
           flow5=dict(buy=2500 if side==1 else 500,sell=500 if side==1 else 2500,count=15),
           flow15=dict(buy=5000 if side==1 else 1000,sell=1000 if side==1 else 5000,count=30),
           chart=dict(end=now-10,price=100-side*.3,ema20=100,ema50=100-side*.5,atr=1,vwap60=100-side*.5,rvol5=2,side=side,next_funding=now+3600))
    if kind=='D':r['chart'].update(ema50=100.1,vwap60=100+side,rvol5=1)
    return r


def feed(now,rows=None):return dict(updated=now,phase='running',observations=rows if rows is not None else [row(now)])


class EngineTests(unittest.TestCase):
    def opened(self,side=1,kind='C'):
        s=e.initial(1000)
        for now in (1000,1002,1004):e.cycle(s,feed(now,[row(now,side,kind)]),now)
        self.assertIsNotNone(s['models'][kind]['position']);return s
    def test_both_models_both_directions(self):
        for model in ('C','D'):
            for side in (-1,1):
                r=row(side=side,kind=model);v=e.evaluate(model,feed(1000),r,1000)
                self.assertTrue(v['passed']);self.assertEqual(v['side'],side)
                s=self.opened(side,model);self.assertEqual(s['models'][model]['position']['side'],side)
    def test_invalid_stale_coverage_cost_funding(self):
        for patch in ({'time':990},{'time':1003},{'price':float('nan')},{'spread':-1},{'ready':False},{'trade_age':11},{'roundtrip_pct':2},{'chart_error':'bad'}):
            r=row();r.update(patch);self.assertFalse(e.evaluate('C',feed(1000),r,1000)['passed'])
        for change in (lambda r:r['bands']['0.0005'].update(covered=False),lambda r:r['chart'].update(next_funding=1100),lambda r:r['flow15'].update(count=1)):
            r=row();change(r);self.assertFalse(e.evaluate('C',feed(1000),r,1000)['passed'])
    def test_models_are_independent_and_can_hold_simultaneously(self):
        s=e.initial(1000)
        for now in (1000,1002,1004):e.cycle(s,feed(now,[row(now,1,'C','TRENDUSDT'),row(now,-1,'D','RANGEUSDT')]),now)
        self.assertEqual(s['models']['C']['position']['symbol'],'TRENDUSDT')
        self.assertEqual(s['models']['D']['position']['symbol'],'RANGEUSDT')
        self.assertAlmostEqual(s['models']['C']['balance'],599.945)
        self.assertAlmostEqual(s['models']['D']['balance'],599.945)
    def test_duplicate_ticks_cannot_open_and_gap_resets_confirmations(self):
        s=e.initial(1000)
        for _ in range(10):e.cycle(s,feed(1000),1000)
        self.assertIsNone(s['models']['C']['position'])
        e.cycle(s,feed(1008),1008);self.assertEqual(s['models']['C']['confirmations']['TESTUSDT']['count'],1)
    def test_long_short_accounting_and_durable_close(self):
        for side in (-1,1):
            s=self.opened(side);r=row(1005,side);r['price']=100+side*1.2
            records=e.cycle(s,feed(1005,[r]),1005);m=s['models']['C']
            self.assertEqual(len(records),1);t=records[0]
            self.assertGreater(t['net'],0);self.assertAlmostEqual(m['balance'],600+t['net']);self.assertAlmostEqual(t['net'],t['gross']-t['entry_fee']-t['exit_fee'])
            self.assertIsNone(m['position']);self.assertEqual(m['closed'],1)
            self.assertEqual(e.cycle(s,feed(1005,[r]),1005),[])
    def test_roundtrip_cost_and_stop(self):
        s=self.opened();m=s['models']['C'];self.assertLess(m['equity'],m['balance']);self.assertLess(m['position']['mfe_net'],0)
        r=row(1005);r['price']=99.6;t=e.cycle(s,feed(1005,[r]),1005)[0]
        self.assertEqual(t['reason'],'Стоп');self.assertLess(t['net'],-.4)
    def test_timeout_and_cooldown(self):
        s=self.opened();records=[]
        for now in range(1005,1185):records+=e.cycle(s,feed(now),now)
        self.assertEqual(records[0]['reason'],'Лимит времени')
        self.assertLess(records[0]['net'],0)
        for now in range(1185,1200):e.cycle(s,feed(now),now)
        self.assertIsNone(s['models']['C']['position'])
    def test_gaps_do_not_fabricate_exit(self):
        for source,now in (({},1005),(feed(1012),1012),(feed(1005,[]),1005)):
            s=self.opened();balance=s['models']['C']['balance'];self.assertEqual(e.cycle(s,source,now),[])
            m=s['models']['C'];self.assertEqual(m['phase'],'halted');self.assertIsNotNone(m['position']);self.assertEqual(m['balance'],balance)
            self.assertEqual(e.cycle(s,feed(1013),1013),[]);self.assertEqual(m['phase'],'halted')
    def test_restart_and_funding_boundary_preserve_position(self):
        s=self.opened();e.resume(s);self.assertEqual(s['models']['C']['phase'],'halted');self.assertIsNotNone(s['models']['C']['position'])
        s=self.opened();s['models']['C']['position']['funding_time']=1005;e.cycle(s,feed(1005),1005);self.assertEqual(s['models']['C']['phase'],'halted')
    def test_sqlite_close_state_transaction_and_duplicate_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            db=e.connect(Path(d)/'test.sqlite');s=self.opened();e.persist(db,s,[])
            r=row(1005);r['price']=101.2;records=e.cycle(s,feed(1005,[r]),1005);e.persist(db,s,records)
            saved=json.loads(db.execute('SELECT data FROM state').fetchone()[0]);self.assertEqual(saved,s);self.assertIsNone(saved['models']['C']['position'])
            s['models']['C']['balance']=1
            with self.assertRaises(Exception):e.persist(db,s,records)
            self.assertEqual(json.loads(db.execute('SELECT data FROM state').fetchone()[0]),saved)
            self.assertEqual(db.execute('SELECT count(*) FROM trades').fetchone()[0],1)
            report=e.report(db,saved);self.assertEqual(report['models']['C']['trades'][0]['net'],records[0]['net']);self.assertNotIn('features',report['models']['C']['trades'][0])
            e.export_csv(db,Path(d));self.assertIn('TESTUSDT',(Path(d)/'journal-c.csv').read_text());self.assertIn('net',(Path(d)/'journal-d.csv').read_text())
            e.atomic(Path(d)/'report.json',report);self.assertEqual(json.loads((Path(d)/'report.json').read_text()),report)
            db.close()
    def test_risk_limit_is_per_model(self):
        s=e.initial(1000);s['models']['C'].update(equity=581,balance=581)
        e.cycle(s,feed(1000),1000)
        self.assertEqual(s['models']['C']['phase'],'halted');self.assertEqual(s['models']['D']['phase'],'running')

if __name__=='__main__':unittest.main(verbosity=2)
