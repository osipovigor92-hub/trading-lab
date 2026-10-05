"""Real selection evidence, freshness, edge transitions and bounded cache integration."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from market_alerts import MarketAlerts
from market_data import MarketData
import selection


def evidence(now=1000, price=100, rvol=1.2, depth=8000, spread=.01, covered=True, symbol='BTCUSDT'):
    quote = dict(symbol=symbol, price=price, turnover=1e8, spread=.01, range24=5,
                 open_interest=1e7, funding=.0001, volume24=1e6)
    chart = dict(status='ok', symbol=symbol, interval='1', updated=now, candle_end=now-20,
                 atr=.4, atr_pct=.4, candles=[dict(volume=10)]*20+[dict(volume=10*rvol)]*5,
                 levels=[dict(side='support',low=99.85,price=99.9,high=99.95)])
    books = [dict(status='ok',symbol=symbol,updated=now-8+i*2,fetched=now-8+i*2,seq=int(now*10)+i,
                  mid=price,spread=spread,buy_impact=.02,sell_impact=.02,
                  bands={'0.001':dict(bid=depth,ask=depth,covered=covered)}) for i in range(5)]
    return dict(tickers=dict(status='ok',updated=now,rows=[quote]),
                charts={symbol:chart},books={symbol:books[-1]},histories={symbol:books})


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.monitor=MarketAlerts()
        self.key=self.monitor.register(selection.parse_filters(),'',1000)

    def tick(self, now=1000, packet=None, **changes):
        self.monitor.update(self.key, **(packet or evidence(now,**changes)), now=now)
        return self.monitor.snapshot(self.key,now)

    def kinds(self, packet):
        return [e['kind'] for e in packet['events']]

    def test_ready_and_level_use_original_sources_and_do_not_repeat(self):
        first=self.tick()
        self.assertCountEqual(self.kinds(first),['ready','near_level'])
        self.assertEqual(first['events'][0]['sources']['book'],1000)
        self.assertEqual(first['events'][0]['sources']['candle'],980)
        second=self.tick(1002)
        self.assertEqual(second['cursor'],first['cursor'])
        self.assertEqual([e['id'] for e in second['events']],[e['id'] for e in first['events']])
        # The event expires; ongoing eligibility remains a condition, not another event.
        later=self.tick(1010)
        self.assertEqual(later['events'],[])
        self.assertEqual(later['rows'][0]['state'],'ready')

    def test_almost_is_one_known_near_miss_not_missing_data(self):
        almost=self.tick(rvol=.9)
        self.assertIn('almost',self.kinds(almost))
        self.assertNotIn('ready',self.kinds(almost))
        for changes in [dict(rvol=.79),dict(rvol=.9,depth=3000),dict(covered=False)]:
            with self.subTest(changes=changes):
                m=MarketAlerts();k=m.register(selection.parse_filters(),'',1000)
                m.update(k,**evidence(**changes),now=1000)
                self.assertNotIn('almost',self.kinds(m.snapshot(k,1000)))
        packet=evidence();packet['tickers']['rows'][0]['open_interest']=None
        result=self.tick(1001,packet)
        self.assertEqual(result['rows'][0]['state'],'unavailable')
        self.assertNotIn('almost',self.kinds(result))

    def test_fresh_failure_cancels_once_and_book_recovery_rearms(self):
        self.tick()
        bad=self.tick(1002,depth=3000)
        self.assertIn('cancelled',self.kinds(bad))
        self.assertIn('book_worse',self.kinds(bad))
        cursor=bad['cursor']
        self.assertEqual(self.tick(1004,depth=3000)['cursor'],cursor)
        recovered=self.tick(1006)
        self.assertNotIn('cancelled',self.kinds(recovered))
        self.assertNotIn('book_worse',self.kinds(recovered))
        again=self.tick(1008,spread=.06)
        self.assertGreater(again['cursor'],recovered['cursor'])
        self.assertEqual(self.kinds(again).count('book_worse'),1)

    def test_stale_error_future_missing_and_old_generation_never_cancel(self):
        initial=self.tick();cursor=initial['cursor']
        for source in ['tickers','charts','books']:
            for mutation in ['old','future','error','refresh_error']:
                packet=evidence(1002)
                value=packet[source] if source=='tickers' else packet[source]['BTCUSDT']
                if mutation=='old':value['updated']=800
                elif mutation=='future':value['updated']=1100
                else:value[mutation]='API unavailable'
                with self.subTest(source=source,mutation=mutation):
                    result=self.tick(1002,packet)
                    self.assertEqual(result['events'],[])
                    self.assertEqual(result['cursor'],cursor)
        packet=evidence(1002);packet['tickers']['rows']=[]
        self.assertEqual(self.tick(1002,packet)['events'],[])
        resumed=self.tick(1004)
        self.assertEqual(resumed['cursor'],cursor)
        self.assertNotIn('cancelled',self.kinds(resumed))

    def test_fresh_book_failure_can_be_reported_without_fabricating_chart_signal(self):
        self.tick();packet=evidence(1002,depth=3000);packet['charts']['BTCUSDT']['refresh_error']='Unavailable'
        result=self.tick(1002,packet)
        self.assertIn('book_worse',self.kinds(result))
        self.assertNotIn('cancelled',self.kinds(result))
        self.assertNotIn('ready',self.kinds(result))

    def test_price_level_hysteresis_and_invalid_levels(self):
        first=self.tick();sequence=first['cursor']
        # A changed pivot inside the same vicinity must not beep every minute.
        packet=evidence(1002,price=100.08);packet['charts']['BTCUSDT']['levels'][0].update(low=99.9,price=99.95,high=100)
        self.assertEqual(self.tick(1002,packet)['cursor'],sequence)
        self.tick(1004,price=100.5)
        self.assertIn('near_level',self.kinds(self.tick(1006)))
        for level in [dict(side='support',low=101,price=100,high=99),dict(side='bad',low=99,price=100,high=101)]:
            packet=evidence(1008);packet['charts']['BTCUSDT']['levels']=[level]
            self.assertNotIn('near_level',self.kinds(self.tick(1008,packet)))

    def test_filter_scope_change_and_restart_have_independent_identity(self):
        first=self.tick()
        filters=selection.parse_filters({'rvol_min':1.5})
        other=self.monitor.register(filters,'',1002)
        self.monitor.update(other,**evidence(1002),now=1002)
        self.assertNotEqual(other,first['scope'])
        self.assertNotIn('cancelled',self.kinds(self.monitor.snapshot(other,1002)))
        self.assertNotEqual(MarketAlerts().epoch,self.monitor.epoch)
        for i in range(10):self.monitor.register(selection.parse_filters({'rvol_min':i}),str(i),1002)
        self.assertEqual(len(self.monitor.scopes),4)
        self.assertEqual(self.monitor.active(1033),[])

    def test_alignment_and_partial_five_samples_cannot_claim_readiness(self):
        for mutate in ['alignment','samples','duplicate','wrong_symbol','wrong_interval']:
            packet=evidence()
            if mutate=='alignment':packet['books']['BTCUSDT']['mid']=102
            elif mutate=='samples':packet['histories']['BTCUSDT'].pop(0)
            elif mutate=='duplicate':packet['histories']['BTCUSDT'][-1]['seq']=packet['histories']['BTCUSDT'][-2]['seq']
            elif mutate=='wrong_symbol':packet['charts']['BTCUSDT']['symbol']='ETHUSDT'
            else:packet['charts']['BTCUSDT']['interval']='5'
            self.assertNotIn('ready',self.kinds(self.tick(packet=packet)),mutate)

    def test_cached_monitor_does_not_schedule_additional_exchange_jobs(self):
        packet=evidence();cache=MarketData(api=lambda *a,**kw:self.fail('Exchange request'))
        try:
            data={('screener','',''):packet['tickers'],('chart','BTCUSDT','1'):packet['charts']['BTCUSDT'],('book','BTCUSDT',''):packet['books']['BTCUSDT']}
            cache.entries.update({k:dict(data=v,error='',future=None,until=999999) for k,v in data.items()})
            cache.book_history=copy.deepcopy(packet['histories'])
            with patch('market_data.time.time',return_value=1000):
                result=cache.alerts_snapshot()
            self.assertIn('ready',self.kinds(result))
            self.assertTrue(all(v['future'] is None for v in cache.entries.values()))
            cache.entries[('book','BTCUSDT','')]['error']='Timeout'
            cache._alerts_tick(1001)
            self.assertEqual(cache.alerts.snapshot(result['scope'],1001)['events'],[])
            with self.assertRaises(ValueError):cache.alerts_snapshot(search='../bad')
        finally:cache.close()

    def test_history_and_tracked_symbols_remain_bounded(self):
        for i in range(100):self.tick(1000+i,depth=8000 if i%2==0 else 3000)
        scope=self.monitor.scopes[self.key]
        self.assertLessEqual(len(scope['events']),50)
        self.assertLessEqual(len(scope['states']),100)
        self.assertTrue(all(e['kind'] in ('ready','almost','cancelled','book_worse','near_level') for e in scope['events']))


if __name__=='__main__':unittest.main()
