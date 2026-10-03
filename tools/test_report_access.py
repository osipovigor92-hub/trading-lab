import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('repair_report_history', ROOT/'tools/repair_report_history.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


class ReportAccessTests(unittest.TestCase):
    def test_plan_only_targets_model_b_history_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'model-b'; root.mkdir(mode=0o700)
            history = root/'history.sqlite'; history.write_text('placeholder')
            os.chmod(history, 0o600)
            owner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            _, rows = repair.plan(root, owner)
            self.assertEqual([row[0].name for row in rows], ['model-b', 'history.sqlite'])
            self.assertTrue(all(not row[2] and not row[3] for row in rows))
            os.chmod(history, 0o644)
            _, rows = repair.plan(root, owner)
            self.assertTrue(rows[-1][3])

    def test_plan_rejects_missing_history_and_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'model-b'; root.mkdir()
            owner = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            with self.assertRaisesRegex(RuntimeError, 'не найден'):
                repair.plan(root, owner)
            target = Path(folder)/'real.sqlite'; target.write_text('x')
            (root/'history.sqlite').symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, 'ссылка'):
                repair.plan(root, owner)


if __name__ == '__main__':
    unittest.main()
