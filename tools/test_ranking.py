"""Independent boundary and freshness checks for the four-part candidate rating."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
import ranking
import selection
from test_selection import row, chart, books


class RankingTests(unittest.TestCase):
    def verdict(self, **values):
        r=dict(row(),turnover=200e6,spread=.01)
        c=chart(1000)
        for bar in c['candles'][-5:]:bar['volume']=20
        b=books(1000)
        for snap in b:
            snap.update(spread=.01,buy_impact=0,sell_impact=0)
            snap['bands']['0.001'].update(bid=20000,ask=25000)
        r.update(values)
        return selection.evaluate(r,1000,c,b,selection.parse_filters(),1000)

    def parts(self, verdict):
        return {p['key']:p for p in verdict['rating']['components']}

    def change(self, verdict, **values):
        v=copy.deepcopy(verdict)
        for check in v['checks']:
            if check['key'] in values:check['value']=values[check['key']]
        v['rating']=ranking.evaluate(v,1000)
        return v

    def test_score_is_sum_of_four_visible_integer_contributions(self):
        v=self.verdict()
        self.assertEqual(v['rating']['score'],95)
        self.assertEqual([p['points'] for p in v['rating']['components']],[25,20,25,25])
        self.assertEqual(v['rating']['score'],sum(p['points'] for p in v['rating']['components']))
        self.assertEqual(self.parts(v)['volume']['label'],'Объём растёт')
        self.assertEqual(self.parts(v)['book']['label'],'Стакан подтверждает')
        self.assertEqual(self.parts(v)['liquidity']['label'],'Ликвидность высокая')
        self.assertEqual(self.parts(v)['spread']['label'],'Спред узкий')

    def test_anchors_rounding_and_extremes(self):
        v=self.verdict()
        a=self.change(v,turnover=20e6,rvol=1)
        self.assertEqual(self.parts(a)['liquidity']['points'],13)
        self.assertEqual(self.parts(a)['volume']['points'],13)
        best=self.change(v,turnover=1e300,spread=1e-9,book_spread=1e-9,rvol=1000,depth=1e10)
        self.assertEqual(best['rating']['score'],100)
        weak=self.change(v,turnover=1e-320,spread=1,book_spread=1,rvol=0,depth=0,impact=1)
        self.assertEqual(weak['rating']['score'],0)
        self.assertEqual(self.parts(self.change(v,turnover=2e6))['liquidity']['points'],0)

    def test_monotonic_liquidity_volume_depth_and_worse_execution(self):
        v=self.verdict()
        for key,values in [('turnover',[2e6,10e6,20e6,100e6,200e6,1e9]),
                           ('rvol',[0,.5,1,1.2,2,10]),('depth',[0,1000,5000,10000,20000,1e6])]:
            scores=[self.change(v,**{key:x})['rating']['score'] for x in values]
            self.assertEqual(scores,sorted(scores))
        for key in ('spread','book_spread','impact'):
            scores=[self.change(v,**{key:x})['rating']['score'] for x in (0,.01,.02,.03,.05,.1)]
            self.assertEqual(scores,sorted(scores,reverse=True))

    def test_worst_book_spread_counts_and_volume_uses_quantity(self):
        v=self.verdict()
        worse=self.change(v,book_spread=.04)
        self.assertEqual(self.parts(worse)['spread']['points'],5)
        self.assertEqual(self.parts(worse)['spread']['values']['worst'],.04)
        v=self.verdict();c=chart(1000)
        for bar in c['candles'][-5:]:bar['turnover']*=100
        result=selection.evaluate(dict(row(),turnover=200e6),1000,c,books(1000),selection.parse_filters(),1000)
        self.assertEqual(self.parts(result)['volume']['points'],13,'price/turnover growth alone does not increase base-quantity RVOL')

    def test_missing_invalid_and_partial_inputs_never_get_a_total(self):
        v=self.verdict()
        for key in ranking.CHECKS[:-1]:
            for value in (None,float('nan'),float('inf'),True,-1):
                with self.subTest(key=key,value=value):
                    self.assertIsNone(self.change(v,**{key:value})['rating']['score'])
        incomplete=self.change(v,coverage=False)
        self.assertIsNone(incomplete['rating']['score'])
        self.assertIsNone(self.parts(incomplete)['book']['points'])
        for count in range(5):
            incomplete=copy.deepcopy(v);incomplete['samples']=count
            self.assertIsNone(ranking.evaluate(incomplete,1000)['score'])
        oi=copy.deepcopy(v)
        next(c for c in oi['checks'] if c['key']=='oi').update(state='pending',value=None)
        r=ranking.evaluate(oi,1000)
        self.assertIsNone(r['score']);self.assertIn('Открытый интерес',r['note'])
        self.assertEqual([p['points'] for p in r['components']],[25,20,25,25],'known contributions are distinct from a complete rating')

    def test_every_source_expires_and_future_sources_are_not_verified(self):
        v=self.verdict()
        for key,value in [('ticker_time',954),('chart_time',924),('candle_end',879),('book_time',987),
                          ('ticker_time',1003),('chart_time',1003),('book_time',1003)]:
            incomplete=copy.deepcopy(v);incomplete[key]=value
            self.assertIsNone(ranking.evaluate(incomplete,1000)['score'],key)

    def test_filter_changes_do_not_rescale_rating_or_override_rejection(self):
        v=self.verdict(funding=.001)
        self.assertEqual(v['status'],'rejected')
        self.assertEqual(v['rating']['score'],95)
        before=self.verdict()
        later=copy.deepcopy(before)
        for c in later['checks']:
            if c['key']=='depth':c.update(min=1,state='pass')
        self.assertEqual(ranking.evaluate(later,1000)['score'],before['rating']['score'])


if __name__=='__main__':unittest.main()
