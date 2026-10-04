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
import re
import socket
import socketserver
import struct
import subprocess
import threading
import time
import uuid
from remote import Remote

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
EXPERIMENT_STORAGE = {
    'A': dict(root=Path('/var/lib/scalp-paper'), unit=MODEL_UNITS['A'],
              files=('state.json', 'journal-report.json')),
    'B': dict(root=Path('/var/lib/scalp-model-b'), unit=MODEL_UNITS['B'],
              files=('state.json', 'history.sqlite', 'history.sqlite-wal', 'history.sqlite-shm')),
    # C and D share one PAPER executor and one journal. They are always archived and
    # started together, never partially reset underneath the other model.
    'CD': dict(root=Path('/var/lib/trading-research'), unit=MODEL_UNITS['C'],
               files=('journal.sqlite', 'journal.sqlite-wal', 'journal.sqlite-shm',
                      'report.json', 'journal-c.csv', 'journal-d.csv')),
}
CAPITAL_LIMITS = (10.0, 1_000_000.0)


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.chmod(tmp, 0o640)
    os.chown(tmp, 0, pwd.getpwnam('tradingbot').pw_gid)
    os.replace(tmp, path)


def restore_bytes(path, body):
    """Rollback helper for controller-owned JSON files only."""
    if body is None:
        path.unlink(missing_ok=True)
        return
    tmp = path.with_suffix('.rollback')
    with tmp.open('wb') as f:
        f.write(body)
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


def experiment_group(model):
    return 'CD' if model in ('C', 'D') else model


def finite_number(value, name, low, high, *, inclusive_high=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Параметр ' + name + ' должен быть числом')
    value = float(value)
    if value < low or value > high or (not inclusive_high and value >= high):
        raise ValueError('Параметр ' + name + ' вне допустимого диапазона')
    return value


def experiment_settings(value):
    """Accept only the three PAPER test settings; no arbitrary model config."""
    if not isinstance(value, dict) or set(value) != {'capital', 'notional', 'max_loss'}:
        raise ValueError('Для нового теста укажи бюджет, размер входа и лимит потерь')
    capital = finite_number(value['capital'], 'бюджет', *CAPITAL_LIMITS)
    notional = finite_number(value['notional'], 'размер входа', 1.0, capital)
    max_loss = finite_number(value['max_loss'], 'лимит потерь', 0.01, capital, inclusive_high=False)
    return dict(capital=capital, notional=notional, max_loss=max_loss)


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.busy = set()
        self.journal = read(ROOT / 'audit.json', [])
        self.remote = Remote(ROOT)

    def audit(self, target, action, outcome, message='', request_id=None):
        self.journal.append(dict(time=time.time(), target=target, action=action,
                                 outcome=outcome, message=message, id=request_id))
        self.journal = self.journal[-500:]
        atomic(ROOT / 'audit.json', self.journal)

    def experiment_path(self, model):
        return ROOT / 'experiments' / (experiment_group(model) + '.json')

    def experiment_record(self, model):
        """Return a small, validated display record. A damaged file is never applied."""
        record = read(self.experiment_path(model), {})
        try:
            if (not isinstance(record, dict) or set(record) != {'version', 'id', 'created', 'settings'} or
                    record['version'] != 1 or not isinstance(record['id'], str) or
                    not re.fullmatch(r'[A-Z]{1,2}-[0-9T-]{15,32}-[0-9a-f]{8}', record['id']) or
                    not isinstance(record['created'], (int, float)) or isinstance(record['created'], bool)):
                return None
            return dict(id=record['id'], created=float(record['created']),
                        settings=experiment_settings(record['settings']))
        except (ValueError, TypeError):
            return None

    def experiment_view(self, model, raw, values):
        group = experiment_group(model)
        source = raw.get('config') if isinstance(raw.get('config'), dict) else {}
        if model in ('C', 'D'):
            source = (values.get('CD') or {}).get('config', source)
        settings = {}
        for name in ('capital', 'notional', 'max_loss'):
            value = source.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                settings[name] = float(value)
        record = self.experiment_record(model)
        if not settings and record:
            settings = dict(record['settings'])
        root = EXPERIMENT_STORAGE[group]['root']
        archive = root / 'archives'
        archived = 0
        try:
            if archive.is_dir() and not archive.is_symlink():
                archived = sum(p.is_dir() and not p.is_symlink() for p in archive.iterdir())
        except OSError:
            pass
        return dict(group=group, id=record and record['id'], created=record and record['created'],
                    settings=settings, archived=archived)

    def new_run_ready(self, model, values):
        group = experiment_group(model)
        if group == 'CD':
            rows = list((values.get('CD') or {}).get('models', {}).values())
        else:
            rows = [values.get(model) or {}]
        return bool(rows) and all(isinstance(row, dict) and not row.get('position') and
                                  row.get('phase') in ('paused', 'halted') for row in rows)

    def new_run_note(self, model, values):
        group = experiment_group(model)
        if group == 'CD':
            rows = list((values.get('CD') or {}).get('models', {}).values())
            prefix = 'C и D используют общий журнал: '
        else:
            rows = [values.get(model) or {}]
            prefix = ''
        if not rows or any(not isinstance(row, dict) for row in rows):
            return prefix + 'нет сохранённого состояния PAPER-теста'
        if any(row.get('position') for row in rows):
            return prefix + 'сначала дождись штатного завершения PAPER-позиции'
        if not all(row.get('phase') in ('paused', 'halted') for row in rows):
            return prefix + 'сначала нажми «Отключить», чтобы запретить новые входы'
        return prefix + 'готов к новому тесту; прошлый журнал будет сохранён'

    def model_busy(self, model):
        return experiment_group(model) in self.busy

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
            raw_phase = raw.get('phase', 'unknown')
            pending = bool(command and command.get('generation') != control.get('generation'))
            phase = raw_phase
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
            blocked = bool(raw_phase == 'halted' and position)
            can_new_run = installed and self.new_run_ready(model, values) and not self.model_busy(model)
            result.append(dict(id=model, name='Модель ' + model, kind='model', installed=installed,
                phase=phase, updated=stamp, fresh=fresh, unit_active=units[unit].get('ActiveState'),
                position=position and {k: position.get(k) for k in ('symbol', 'side', 'opened')},
                equity=raw.get('equity'), closed=raw.get('closed', len(raw.get('trades', []))),
                reason=error, pending=pending, requested=command.get('action'),
                busy=self.model_busy(model), generation=command.get('generation', 0),
                experiment=self.experiment_view(model, raw, values),
                new_run_note=self.new_run_note(model, values),
                actions=dict(start=installed and not blocked and raw.get('phase') != 'halted',
                             stop=installed, restart=installed and not blocked and
                             isinstance(raw.get('equity'), (int, float)) and raw['equity'] > 582,
                             new_run=can_new_run)))
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
            starting = active and s.get('phase') not in ('running', 'starting')
            if starting:
                phase = 'starting'
            if not active and phase in ('running', 'starting'):
                phase = 'interrupted'
            runs = read(PLATFORM_STATE / engine / 'runs.json', [])
            reason = ('Служба теста изменилась после подготовки; запуск отключён' if installed and not trusted else
                      'Для теста нужно ' + str(minimum) + ' ГБ RAM с резервом для панели'
                      if not enough else 'Нужна подготовка изолированного движка' if not installed
                      else 'Подготовка нового тестового запуска' if starting else s.get('reason', 'Готов к отдельному тесту'))
            item = dict(id=engine, name=name, kind='engine', mode=mode, installed=installed,
                phase=phase, reason=reason, version=configured.get('version'),
                required_gb=minimum, memory_ok=enough, updated=s.get('updated'),
                metrics=None if starting else s.get('metrics'), settings=None if starting else s.get('settings'), runs=runs[-20:][::-1],
                busy=engine in self.busy, generation=len(runs),
                actions=dict(start=trusted and enough and not active, stop=installed and active,
                             restart=trusted and enough and not active))
            pc = self.remote.item(engine)
            item['execution'] = 'vds'
            item['test_active'] = active
            item['executors'] = dict(vds=dict(item), pc=pc)
            item['test_active'] = active or pc['test_active']
            result.append(item)
        return result

    def status(self):
        with self.lock:
            return dict(status='ok', updated=time.time(), models=self.models(), engines=self.engines(),
                        memory=memory(), worker=self.remote.status(), audit=self.journal[-30:][::-1])

    def journal_csv(self, engine):
        if engine not in ENGINES:
            raise ValueError('Unknown engine')
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['run_id', 'engine', 'execution', 'started_utc_unix', 'finished_utc_unix', 'phase',
                         'strategy', 'symbol', 'interval', 'trades', 'paper_fills', 'net_usdt',
                         'equity_usdt', 'reason'])
        runs = read(PLATFORM_STATE / engine / 'runs.json', [])[-100:]
        runs += [r for r in self.remote.data['runs'] if r['engine'] == engine][-100:]
        for r in sorted(runs, key=lambda r: r.get('started', r.get('created', 0))):
            m, s = r.get('metrics') or {}, r.get('settings') or {}
            fields = [r.get('id'), engine, r.get('execution', 'vds'), r.get('started', r.get('created')), r.get('finished'), r.get('phase'),
                s.get('strategy'), s.get('pair'), s.get('interval'), m.get('count'), m.get('fills'),
                m.get('net'), m.get('equity'), r.get('reason')]
            writer.writerow(["'"+v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in fields])
        return dict(csv='\ufeff' + stream.getvalue())

    def archivable(self, group):
        root = EXPERIMENT_STORAGE[group]['root']
        if group == 'CD':
            rows = list((read(root / 'report.json', {}) or {}).get('models', {}).values())
        else:
            rows = [read(root / 'state.json', {}) or {}]
        return bool(rows) and all(isinstance(row, dict) and not row.get('position') for row in rows)

    def command_generations(self, group):
        targets = ('C', 'D') if group == 'CD' else (group,)
        result = {}
        for target in targets:
            previous = read(ROOT / 'commands' / (target + '.json'), {})
            generation = previous.get('generation', 0) if isinstance(previous, dict) else 0
            if type(generation) is not int or generation < 0:
                raise ValueError('Некорректное предыдущее состояние управления')
            result[target] = generation + 1
        return result

    def new_experiment(self, target, settings, uid):
        """Archive a stopped PAPER run, then start a clean, explicitly configured one."""
        group = experiment_group(target)
        storage = EXPERIMENT_STORAGE[group]
        root, unit = storage['root'], storage['unit']
        archive_root = root / 'archives'
        record_path = self.experiment_path(target)
        command_paths = {model: ROOT / 'commands' / (model + '.json')
                         for model in (('C', 'D') if group == 'CD' else (target,))}
        previous_record = None
        previous_commands = {}
        was_active = unit_status(unit).get('ActiveState') in ('active', 'activating', 'deactivating')
        moved = []
        archive = None
        try:
            if root.is_symlink() or archive_root.is_symlink() or record_path.is_symlink():
                raise ValueError('Недопустимая ссылка в пути PAPER-теста')
            for path in command_paths.values():
                if path.is_symlink():
                    raise ValueError('Недопустимая ссылка в пути управления')
            previous_record = record_path.read_bytes() if record_path.exists() else None
            previous_commands = {model: path.read_bytes() if path.exists() else None
                                 for model, path in command_paths.items()}
            # The cooperative Stop command has already disabled entries. Stopping the
            # unit here closes SQLite/WAL files before moving them; no position is ever
            # fabricated or closed by this operation.
            system('stop', unit)
            if not self.archivable(group):
                raise ValueError('PAPER-позиция появилась или не завершена; новый тест отменён')
            archive_root.mkdir(mode=0o750, parents=True, exist_ok=True)
            os.chown(archive_root, 0, pwd.getpwnam('tradingbot').pw_gid)
            archive = archive_root / (group + '-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uid[:8])
            archive.mkdir(mode=0o750)
            os.chown(archive, 0, pwd.getpwnam('tradingbot').pw_gid)
            for name in storage['files']:
                source = root / name
                if not source.exists():
                    continue
                if source.is_symlink():
                    raise ValueError('Недопустимая ссылка в архиве PAPER-теста')
                destination = archive / name
                os.replace(source, destination)
                moved.append((source, destination))
            record = dict(version=1, id=group + '-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime()) + '-' + uid[:8],
                          created=time.time(), settings=settings)
            atomic(archive / 'experiment.json', record)
            record_path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            os.chown(record_path.parent, 0, pwd.getpwnam('tradingbot').pw_gid)
            atomic(record_path, record)
            for model, generation in self.command_generations(group).items():
                atomic(command_paths[model], dict(action='start', generation=generation, id=uid, time=time.time()))
            system('start', unit)
            message = ('C/D: ' if group == 'CD' else '') + 'новый PAPER-тест запущен; архив ' + archive.name
            outcome = 'delivered'
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            # A failed reset restores the previous state/configuration before the
            # process can be started again. Archives are a move, not a deletion.
            try:
                system('stop', unit)
            except (ValueError, subprocess.TimeoutExpired):
                pass
            for source, destination in reversed(moved):
                if destination.exists() and not source.exists():
                    os.replace(destination, source)
            try:
                restore_bytes(record_path, previous_record)
                for model, path in command_paths.items():
                    restore_bytes(path, previous_commands.get(model))
            except (OSError, KeyError):
                pass
            if was_active:
                try:
                    system('start', unit)
                except (ValueError, subprocess.TimeoutExpired):
                    pass
            outcome, message = 'error', str(exc)[:200]
        with self.lock:
            self.busy.discard(group)
            self.audit(target, 'new_run', outcome, message, uid)

    def command(self, request):
        if not isinstance(request, dict):
            raise ValueError('Неизвестные поля команды')
        is_new_run = request.get('action') == 'new_run'
        allowed = {'target', 'action', 'generation', 'experiment'} if is_new_run else {'target', 'action', 'generation'}
        fields_ok = set(request) == allowed if is_new_run else set(request) in (allowed, allowed | {'execution'})
        if not fields_ok:
            raise ValueError('Неизвестные поля команды')
        target, action, generation = (request[k] for k in ('target', 'action', 'generation'))
        execution = request.get('execution', 'vds')
        if (not isinstance(target, str) or target not in (*MODEL_UNITS, *ENGINES) or
                action not in ('start', 'stop', 'restart', 'new_run') or type(generation) is not int or
                execution not in ('vds', 'pc') or (target in MODEL_UNITS and 'execution' in request)):
            raise ValueError('Недопустимая команда')
        if action == 'new_run' and target not in MODEL_UNITS:
            raise ValueError('Новый прогон доступен только для PAPER-моделей')
        with self.lock:
            items = self.models() if target in MODEL_UNITS else self.engines()
            item = next(i for i in items if i['id'] == target)
            if target in ENGINES and execution == 'pc':
                item = item.get('executors', {}).get('pc') or self.remote.item(target)
            busy_key = experiment_group(target) if target in MODEL_UNITS else target
            if busy_key in self.busy or generation != item['generation']:
                raise ValueError('Состояние изменилось. Обновите карточку и повторите действие')
            if action == 'new_run':
                settings = experiment_settings(request['experiment'])
                if not item['actions'].get('new_run'):
                    raise ValueError(item.get('new_run_note') or 'Новый тест сейчас недоступен')
                if target in ('C', 'D'):
                    siblings = [row for row in items if row['id'] in ('C', 'D')]
                    if any(row.get('pending') or row.get('busy') for row in siblings):
                        raise ValueError('C/D ещё применяют предыдущую команду')
                uid = str(uuid.uuid4())
                self.busy.add(busy_key)
                self.audit(target, action, 'accepted', 'Сохраняем текущий журнал и готовим новый PAPER-тест', uid)
                threading.Thread(target=self.new_experiment, args=(target, settings, uid), daemon=True).start()
                return dict(status='accepted', id=uid, message='Новый PAPER-тест принят')
            if not item['actions'][action]:
                raise ValueError(item['reason'] or 'Действие сейчас недоступно')
            if target in ENGINES and action != 'stop':
                if self.remote.active():
                    raise ValueError('Другой тест ещё работает на ПК или его завершение не подтверждено')
                # A single heavyweight test slot, across all three engines.
                if any(unit_status('trading-test-' + x + '.service').get('ActiveState')
                       in ('active', 'activating', 'deactivating') for x in ENGINES):
                    raise ValueError('Другой тест ещё работает. Доступно одно тестовое задание')
                if any(x in self.busy for x in ENGINES):
                    raise ValueError('Другой тест запускается')
            if target in ENGINES and execution == 'pc':
                uid = self.remote.command(target, action, generation)
                self.audit(target, action, 'accepted', 'ПК: команда сохранена в очереди', uid)
                self.audit(target, action, 'delivered', 'ПК: ожидаем подтверждения исполнителя', uid)
                return dict(status='accepted', id=uid, message='Задание принято для ПК')
            uid = str(uuid.uuid4())
            if target in MODEL_UNITS:
                atomic(ROOT / 'commands' / (target + '.json'),
                       dict(action=action, generation=generation + 1, id=uid, time=time.time()))
            self.busy.add(busy_key)
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
            self.busy.discard(experiment_group(target) if target in MODEL_UNITS else target)
            self.audit(target, action, outcome, message, uid)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        uid = struct.unpack('3i', self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
        if uid not in (0, pwd.getpwnam('tradingbot').pw_uid):
            return
        self.request.settimeout(5)
        try:
            raw = self.rfile.readline(65537)
            if len(raw) > 65536 or not raw.endswith(b'\n'):
                raise ValueError('Слишком длинная команда')
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError('Недопустимый запрос')
            if request.get('op') != 'worker' and len(raw) > 8192:
                raise ValueError('Слишком длинная команда')
            if request == {'op': 'status'}:
                response = self.server.manager.status()
            elif isinstance(request, dict) and set(request) == {'op', 'engine'} and request['op'] == 'journal':
                response = self.server.manager.journal_csv(request['engine'])
            elif isinstance(request, dict) and set(request) == {'op', 'command'} and request['op'] == 'command':
                response = self.server.manager.command(request['command'])
            elif isinstance(request, dict) and set(request) == {'op', 'key', 'payload'} and request['op'] == 'worker':
                with self.server.manager.lock:
                    response = self.server.manager.remote.exchange(request['key'], request['payload'])
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
