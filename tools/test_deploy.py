import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import deploy

class DeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def dest(self,name):return self.root/Path(name).name
    def test_drift_and_protected_models(self):
        name='src/trading-panel/app.js';p=self.dest(name);p.write_text('old')
        old={name:deploy.digest(p)}
        with patch.object(deploy,'destination',self.dest):
            self.assertEqual(deploy.plan(old,{name:'new'}),[name])
            p.write_text('local edit')
            with self.assertRaisesRegex(RuntimeError,'differs'):deploy.plan(old,{name:'new'})
            with self.assertRaisesRegex(RuntimeError,'Separate model'):deploy.plan({}, {'src/scalp-model-b/model_b.py':'new'})
    def test_paths(self):
        for path in ('../state.json','src/trading-panel/../x','src/unknown/x.py','deploy/state.json'):
            with self.assertRaises(ValueError):deploy.destination(path)
    def test_atomic_and_symlink(self):
        p=self.root/'file';deploy.atomic(p,b'old',0o600);deploy.atomic(p,b'new',0o600)
        self.assertEqual(p.read_bytes(),b'new');self.assertEqual(p.stat().st_mode&0o777,0o600)
        alias=self.root/'app.js';alias.symlink_to(p)
        with patch.object(deploy,'destination',self.dest):
            with self.assertRaisesRegex(RuntimeError,'Symlink'):deploy.plan({}, {'src/trading-panel/app.js':'x'})
    def run_update(self,fail=False):
        name='src/trading-panel/app.js';server=self.root/'server';repo=self.root/'repo';track=self.root/'track'
        server.mkdir();track.mkdir();source=repo/name;source.parent.mkdir(parents=True);source.write_text('new')
        live=server/'app.js';live.write_text('old')
        expected={name:deploy.digest(live)};target={name:deploy.digest(source)};calls=[]
        with patch.object(deploy,'TRACK',track),patch.object(deploy,'REPO',repo),patch.object(deploy,'destination',lambda n:server/Path(n).name),patch.object(deploy,'active',return_value=True),patch.object(deploy,'system',side_effect=lambda *a:calls.append(a)),patch.object(deploy.subprocess,'run'),patch.object(deploy,'health',side_effect=RuntimeError('health failed') if fail else None):
            if fail:
                with self.assertRaisesRegex(RuntimeError,'health failed'):deploy.apply(expected,target,[name],'a'*40)
            else:deploy.apply(expected,target,[name],'a'*40)
        self.assertEqual(live.read_text(),'old' if fail else 'new')
        self.assertEqual((track/'installed.json').exists(),not fail)
        self.assertTrue(all(unit=='trading-panel.service' for call in calls for unit in call[1:]))
    def test_success(self):self.run_update()
    def test_health_failure_rolls_back(self):self.run_update(True)

if __name__=='__main__':unittest.main()
