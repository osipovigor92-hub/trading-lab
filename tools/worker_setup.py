"""Prepare/connect the unprivileged Ubuntu/WSL worker, without server model services."""
import argparse
import fcntl
import getpass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pc_agent_setup', REPO/'integrations/worker/agent.py')
agent = importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
PACKAGES = {'freqtrade':'freqtrade==2026.9', 'jesse':'jesse==3.2.4'}


def release():
    path = REPO/'worker-release.json'
    if not path.exists():
        return  # Development/CI checkout; exported PC bundles always carry hashes.
    manifest = json.loads(path.read_text())
    for name, digest in manifest['files'].items():
        source = REPO/name
        if source.is_symlink() or '..' in Path(name).parts or not source.is_relative_to(REPO):
            raise ValueError('Недопустимый путь версии исполнителя')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Файлы архива отличаются от указанной версии: '+name)


def main():
    p = argparse.ArgumentParser();p.add_argument('--root', type=Path, default=agent.ROOT)
    sub = p.add_subparsers(dest='command', required=True)
    connect = sub.add_parser('connect');connect.add_argument('--url', default='http://127.0.0.1:18787')
    connect.add_argument('--ca-file', type=Path)
    prepare = sub.add_parser('prepare');prepare.add_argument('--engine', choices=agent.ENGINES, required=True)
    group = prepare.add_mutually_exclusive_group(required=True)
    group.add_argument('--install', action='store_true');group.add_argument('--python', type=Path)
    prepare.add_argument('--source-dir', type=Path)
    sub.add_parser('status')
    args = p.parse_args()
    if os.geteuid() == 0:
        raise SystemExit('Выполняй от пользователя Ubuntu, без sudo')
    release()
    root = args.root.absolute()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents) or str(root).startswith('/mnt/'):
        raise SystemExit('Исполнитель и секреты должны храниться в домашней папке Ubuntu, не на /mnt/c')
    root.mkdir(parents=True, mode=0o700, exist_ok=True);root.chmod(0o700)
    if args.command == 'connect':
        agent.endpoint(args.url)
        key = getpass.getpass('Код подключения из VDS (ввод скрыт): ').strip()
        if not 32 <= len(key) <= 128 or not key.isascii():
            raise SystemExit('Неверный код подключения')
        config = dict(url=args.url, key=key)
        if args.ca_file:
            config['ca_file'] = str(args.ca_file.absolute())
        agent.atomic(root/'config.json', config)
        print('Подключение сохранено. Код в вывод не попал.')
        return
    if args.command == 'status':
        print('RAM Ubuntu/WSL:', agent.memory())
        registry = agent.read(root/'engines.json', {})
        for engine in agent.ENGINES:
            v=registry.get(engine,{})
            print(engine, 'готов:', bool(v.get('ready')), 'версия:', v.get('version','—'))
        print('Подключение настроено:', (root/'config.json').is_file())
        return
    with (root/'agent.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Перед подготовкой останови исполнитель Ctrl+C')
        minimum = agent.MINIMUM[args.engine];mem=agent.memory()
        if mem['total_gb'] < minimum-.15 or mem['available_gb'] < minimum-1:
            raise SystemExit('Недостаточно памяти Ubuntu/WSL для этого движка: '+str(mem))
        if args.install:
            if args.engine not in PACKAGES:
                raise SystemExit('Hummingbot: укажи Python готового официального скомпилированного окружения')
            folder=root/'envs'/args.engine
            if not folder.exists():
                folder.parent.mkdir(exist_ok=True)
                subprocess.run([sys.executable,'-m','venv',str(folder)], check=True)
            python=folder/'bin/python'
            subprocess.run([str(python),'-m','pip','install',PACKAGES[args.engine]], check=True, timeout=1800)
        else:
            python=args.python.absolute()
        if not python.is_file() or not os.access(python, os.X_OK):
            raise SystemExit('Не найден Python окружения')
        source=args.source_dir.absolute() if args.source_dir else None
        if source and (args.engine!='hummingbot' or not (source/'hummingbot').is_dir()):
            raise SystemExit('Нужен каталог скомпилированных исходников Hummingbot')
        probe=subprocess.run([str(python),'-B',str(REPO/'integrations/platforms/runner.py'),args.engine,'--probe'],
            capture_output=True, text=True, timeout=90, env=agent.env(root,source))
        if probe.returncode:
            raise SystemExit('Движок не прошёл проверку импорта. Подробности: '+probe.stderr[-1200:])
        info=json.loads(probe.stdout.strip().splitlines()[-1])
        if args.engine in agent.VERSIONS and info['version']!=agent.VERSIONS[args.engine]:
            raise SystemExit('Версия движка не проверена этой интеграцией')
        registry=agent.read(root/'engines.json',{})
        registry[args.engine]=dict(ready=True, version=info['version'],python=str(python),source=str(source) if source else None)
        agent.atomic(root/'engines.json',registry)
        print(args.engine+' подготовлен на ПК. Можно запустить исполнитель и выбрать «Мой ПК» в панели.')


if __name__ == '__main__':
    main()
