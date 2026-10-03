"""Outbound-only native test executor for Linux/Ubuntu in Windows WSL2."""
import argparse
import ctypes
import fcntl
import json
import math
import os
from pathlib import Path
import resource
import signal
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, HTTPSHandler
import uuid

HERE = Path(__file__).resolve().parent
ROOT = Path.home()/'.local/share/trading-lab-worker'
ENGINES = ('freqtrade', 'jesse', 'hummingbot')
MINIMUM = {'freqtrade': 3, 'jesse': 3, 'hummingbot': 5}
VERSIONS = {'freqtrade': '2026.9', 'jesse': '3.2.4'}
TERMINAL = ('completed', 'cancelled', 'failed', 'interrupted')
FIELDS = ('phase', 'reason', 'version', 'metrics', 'settings')


def atomic(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    os.chmod(temporary, 0o600); os.replace(temporary, path)


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in ('MemTotal', 'MemAvailable'):
            values[name] = int(value.strip().split()[0])/1024**2
    return dict(total_gb=round(values['MemTotal'], 2), available_gb=round(values['MemAvailable'], 2))


def endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('Нужен адрес панели без пути, пароля и параметров')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('HTTP разрешён только внутри локального SSH-туннеля')
    return url.rstrip('/')+'/api/worker', parsed.scheme == 'http'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Redirect запрещён: проверь адрес панели')


class Transport:
    def __init__(self, config):
        self.url, self.tunnel = endpoint(config['url'])
        self.key = config['key']
        context = ssl.create_default_context(cafile=config.get('ca_file'))
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context))

    def post(self, payload):
        headers = {'Content-Type':'application/json', 'X-Lab-Worker':self.key}
        if self.tunnel:
            headers['Host'] = '127.0.0.1:8787'
        body = json.dumps(payload, allow_nan=False).encode()
        if len(body) > 32768:
            raise ValueError('Отчёт слишком большой')
        with self.opener.open(Request(self.url, body, headers=headers, method='POST'), timeout=5) as response:
            raw = response.read(32769)
        if len(raw) > 32768:
            raise ValueError('Слишком большой ответ панели')
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('status') != 'ok' or data.get('version') != 1:
            raise ValueError('Нет подтверждения панели')
        return data


def env(root, source=None):
    result = dict(os.environ, NUMBA_NUM_THREADS='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
        POLARS_MAX_THREADS='1', PYTHONDONTWRITEBYTECODE='1',
        NUMBA_CACHE_DIR=str(root/'.numba-cache'), XDG_CACHE_HOME=str(root/'.cache'))
    if source:
        result['PYTHONPATH'] = str(source)
    else:
        result.pop('PYTHONPATH', None)
    return result


def process_start(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def reap_job(job_id):
    """Reap surviving native descendants after an agent crash, by an inherited lease marker."""
    marker = ('LAB_WORKER_JOB='+job_id).encode()
    groups = set()
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid() or marker not in (path/'environ').read_bytes().split(b'\0'):
                continue
            group = os.getpgid(int(path.name))
            if group != os.getpgrp():
                groups.add(group)
        except (OSError, ValueError):
            continue
    for group in groups:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def kill_group(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)
    except ProcessLookupError:
        pass


def child_limits(parent):
    # prctl closes the crash window; session/group cancellation also covers native CLI children.
    ctypes.CDLL(None).prctl(1, signal.SIGTERM)
    if os.getppid() != parent:
        os._exit(1)
    os.nice(15)
    resource.setrlimit(resource.RLIMIT_CPU, (2100, 2110))
    if hasattr(os, 'sched_getaffinity'):
        os.sched_setaffinity(0, set(sorted(os.sched_getaffinity(0))[:2]))


def report(path, phase='running', reason='Нативный тест исполняется на ПК', job_id=None):
    data = read(path, {})
    if not isinstance(data, dict) or (job_id is not None and data.get('id') != job_id):
        data = {}
    result = {k:data.get(k) for k in FIELDS if data.get(k) is not None}
    result.setdefault('phase', phase); result.setdefault('reason', reason)
    result.setdefault('version', '')
    for key in ('reason', 'version'):
        result[key] = ' '.join(str(result[key]).split())[:240 if key == 'reason' else 80]
    if len(json.dumps(result).encode()) > 16000:
        return dict(phase='failed', reason='Слишком большой отчёт нативного теста', version='')
    return result


class Agent:
    def __init__(self, root, transport):
        self.root, self.transport = Path(root), transport
        self.session = str(uuid.uuid4())
        self.process = None
        self.job = None
        self.log = None
        self.last_ok = time.monotonic()
        self.active = read(self.root/'delivery.json')
        if self.active and self.active.get('report', {}).get('phase') not in TERMINAL:
            reap_job(str(uuid.UUID(self.active['job_id'])))
            self.active = dict(job_id=self.active['job_id'], report=dict(
                phase='interrupted', reason='Исполнитель перезапущен; старый тест не возобновлялся', version=''))
            self.persist()

    def persist(self):
        if self.active is None:
            (self.root/'delivery.json').unlink(missing_ok=True)
        else:
            atomic(self.root/'delivery.json', self.active)

    def capabilities(self):
        registry = read(self.root/'engines.json', {})
        return {e:dict(ready=bool(v.get('ready')), version=v.get('version', '')) for e,v in registry.items() if e in ENGINES}

    def stop(self, phase, reason):
        kill_group(self.process)
        if self.active:
            reap_job(self.active['job_id'])
        if self.log:
            self.log.close(); self.log = None
        self.process = None
        if self.active:
            current = self.active.get('report', {})
            if self.job:
                current = report(self.root/'results'/self.job['engine']/'state.json', job_id=self.job['id'])
            current.update(phase=phase, reason=reason)
            self.active = dict(job_id=self.active['job_id'], report=current)
            self.persist()

    def start(self, job):
        if (not isinstance(job, dict) or set(job) != {'id','engine','timeout','created'} or
                job['engine'] not in ENGINES or type(job['timeout']) is not int or job['timeout'] != 2700 or
                not isinstance(job['id'], str) or str(uuid.UUID(job['id'])) != job['id']):
            raise ValueError('Неверное задание панели')
        if self.active:
            if job['id'] == self.active['job_id']:
                return
            raise ValueError('На ПК уже есть незавершённое задание')
        registry = read(self.root/'engines.json', {})
        entry = registry.get(job['engine']) or {}
        mem = memory(); minimum = MINIMUM[job['engine']]
        self.active = dict(job_id=job['id'], report=dict(phase='running', reason='Подготовка теста на ПК', version=entry.get('version','')))
        self.job = dict(job, deadline=time.monotonic()+2700)
        if not entry.get('ready') or mem['total_gb'] < minimum-.15 or mem['available_gb'] < minimum-1:
            self.stop('failed', 'Окружение не готово или память ПК изменилась перед запуском'); return
        run_dir = self.root/'results'/job['engine']/job['id']
        if run_dir.exists():
            previous = read(run_dir/'report.json')
            if previous and previous.get('phase') in TERMINAL:
                self.active['report'] = {k:previous[k] for k in FIELDS if k in previous}
            else:
                self.stop('interrupted', 'Это задание уже запускалось; повторное исполнение запрещено')
            self.persist(); return
        self.persist()
        logs = self.root/'logs'; logs.mkdir(exist_ok=True)
        self.log = (logs/(job['id']+'.log')).open('ab')
        args = [entry['python'], '-B', '-u', str(HERE/'job.py'), '--engine', job['engine'],
                '--id', job['id'], '--data', str(self.root/'results')]
        try:
            parent = os.getpid()
            environment = env(self.root, entry.get('source'))
            environment['LAB_WORKER_JOB'] = job['id']
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT,
                start_new_session=True, env=environment,
                preexec_fn=lambda:child_limits(parent))
            self.active.update(pid=self.process.pid, pid_start=process_start(self.process.pid)); self.persist()
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            self.stop('failed', 'Не удалось запустить подготовленный Python движка')

    def tick(self):
        if self.process:
            self.active['report'] = report(self.root/'results'/self.job['engine']/'state.json', job_id=self.job['id'])
            if self.process.poll() is not None:
                current = self.active['report']
                if current.get('phase') not in TERMINAL:
                    current.update(phase='failed', reason='Нативный процесс завершился без итогового отчёта')
                self.stop(current['phase'], current.get('reason', 'Тест завершён'))
            elif time.monotonic() >= self.job['deadline']:
                self.stop('interrupted', 'Лимит теста 45 минут')
        active = self.active and dict(job_id=self.active['job_id'], report=self.active['report'])
        response = self.transport.post(dict(version=1, worker='pc-01', session=self.session,
            memory=memory(), engines=self.capabilities(), active=active))
        self.last_ok = time.monotonic()
        if self.active and response.get('ack') == self.active['job_id']:
            self.active = None; self.job = None; self.persist()
        cancel = response.get('cancel')
        if cancel:
            if self.active and cancel == self.active['job_id']:
                self.stop('cancelled', 'Тест остановлен из панели')
            elif not self.active and isinstance(cancel, str) and str(uuid.UUID(cancel)) == cancel:
                self.active = dict(job_id=cancel, report=dict(phase='cancelled',
                    reason='Отмена получена до локального запуска', version=''))
                self.persist()
        if response.get('job'):
            self.start(response['job'])

    def run(self):
        last_message = 0
        try:
            while True:
                try:
                    self.tick()
                except (OSError, ValueError, KeyError, TypeError):
                    if self.process and time.monotonic()-self.last_ok >= 15:
                        self.stop('interrupted', 'Потеря связи с панелью; автоматического повтора нет')
                    if time.monotonic()-last_message >= 15:
                        print('Нет подтверждённой связи с панелью. Проверь SSH-туннель и код подключения.', flush=True)
                        last_message = time.monotonic()
                time.sleep(2)
        finally:
            if self.process:
                self.stop('interrupted', 'Исполнитель завершён пользователем')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(); root = args.root.absolute()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path = root/'config.json'
    if not config_path.is_file():
        raise SystemExit('Сначала выполни tools/worker_setup.py connect')
    if (config_path.is_symlink() or any(p.is_symlink() for p in config_path.parents) or
            config_path.stat().st_uid != os.getuid() or config_path.stat().st_mode & 0o077):
        raise SystemExit('Конфигурация ПК должна принадлежать тебе и иметь chmod 600')
    config = read(config_path)
    if (not isinstance(config, dict) or set(config)-{'url','key','ca_file'} or
            not isinstance(config.get('url'), str) or not isinstance(config.get('key'), str) or
            not 32 <= len(config['key']) <= 128 or not config['key'].isascii()):
        raise SystemExit('Сначала выполни tools/worker_setup.py connect')
    with (root/'agent.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Исполнитель уже работает')
        print('Исполнитель ПК запущен. Задания запускаются из вкладки Модели.', flush=True)
        try:
            Agent(root, Transport(config)).run()
        except KeyboardInterrupt:
            print('Исполнитель остановлен. Текущий тест отмечен как прерванный.', flush=True)


if __name__ == '__main__':
    main()
