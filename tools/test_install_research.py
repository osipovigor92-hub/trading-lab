import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import install_research as i

class InstallTests(unittest.TestCase):
    def test_preflight_untracked_drift_and_upgrade(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'engine.py';target={p:b'new'};i.preflight(target,None)
            p.write_bytes(b'old')
            with self.assertRaisesRegex(RuntimeError,'без записи'):i.preflight(target,None)
            state={'files':{str(p):i.hashlib.sha256(b'new').hexdigest()}}
            with self.assertRaisesRegex(RuntimeError,'Локальные'):i.preflight(target,state)
            p.write_bytes(b'new');i.preflight(target,state)
            with self.assertRaisesRegex(RuntimeError,'миграции'):i.preflight({p:b'changed'},state)
    def run_install(self,fail=False):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d);root=base/'state';code=base/'code';unit=base/'unit';manifest=base/'installed.json';calls=[]
            with patch.multiple(i,ROOT=root,CODE=code,UNIT=unit,MANIFEST=manifest),patch.object(i.os,'chown'),patch.object(i.deploy,'system',side_effect=lambda *a:calls.append(a)),patch.object(i.deploy,'active',return_value=True),patch.object(i.subprocess,'run',return_value=SimpleNamespace(stdout='not-found\n')),patch.object(i,'health',side_effect=RuntimeError('fail') if fail else None,return_value={'models':{'C':{'phase':'waiting'},'D':{'phase':'waiting'}}}):
                target={code/'engine.py':b'pass\n',unit:b'[Unit]\n'}
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'fail'):i.install(target,'a'*40,SimpleNamespace(pw_uid=1,pw_gid=1))
                    self.assertFalse(unit.exists());self.assertFalse((code/'engine.py').exists());self.assertFalse(manifest.exists())
                else:
                    i.install(target,'a'*40,SimpleNamespace(pw_uid=1,pw_gid=1));self.assertTrue(manifest.exists())
                    before=list(calls);i.install(target,'a'*40,SimpleNamespace(pw_uid=1,pw_gid=1));self.assertEqual(calls,before)
                    self.assertEqual(json.loads(manifest.read_text())['revision'],'a'*40)
                self.assertTrue(all(a[1]==i.SERVICE for a in calls if len(a)>1))
    def test_install_and_idempotence(self):self.run_install()
    def test_failed_health_removes_only_new_code(self):self.run_install(True)

if __name__=='__main__':unittest.main()
