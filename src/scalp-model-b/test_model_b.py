import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
import model_b as m


class Tests(unittest.TestCase):
    def book(self):
        b=m.Book('TESTUSDT')
        now=time.time()
        b.book(dict(type='snapshot',ts=now*1000,data=dict(s='TESTUSDT',u=10,seq=10,
               b=[['99.99','200'],['99.90','200']],a=[['100.01','200'],['100.10','200']])))
        return b
    def test_ofi_price_changes_and_sizes(self):
        old=(99,2,101,3)
        self.assertEqual(m.ofi(old,(99,4,101,3)),2)
        self.assertEqual(m.ofi(old,(99,1,101,3)),-1)
        self.assertEqual(m.ofi(old,(99,2,101,1)),2)
        self.assertEqual(m.ofi(old,(100,5,101,3)),5)
        self.assertEqual(m.ofi(old,(98,5,101,3)),-2)
        self.assertEqual(m.ofi(old,(99,2,100,7)),-7)
    def test_snapshot_delta_delete_reset(self):
        b=self.book()
        b.book(dict(type='delta',ts=time.time()*1000,data=dict(s='TESTUSDT',u=15,seq=15,
                    b=[['99.99','0'],['99.95','300']],a=[])))
        self.assertNotIn(99.99,b.b)
        self.assertEqual(b.b[99.95],300)
        b.book(dict(type='snapshot',ts=time.time()*1000,data=dict(s='TESTUSDT',u=1,seq=1,
                    b=[['98','10']],a=[['102','20']])))
        self.assertEqual(b.b,{98.:10.})
        self.assertEqual(len(b.ofis),0)
    def test_bad_books(self):
        b=self.book()
        with self.assertRaises(ValueError):
            b.book(dict(type='delta',ts=time.time()*1000,data=dict(s='TESTUSDT',u=9,seq=9,b=[],a=[])))
        with self.assertRaises(ValueError):
            b.book(dict(type='delta',ts=time.time()*1000,data=dict(s='TESTUSDT',u=11,seq=11,b=[['101','1']],a=[])))
    def test_walk_and_insufficient_depth(self):
        self.assertAlmostEqual(m.walk([(100,1),(101,2)],2),100.5)
        self.assertIsNone(m.walk([(100,1)],2))
    def test_trade_dedup_side_and_block(self):
        b=self.book()
        t=time.time()*1000
        msg=dict(data=[dict(s='TESTUSDT',i='x',T=t,S='Buy',p='100',v='2'),
                       dict(s='TESTUSDT',i='y',T=t,S='Sell',p='100',v='1'),
                       dict(s='TESTUSDT',i='z',T=t,S='Buy',p='100',v='20',BT=True)])
        b.trades(msg)
        b.trades(msg)
        metrics=b.metrics(time.time()+.01)
        self.assertEqual(metrics['flow5']['buy'],200)
        self.assertEqual(metrics['flow5']['sell'],100)
        self.assertEqual(metrics['flow5']['count'],2)
    def test_roundtrip_and_long_short_accounting(self):
        for side in (1,-1):
            b=self.book()
            entry=b.execution(1,side)
            p=dict(symbol='TESTUSDT',side=side,quantity=1,entry=entry,
                   entry_fee=entry*m.C['fee'],opened=time.time(),features={})
            state=m.initial()
            state.update(position=p,balance=600-p['entry_fee'],fees=p['entry_fee'])
            price,gross,fee,net=m.mark_position(p,b)
            self.assertLess(net,0)
            m.close(state,b,time.time(),'TEST')
            self.assertAlmostEqual(state['balance'],600+net)
            self.assertAlmostEqual(state['fees'],p['entry_fee']+fee)
            self.assertEqual(len(state['trades']),1)
            self.assertIsNone(state['position'])
    def test_favorable_move(self):
        for side in (1,-1):
            b=self.book()
            p=dict(side=side,quantity=1,entry=b.execution(1,side),entry_fee=.055)
            b.b={k+side:v for k,v in b.b.items()}
            b.a={k+side:v for k,v in b.a.items()}
            self.assertGreater(m.mark_position(p,b)[3],0)
    def test_closed_candles_and_gap(self):
        end=int(time.time()//60)*60
        bars=[]
        for i in range(125):
            ts=end-(124-i)*60
            price=100+i*.01
            bars.append([str(ts*1000),str(price),str(price+.1),str(price-.1),
                         str(price+.02),'10',str((price+.02)*10)])
        chart=m.chart_from_bars(list(reversed(bars)),end+10)
        self.assertEqual(chart['end'],end)
        self.assertGreater(chart['atr'],0)
        broken=bars[:]
        broken[50]=bars[49]
        with self.assertRaises(ValueError):
            m.chart_from_bars(broken,end+10)
    def test_signal_and_cost_funding_filters(self):
        now=time.time()
        b=self.book()
        b.armed=dict(time=now-20,side=1)
        b.prices.extend((now-i,100.11) for i in range(12,1,-1))
        features=dict(ready=True,price=100.2,spread=.01,
                      bands={'0.001':dict(bid=10000,ask=10000),
                             '0.0005':dict(imbalance=.3)},ofi5=10,
                      flow5=dict(ratio=.6),flow15=dict(ratio=.5,buy=2500,sell=500,count=30),
                      roundtrip_pct=.23)
        chart=dict(end=now-40,side=1,atr=1,ema20=100,atr_pct=1,rvol5=2,next_funding=now+3600)
        self.assertEqual(m.signal(b,features,chart,now)[0],1)
        chart['next_funding']=now+20
        self.assertEqual(m.signal(b,features,chart,now)[0],0)
        chart['next_funding']=now+3600
        features['roundtrip_pct']=5
        self.assertEqual(m.signal(b,features,chart,now)[0],0)
    def test_open_position_gap_does_not_close(self):
        b=self.book()
        state=m.initial()
        state['position']=dict(symbol='TESTUSDT')
        state['market_time']=time.time()-20
        before=copy.deepcopy(state)
        with self.assertRaises(ValueError):
            m.cycle(state,{'TESTUSDT':b},None,time.time())
        self.assertEqual(state,before)
    def test_atomic_state(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'state.json'
            state=m.initial()
            m.atomic(path,state)
            self.assertEqual(json.loads(path.read_text()),state)
    def test_cycle_open_close_and_cooldown(self):
        from unittest.mock import patch
        now=time.time()
        b=self.book()
        b.started=now-80
        b.trade_ts=now
        chart=dict(end=now-40,side=1,atr=1,ema20=100,atr_pct=1,rvol5=2,next_funding=now+3600)
        class Charts:
            def get(self,symbol):
                return chart,''
        state=m.initial()
        with patch.object(m,'signal',return_value=(1,[])):
            m.cycle(state,{'TESTUSDT':b},Charts(),now)
            self.assertIsNotNone(state['position'])
            self.assertLess(state['equity'],state['balance'])
            self.assertAlmostEqual(state['position']['quantity']*state['position']['entry'],100,places=6)
            b.b={k+2:v for k,v in b.b.items()}
            b.a={k+2:v for k,v in b.a.items()}
            b.ts=now+1
            m.cycle(state,{'TESTUSDT':b},Charts(),now+1)
            self.assertIsNone(state['position'])
            self.assertEqual(len(state['trades']),1)
            self.assertGreater(state['trades'][0]['net'],0)
            self.assertGreater(state['cooldown_until'],now+1)
    def test_missing_exit_liquidity(self):
        b=self.book()
        p=dict(side=1,quantity=1000,entry=100,entry_fee=.1)
        with self.assertRaises(ValueError):
            m.mark_position(p,b)

if __name__=='__main__':
    unittest.main()
