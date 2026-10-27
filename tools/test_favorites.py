import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from favorites import Favorites

KEY = 'lab-favorites-v1'
def command(number, symbol, present=True):
    return dict(id=f'favorite-{number}', changes=[dict(key=KEY, value=symbol, present=present)])

class FavoritesTests(unittest.TestCase):
    def test_merge_retry_remove_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'favorites.json'
            store = Favorites(path)
            first = command(1, 'BTCUSDT')
            store.command(first)
            store.command(command(2, 'ETHUSDT'))
            self.assertEqual(store.snapshot()['groups'][KEY], ['BTCUSDT', 'ETHUSDT'])
            store.command(command(3, 'BTCUSDT', False))
            store.command(first)  # Lost acknowledgement must not resurrect removed coin.
            self.assertEqual(Favorites(path).snapshot()['groups'][KEY], ['ETHUSDT'])
            with self.assertRaises(ValueError):store.command(command(1, 'SOLUSDT'))

    def test_invalid_limit_and_disk_failure_are_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Favorites(Path(folder)/'favorites.json')
            store.command(command(1, 'BTCUSDT'))
            old = store.snapshot()
            with self.assertRaises(ValueError):store.command(command(2, '../../bad'))
            huge = dict(id='huge-import', changes=[dict(key=KEY,value=f'COIN{i}USDT',present=True) for i in range(9)])
            with self.assertRaises(ValueError):store.command(huge)
            with patch('favorites.write', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):store.command(command(3, 'ETHUSDT'))
            current=store.snapshot()
            self.assertEqual(current['storage_error'],'disk full')
            current['storage_error']=None
            self.assertEqual(old, current)

    def test_corrupt_storage_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'favorites.json';path.write_text('broken')
            store=Favorites(path)
            self.assertEqual(store.snapshot()['status'], 'unavailable')
            with self.assertRaises(OSError):store.command(command(1, 'BTCUSDT'))
            self.assertEqual(path.read_text(), 'broken')

if __name__ == '__main__':unittest.main()
