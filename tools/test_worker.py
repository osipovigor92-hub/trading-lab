"""PC protocol, lease persistence, native lifecycle and broker-only migration checks."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'integrations/control'))
sys.path.insert(0, str(REPO/'src/trading-panel'))
import remote
import manager
import control_client
import install_control
import pair_pc

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO/path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value

agent = module('pc_agent_test', 'integrations/worker/agent.py')
panel = module('pc_panel_test', 'src/trading-panel/server.py')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.key = 'test-credential-'+('x'*32)
        remote.atomic(self.root/'pc-key.json', dict(worker='pc-01', sha256=hashlib.sha256(self.key.encode()).hexdigest()))
        self.broker = remote.Remote(self.root)
        self.session = str(uuid.uuid4())
        self.payload = dict(version=1, worker='pc-01', session=self.session,
            memory=dict(total_gb=8, available_gb=7),
            engines={e:dict(ready=True, version=remote.VERSIONS.get(e,'compiled')) for e in remote.ENGINES}, active=None)
        self.broker.exchange(self.key, self.payload, 100)

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, engine='freqtrade'):
        return self.broker.command(engine, 'start', self.broker.data['generation'], 101)

    def exchange(self, phase=None, job=None, now=102):
        payload = copy.deepcopy(self.payload)
        if phase:
            payload['active'] = dict(job_id=job or self.broker.active()['id'],
                report=dict(phase=phase, reason='test', version='2026.9', metrics=dict(count=0, net=0)))
        return self.broker.exchange(self.key, payload, now)

    def test_credentials_bounded_protocol_and_version_pins(self):
        for key in ('bad', 'é'*43, self.key+'x'):
            with self.assertRaisesRegex(ValueError, 'авторизован'):
                self.broker.exchange(key, self.payload, 102)
        for change in (dict(worker='other'), dict(version=True), dict(session='../root'),
                       dict(memory=dict(total_gb=8, available_gb=float('nan'))),
                       dict(engines={'shell':dict(ready=True, version='1')}), dict(shell='reboot')):
            with self.assertRaises(ValueError):
                self.broker.exchange(self.key, dict(self.payload, **change), 102)
        p=copy.deepcopy(self.payload);p['engines']['freqtrade']['version']='unverified'
        self.broker.exchange(self.key, p, 102)
        self.assertFalse(self.broker.item('freqtrade', 102)['actions']['start'])
        self.assertNotIn(self.key, json.dumps(self.broker.status(102)))

    def test_memory_gate_uses_pc_and_stale_reports_disable_new_tests(self):
        self.assertTrue(self.broker.item('jesse', 101)['actions']['start'])
        self.assertFalse(self.broker.item('jesse', 120)['actions']['start'])
        p=dict(self.payload, memory=dict(total_gb=2, available_gb=1))
        self.broker.exchange(self.key, p, 102)
        self.assertFalse(self.broker.item('freqtrade', 102)['memory_ok'])

    def test_offer_retry_restart_and_terminal_retry_have_one_journal_record(self):
        uid=self.start(); first=self.exchange()['job']
        self.assertEqual(first['id'],uid);self.assertEqual(self.exchange(now=103)['job']['id'],uid)
        self.broker=remote.Remote(self.root)
        self.assertFalse(self.broker.broken)
        self.assertIsNone(self.exchange('running', now=104)['job'])
        self.assertEqual(self.exchange('completed', now=105)['ack'],uid)
        self.assertEqual(self.exchange('completed',uid,106)['ack'],uid)
        self.assertEqual(len(self.broker.data['runs']),1)
        self.assertEqual(self.broker.data['runs'][0]['metrics']['net'],0)
        self.assertTrue(self.broker.item('freqtrade',106)['actions']['start'])

    def test_cancel_queued_never_launches_and_cancel_dispatched_requires_ack(self):
        self.start();self.broker.command('freqtrade','stop',1,102)
        self.assertIsNone(self.exchange(now=103)['job'])
        self.assertEqual(self.broker.data['runs'][0]['phase'],'cancelled')
        uid=self.broker.command('jesse','start',2,103);self.exchange(now=104)
        self.broker.command('jesse','stop',3,105)
        self.assertEqual(self.exchange('running', now=106)['cancel'],uid)
        self.assertFalse(self.broker.item('freqtrade',106)['actions']['start'])
        self.exchange('cancelled',now=107)
        self.assertIsNone(self.broker.active())

    def test_disconnect_does_not_fabricate_completion_or_reassign(self):
        uid=self.start();self.exchange(now=102)
        item=self.broker.item('freqtrade',130)
        self.assertEqual(item['phase'],'lost');self.assertTrue(item['actions']['stop'])
        self.assertEqual(self.broker.active()['id'],uid)
        p=dict(self.payload, session=str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'Другой экземпляр'):
            self.broker.exchange(self.key,p,110)
        response=self.broker.exchange(self.key,p,140)
        self.assertIsNone(response['job']);self.assertEqual(response['cancel'],uid)
        p['active']=dict(job_id=uid,report=dict(phase='cancelled',reason='reboot acknowledged'))
        self.assertEqual(self.broker.exchange(self.key,p,141)['ack'],uid)

    def test_generation_unknown_jobs_reports_and_corrupt_state_fail_closed(self):
        self.start()
        with self.assertRaises(ValueError):self.broker.command('freqtrade','stop',0,102)
        for report in (dict(phase='completed',shell='x'),dict(phase='completed',metrics=dict(net=float('inf'))),
                       dict(phase='completed',settings=dict(api_key='secret'))):
            p=dict(self.payload,active=dict(job_id=self.broker.active()['id'],report=report))
            with self.assertRaises(ValueError):self.broker.exchange(self.key,p,102)
        with self.assertRaises(ValueError):self.exchange('completed',str(uuid.uuid4()))
        (self.root/'pc-state.json').write_text('{corrupt')
        broken=remote.Remote(self.root)
        self.assertFalse(broken.item('freqtrade',103)['actions']['start'])
        with self.assertRaisesRegex(ValueError,'повреждено'):broken.exchange(self.key,self.payload,103)

    def test_manager_routes_only_engines_to_pc_and_serializes_across_vds(self):
        with patch.object(manager,'ROOT',self.root),patch.object(manager,'PLATFORM_STATE',self.root/'local'), \
                patch.object(manager,'unit_status',return_value=dict(LoadState='not-found',ActiveState='inactive')):
            m=manager.Manager();m.audit=lambda *a,**kw:None
            with patch.object(remote.time,'time',return_value=101):
                result=m.command(dict(target='jesse',action='start',generation=0,execution='pc'))
            self.assertEqual(result['status'],'accepted')
            self.assertEqual(m.remote.active()['engine'],'jesse')
            csv=m.journal_csv('jesse')['csv'];self.assertIn('execution',csv)
            with self.assertRaises(ValueError):m.command(dict(target='A',action='stop',generation=0,execution='pc'))
            local=dict(id='freqtrade',generation=1,actions=dict(start=True,stop=True,restart=True),reason='')
            with patch.object(m,'engines',return_value=[local]):
                with self.assertRaisesRegex(ValueError,'на ПК'):m.command(dict(target='freqtrade',action='start',generation=1))

    def test_http_worker_auth_is_independent_and_bounded(self):
        body=json.dumps(self.payload).encode()
        good={'Host':'127.0.0.1:8787','Content-Type':'application/json','Content-Length':str(len(body)), 'X-Lab-Worker':self.key}
        def post(headers, content=body):
            result=[];h=SimpleNamespace(path='/api/worker',headers=headers,rfile=io.BytesIO(content),
                send=lambda code,data,kind:result.append((code,json.loads(data))))
            panel.Handler.do_POST(h);return result[0]
        with patch.object(control_client,'call',return_value=dict(status='ok')) as call:
            self.assertEqual(post(good)[0],200)
            self.assertEqual(call.call_args.args[0]['op'],'worker')
            call.reset_mock()
            for headers in (dict(good,Host='other'),dict(good,**{'Content-Length':'40000'}),
                dict(good,**{'X-Lab-Worker':''}),dict(good,**{'Transfer-Encoding':'chunked'}),
                dict(good,**{'Sec-Fetch-Site':'cross-site'})):
                self.assertNotEqual(post(headers)[0],200)
            call.assert_not_called()
        with patch.object(control_client,'call',return_value=dict(status='error',error='Исполнитель не авторизован')):
            self.assertEqual(post(good)[0],409)

    def test_agent_offer_native_id_cancellation_and_durable_ack(self):
        remote.atomic(self.root/'engines.json',dict(freqtrade=dict(ready=True,version='2026.9',python=sys.executable)))
        transport=SimpleNamespace(post=lambda p:dict(status='ok',version=1))
        worker=agent.Agent(self.root,transport);uid=str(uuid.uuid4())
        job=dict(id=uid,engine='freqtrade',timeout=2700,created=100)
        process=SimpleNamespace(pid=12345,poll=lambda:None,wait=lambda timeout:0)
        with patch.object(agent,'memory',return_value=dict(total_gb=8,available_gb=7)), \
                patch.object(agent.subprocess,'Popen',return_value=process) as spawn, \
                patch.object(agent,'process_start',return_value='start'):
            worker.start(job);worker.start(job);self.assertEqual(spawn.call_count,1)
        self.assertEqual(spawn.call_args.kwargs['env']['LAB_WORKER_JOB'],uid)
        self.assertIn('job.py',spawn.call_args.args[0][3])
        (self.root/'results/freqtrade').mkdir(parents=True)
        remote.atomic(self.root/'results/freqtrade/state.json',dict(id='previous',phase='completed',metrics=dict(net=999)))
        with patch.object(agent,'kill_group'),patch.object(agent,'reap_job'):
            worker.stop('cancelled','cancelled from panel')
        self.assertNotIn('metrics',worker.active['report'],'previous native report must not leak into the new job')
        self.assertEqual(json.loads((self.root/'delivery.json').read_text())['report']['phase'],'cancelled')
        transport.post=lambda p:dict(status='ok',version=1,ack=uid)
        worker.tick();self.assertIsNone(worker.active);self.assertFalse((self.root/'delivery.json').exists())

    def test_agent_recovery_no_repeat_and_report_strings(self):
        uid=str(uuid.uuid4())
        remote.atomic(self.root/'delivery.json',dict(job_id=uid,pid=1,report=dict(phase='running')))
        with patch.object(agent,'reap_job') as reap:
            worker=agent.Agent(self.root,SimpleNamespace())
            reap.assert_called_once_with(uid)
        self.assertEqual(worker.active['report']['phase'],'interrupted')
        self.assertEqual(worker.active['job_id'],uid)
        native=self.root/'native.json';remote.atomic(native,dict(id=uid,phase='failed',reason='one\ntwo'))
        self.assertEqual(agent.report(native,job_id=uid)['reason'],'one two')
        for url in ('http://78.17.187.70:8787','https://user:pass@host','https://host/api/worker','https://host?key=bad'):
            with self.assertRaises(ValueError):agent.endpoint(url)
        self.assertEqual(agent.endpoint('http://127.0.0.1:18787'),('http://127.0.0.1:18787/api/worker',True))
        with self.assertRaises(ValueError):agent.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_agent_kills_test_on_link_loss_and_acknowledges_cancel_before_launch(self):
        worker=agent.Agent(self.root,SimpleNamespace(post=lambda p:dict(status='ok',version=1,cancel=str(uuid.uuid4()))))
        worker.tick();self.assertEqual(worker.active['report']['phase'],'cancelled')
        worker.process=object();worker.last_ok=0
        def stop(phase,reason):
            worker.process=None;self.assertEqual(phase,'interrupted')
        def sleep(_):raise KeyboardInterrupt()
        with patch.object(worker,'tick',side_effect=OSError('disconnected')),patch.object(worker,'stop',side_effect=stop) as halt, \
                patch.object(agent.time,'sleep',side_effect=sleep),patch.object(agent.time,'monotonic',return_value=20):
            with self.assertRaises(KeyboardInterrupt):worker.run()
        halt.assert_called_once()

    def test_bundle_has_only_reviewed_source_hashes_and_no_credential(self):
        out=self.root/'bundle.tar.gz';manifest=pair_pc.export_bundle(out,'a'*40)
        with tarfile.open(out) as archive:
            self.assertEqual(set(archive.getnames()),{'trading-lab-pc/'+p for p in pair_pc.FILES}|{'trading-lab-pc/worker-release.json'})
            for name,digest in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.extractfile('trading-lab-pc/'+name).read()).hexdigest(),digest)
        self.assertEqual(out.stat().st_mode & 0o777,0o600)
        self.assertNotIn(self.key,out.read_bytes().decode('latin1'))

    def test_real_http_transport_lease_report_and_ack(self):
        try:
            server=ThreadingHTTPServer(('127.0.0.1',0),panel.Handler)
        except PermissionError:
            self.skipTest('Local sockets unavailable; this check runs in GitHub Actions')
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(request):
            try:return self.broker.exchange(request['key'],request['payload'],102)
            except ValueError as exc:return dict(status='error',error=str(exc))
        try:
            transport=agent.Transport(dict(url='http://127.0.0.1:'+str(server.server_port),key=self.key))
            uid=self.start()
            with patch.object(control_client,'call',side_effect=call):
                self.assertEqual(transport.post(self.payload)['job']['id'],uid)
                payload=dict(self.payload,active=dict(job_id=uid,report=dict(phase='completed',metrics=dict(count=0,net=0))))
                self.assertEqual(transport.post(payload)['ack'],uid)
                self.assertEqual(transport.post(payload)['ack'],uid)
                self.assertEqual(len(self.broker.data['runs']),1)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_native_group_can_be_reaped_after_crash_without_pid_reuse(self):
        uid=str(uuid.uuid4())
        process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],
            env=dict(os.environ,LAB_WORKER_JOB=uid),start_new_session=True)
        try:
            try:(Path('/proc')/str(process.pid)/'environ').read_bytes()
            except PermissionError:
                self.skipTest('This runtime restricts /proc; the real process recovery check runs in GitHub Actions')
            remote.atomic(self.root/'delivery.json',dict(job_id=uid,report=dict(phase='running')))
            worker=agent.Agent(self.root,SimpleNamespace())
            process.wait(timeout=5)
            self.assertNotEqual(process.returncode,0)
            self.assertEqual(worker.active['report']['phase'],'interrupted')
        finally:
            if process.poll() is None:
                process.kill();process.wait(timeout=5)

    def test_broker_migration_only_restarts_controller_and_rolls_back(self):
        old=b'old broker'
        folder=self.root/'code';folder.mkdir();control=self.root/'control';control.mkdir()
        main=folder/'manager.py';main.write_bytes(old)
        additional=folder/'runtime.py';additional.write_bytes(b'unchanged')
        pc=folder/'remote.py';manifest=control/'installed.json'
        saved=dict(files={str(main):'7ce07edd39e6adcd5c93ea942f4231bf2420b6531ef30ba60f63b1691de485a1',
                          str(additional):hashlib.sha256(b'unchanged').hexdigest()})
        manifest.write_text(json.dumps(saved));files={main:b'new broker',pc:b'new remote',additional:b'unchanged'}
        backup=self.root/'backup';backup.mkdir()
        digest=lambda p:saved['files'][str(p)]
        active=lambda u:u=='trading-control.service'
        with patch.object(install_control,'CODE',folder),patch.object(install_control,'MANIFEST',manifest), \
                patch.object(install_control.deploy,'digest',side_effect=digest),patch.object(install_control.deploy,'active',side_effect=active), \
                patch.object(install_control.tempfile,'mkdtemp',return_value=str(backup)),patch.object(install_control.os,'chown'), \
                patch.object(install_control.deploy,'system') as system,patch.object(install_control.time,'sleep'), \
                patch.object(control_client,'call',return_value=dict(status='ok',worker={})): 
            install_control.upgrade_controller(files,saved,'b'*40,SimpleNamespace(pw_gid=0))
            self.assertEqual(main.read_bytes(),b'new broker');self.assertEqual(pc.read_bytes(),b'new remote')
            self.assertTrue(all(c.args[-1]=='trading-control.service' for c in system.call_args_list))
            main.write_bytes(old);pc.unlink();manifest.write_text(json.dumps(saved));system.reset_mock()
            with patch.object(control_client,'call',side_effect=OSError('unavailable')):
                with self.assertRaisesRegex(RuntimeError,'не ответил'):
                    install_control.upgrade_controller(files,saved,'b'*40,SimpleNamespace(pw_gid=0))
            self.assertEqual(main.read_bytes(),old);self.assertFalse(pc.exists())
            self.assertEqual(json.loads(manifest.read_text()),saved)
            self.assertTrue(all(c.args[-1]=='trading-control.service' for c in system.call_args_list))
            with self.assertRaisesRegex(RuntimeError,'миграции'):
                install_control.upgrade_controller(files,dict(files={}), 'b'*40, SimpleNamespace(pw_gid=0))


if __name__=='__main__':unittest.main()
