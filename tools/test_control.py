import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'integrations/control'))
sys.path.insert(0,str(REPO/'src/trading-panel'))
import manager
import control_client as client
import install_control
import prepare_engine
import diagnose_models
spec=importlib.util.spec_from_file_location('controlled_panel_server',REPO/'src/trading-panel/server.py')
panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)


class ControlTests(unittest.TestCase):
    def item(self,model='A',**kw):
        return dict(id=model,generation=1,reason='',actions=dict(start=True,stop=True,restart=True),**kw)
    def test_token_origin_and_content_type(self):
        good={'Content-Type':'application/json','X-Lab-Control':client.TOKEN,'Sec-Fetch-Site':'same-origin'}
        self.assertTrue(client.authorized(good))
        for wrong in [{'X-Lab-Control':'bad'},{'X-Lab-Control':'é'},{'Sec-Fetch-Site':'cross-site'},{'Origin':'null'},{'Content-Type':'text/plain'}]:
            self.assertFalse(client.authorized(dict(good,**wrong)))
    def test_http_commands_require_host_token_bounded_json_and_report_rejection(self):
        body=json.dumps(dict(target='B',action='stop',generation=1)).encode()
        good={'Host':'127.0.0.1:8787','Content-Type':'application/json','Content-Length':str(len(body)),
              'X-Lab-Control':client.TOKEN,'Sec-Fetch-Site':'same-origin'}
        def post(headers=good,path='/api/models-control',payload=body):
            result=[]
            handler=SimpleNamespace(path=path,headers=headers,rfile=io.BytesIO(payload),send=lambda code,data,kind:result.append((code,json.loads(data))))
            panel.Handler.do_POST(handler);return result[0]
        with patch.object(client,'call',return_value=dict(status='accepted')) as broker:
            self.assertEqual(post()[0],202)
            broker.assert_called_once_with(dict(op='command',command=dict(target='B',action='stop',generation=1)))
            broker.reset_mock()
            self.assertEqual(post(dict(good,Host='other-site'))[0],403)
            self.assertEqual(post(dict(good,**{'X-Lab-Control':'bad'}))[0],403)
            self.assertEqual(post(dict(good,**{'Content-Length':'5000'}))[0],400)
            self.assertEqual(post(path='/api/xray')[0],404)
            broker.assert_not_called()
        with patch.object(client,'call',return_value=dict(status='error',error='changed')):
            code,data=post();self.assertEqual(code,409);self.assertEqual(data['error'],'changed')
    def test_only_whitelisted_fixed_commands_and_optimistic_generation(self):
        with tempfile.TemporaryDirectory() as d,patch.object(manager,'ROOT',Path(d)):
            (Path(d)/'commands').mkdir(); m=manager.Manager()
            with patch.object(m,'models',return_value=[self.item()]),patch.object(m,'audit'),patch.object(manager,'atomic') as write,patch.object(manager.threading,'Thread') as thread:
                for cmd in [dict(target='xray.service',action='stop',generation=1),dict(target='A',action='stop;reboot',generation=1),dict(target='A',action='stop',generation=0),dict(target='A',action='stop',generation=1,shell='x')]:
                    with self.assertRaises(ValueError):m.command(cmd)
                r=m.command(dict(target='A',action='stop',generation=1))
                self.assertEqual(r['status'],'accepted');self.assertEqual(write.call_args[0][1]['generation'],2)
                self.assertTrue(thread.called)
                with self.assertRaises(ValueError):m.command(dict(target='A',action='start',generation=1))
    def test_new_run_only_accepts_bounded_paper_settings_and_keeps_lifecycle_allowlist(self):
        with tempfile.TemporaryDirectory() as d,patch.object(manager,'ROOT',Path(d)):
            (Path(d)/'commands').mkdir(); m=manager.Manager()
            item=self.item(phase='paused');item['actions']['new_run']=True
            with patch.object(m,'models',return_value=[item]),patch.object(m,'audit'),patch.object(manager.threading,'Thread') as thread:
                good=dict(target='A',action='new_run',generation=1,experiment=dict(capital=300,notional=75,max_loss=9))
                for bad in [
                    dict(good, shell='x'),
                    dict(target='A',action='new_run',generation=1,experiment=dict(capital=300,notional=75)),
                    dict(target='A',action='new_run',generation=1,experiment=dict(capital=9,notional=1,max_loss=1)),
                    dict(target='A',action='new_run',generation=1,experiment=dict(capital=300,notional=301,max_loss=9)),
                    dict(target='freqtrade',action='new_run',generation=1,experiment=dict(capital=300,notional=75,max_loss=9)),
                ]:
                    with self.assertRaises(ValueError):m.command(bad)
                result=m.command(good)
                self.assertEqual(result['status'],'accepted');self.assertTrue(thread.called)

    def test_new_run_archives_stopped_state_before_writing_clean_settings(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); control=base/'control';(control/'commands').mkdir(parents=True)
            root=base/'paper';root.mkdir()
            (root/'state.json').write_text(json.dumps(dict(phase='paused',position=None,config=dict(capital=600))))
            (root/'journal-report.json').write_text(json.dumps(dict(recorded=2)))
            (control/'commands'/'A.json').write_text(json.dumps(dict(action='stop',generation=4)))
            storage=dict(manager.EXPERIMENT_STORAGE,A=dict(root=root,unit='paper-test.service',files=('state.json','journal-report.json')))
            writes=[];audits=[]
            def write(path,data):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data));writes.append((path,data))
            with patch.object(manager,'ROOT',control),patch.object(manager,'EXPERIMENT_STORAGE',storage),patch.object(manager,'atomic',side_effect=write),patch.object(manager,'system') as system,patch.object(manager,'unit_status',return_value=dict(ActiveState='active')),patch.object(manager.os,'chown'),patch.object(manager.pwd,'getpwnam',return_value=SimpleNamespace(pw_gid=1)):
                m=manager.Manager();m.audit=lambda *args:audits.append(args)
                m.new_experiment('A',dict(capital=300.,notional=75.,max_loss=9.),'1234abcd-ignored')
            archives=list((root/'archives').iterdir());self.assertEqual(len(archives),1)
            self.assertTrue((archives[0]/'state.json').is_file());self.assertTrue((archives[0]/'journal-report.json').is_file())
            self.assertFalse((root/'state.json').exists())
            record=json.loads((control/'experiments'/'A.json').read_text());self.assertEqual(record['settings']['capital'],300.)
            command=json.loads((control/'commands'/'A.json').read_text());self.assertEqual(command['action'],'start');self.assertEqual(command['generation'],5)
            self.assertEqual(system.call_args_list[0].args,('stop','paper-test.service'));self.assertEqual(system.call_args_list[-1].args,('start','paper-test.service'))
            self.assertEqual(audits[-1][2],'delivered')
    def test_stop_does_not_kill_the_shared_market_feed(self):
        with tempfile.TemporaryDirectory() as d,patch.object(manager,'ROOT',Path(d)),patch.object(manager,'system') as system:
            m=manager.Manager();m.audit=lambda *a:None
            m.execute('B','stop','test');system.assert_not_called()
            m.execute('C','start','test');system.assert_called_once_with('start','trading-research.service')
    def test_one_external_test_slot(self):
        with tempfile.TemporaryDirectory() as d,patch.object(manager,'ROOT',Path(d)):
            m=manager.Manager(); m.engines=lambda:[self.item('freqtrade')]
            with patch.object(manager,'unit_status',return_value=dict(ActiveState='active')):
                with self.assertRaisesRegex(ValueError,'Другой тест'):m.command(dict(target='freqtrade',action='start',generation=1))
    def test_engine_csv_keeps_cancelled_failed_and_zero_return(self):
        with tempfile.TemporaryDirectory() as d,patch.object(manager,'PLATFORM_STATE',Path(d)),patch.object(manager,'ROOT',Path(d)):
            root=Path(d)/'jesse';root.mkdir();(root/'runs.json').write_text(json.dumps([dict(id='zero',phase='completed',metrics=dict(count=0,net=0)),dict(id='cancel',phase='cancelled'),dict(id='error',phase='failed')]))
            csv=manager.Manager().journal_csv('jesse')['csv'];self.assertIn('completed',csv);self.assertIn('cancelled',csv);self.assertIn('failed',csv)
            with self.assertRaises(ValueError):manager.Manager().journal_csv('../root')
    def test_install_preflight_protects_existing_code_and_units(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'unit';p.write_bytes(b'old')
            with self.assertRaisesRegex(RuntimeError,'без записи'):install_control.preflight({p:b'new'},None)
            saved={'files':{str(p):install_control.hashlib.sha256(b'old').hexdigest()}}
            install_control.preflight({p:b'old'},saved)
            with self.assertRaisesRegex(RuntimeError,'миграция'):install_control.preflight({p:b'new'},saved)
    def test_open_position_and_signal_refuse_first_install(self):
        good=dict(updated=100,phase='running',position=None,cooldown_until=140,observations=[])
        self.assertTrue(install_control.safe({'A':good,'B':good},100))
        self.assertFalse(install_control.safe({'A':dict(good,position={'symbol':'TEST'})},100))
        self.assertFalse(install_control.safe({'B':dict(good,observations=[dict(signal='LONG')])},100))
        self.assertFalse(install_control.safe({'A':dict(good,cooldown_until=100)},100))
    def test_test_units_have_no_restart_or_boot_enable(self):
        for engine in prepare_engine.MINIMUM:
            body=prepare_engine.unit(engine,Path('/opt/test/bin/python')).decode()
            self.assertNotIn('Restart=',body);self.assertNotIn('[Install]',body)
            self.assertIn('KillMode=control-group',body);self.assertIn('NoNewPrivileges=true',body)
            self.assertIn('NUMBA_CACHE_DIR=/var/lib/trading-platforms/'+engine,body)
        self.assertIn('PYTHONPATH=/opt/hummingbot',prepare_engine.unit('hummingbot',Path('/opt/env/bin/python'),Path('/opt/hummingbot')).decode())

    def test_diagnostic_report_excludes_token_audit_strategy_and_position_details(self):
        raw=dict(status='ok',updated=100,token='PRIVATE_TOKEN',audit=[dict(message='PRIVATE_LOG')],
                 memory=dict(total_gb=1,available_gb=.7,private='PRIVATE_MEMORY'),
                 models=[dict(id='B',phase='paused',fresh=True,position=dict(symbol='PRIVATE_POSITION',entry=100),config='PRIVATE_CONFIG')],
                 engines=[dict(id='jesse',phase='not_installed',settings='PRIVATE_SETTINGS')])
        result=diagnose_models.sanitized_status(raw,101)
        self.assertTrue(result['fresh']);self.assertTrue(result['models'][0]['has_position'])
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('token',result)
        self.assertFalse(diagnose_models.sanitized_status(raw,110)['fresh'])
        self.assertFalse(diagnose_models.sanitized_status(dict(status='error'),101)['available'])

    def test_diagnostic_integrity_rejects_unknown_manifest_paths_and_unit_inspection_only_shows(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'launcher.py';p.write_bytes(b'checked code')
            manifest=dict(files={str(p):diagnose_models.hashlib.sha256(p.read_bytes()).hexdigest()})
            with patch.object(diagnose_models,'CONTROL_FILES',{str(p)}):
                self.assertTrue(diagnose_models.integrity(manifest))
                p.write_bytes(b'changed');self.assertFalse(diagnose_models.integrity(manifest))
                self.assertFalse(diagnose_models.integrity(dict(files={'/root/private': 'hash'})))
        output='Id=trading-panel.service\nLoadState=loaded\nActiveState=active\n\nId=trading-control.service\nLoadState=not-found\nActiveState=inactive\n'
        with patch.object(diagnose_models.subprocess,'run',return_value=SimpleNamespace(stdout=output)) as run:
            states=diagnose_models.unit_states()
            self.assertEqual(states['trading-panel.service']['active'],'active')
            self.assertEqual(states['trading-control.service']['load'],'not-found')
            self.assertEqual(run.call_args.args[0][:2],['/usr/bin/systemctl','show'])

    def test_alert_diagnostic_distinguishes_monitor_response_from_source_readiness(self):
        packet=dict(status='ok',updated=100,token='PRIVATE',analyzing=['BTCUSDT'],
                    rows=[dict(state='ready',sources=dict(quote=100,chart=100,candle=80,book=100,fetched=100))],
                    events=[dict(expires=108,detail='PRIVATE')])
        report=diagnose_models.sanitized_alerts(packet,101)
        self.assertEqual(report['sources_ready'],1)
        self.assertEqual(report['confirmed_candidates'],1)
        self.assertEqual(report['current_events'],1)
        self.assertNotIn('PRIVATE',json.dumps(report))
        packet['updated']=110
        report=diagnose_models.sanitized_alerts(packet,110)
        self.assertTrue(report['fresh'])
        self.assertEqual(report['sources_ready'],0)
        self.assertEqual(report['current_events'],0)

    def test_candidate_journal_diagnostic_reports_readability_and_collection_separately(self):
        packet=dict(status='partial',updated=100,total=42,rows=[dict(body='PRIVATE')],
                    collector=dict(installed=True,collecting=False,last_cycle=90,error='PRIVATE_STORAGE_ERROR'))
        result=diagnose_models.sanitized_journal(packet,101)
        self.assertTrue(result['available']);self.assertTrue(result['fresh']);self.assertFalse(result['collecting'])
        self.assertEqual(result['records'],42);self.assertNotIn('PRIVATE',json.dumps(result))
        packet['collector']['collecting']=True
        self.assertTrue(diagnose_models.sanitized_journal(packet,101)['collecting'])
        self.assertFalse(diagnose_models.sanitized_journal(packet,140)['collecting'])
        self.assertFalse(diagnose_models.sanitized_journal(dict(status='unavailable'),101)['available'])

    def test_failed_first_install_removes_dropins_and_restores_previous_startup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); state=root/'state.json'; state.write_text(json.dumps(dict(updated=100,position=None)))
            file=root/'code'/'launcher.py'; manifest=root/'control'/'installed.json'
            owner=SimpleNamespace(pw_gid=0)
            with patch.object(install_control,'ROOT',manifest.parent),patch.object(install_control,'MANIFEST',manifest),patch.object(install_control,'CODE',file.parent),patch.object(install_control,'SOURCES',{'B':('src/scalp-model-b/model_b.py',state,'test-model.service')}),patch.object(install_control,'snapshots',return_value={}),patch.object(install_control,'safe',return_value=True),patch.object(install_control,'REPO',REPO),patch.object(install_control.deploy,'active',return_value=True),patch.object(install_control.deploy,'digest',return_value='same'),patch.object(install_control.deploy,'system') as system,patch.object(install_control.subprocess,'run') as run,patch.object(install_control.tempfile,'mkdtemp',return_value=str(root/'backup')),patch.object(install_control.time,'sleep'),patch.object(install_control.os,'chown'),patch.object(client,'call',side_effect=OSError('socket unavailable')):
                (root/'backup').mkdir()
                with self.assertRaisesRegex(RuntimeError,'Контроллер не ответил'):
                    install_control.install({file:b'new'},'test-revision',owner)
                self.assertFalse(file.exists());self.assertFalse(manifest.exists())
                self.assertEqual(json.loads(state.read_text())['position'],None)
                calls=[x.args[0] for x in run.call_args_list]
                self.assertIn(['systemctl','disable','--now','trading-control.service'],calls)
                self.assertIn(['systemctl','start','test-model.service'],calls)


if __name__=='__main__': unittest.main()
