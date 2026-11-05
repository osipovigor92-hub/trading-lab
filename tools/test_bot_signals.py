import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from bot_signals import level_break

class SignalTests(unittest.TestCase):
    def setUp(self):
        self.now=1322
        self.packet=dict(status='ok',updated=1320,interval='1',candle_end=1320,
                         exchange='bybit',symbol='BTCUSDT',candles=[
            dict(t=60+i*60,open=99,low=98,high=102,close=99,volume=10) for i in range(21)])
        self.packet['candles'][-1].update(close=101,volume=20)
        self.level=dict(exchange='bybit',symbol='BTCUSDT',price=100,confirmed_at=1200)
    def run_signal(self):return level_break(self.packet,self.level,now=self.now)
    def test_long_and_stable_key(self):
        a=self.run_signal();self.assertEqual(a['side'],'long');self.assertEqual(a['event_key'],self.run_signal()['event_key'])
    def test_short(self):
        self.packet['candles'][-2]['close']=101;self.packet['candles'][-1]['close']=99
        self.assertEqual(self.run_signal()['side'],'short')
    def test_reject_stale_future_and_gap(self):
        for updated in (1200,1400):
            self.packet['updated']=updated;self.assertEqual(self.run_signal()['status'],'blocked')
        self.packet['updated']=1320;self.packet['candles'][-2]['t']-=60
        self.assertEqual(self.run_signal()['status'],'blocked')
    def test_no_lookahead(self):
        self.level['confirmed_at']=1320;self.assertEqual(self.run_signal()['status'],'blocked')
    def test_wick_is_not_cross(self):
        self.packet['candles'][-1]['close']=99;self.assertEqual(self.run_signal()['status'],'waiting')
    def test_volume_excludes_signal_bar(self):
        self.assertEqual(self.run_signal()['volume_x'],2)
        self.packet['candles'][-1]['volume']=14;self.assertEqual(self.run_signal()['status'],'waiting')
    def test_wrong_exchange(self):
        self.level['exchange']='binance';self.assertEqual(self.run_signal()['status'],'blocked')
    def test_forming_bar_not_used(self):
        self.packet['current_candle']=dict(close=10000)
        self.assertEqual(self.run_signal()['signal_price'],101)
if __name__=='__main__':unittest.main()
