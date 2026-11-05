import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from strategy_monitor import StrategyMonitor
from bot_builder import BotBuilder,DEFAULTS
from favorites import Favorites
class Feed:
    def chart_snapshot(self,*args):
        bars=[dict(t=60+i*60,open=99,low=98,high=100,close=99,volume=10) for i in range(22)]
        bars[-1].update(high=102,close=101,volume=20)
        return dict(status='ok',updated=1380,interval='1',candle_end=1380,exchange='bybit',symbol='BTCUSDT',candles=bars)
class Tests(unittest.TestCase):
    def test_persistent_dedup_and_levels(self):
        b=BotBuilder();b.command(dict(revision=0,config=dict(DEFAULTS,strategy='level_break',scope='pair')))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'signals.json';m=StrategyMonitor(Feed(),Favorites(),b,p)
            m.cycle(1382);m.cycle(1383)
            e=m.snapshot()['events'];self.assertEqual(len(e),1);self.assertLess(e[0]['stop'],e[0]['signal_price'])
            n=StrategyMonitor(Feed(),Favorites(),b,p);n.cycle(1384);self.assertEqual(len(n.snapshot()['events']),1)
    def test_short_coverage_reports_trigger(self):
        class ShortFeed(Feed):
            def chart_snapshot(self,*args):
                p=super().chart_snapshot(*args);p['candles'][-1].update(low=96,close=97);return p
        b=BotBuilder();b.command(dict(revision=0,config=dict(DEFAULTS,strategy='level_break',scope='pair')))
        m=StrategyMonitor(ShortFeed(),Favorites(),b);m.cycle(1382)
        self.assertEqual(m.snapshot()['coverage'][0]['status'],'triggered')
        self.assertEqual(m.snapshot()['events'][0]['side'],'short')
    def test_empty_and_stale_sources_are_not_monitoring(self):
        b=BotBuilder();b.command(dict(revision=0,config=dict(DEFAULTS,strategy='level_break')))
        m=StrategyMonitor(Feed(),Favorites(),b);m.cycle(1382)
        self.assertEqual(m.snapshot()['state'],'empty_scope')
        b.command(dict(revision=1,config=dict(DEFAULTS,strategy='level_break',scope='pair')))
        m.cycle(1500);self.assertEqual(m.snapshot()['state'],'waiting_data')
        self.assertEqual(m.snapshot()['ready'],0)
    def test_chart_favorites_are_included(self):
        b=BotBuilder();b.command(dict(revision=0,config=dict(DEFAULTS,strategy='level_break')))
        f=Favorites();f.command(dict(id='test12345',changes=[dict(key='lab-exchange-favorites-v1',value='bybit:BTCUSDT',present=True)]))
        m=StrategyMonitor(Feed(),f,b);m.cycle(1382)
        self.assertEqual(m.snapshot()['monitored'],1)
        self.assertEqual(m.snapshot()['state'],'monitoring')
    def test_corrupt_storage_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'signals.json';p.write_text('broken');m=StrategyMonitor(Feed(),Favorites(),BotBuilder(),p);m.cycle(1382)
            self.assertEqual(p.read_text(),'broken');self.assertEqual(m.snapshot()['status'],'unavailable')
if __name__=='__main__':unittest.main()
