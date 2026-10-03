"""Small local lifecycle broker. Only fixed PAPER engines and approved test units."""
import fcntl
import hashlib
import csv
import io
import json
import math
import os
from pathlib import Path
import pwd
import socket
import socketserver
import struct
import subprocess
import threading
import time
import uuid

ROOT = Path('/var/lib/trading-control')
SOCKET = Path('/run/trading-control/control.sock')
MODEL_UNITS = {'A': 'scalp-paper.service', 'B': 'scalp-model-b.service',
               'C': 'trading-research.service', 'D': 'trading-research.service'}
STATES = {'A': Path('/var/lib/scalp-paper/state.json'),
          'B': Path('/var/lib/scalp-model-b/state.json'),
          'CD': Path('/var/lib/trading-research/report.json')}
ENGINES = {'freqtrade': ('Freqtrade', 'backtest', 3),
           'hummingbot': ('Hummingbot', 'paper', 5),
           'jesse': ('Jesse', 'backtest', 3)}
PLATFORM_STATE = Path('/var/lib/trading-platforms')
CODE = Path('/opt/trading-control')


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o640)
    os.chown(tmp, 0, pwd.getpwnam('tradingbot').pw_gid)
    os.replace(tmp, path)


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def system(*args):
    r = subprocess.run(['/usr/bin/systemctl', *args], capture_output=True, text=True, timeout=12)
    if r.returncode:
        raise ValueError('systemd: ' + r.stderr.strip()[:180])
    return r.stdout.strip()


def unit_status(unit):
    try:
        r = system('show', unit, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState')
        return dict(line.split('=', 1) for line in r.splitlines() if '=' in line)
    except (ValueError, subprocess.TimeoutExpired):
        return dict(LoadState='unknown', ActiveState='unknown')


def memory():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        k, v = line.split(':', 1)
        if k in ('MemTotal', 'MemAvailable'):
            values[k] = int(v.strip().split()[0]) / 1024**2
    return dict(total_gb=round(values['MemTotal'], 2), available_gb=round(values['MemAvailable'], 2))


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.busy = set()
        self.journal = read(ROOT / 'audit.json', [])

    def audit(self, target, action, outcome, message='', request_id=None):
        self.journal.append(dict(time=time.time(), target=target, action=action,
                                 outcome=outcome, message=message, id=request_id))
        self.journal = self.journal[-500:]
        atomic(ROOT / 'audit.json', self.journal)

    def models(self):
        values = {k: read(p) for k, p in STATES.items()}
        units = {u: unit_status(u) for u in set(MODEL_UNITS.values())}
        result = []
        for model, unit in MODEL_UNITS.items():
            raw = values[model] if model in 'AB' else (values['CD'] or {}).get('models', {}).get(model)
            raw = raw or {}
            stamp = raw.get('updated', (values['CD'] or {}).get('updated', 0))
            fresh = isinstance(stamp, (int, float)) and 0 <= time.time() - stamp <= 8
            command = read(ROOT / 'commands' / (model + '.json'), {})
            control = raw.get('control', {})
            installed = (units[unit].get('LoadState') == 'loaded' and
                         (ROOT / 'installed.json').is_file() and
                         (CODE / 'launcher.py').is_file() and
                         Path('/etc/systemd/system', unit + '.d', 'lab-control.conf').is_file())
            position = raw.get('position')
            pending = bool(command and command.get('generation') != control.get('generation'))
            phase = raw.get('phase', 'unknown')
            if units[unit].get('ActiveState') not in ('active', 'activating'):
                phase = 'halted' if phase == 'halted' else 'stopped'
            elif pending and command.get('action') in ('stop', 'restart'):
                phase = 'draining' if position else 'pending'
            elif not fresh:
                phase = 'stale'
            error = control.get('error') or raw.get('reason') or ''
            if units[unit].get('LoadState') == 'not-found':
                phase, error = 'not_installed', 'Модель пока не установлена'
            if (command.get('id') and not pending and
                    not any(e['id'] == command['id'] and e['outcome'] == 'applied' for e in self.journal)):
                self.audit(model, command['action'], 'applied', 'Движок подтвердил состояние', command['id'])
            blocked = bool(raw.get('phase') == 'halted' and position)
            result.append(dict(id=model, name='Модель ' + model, kind='model', installed=installed,
                phase=phase, updated=stamp, fresh=fresh, unit_active=units[unit].get('ActiveState'),
                position=position and {k: position.get(k) for k in ('symbol', 'side', 'opened')},
                equity=raw.get('equity'), closed=raw.get('closed', len(raw.get('trades', []))),
                reason=error, pending=pending, requested=command.get('action'),
                busy=model in self.busy, generation=command.get('generation', 0),
                actions=dict(start=installed and not blocked and raw.get('phase') != 'halted',
                             stop=installed, restart=installed and not blocked and
                             isinstance(raw.get('equity'), (int, float)) and raw['equity'] > 582)))
        return result

    def engines(self):
        registry = read(ROOT / 'platforms.json', {})
        mem = memory()
        result = []
        for engine, (name, mode, minimum) in ENGINES.items():
            configured = registry.get(engine, {})
            unit = unit_status('trading-test-' + engine + '.service')
            installed = bool(configured and unit.get('LoadState') == 'loaded')
            path = Path('/etc/systemd/system/trading-test-' + engine + '.service')
            trusted = installed and not path.is_symlink() and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == configured.get('unit_sha')
            active = unit.get('ActiveState') in ('active', 'activating', 'deactivating')
            s = read(PLATFORM_STATE / engine / 'state.json', {})
            enough = mem['total_gb'] >= minimum - .15 and mem['available_gb'] >= minimum - 1
            phase = 'running' if active else s.get('phase', 'idle') if installed else 'not_installed'
            if not active and phase in ('running', 'starting'):
                phase = 'interrupted'
            runs = read(PLATFORM_STATE / engine / 'runs.json', [])
            reason = ('Служба теста изменилась после подготовки; запуск отключён' if installed and not trusted else
                      'Для теста нужно ' + str(minimum) + ' ГБ RAM с резервом для панели'
                      if not enough else 'Нужна подготовка изолированного движка' if not installed
                      else s.get('reason', 'Готов к отдельному тесту'))
            result.append(dict(id=engine, name=name, kind='engine', mode=mode, installed=installed,
                phase=phase, reason=reason, version=configured.get('version'),
                required_gb=minimum, memory_ok=enough, updated=s.get('updated'),
                metrics=s.get('metrics'), settings=s.get('settings'), runs=runs[-20:][::-1],
                busy=engine in self.busy, generation=len(runs),
                actions=dict(start=trusted and enough and not active, stop=installed and active,
                             restart=trusted and enough and not active)))
        return result

    def status(self):
        with self.lock:
            return dict(status='ok', updated=time.time(), models=self.models(), engines=self.engines(),
                        memory=memory(), audit=self.journal[-30:][::-1])

    def journal_csv(self, engine):
        if engine not in ENGINES:
            raise ValueError('Unknown engine')
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['run_id', 'engine', 'started_utc_unix', 'finished_utc_unix', 'phase',
                         'strategy', 'symbol', 'interval', 'trades', 'paper_fills', 'net_usdt',
                         'equity_usdt', 'reason'])
        for r in read(PLATFORM_STATE / engine / 'runs.json', [])[-100:]:
            m, s = r.get('metrics') or {}, r.get('settings') or {}
            fields = [r.get('id'), engine, r.get('started'), r.get('finished'), r.get('phase'),
                s.get('strategy'), s.get('pair'), s.get('interval'), m.get('count'), m.get('fills'),
                m.get('net'), m.get('equity'), r.get('reason')]
            writer.writerow(["'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in fields])
        return dict(csv='\ufeff' + stream.getvalue())

    def command(self, request):
        if not isinstance(request, dict) or set(request) != {'target', 'action', 'generation'}:
            raise ValueError('Неизвестные поля команды')
        target, action, generation = (request[k] for k in ('target', 'action', 'generation'))
        if (not isinstance(target, str) or target not in (*MODEL_UNITS, *ENGINES) or
                action not in ('start', 'stop', 'restart') or type(generation) is not int):
            raise ValueError('Недопустимая команда')
        with self.lock:
            items = self.models() if target in MODEL_UNITS else self.engines()
            item = next(i for i in items if i['id'] == target)
            if target in self.busy or generation != item['generation']:
                raise ValueError('Состояние изменилось. Обновите карточку и повторите действие')
            if not item['actions'][action]:
                raise ValueError(item['reason'] or 'Действие сейчас недоступно')
            if target in ENGINES and action != 'stop':
                # A single heavyweight test slot, across all three engines.
                if any(unit_status('trading-test-' + x + '.service').get('ActiveState')
                       in ('active', 'activating', 'deactivating') for x in ENGINES):
                    raise ValueError('Другой тест ещё работает. Доступно одно тестовое задание')
                if any(x in self.busy for x in ENGINES):
                    raise ValueError('Другой тест запускается')
            uid = str(uuid.uuid4())
            if target in MODEL_UNITS:
                atomic(ROOT / 'commands' / (target + '.json'),
                       dict(action=action, generation=generation + 1, id=uid, time=time.time()))
            self.busy.add(target)
            self.audit(target, action, 'accepted', request_id=uid)
            threading.Thread(target=self.execute, args=(target, action, uid), daemon=True).start()
            return dict(status='accepted', id=uid, message='Команда принята сервером')

    def execute(self, target, action, uid):
        try:
            if target in MODEL_UNITS:
                # stop is cooperative: the price feed stays up for dependent C/D models.
                if action != 'stop':
                    system('start', MODEL_UNITS[target])
                outcome, message = 'delivered', 'Ожидаем подтверждения движка'
            else:
                unit = 'trading-test-' + target + '.service'
                system('stop' if action == 'stop' else 'start', unit)
                outcome, message = 'delivered', 'Действие передано тестовой службе'
        except (ValueError, subprocess.TimeoutExpired) as exc:
            outcome, message = 'error', str(exc)[:200]
        with self.lock:
            self.busy.discard(target)
            self.audit(target, action, outcome, message, uid)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        uid = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
        if uid not in (0, pwd.getpwnam('tradingbot').pw_uid):
            return
        self.request.settimeout(5)
        try:
            raw = self.rfile.readline(8193)
            if len(raw) > 8192 or not raw.endswith(b'\n'):
                raise ValueError('Слишком длинная команда')
            request = json.loads(raw)
            if request == {'op': 'status'}:
                response = self.server.manager.status()
            elif isinstance(request, dict) and set(request) == {'op', 'engine'} and request['op'] == 'journal':
                response = self.server.manager.journal_csv(request['engine'])
            elif isinstance(request, dict) and set(request) == {'op', 'command'} and request['op'] == 'command':
                response = self.server.manager.command(request['command'])
            else:
                raise ValueError('Неизвестная операция')
        except (ValueError, KeyError, TypeError, OSError) as exc:
            response = dict(status='error', error=str(exc)[:220])
        self.wfile.write(json.dumps(response, ensure_ascii=False, allow_nan=False).encode() + b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


if __name__ == '__main__':
    with (ROOT / 'manager.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        SOCKET.unlink(missing_ok=True)
        with Server(str(SOCKET), Handler) as server:
            server.manager = Manager()
            os.chown(SOCKET, 0, pwd.getpwnam('tradingbot').pw_gid)
            os.chmod(SOCKET, 0o660)
            server.serve_forever()
