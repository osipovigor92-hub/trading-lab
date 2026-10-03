"""One paired PC, one durable test lease. No shell commands or model account access."""
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import time
import uuid

ENGINES = ('freqtrade', 'hummingbot', 'jesse')
VERSIONS = {'freqtrade': '2026.9', 'jesse': '3.2.4'}
MINIMUM = {'freqtrade': 3, 'jesse': 3, 'hummingbot': 5}
TERMINAL = ('completed', 'cancelled', 'failed', 'interrupted')
ACTIVE = ('queued', 'dispatched', 'running', 'cancelling', 'lost')
FRESH = 15


def read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Неверное числовое поле исполнителя')
    return value


def text(value, limit=240):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Неверное текстовое поле исполнителя')
    return value


def identifier(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Неверный идентификатор задания') from None
    return value


def summary(raw):
    """Accept only the small report fields needed by the existing native-test cards."""
    if not isinstance(raw, dict) or set(raw) - {'phase', 'reason', 'version', 'metrics', 'settings'}:
        raise ValueError('Неизвестные поля отчёта ПК')
    if raw.get('phase') not in ('running', *TERMINAL):
        raise ValueError('Неверное состояние теста ПК')
    out = dict(phase=raw['phase'], reason=text(raw.get('reason', '')),
               version=text(raw.get('version', ''), 80), metrics=None, settings=None)
    metrics = raw.get('metrics')
    if metrics is not None:
        allowed = {'count', 'net', 'equity', 'profit_factor', 'drawdown_pct', 'win_rate', 'fills', 'turnover', 'valuation'}
        if not isinstance(metrics, dict) or set(metrics) - allowed:
            raise ValueError('Неизвестные метрики теста ПК')
        result = {}
        for k, v in metrics.items():
            if v is None:
                result[k] = None
            elif k == 'valuation':
                if type(v) is not bool:
                    raise ValueError('Неверный флаг оценки')
                result[k] = v
            elif k in ('count', 'fills'):
                if type(v) is not int or not 0 <= v <= 1000000:
                    raise ValueError('Неверное число исполнений')
                result[k] = v
            else:
                result[k] = number(v, -1e12, 1e12)
        out['metrics'] = result
    settings = raw.get('settings')
    if settings is not None:
        numeric = {'start', 'end', 'fee_pct', 'duration', 'bid_spread_pct', 'ask_spread_pct'}
        strings = {'strategy', 'pair', 'interval', 'mode', 'assumptions'}
        if not isinstance(settings, dict) or set(settings) - numeric - strings:
            raise ValueError('Неизвестные параметры теста ПК')
        out['settings'] = {k: number(v, 0, 1e12) if k in numeric else text(v, 400)
                           for k, v in settings.items()}
    return out


class Remote:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / 'pc-state.json'
        self.key_path = self.root / 'pc-key.json'
        data = read(self.path, {})
        self.broken = self.path.exists() and not self.valid_state(data)
        self.data = data if isinstance(data, dict) and not self.broken else {}
        self.data.setdefault('generation', 0)
        self.data.setdefault('runs', [])

    @staticmethod
    def valid_state(data):
        try:
            if (not isinstance(data, dict) or type(data.get('generation')) is not int or
                    data['generation'] < 0 or not isinstance(data.get('runs'), list)):
                return False
            number(data.get('seen', 0), 0, 1e12)
            if data.get('session'):
                identifier(data['session'])
            memory = data.get('memory') or {'total_gb':0, 'available_gb':0}
            total = number(memory['total_gb'], 0, 4096)
            number(memory['available_gb'], 0, total)
            if not isinstance(data.get('engines', {}), dict):
                return False
            for engine, capability in data.get('engines', {}).items():
                if engine not in ENGINES or type(capability.get('ready')) is not bool:
                    return False
                text(capability['version'], 80)
            records = list(data['runs']) + ([data['job']] if data.get('job') else [])
            for record in records:
                identifier(record['id'])
                if record['engine'] not in ENGINES or record['phase'] not in (*ACTIVE, *TERMINAL):
                    return False
                number(record['created'], 0, 1e12)
                if record.get('session'):
                    identifier(record['session'])
                if record['phase'] in ('running', *TERMINAL):
                    summary({k:v for k,v in record.items() if k in ('phase','reason','version','metrics','settings')})
            return True
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def save(self):
        atomic(self.path, self.data)

    def configured(self):
        key = read(self.key_path, {})
        return (isinstance(key, dict) and key.get('worker') == 'pc-01' and
                isinstance(key.get('sha256'), str) and len(key['sha256']) == 64)

    def current(self, now=None):
        now = time.time() if now is None else now
        seen = self.data.get('seen', 0)
        return not self.broken and self.configured() and type(seen) in (int, float) and 0 <= now - seen <= FRESH

    def active(self):
        job = self.data.get('job')
        return job if isinstance(job, dict) and job.get('phase') in ACTIVE else None

    def status(self, now=None):
        now = time.time() if now is None else now
        job = self.active()
        seen = self.data.get('seen', 0)
        return dict(id='pc-01', name='Мой ПК', configured=self.configured(), online=self.current(now),
                    last_seen=seen or None, memory=self.data.get('memory'),
                    engines=self.data.get('engines', {}),
                    job=job and {k: job.get(k) for k in ('id', 'engine', 'phase', 'created', 'cancel')})

    def item(self, engine, now=None):
        now = time.time() if now is None else now
        online = self.current(now)
        capability = self.data.get('engines', {}).get(engine, {})
        installed = capability.get('ready') is True
        mem = self.data.get('memory') or {}
        enough = (online and mem.get('total_gb', 0) >= MINIMUM[engine] - .15 and
                  mem.get('available_gb', 0) >= MINIMUM[engine] - 1)
        job = self.active()
        mine = job and job['engine'] == engine
        runs = [r for r in self.data['runs'] if r['engine'] == engine][-100:]
        last = job if mine else runs[-1] if runs else {}
        phase = ('lost' if not online else 'starting' if job['phase'] in ('queued', 'dispatched')
                 else job['phase']) if mine else last.get('phase', 'idle' if installed else 'not_installed')
        reason = ('Состояние очереди ПК повреждено; требуется восстановление' if self.broken else
                  'ПК недоступен; исполнение задания не подтверждено' if mine and not online else
                  'Остановка передана ПК; ожидаем окончания процесса' if mine and job.get('cancel') else
                  'Подключи исполнитель на ПК' if not self.configured() else
                  'ПК не подключён или нет свежего ответа' if not online else
                  'Окружение на ПК не подготовлено' if not installed else
                  'На ПК недостаточно свободной памяти' if not enough and not mine else
                  last.get('reason', 'ПК готов к отдельному тесту'))
        return dict(id=engine, kind='engine', execution='pc', installed=installed, memory_ok=bool(enough),
                    required_gb=MINIMUM[engine], version=capability.get('version'), phase=phase,
                    reason=reason, updated=self.data.get('seen'), metrics=last.get('metrics'),
                    settings=last.get('settings'), runs=list(reversed(runs[-20:])),
                    generation=self.data['generation'], busy=False, test_active=bool(mine),
                    actions=dict(start=bool(online and installed and enough and not job),
                                 restart=bool(online and installed and enough and not job), stop=bool(mine)))

    def command(self, engine, action, generation, now=None):
        now = time.time() if now is None else now
        item = self.item(engine, now)
        if generation != self.data['generation']:
            raise ValueError('Состояние ПК изменилось. Обновите карточку')
        if not item['actions'].get(action):
            raise ValueError(item['reason'])
        request_id = str(uuid.uuid4())
        if action == 'stop':
            job = self.data['job']
            if job['phase'] == 'queued':
                job.update(phase='cancelled', reason='Отменено до передачи исполнителю', finished=now)
                self.data['runs'].append({k: v for k, v in job.items() if k not in ('session', 'cancel')})
                self.data['runs'] = self.data['runs'][-300:]
                self.data['job'] = None
            else:
                job['cancel'] = True
                job['phase'] = 'cancelling'
        else:
            self.data['job'] = dict(id=request_id, engine=engine, phase='queued', created=now,
                session=self.data['session'], cancel=False, reason='Задание ожидает исполнителя ПК',
                execution='pc', metrics=None, settings=None)
        self.data['generation'] += 1
        self.save()
        return request_id

    def exchange(self, key, payload, now=None):
        now = time.time() if now is None else now
        configured = read(self.key_path, {})
        if (not isinstance(key, str) or not 32 <= len(key) <= 128 or not key.isascii() or
                not isinstance(configured, dict) or not isinstance(configured.get('sha256'), str) or
                not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), configured['sha256'])):
            raise ValueError('Исполнитель не авторизован')
        if self.broken:
            raise ValueError('Состояние очереди ПК повреждено; требуется восстановление')
        if (not isinstance(payload, dict) or set(payload) != {'version', 'worker', 'session', 'memory', 'engines', 'active'}
                or type(payload['version']) is not int or payload['version'] != 1 or
                payload['worker'] != configured.get('worker')):
            raise ValueError('Неверный протокол исполнителя')
        session = identifier(payload['session'])
        mem = payload['memory']
        if not isinstance(mem, dict) or set(mem) != {'total_gb', 'available_gb'}:
            raise ValueError('Неверный отчёт памяти ПК')
        total = number(mem['total_gb'], 0, 4096)
        memory = dict(total_gb=total, available_gb=number(mem['available_gb'], 0, total))
        engines = payload['engines']
        if not isinstance(engines, dict) or set(engines) - set(ENGINES):
            raise ValueError('Неизвестный движок ПК')
        capabilities = {}
        for engine, value in engines.items():
            if not isinstance(value, dict) or set(value) != {'ready', 'version'} or type(value['ready']) is not bool:
                raise ValueError('Неверная подготовка движка ПК')
            version = text(value['version'], 80)
            capabilities[engine] = dict(ready=value['ready'] and
                (engine not in VERSIONS or version == VERSIONS[engine]), version=version)
        active = payload['active']
        if active is not None:
            if not isinstance(active, dict) or set(active) != {'job_id', 'report'}:
                raise ValueError('Неверное подтверждение задания ПК')
            active = dict(job_id=identifier(active['job_id']), report=summary(active['report']))
        old_session = self.data.get('session')
        if old_session and old_session != session and 0 <= now - self.data.get('seen', 0) <= 30:
            raise ValueError('Другой экземпляр исполнителя ПК ещё подключён')
        job = self.active()
        ack = None
        if active is not None:
            if not job or active['job_id'] != job['id']:
                # Retried terminal delivery is acknowledged without a duplicate journal row.
                if any(r['id'] == active['job_id'] for r in self.data['runs']) and active['report']['phase'] in TERMINAL:
                    ack = active['job_id']
                else:
                    raise ValueError('Задание не соответствует сохранённой очереди')
            elif job['session'] != session and active['report']['phase'] not in TERMINAL:
                raise ValueError('Новый исполнитель не может продолжить старое задание')
            else:
                job.update(active['report'])
                if job.get('cancel') and job['phase'] == 'running':
                    job['phase'] = 'cancelling'
                if job['phase'] in TERMINAL:
                    job.update(finished=now, execution='pc')
                    self.data['runs'].append({k: v for k, v in job.items() if k not in ('session', 'cancel')})
                    self.data['runs'] = self.data['runs'][-300:]
                    self.data['job'] = None
                    self.data['generation'] += 1
                    ack = job['id']
                    job = None
        elif job and old_session != session:
            # Reboot is not proof that the old native process has stopped.
            job['phase'] = 'lost'
            job['cancel'] = True
            job['reason'] = 'Новый сеанс ПК; нужно подтверждение завершения старого задания'
        if job and job['phase'] in ('queued', 'dispatched') and now - job['created'] > 60:
            if job['phase'] == 'queued':
                job.update(phase='interrupted', reason='ПК не забрал задание за 60 секунд', finished=now)
                self.data['runs'].append({k: v for k, v in job.items() if k not in ('session', 'cancel')})
                self.data['runs'] = self.data['runs'][-300:]
                self.data['job'] = None
                self.data['generation'] += 1
                job = None
            else:
                job['phase'] = 'lost'
                job['cancel'] = True
        self.data.update(session=session, seen=now, memory=memory, engines=capabilities)
        offer = None
        if job and not active and job['session'] == session and job['phase'] in ('queued', 'dispatched') and not job['cancel']:
            job['phase'] = 'dispatched'
            job.setdefault('started', now)
            offer = dict(id=job['id'], engine=job['engine'], timeout=2700, created=job['created'])
        self.save()
        return dict(status='ok', version=1, job=offer, ack=ack,
                    cancel=job['id'] if job and job.get('cancel') else None)
