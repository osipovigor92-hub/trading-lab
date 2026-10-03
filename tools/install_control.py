"""Install cooperative model wrappers once; do not overwrite engine code or saved state."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import deploy

REPO = Path(__file__).resolve().parents[1]
CODE = Path('/opt/trading-control')
ROOT = Path('/var/lib/trading-control')
MANIFEST = ROOT / 'installed.json'
UNIT = Path('/etc/systemd/system/trading-control.service')
SOURCES = {'A': ('src/scalp-paper/paper.py', Path('/var/lib/scalp-paper/state.json'), 'scalp-paper.service'),
           'B': ('src/scalp-model-b/model_b.py', Path('/var/lib/scalp-model-b/state.json'), 'scalp-model-b.service'),
           'CD': ('integrations/research/engine.py', Path('/var/lib/trading-research/report.json'), 'trading-research.service')}


def targets():
    source = REPO / 'integrations/control'
    result = {CODE / n: (source / n).read_bytes() for n in ('runtime.py', 'launcher.py', 'manager.py', 'remote.py')}
    result[UNIT] = (source / UNIT.name).read_bytes()
    for model, (_, _, unit) in SOURCES.items():
        result[Path('/etc/systemd/system', unit + '.d', 'lab-control.conf')] = (
            '[Service]\nExecStart=\nExecStart=/usr/bin/python3 -B -u /opt/trading-control/launcher.py ' + model + '\n').encode()
    return result


def preflight(files, saved):
    for path, body in files.items():
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise RuntimeError('Symlink: ' + str(path))
        if saved:
            wanted = hashlib.sha256(body).hexdigest()
            if saved['files'].get(str(path)) != wanted or deploy.digest(path) != wanted:
                raise RuntimeError('Управление изменилось: нужна отдельная миграция ' + str(path))
        elif path.exists():
            raise RuntimeError('Путь существует без записи установщика: ' + str(path))


def snapshots():
    result = {}
    for model, (_, state, unit) in SOURCES.items():
        if deploy.active(unit):
            result[model] = json.loads(state.read_text())
    return result


def safe(states, now):
    for model, state in states.items():
        if not isinstance(state.get('updated'), (int, float)) or not 0 <= now - state['updated'] <= 6:
            return False
        rows = state.get('models', {}).values() if model == 'CD' else (state,)
        for row in rows:
            if row.get('position'):
                return False
            if row.get('phase') == 'halted':
                continue
            if model == 'A' and row.get('cooldown_until', 0) - now < 15:
                return False
            if any(r.get('signal') in ('LONG', 'SHORT') or r.get('confirmed')
                   for r in row.get('observations', [])):
                return False
    return True


def upgrade_controller(files, saved, revision, owner):
    """The one approved migration changes the broker only, never model wrappers/state."""
    manager = CODE / 'manager.py'
    remote = CODE / 'remote.py'
    old_sha = '7ce07edd39e6adcd5c93ea942f4231bf2420b6531ef30ba60f63b1691de485a1'
    if (set(saved.get('files', {})) != {str(p) for p in files if p != remote} or
            saved['files'].get(str(manager)) != old_sha or remote.exists()):
        raise RuntimeError('Эта версия управления требует отдельной миграции')
    for path, body in files.items():
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise RuntimeError('Symlink: ' + str(path))
        if path != remote and deploy.digest(path) != saved['files'][str(path)]:
            raise RuntimeError('Установленный файл изменён: ' + str(path))
        if path not in (manager, remote) and hashlib.sha256(body).hexdigest() != saved['files'][str(path)]:
            raise RuntimeError('Миграция не должна менять обёртки моделей: ' + str(path))
    if any(deploy.active('trading-test-' + engine + '.service') for engine in ('freqtrade', 'jesse', 'hummingbot')):
        raise RuntimeError('Дождитесь окончания внешнего теста')
    backup = Path(tempfile.mkdtemp(prefix='pc-control-backup-', dir='/opt'))
    shutil.copy2(manager, backup/'manager.py')
    shutil.copy2(MANIFEST, backup/'installed.json')
    was_active = deploy.active('trading-control.service')
    try:
        deploy.system('stop', 'trading-control.service')
        deploy.atomic(manager, files[manager]); deploy.atomic(remote, files[remote])
        deploy.atomic(MANIFEST, json.dumps(dict(revision=revision, files={str(p):hashlib.sha256(b).hexdigest() for p,b in files.items()})).encode(), 0o640)
        os.chown(MANIFEST, 0, owner.pw_gid)
        deploy.system('start', 'trading-control.service')
        sys.path.insert(0, str(REPO/'src/trading-panel'))
        import control_client
        for attempt in range(20):
            try:
                response = control_client.call(dict(op='status'))
                if response.get('status') == 'ok' and isinstance(response.get('worker'), dict):
                    break
            except (OSError, ValueError):
                pass
            if attempt == 19:
                raise RuntimeError('Обновлённый контроллер не ответил')
            time.sleep(.5)
    except BaseException:
        deploy.system('stop', 'trading-control.service')
        deploy.atomic(manager, (backup/'manager.py').read_bytes())
        remote.unlink(missing_ok=True)
        deploy.atomic(MANIFEST, (backup/'installed.json').read_bytes(), 0o640)
        os.chown(MANIFEST, 0, owner.pw_gid)
        if was_active:
            deploy.system('start', 'trading-control.service')
        raise
    print('Исполнитель ПК поддерживается. Обновлён только контроллер; A/B/C/D не перезапускались.')
    print('Резервная копия:', backup)


def install(files, revision, owner, timeout=600, upgrade=False):
    for path in (ROOT, ROOT/'commands', MANIFEST):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise RuntimeError('Недопустимая ссылка в пути управления: ' + str(path))
    saved = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    try:
        preflight(files, saved)
    except RuntimeError:
        if saved and upgrade:
            upgrade_controller(files, saved, revision, owner)
            return
        raise
    if saved:
        if not deploy.active('trading-control.service'):
            deploy.system('start', 'trading-control.service')
        print('Управление уже установлено. Модели не перезапускались.')
        return
    for model, (source, _, _) in SOURCES.items():
        path = deploy.destination(source) if source.startswith('src/') else Path('/opt/trading-research/engine.py')
        if path.is_file() and deploy.digest(path) != deploy.digest(REPO / source):
            raise RuntimeError('Локальная версия модели отличается: ' + str(path))
    print('Ожидаю паузы между PAPER-сделками для первой установки (до 10 минут)…', flush=True)
    deadline, next_notice = time.monotonic() + timeout, 0
    while True:
        states = snapshots()
        if safe(states, time.time()):
            time.sleep(1)
            if safe(snapshots(), time.time()):
                break
        if time.monotonic() >= deadline:
            raise RuntimeError('Пауза не найдена. Исходники и службы не изменены; повторите установку позже')
        if time.monotonic() >= next_notice:
            print('Ожидание безопасной паузы: ' + ', '.join(states), flush=True)
            next_notice = time.monotonic() + 30
        time.sleep(1)
    active = [unit for _, _, unit in SOURCES.values() if deploy.active(unit)]
    backup = Path(tempfile.mkdtemp(prefix='model-control-backup-', dir='/opt'))
    for key, (_, path, _) in SOURCES.items():
        if path.is_file():
            shutil.copy2(path, backup / (key + '-state.json'))
    stopped = []
    try:
        for unit in reversed(active):
            deploy.system('stop', unit)
            stopped.append(unit)
        # Re-read after termination: never silently adopt a position opened during preflight.
        for model, (_, state, unit) in SOURCES.items():
            if unit in stopped:
                s = json.loads(state.read_text())
                rows = s['models'].values() if model == 'CD' else (s,)
                if any(m.get('position') for m in rows):
                    raise RuntimeError('Позиция появилась во время установки; установка отменена, её состояние сохранено')
        for folder in (ROOT, ROOT / 'commands'):
            folder.mkdir(mode=0o750, parents=True, exist_ok=True)
            os.chown(folder, 0, owner.pw_gid); os.chmod(folder, 0o750)
        CODE.mkdir(mode=0o755, exist_ok=True)
        for path, body in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            deploy.atomic(path, body)
        deploy.atomic(MANIFEST, json.dumps(dict(revision=revision, files={str(p): hashlib.sha256(b).hexdigest() for p, b in files.items()})).encode(), 0o640)
        os.chown(MANIFEST, 0, owner.pw_gid)
        deploy.system('daemon-reload')
        deploy.system('enable', '--now', 'trading-control.service')
        for unit in active:
            deploy.system('start', unit)
        sys.path.insert(0, str(REPO / 'src/trading-panel'))
        import control_client
        for i in range(20):
            try:
                r = control_client.call(dict(op='status'))
                if r.get('status') == 'ok':
                    break
            except (OSError, ValueError):
                pass
            if i == 19:
                raise RuntimeError('Контроллер не ответил')
            time.sleep(.5)
    except BaseException:
        for unit in active:
            subprocess.run(['systemctl', 'stop', unit], timeout=30)
        subprocess.run(['systemctl', 'disable', '--now', 'trading-control.service'], timeout=30)
        for path in files:
            path.unlink(missing_ok=True)
        MANIFEST.unlink(missing_ok=True)
        subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
        for unit in active:
            subprocess.run(['systemctl', 'start', unit], timeout=30)
        print('Обёртки отменены. Балансы и журналы сохранены; копия состояния: ' + str(backup))
        raise
    print('Управление A/B/C/D установлено. Балансы и журналы сохранены.')
    print('Первая установка требует прогрева B около 60 секунд. Резервная копия: ' + str(backup))
    print('Тяжёлые движки не устанавливались. Для них: tools/prepare_engine.py')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--wait', type=int, default=600)
    parser.add_argument('--upgrade', action='store_true', help='Upgrade the approved broker version only; no model restarts')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Запусти от root')
    track = deploy.TRACK
    with (track / 'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        revision = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
        if subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain'], text=True).strip():
            raise RuntimeError('Checkout must be clean')
        registered = json.loads((track / 'installed.json').read_text())
        if registered['revision'] != revision:
            raise RuntimeError('Сначала обновите панель до этого коммита')
        deploy.plan(registered['files'], deploy.inventory())
        files = targets()
        for path, body in files.items():
            if path.suffix == '.py':
                ast.parse(body, filename=str(path))
        subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(REPO / 'integrations/control'), '-v'], check=True, timeout=30)
        install(files, revision, pwd.getpwnam('tradingbot'), args.wait, args.upgrade)


if __name__ == '__main__':
    main()
