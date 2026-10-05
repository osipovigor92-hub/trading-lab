"""Give only the panel's manual PAPER ledger a persistent writable directory."""
import fcntl
import json
import os
import pwd
import stat
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen
import deploy

DROPIN = Path('/etc/systemd/system/trading-panel.service.d/lab-manual-paper.conf')
BODY = b'[Service]\nStateDirectory=trading-manual-paper\nStateDirectoryMode=0700\n'
ROOT = Path('/var/lib/trading-manual-paper')


def validate(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError('Symlink in installation path: '+str(path))


def health():
    for attempt in range(20):
        try:
            with urlopen('http://127.0.0.1:8787/api/manual-paper', timeout=3) as response:
                if json.load(response).get('status') == 'ok':
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('Ручной PAPER не ответил после установки')


def install():
    validate(DROPIN)
    validate(ROOT)
    if DROPIN.exists() and DROPIN.read_bytes() != BODY:
        raise RuntimeError('Настройка панели изменена; автоматическая перезапись запрещена')
    if ROOT.exists() and not DROPIN.exists():
        # A failed first start may leave the ledger directory. Preserve it and
        # permit retry only for the dedicated service-owned SQLite directory.
        owner = pwd.getpwnam('tradingbot')
        if (not ROOT.is_dir() or ROOT.stat().st_uid != owner.pw_uid
                or stat.S_IMODE(ROOT.stat().st_mode) != 0o700
                or any(p.name not in ('paper.sqlite3', 'paper.sqlite3-journal') or p.is_symlink() or not p.is_file() for p in ROOT.iterdir())):
            raise RuntimeError('Каталог уже существует без подтверждённого владельца PAPER')
    manifest = json.loads((deploy.TRACK/'installed.json').read_text())
    for name in ('server.py', 'manual_paper.py'):
        key = 'src/trading-panel/'+name
        if not manifest['files'].get(key) or deploy.digest(Path('/opt/trading-panel')/name) != manifest['files'][key]:
            raise RuntimeError('Сначала установите проверенную версию этапа 5')
    if not deploy.active('trading-panel.service'):
        raise RuntimeError('Панель не работает')
    if DROPIN.exists():
        health()
        print('Ручной PAPER уже установлен; счёт и позиции сохранены.')
        return
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    deploy.atomic(DROPIN, BODY, 0o644)
    try:
        deploy.system('daemon-reload')
        deploy.system('restart', 'trading-panel.service')
        health()
    except BaseException:
        DROPIN.unlink()
        deploy.system('daemon-reload')
        deploy.system('restart', 'trading-panel.service')
        raise
    print('Ручной PAPER установлен. A/B/C/D и их состояния не менялись.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the server')
    deploy.TRACK.mkdir(parents=True, exist_ok=True)
    with (deploy.TRACK/'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install()
