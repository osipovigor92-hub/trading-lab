"""Create one PC credential and a source-only transfer bundle. Run on the VDS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import io
import time

REPO = Path(__file__).resolve().parents[1]
ROOT = Path('/var/lib/trading-control')
BUNDLE = Path('/root/trading-lab-pc.tar.gz')
SECRET = Path('/root/trading-lab-pc-key.txt')
FILES = ('integrations/worker/agent.py', 'integrations/worker/job.py',
         'integrations/platforms/runner.py', 'integrations/platforms/LabEMATest.py',
         'integrations/platforms/jesse_strategy.py', 'tools/worker_setup.py')


def export_bundle(destination, revision):
    if destination.is_symlink() or any(p.is_symlink() for p in destination.parents):
        raise ValueError('Недопустимый путь архива ПК')
    manifest = dict(revision=revision, files={n:hashlib.sha256((REPO/n).read_bytes()).hexdigest() for n in FILES})
    temporary = destination.with_suffix('.tmp')
    with tarfile.open(temporary, 'w:gz') as archive:
        for name in FILES:
            archive.add(REPO/name, arcname='trading-lab-pc/'+name, recursive=False)
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo('trading-lab-pc/worker-release.json');info.size=len(data);info.mode=0o644
        archive.addfile(info, io.BytesIO(data))
    os.chmod(temporary, 0o600);os.replace(temporary, destination)
    return manifest


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--rotate', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Запусти на VDS от root')
    if not (ROOT/'installed.json').is_file() or not Path('/opt/trading-control/remote.py').is_file():
        raise SystemExit('Сначала установите поддержку ПК: tools/install_control.py --upgrade')
    paths = (ROOT/'pc-key.json', SECRET, BUNDLE)
    if any(p.is_symlink() or any(a.is_symlink() for a in p.parents) for p in paths):
        raise SystemExit('Недопустимая ссылка в пути подключения ПК')
    saved = json.loads((ROOT/'pc-state.json').read_text()) if (ROOT/'pc-state.json').exists() else {}
    if args.rotate and saved.get('job'):
        raise SystemExit('Сначала завершите тест ПК и получите подтверждение остановки')
    key_file = ROOT/'pc-key.json'
    if key_file.exists() and not args.rotate:
        if not SECRET.exists():
            raise SystemExit('Код подключения не сохранён. При отсутствии теста используйте --rotate')
        key = SECRET.read_text().strip()
        if json.loads(key_file.read_text()).get('sha256') != hashlib.sha256(key.encode()).hexdigest():
            raise SystemExit('Код подключения не соответствует регистрации')
    else:
        key = secrets.token_urlsafe(32)
        temporary = key_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(worker='pc-01', sha256=hashlib.sha256(key.encode()).hexdigest(), created=time.time())))
        temporary.chmod(0o600);os.replace(temporary, key_file)
        SECRET.write_text(key+'\n');SECRET.chmod(0o600)
    revision = subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'], text=True).strip()
    export_bundle(BUNDLE, revision)
    print('Архив для ПК:', BUNDLE)
    print('Версия:', revision)
    print('Код подключения хранится в', SECRET)
    print('Посмотреть код: cat /root/trading-lab-pc-key.txt')
    print('Код вводится на ПК скрыто; не присылай его в чат.')


if __name__ == '__main__':
    main()
