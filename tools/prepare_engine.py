"""Register one installed native test environment. Never installs Docker or opens ports."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import deploy

REPO = Path(__file__).resolve().parents[1]
CONTROL = Path('/var/lib/trading-control')
ROOT = Path('/var/lib/trading-platforms')
CODE = Path('/opt/trading-platforms')
MINIMUM = {'freqtrade': 3, 'jesse': 3, 'hummingbot': 5}
PACKAGES = {'freqtrade': 'freqtrade==2026.9', 'jesse': 'jesse==3.2.4'}


def unit(engine, python, source=None):
    return ('[Unit]\nDescription=Native ' + engine + ' isolated test only\nAfter=network-online.target\n'
        '[Service]\nType=simple\nUser=tradingbot\nGroup=tradingbot\n'
        'ExecStart=' + str(python) + ' -B -u /opt/trading-platforms/runner.py ' + engine + '\n'
        'WorkingDirectory=/var/lib/trading-platforms/' + engine + '\n'
        'RuntimeMaxSec=45min\nTimeoutStopSec=15\nKillMode=control-group\n'
        'CPUQuota=50%\nMemoryMax=' + ('4G' if engine == 'hummingbot' else '2G') + '\n'
        'TasksMax=64\nNice=19\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\n'
        'ProtectSystem=strict\nProtectHome=true\nReadWritePaths=/var/lib/trading-platforms/' + engine + '\n'
        'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\nEnvironment=PYTHONDONTWRITEBYTECODE=1\n'
        'Environment=NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 POLARS_MAX_THREADS=1\n'
        'Environment=NUMBA_CACHE_DIR=/var/lib/trading-platforms/' + engine + '/.numba-cache\n'
        'Environment=XDG_CACHE_HOME=/var/lib/trading-platforms/' + engine + '/.cache\n' +
        ('Environment=PYTHONPATH=' + str(source) + '\n' if source else '')).encode()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--engine', choices=tuple(MINIMUM), required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--python', type=Path, help='Existing isolated environment, outside /root')
    group.add_argument('--install', action='store_true', help='Create a venv for pinned Freqtrade or Jesse')
    p.add_argument('--source-dir', type=Path, help='Compiled official Hummingbot source directory, if not installed in site-packages')
    args = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Запусти от root')
    if not (CONTROL / 'installed.json').is_file():
        raise SystemExit('Сначала установите управление моделями')
    for path in (CONTROL, ROOT, CODE, Path('/opt/trading-test-envs'), CONTROL/'platforms.json'):
        if path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise SystemExit('Недопустимая ссылка в пути подготовки: ' + str(path))
    total = int(next(l for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemTotal:')).split()[1]) / 1024**2
    if total < MINIMUM[args.engine] - .15:
        raise SystemExit('Нужно ' + str(MINIMUM[args.engine]) + ' ГБ RAM с резервом для панели. Зависимости не устанавливались.')
    with (CONTROL / 'setup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for engine in MINIMUM:
            if deploy.active('trading-test-' + engine + '.service'):
                raise SystemExit('Сначала завершите текущий тест')
        service = Path('/etc/systemd/system/trading-test-' + args.engine + '.service')
        registry_path = CONTROL / 'platforms.json'
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
        if service.exists() and (service.is_symlink() or registry.get(args.engine, {}).get('unit_sha') != deploy.digest(service)):
            raise SystemExit('Служба существует без регистрации или была изменена; подготовка отменена')
        if args.install:
            if args.engine not in PACKAGES:
                raise SystemExit('Hummingbot требует готовое официальное окружение. Используйте --python /opt/.../bin/python')
            env = Path('/opt/trading-test-envs') / args.engine
            if env.exists():
                raise SystemExit('Окружение уже существует; используйте --python ' + str(env / 'bin/python'))
            env.parent.mkdir(mode=0o755, exist_ok=True)
            subprocess.run(['/usr/bin/python3', '-m', 'venv', str(env)], check=True)
            python = env / 'bin/python'
            subprocess.run([str(python), '-m', 'pip', 'install', PACKAGES[args.engine]], check=True, timeout=1800)
        else:
            python = args.python.absolute()
        source = args.source_dir.absolute() if args.source_dir else None
        if source and (args.engine != 'hummingbot' or not (source/'hummingbot').is_dir()
                       or any(c in str(source) for c in '\n\r \t%') or '/root/' in str(source)):
            raise SystemExit('Нужен каталог официальных скомпилированных исходников Hummingbot в /opt без пробелов')
        if not python.is_file() or not os.access(python, os.X_OK) or any(c in str(python) for c in '\n\r \t%'):
            raise SystemExit('Нужен исполняемый Python по абсолютному пути без пробелов')
        if '/root/' in str(python):
            raise SystemExit('Окружение нужно перенести в /opt: служба не читает /root')
        CODE.mkdir(mode=0o755, exist_ok=True)
        for name in ('runner.py', 'LabEMATest.py', 'jesse_strategy.py'):
            path = CODE / name; content = (REPO / 'integrations/platforms' / name).read_bytes()
            if path.exists() and path.read_bytes() != content:
                raise SystemExit('Версия адаптера отличается; нужна отдельная миграция тестовых движков')
            deploy.atomic(path, content)
        # Probe native imports as the unprivileged user who will run the test.
        probe = subprocess.run(['runuser', '-u', 'tradingbot', '--', str(python), '-B', str(CODE / 'runner.py'),
                                args.engine, '--probe'], capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, NUMBA_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                                    **({'PYTHONPATH':str(source)} if source else {})))
        if probe.returncode:
            raise SystemExit('Нативный движок не прошёл проверку импорта: ' + probe.stderr[-1000:])
        info = json.loads(probe.stdout.strip().splitlines()[-1])
        if args.engine in PACKAGES and info['version'] != PACKAGES[args.engine].split('==')[1]:
            raise SystemExit('Непроверенная версия движка: ' + info['version'])
        owner = pwd.getpwnam('tradingbot')
        ROOT.mkdir(mode=0o755, exist_ok=True)
        state = ROOT / args.engine; state.mkdir(mode=0o700, exist_ok=True)
        os.chown(state, owner.pw_uid, owner.pw_gid)
        body = unit(args.engine, python, source)
        deploy.atomic(service, body)
        deploy.system('daemon-reload')
        registry[args.engine] = dict(version=info['version'], mode=info['mode'], registered=__import__('time').time(),
            unit_sha=hashlib.sha256(body).hexdigest(), python=str(python), source=str(source) if source else None)
        deploy.atomic(registry_path, json.dumps(registry).encode(), 0o640)
        os.chown(registry_path, 0, owner.pw_gid)
        print(info['engine'] + ' готов. Во вкладке Модели можно запускать и отменять отдельные тесты.')


if __name__ == '__main__':
    main()
