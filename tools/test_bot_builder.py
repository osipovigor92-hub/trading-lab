import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
from bot_builder import BotBuilder, DEFAULTS, CATALOG

class BuilderTests(unittest.TestCase):
    def test_all_templates_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bots.json'; store=BotBuilder(path)
            for i,(key,*_) in enumerate(CATALOG):
                store.command(dict(revision=i,config=dict(DEFAULTS,strategy=key)))
            restored=BotBuilder(path).snapshot()
            self.assertEqual(len(restored['drafts']),10)
            self.assertFalse(restored['execution_ready'])
    def test_conflict_and_retry(self):
        store=BotBuilder(); cmd=dict(revision=0,config=DEFAULTS.copy())
        store.command(cmd); store.command(cmd)
        self.assertEqual(store.snapshot()['revision'],1)
        with self.assertRaises(ValueError):
            store.command(dict(revision=0,config=dict(DEFAULTS,notional=200)))
    def test_invalid_numbers(self):
        for value in [float('nan'),float('inf'),True,-1,0]:
            with self.assertRaises(ValueError):
                BotBuilder().command(dict(revision=0,config=dict(DEFAULTS,notional=value)))
    def test_corruption_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bots.json';path.write_text('broken')
            store=BotBuilder(path)
            with self.assertRaises(OSError):store.command(dict(revision=0,config=DEFAULTS.copy()))
            self.assertEqual(path.read_text(),'broken')
if __name__=='__main__':unittest.main()
