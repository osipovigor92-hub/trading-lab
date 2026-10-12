"""Observation starts without trading candidates and keeps trade windows separate."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('live_observer', Path(__file__).resolve().parents[1]/'src/trading-live/live.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveObserverTests(unittest.TestCase):
    def test_no_scanner_or_no_candidates_still_starts_a_watchlist(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live, 'SOURCE', Path(folder)/'scanner.json'):
            self.assertEqual(live.select_symbols(), live.DEFAULT_SYMBOLS)
            for content in ('bad json', 'null', json.dumps(dict(status='ok', finished=time.time(), rows=[]))):
                live.SOURCE.write_text(content)
                self.assertEqual(live.select_symbols(), live.DEFAULT_SYMBOLS)
            now = time.time()
            live.SOURCE.write_text(json.dumps(dict(status='ok', finished=now, rows=[
                dict(symbol='LINKUSDT', candidate=True, sampled_at=now, candle_end=now),
                dict(symbol='BTCUSDT', candidate=False, sampled_at=now, candle_end=now)])))
            self.assertEqual(live.select_symbols(), ['LINKUSDT'])

    def test_book_is_displayed_before_the_trade_window_is_warm(self):
        now=time.time();m=live.Market('BTCUSDT')
        m.book(dict(type='snapshot',ts=now*1000,data=dict(s='BTCUSDT',u=10,seq=10,b=[['99.99','100']],a=[['100.01','100']])))
        m.trades(dict(ts=now*1000,data=[dict(s='BTCUSDT',i='one',T=now*1000,S='Buy',p='100',v='2')]))
        row=m.metrics(now)
        self.assertEqual(row['price'],100)
        self.assertFalse(row['ready'])
        self.assertEqual(row['flow5']['buy'],200)
        self.assertEqual(row['flow60']['count'],1)
        self.assertGreaterEqual(row['trade_age'],0)
        later=m.metrics(now+16)
        self.assertEqual(later['flow5']['buy'],0)
        self.assertEqual(later['flow15']['buy'],0)
        self.assertEqual(later['flow60']['buy'],200)


if __name__=='__main__':unittest.main()
