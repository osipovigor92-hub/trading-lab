import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install_journal


class InstallJournalTests(unittest.TestCase):
    def test_panel_only_idempotent_additive_dropin_and_rollback_preserve_all_data(self):
        for failure in (False,True):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);track=root/'track';track.mkdir();drop=root/'unit.d'/'lab-candidate-journal.conf'
                drop.parent.mkdir();manual=drop.parent/'lab-manual-paper.conf';manual.write_bytes(b'[Service]\nStateDirectory=trading-manual-paper\n')
                ledger=root/'paper.sqlite3';ledger.write_bytes(b'account and position must survive')
                (track/'installed.json').write_text(json.dumps(dict(files={f'src/trading-panel/{name}':'safe' for name in ('server.py','market_data.py','candidate_journal.py')})))
                calls=[]
                with patch.object(install_journal,'ROOT',root/'state'),patch.object(install_journal,'DROPIN',drop),patch.object(install_journal.deploy,'TRACK',track),patch.object(install_journal.deploy,'digest',return_value='safe'),patch.object(install_journal.deploy,'active',return_value=True),patch.object(install_journal.deploy,'system',side_effect=lambda *a:calls.append(a)),patch.object(install_journal,'health',side_effect=RuntimeError('health failed') if failure else None):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError,'health failed'):install_journal.install()
                        self.assertFalse(drop.exists())
                    else:
                        install_journal.install();install_journal.install()
                        self.assertEqual(drop.read_bytes(),install_journal.BODY)
                        self.assertEqual(calls.count(('restart','trading-panel.service')),1)
                self.assertTrue(all(c in (('daemon-reload',),('restart','trading-panel.service')) for c in calls))
                self.assertEqual(manual.read_bytes(),b'[Service]\nStateDirectory=trading-manual-paper\n')
                self.assertEqual(ledger.read_bytes(),b'account and position must survive')

    def test_foreign_config_symlink_and_unverified_files_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);drop=root/'journal.conf';drop.write_bytes(b'custom')
            with patch.object(install_journal,'ROOT',root/'state'),patch.object(install_journal,'DROPIN',drop):
                with self.assertRaisesRegex(RuntimeError,'изменена'):install_journal.install()
            self.assertEqual(drop.read_bytes(),b'custom')
            alias=root/'alias';alias.symlink_to(drop)
            with self.assertRaisesRegex(RuntimeError,'Symlink'):install_journal.validate(alias)
            drop.unlink();track=root/'track';track.mkdir();(track/'installed.json').write_text('{"files":{}}')
            with patch.object(install_journal,'ROOT',root/'state'),patch.object(install_journal,'DROPIN',drop),patch.object(install_journal.deploy,'TRACK',track):
                with self.assertRaisesRegex(RuntimeError,'этапа 7'):install_journal.install()
            self.assertFalse(drop.exists())
