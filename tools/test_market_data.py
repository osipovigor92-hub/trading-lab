import copy
import importlib.util
import math
from pathlib import Path
import threading
import unittest
import sys

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
