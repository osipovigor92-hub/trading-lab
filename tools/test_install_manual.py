import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import install_manual


class InstallManualTests(unittest.TestCase):
    def test_panel_only_install_idempotence_and_rollback(self):
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                root = Path(folder);track=root/'track';track.mkdir();drop=root/'unit.d'/'lab-manual-paper.conf'
                (track/'installed.json').write_text(json.dumps(dict(files={'src/trading-panel/server.py':'safe','src/trading-panel/manual_paper.py':'safe'})))
                calls=[]
                with patch.object(install_manual, 'ROOT', root/'state'), patch.object(install_manual, 'DROPIN', drop), patch.object(install_manual.deploy, 'TRACK', track), patch.object(install_manual.deploy, 'digest', return_value='safe'), patch.object(install_manual.deploy, 'active', return_value=True), patch.object(install_manual.deploy, 'system', side_effect=lambda *args:calls.append(args)), patch.object(install_manual, 'health', side_effect=RuntimeError('health failed') if failure else None):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, 'health failed'):
                            install_manual.install()
                        self.assertFalse(drop.exists())
                    else:
                        install_manual.install()
                        self.assertEqual(drop.read_bytes(), install_manual.BODY)
                        install_manual.install()
                        self.assertEqual(calls.count(('restart','trading-panel.service')), 1)
                    self.assertTrue(all(c in (('daemon-reload',), ('restart','trading-panel.service')) for c in calls))

    def test_custom_dropin_and_symlink_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);drop=root/'manual.conf';drop.write_bytes(b'custom')
            with patch.object(install_manual, 'ROOT', root/'state'), patch.object(install_manual, 'DROPIN', drop):
                with self.assertRaisesRegex(RuntimeError, 'изменена'):
                    install_manual.install()
            target=root/'target';target.write_bytes(b'original');alias=root/'alias';alias.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, 'Symlink'):
                install_manual.validate(alias)
            self.assertEqual(drop.read_bytes(), b'custom')
