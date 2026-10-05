"""Install only the panel's separate, persistent candidate evidence directory."""
import fcntl
import json
import os
from pathlib import Path
import pwd
import stat
import time
from urllib.request import urlopen
import deploy

DROPIN = Path('/etc/systemd/system/trading-panel.service.d/lab-candidate-journal.conf')
BODY = b'[Service]\nStateDirectory=trading-candidate-journal\nStateDirectoryMode=0700\n'
ROOT = Path('/var/lib/trading-candidate-journal')


def validate(path):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RuntimeError('Symlink in installation path: '+str(path))


def health():
    for attempt in range(20):
        try:
            with urlopen('http://127.0.0.1:8787/api/candidate-journal?limit=1', timeout=3) as response:
                value = json.load(response)
                if value.get('status') in ('ok', 'partial') and value.get('collector', {}).get('installed') is True:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('Постоянный журнал не ответил после установки')


def install():
    validate(DROPIN)
    validate(ROOT)
    if DROPIN.exists() and DROPIN.read_bytes() != BODY:
        raise RuntimeError('Настройка журнала изменена; автоматическая перезапись запрещена')
    if ROOT.exists() and not DROPIN.exists():
        owner = pwd.getpwnam('tradingbot')
        if (not ROOT.is_dir() or ROOT.stat().st_uid != owner.pw_uid or stat.S_IMODE(ROOT.stat().st_mode) != 0o700
                or any(p.name not in ('candidates.sqlite3', 'candidates.sqlite3-journal') or p.is_symlink()
                       or not p.is_file() for p in ROOT.iterdir())):
            raise RuntimeError('Каталог журнала существует без подтверждённого владельца')
    manifest = json.loads((deploy.TRACK/'installed.json').read_text())
    for name in ('server.py', 'market_data.py', 'candidate_journal.py'):
        key = 'src/trading-panel/'+name
        if not manifest['files'].get(key) or deploy.digest(Path('/opt/trading-panel')/name) != manifest['files'][key]:
            raise RuntimeError('Сначала установите проверенную версию этапа 7')
    if not deploy.active('trading-panel.service'):
        raise RuntimeError('Панель не работает')
    if DROPIN.exists():
        health()
        print('Постоянный журнал уже установлен; вся история сохранена.')
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
    print('Постоянный журнал установлен. Счета, позиции и журналы A/B/C/D и ручного PAPER сохранены.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run as root on the server')
    deploy.TRACK.mkdir(parents=True, exist_ok=True)
    with (deploy.TRACK/'deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install()
