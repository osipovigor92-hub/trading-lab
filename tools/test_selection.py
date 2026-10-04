"""Selection safety, units, freshness and bounded shared warmup; no exchange calls."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PANEL = Path(__file__).resolve().parents[1]/'src/trading-panel'
sys.path.insert(0, str(PANEL))
import market_data
import selection


def row(symbol='BTCUSDT'):
    return dict(symbol=symbol, turnover=20e6, spread=.03, range24=1,
                open_interest=1e6, funding=-.0005, volume24=1000,
                funding_interval_hours=4)


def chart(now, symbol='BTCUSDT'):
    return dict(symbol=symbol, interval='1', status='ok', updated=now,
                candle_end=now-30, atr_pct=.08,
                candles=[dict(volume=10, turnover=1000+i*100) for i in range(25)])


def book(now, seq=1, symbol='BTCUSDT'):
    return dict(symbol=symbol, status='ok', updated=now, seq=seq, spread=.03,
                buy_impact=.05, sell_impact=.01,
                bands={'0.001':dict(bid=5000, ask=6000, covered=True)})


def books(now):
    return [book(now-8+i*2, i+1) for i in range(5)]


class SelectionTests(unittest.TestCase):
    def evaluate(self, r=None, c=None, b=None, now=1000, stamp=1000, filters=None):
        return selection.evaluate(r or row(), stamp, chart(now) if c is None else c,
                                  books(now) if b is None else b,
                                  selection.parse_filters(filters), now)

    def test_boundaries_units_and_contract_funding_interval(self):
        result=self.evaluate()
        self.assertEqual(result['status'], 'passed')
        checks={c['key']:c for c in result['checks']}
        self.assertEqual(checks['funding']['value'], .05)
        self.assertEqual(checks['oi']['value'], 1e6)
        self.assertEqual(result['funding_interval_hours'], 4)
        for key,value in [('turnover',20e6-1),('spread',.03001),('range24',.99),
                          ('open_interest',999999),('funding',.000501),('volume24',0)]:
            with self.subTest(key=key):
                self.assertEqual(self.evaluate(dict(row(), **{key:value}))['status'], 'rejected')

    def test_base_volume_not_price_growth_and_missing_oi_not_zero(self):
        c=chart(1000)
        self.assertEqual(self.evaluate(c=c,filters={'rvol_min':1.1})['status'], 'rejected')
        for bar in c['candles'][-5:]:bar['volume']=12
        self.assertEqual(self.evaluate(c=c,filters={'rvol_min':1.1})['status'], 'passed')
        r=row();r['open_interest']=None
        result=self.evaluate(r=r)
        self.assertEqual(result['status'], 'pending')
        self.assertEqual(next(c for c in result['checks'] if c['key']=='oi')['state'], 'pending')

    def test_stale_future_wrong_timeframe_and_empty_volumes_cannot_pass(self):
        for stamp in (954,1003):self.assertEqual(self.evaluate(stamp=stamp)['status'],'pending')
        for changes in ({'updated':924},{'updated':1003},{'candle_end':879},
                        {'symbol':'ETHUSDT'},{'interval':'5'},
                        {'candles':[dict(volume=0)]*25}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(c=dict(chart(1000),**changes))['status'],'pending')

    def test_five_distinct_spaced_fresh_snapshots_and_worst_book(self):
        for count in range(5):self.assertEqual(self.evaluate(b=books(1000)[:count])['status'],'pending')
        for change in ('duplicate','time','stale','missing_seq','nan_spread'):
            b=books(1000)
            if change=='duplicate':b[-1]['seq']=b[-2]['seq']
            if change=='time':b[-1]['updated']=b[-2]['updated']+1
            if change=='stale':b=[dict(x,updated=x['updated']-13) for x in b]
            if change=='missing_seq':b[0]['seq']=None
            if change=='nan_spread':b[0]['spread']=float('nan')
            self.assertEqual(self.evaluate(b=b)['status'],'pending',change)
        for change in ('depth','spread','impact','coverage'):
            b=books(1000)
            if change=='depth':b[2]['bands']['0.001']['bid']=4999
            if change=='spread':b[2]['spread']=.031
            if change=='impact':b[2]['buy_impact']=.051
            if change=='coverage':b[2]['bands']['0.001']['covered']=False
            self.assertEqual(self.evaluate(b=b)['status'],'rejected',change)
        b=books(1000);b[-1]['sell_impact']=None
        self.assertEqual(self.evaluate(b=b)['status'],'pending')

    def test_filter_validation(self):
        for filters in ({'unknown':0},{'oi_min':True},{'spread_max':'nan'},
                        {'atr_min':-1},{'depth_min':'inf'},{'turnover_min':''},
                        {'range_min':31},{'atr_max':.01},{'spread_max':11}):
            with self.assertRaises(ValueError,msg=str(filters)):selection.parse_filters(filters)
        self.assertEqual(selection.parse_filters({'oi_min':'0'})['oi_min'],0)

    def test_price_impact_uses_walked_levels_and_insufficient_depth_waits(self):
        # Mid=100, quantity=1 coin; a thin best ask forces a second price level.
        raw=dict(s='BTCUSDT',ts=1e6,seq=5,
                 b=[['99.99','.5'],['99.8','1']],a=[['100.01','.2'],['100.2','1']])
        result=market_data.orderbook_analysis('BTCUSDT',raw,1000)
        self.assertAlmostEqual(result['buy_impact'],((100.01*.2+100.2*.8)/100.01-1)*100)
        self.assertGreater(result['sell_impact'],.05)
        raw['a']=[['100.01','.2']]
        self.assertIsNone(market_data.orderbook_analysis('BTCUSDT',raw,1000)['buy_impact'])

    def test_shortlist_and_history_are_bounded_without_scheduling_all_pairs(self):
        now=time.time();cache=market_data.MarketData(api=lambda *a,**kw:None)
        tickers=dict(status='ok',updated=now,rows=[row('COIN'+str(i)+'USDT') for i in range(100)])
        try:
            with patch.object(cache,'get',return_value=tickers) as get:
                result=cache.selection_snapshot(now=now)
                get.assert_called_once_with('screener')
            self.assertEqual(len(result['analyzing']),8)
            self.assertEqual(result['counts']['pending'],100)
            with patch.object(cache,'get',return_value=tickers):
                self.assertEqual(cache.selection_snapshot(search='COIN99',now=now)['analyzing'],['COIN99USDT'])
                self.assertEqual(cache.selection_snapshot(search='MISSING',now=now)['analyzing'],[])
                for bad in ('../passwd','btcusdt','BTC&x=1'):
                    with self.assertRaises(ValueError):cache.selection_snapshot(search=bad,now=now)
            for i in range(30):
                symbol='COIN'+str(i)+'USDT'
                for j in range(8):cache._record_book(symbol,book(now-14+j*2,j+1,symbol),now)
            self.assertEqual(len(cache.book_history),24)
            self.assertTrue(all(len(h)==5 for h in cache.book_history.values()))
            symbol='COIN29USDT';latest=cache.book_history[symbol][-1]
            cache._record_book(symbol,copy.deepcopy(latest),now)
            self.assertEqual(len(cache.book_history[symbol]),5)
            cache._record_book(symbol,dict(latest,seq=1,updated=now+1),now+1)
            self.assertEqual(len(cache.book_history[symbol]),1,'a backwards exchange sequence restarts collection')
        finally:cache.close()

    def test_http_rejects_bad_filters_and_returns_read_only_snapshot(self):
        spec=importlib.util.spec_from_file_location('selection_panel',PANEL/'server.py')
        panel=importlib.util.module_from_spec(spec)
        with patch.object(market_data.MarketData,'start_background'):
            spec.loader.exec_module(panel)
        def request(path):
            output=[]
            handler=SimpleNamespace(path=path,headers={'Host':'127.0.0.1:8787'},
                send=lambda code,data,kind:output.append((code,json.loads(data))),
                api_error=lambda code,message:output.append((code,{'error':message})))
            panel.Handler.do_GET(handler)
            return output[0]
        with patch.object(panel.MARKET,'selection_snapshot',return_value={'status':'pending'}) as snapshot:
            self.assertEqual(request('/api/market-selection?spread_max=.01&search=BTC')[0],200)
            self.assertEqual(snapshot.call_args.args[0]['spread_max'],.01)
            self.assertEqual(snapshot.call_args.args[1],'BTC')
            snapshot.reset_mock()
            for query in ('oi_min=nan','x=1','rvol_min=','oi_min=1&oi_min=2','atr_min=5&atr_max=1'):
                self.assertEqual(request('/api/market-selection?'+query)[0],400)
            snapshot.assert_not_called()
        panel.MARKET.close()

    def test_warmup_respects_two_outstanding_calls_and_harvests_all_watched_books(self):
        release=threading.Event();now=time.time()
        def api(*args,**kw):
            release.wait(2)
            raise ValueError('Offline fixture')
        cache=market_data.MarketData(api=api,clock=lambda:0)
        try:
            cache.selection_until=100
            cache.selection_watch=['COIN'+str(i)+'USDT' for i in range(8)]
            for i in range(8):cache._selection_tick()
            self.assertLessEqual(sum(v['future'] is not None for v in cache.entries.values()),2)
            self.assertLessEqual(len(cache.entries),24)
            release.set()
            for item in cache.entries.values():
                if item['future']:
                    try:item['future'].result(timeout=2)
                    except ValueError:pass
            for symbol in cache.selection_watch:
                cache.entries[('book',symbol,'')]['data']=book(now,1,symbol)
            with patch.object(cache,'get',return_value={}),patch.object(market_data.time,'time',return_value=now):
                cache._selection_tick()
            self.assertEqual(len(cache.book_history),8,'one tick records all completed books')
            self.assertTrue(all(len(h)==1 for h in cache.book_history.values()))
        finally:release.set();cache.close()


if __name__=='__main__':unittest.main()
