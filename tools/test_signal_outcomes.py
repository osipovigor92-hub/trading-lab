import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from bot_signals import signal_outcome
class Outcomes(unittest.TestCase):
    def setUp(self):
        self.event=dict(exchange='bybit',symbol='BTCUSDT',side='long',closed_at=120,expires=180,stop=99,target=102)
        self.packet=dict(exchange='bybit',symbol='BTCUSDT',status='ok',updated=182,interval='1',candles=[dict(t=120,low=100,high=101)])
    def result(self):return signal_outcome(self.event,self.packet,182)
    def test_no_touch_expiry(self):self.assertEqual(self.result()['outcome'],'expired')
    def test_stop_target_and_ambiguity(self):
        for low,high,outcome in [(98,101,'stop'),(100,103,'target'),(98,103,'ambiguous')]:
            self.packet['candles']=[dict(t=120,low=low,high=high)]
            self.assertEqual(self.result()['outcome'],outcome)
    def test_missing_history_is_unknown(self):
        self.packet['candles']=[];self.assertNotIn('outcome',self.result())
    def test_signal_candle_does_not_count(self):
        self.packet['candles'].insert(0,dict(t=60,low=1,high=200))
        self.assertEqual(self.result()['outcome'],'expired')
    def test_stale_wrong_source_and_forming_rejected(self):
        for patch in [dict(updated=1),dict(symbol='ETHUSDT'),dict(stale=True),dict(updated=200)]:
            self.assertNotIn('outcome',signal_outcome(self.event,dict(self.packet,**patch),182))
        self.assertNotIn('outcome',signal_outcome(self.event,dict(self.packet,updated=150),150))
    def test_short(self):
        self.event.update(side='short',stop=102,target=99)
        self.packet['candles']=[dict(t=120,low=98,high=101)]
        self.assertEqual(self.result()['outcome'],'target')
    def test_terminal_outcome_immutable(self):
        self.event['outcome']='ambiguous';self.assertEqual(self.result(),self.event)
if __name__=='__main__':unittest.main()
