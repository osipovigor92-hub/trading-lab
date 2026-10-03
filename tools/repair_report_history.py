"""Repair only the report reader's access to Model B history.

This never restarts a trading model and never changes database contents.  It is
intentionally narrow: the Model B service itself runs as ``tradingbot``, so an
older root-owned SQLite file can safely be returned to that owner.
"""
import argparse
import os
from pathlib import Path
import pwd
import stat
import subprocess


ROOT = Path('/var/lib/scalp-model-b')
NAMES = ('history.sqlite', 'history.sqlite-wal', 'history.sqlite-shm')


def safe_directory(path):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise RuntimeError('Недопустимая ссылка: ' + str(item))
        if item == Path('/'):
            break
    if not path.is_dir():
        raise RuntimeError('Каталог истории B не найден: ' + str(path))


def plan(root=ROOT, owner=None):
    owner = owner or pwd.getpwnam('tradingbot')
    safe_directory(root)
    history = root / NAMES[0]
    if history.is_symlink():
        raise RuntimeError('Недопустимая ссылка: ' + str(history))
    if not history.is_file():
        raise RuntimeError('Файл истории B не найден: ' + str(history))
    targets = [root] + [root / name for name in NAMES if (root / name).exists()]
    rows = []
    for path in targets:
        if path.is_symlink() or not path.is_file() and path != root:
            raise RuntimeError('Недопустимый путь: ' + str(path))
        mode = 0o700 if path == root else 0o600
        current = path.stat()
        need_owner = (current.st_uid, current.st_gid) != (owner.pw_uid, owner.pw_gid)
        need_mode = stat.S_IMODE(current.st_mode) != mode
        rows.append((path, mode, need_owner, need_mode))
    return owner, rows


def repair(root=ROOT, owner=None, apply=False):
    owner, rows = plan(root, owner)
    for path, mode, need_owner, need_mode in rows:
        action = []
        if need_owner:
            action.append('владелец')
        if need_mode:
            action.append('права')
        print(('ИСПРАВИТЬ' if action else 'OK') + ' ' + str(path) + (' · ' + ', '.join(action) if action else ''))
        if apply:
            if need_owner:
                os.chown(path, owner.pw_uid, owner.pw_gid)
            if need_mode:
                os.chmod(path, mode)
    return rows


def main():
    parser = argparse.ArgumentParser(description='Проверить доступ отчёта к архиву Model B')
    parser.add_argument('--apply', action='store_true', help='Исправить владельца и права, затем обновить только отчёт')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Запусти от root')
    repair(apply=args.apply)
    if not args.apply:
        print('Проверка завершена. Для исправления добавь --apply.')
        return
    subprocess.run(['systemctl', 'restart', 'trading-report.service'], check=True, timeout=60)
    print('Готово: обновлён только отчёт. Модель B и торговые службы не перезапускались.')


if __name__ == '__main__':
    main()
