"""Inspect model setup without starting/stopping services or exposing session tokens."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src/trading-panel'))
import control_client

TRACK = Path('/var/lib/trading-lab-deploy/installed.json')
MANIFEST = Path('/var/lib/trading-control/installed.json')
UNITS = ('trading-panel.service', 'trading-control.service', 'scalp-paper.service',
         'scalp-model-b.service', 'trading-research.service')
CONTROL_FILES = {
    '/opt/trading-control/runtime.py', '/opt/trading-control/launcher.py',
    '/opt/trading-control/manager.py', '/opt/trading-control/remote.py', '/etc/systemd/system/trading-control.service',
    *('/etc/systemd/system/' + unit + '.d/lab-control.conf' for unit in UNITS[2:])
}


def read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def revision(data):
    value = data.get('revision', '')
    return value if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value) else None


def integrity(data):
    """Only hash the fixed wrapper paths; never follow arbitrary manifest paths."""
    files = data.get('files')
    if not isinstance(files, dict) or set(files) != CONTROL_FILES:
        return None if not data else False
    for name, digest in files.items():
        path = Path(name)
        try:
            if path.is_symlink() or any(p.is_symlink() for p in path.parents) or not isinstance(digest, str):
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                return False
        except OSError:
            return False
    return True


def unit_states():
    result = {u: dict(load='unknown', active='unknown') for u in UNITS}
    try:
        completed = subprocess.run(
            ['/usr/bin/systemctl', 'show', *UNITS, '-p', 'Id', '-p', 'LoadState', '-p', 'ActiveState'],
            capture_output=True, text=True, timeout=12,
        )
        for block in completed.stdout.strip().split('\n\n'):
            fields = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if fields.get('Id') in result:
                result[fields['Id']] = dict(load=fields.get('LoadState', 'unknown'),
                                           active=fields.get('ActiveState', 'unknown'))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return result


def sanitized_status(raw, now):
    """Build a whitelist report. Tokens, audit messages and strategy data stay out."""
    if not isinstance(raw, dict) or raw.get('status') != 'ok':
        return dict(available=False, fresh=False, memory=None, models=[], engines=[])
    stamp = raw.get('updated')
    fresh = isinstance(stamp, (int, float)) and 0 <= now - stamp <= 8
    memory = raw.get('memory') if isinstance(raw.get('memory'), dict) else {}
    result = dict(available=True, fresh=fresh,
                  memory={k: memory.get(k) for k in ('total_gb', 'available_gb')}, models=[], engines=[])
    for row in raw.get('models', []):
        if not isinstance(row, dict) or row.get('id') not in ('A', 'B', 'C', 'D'):
            continue
        result['models'].append({k: row.get(k) for k in ('id', 'phase', 'installed', 'fresh', 'pending', 'unit_active')}
                                | dict(has_position=bool(row.get('position'))))
    for row in raw.get('engines', []):
        if not isinstance(row, dict) or row.get('id') not in ('freqtrade', 'hummingbot', 'jesse'):
            continue
        result['engines'].append({k: row.get(k) for k in ('id', 'phase', 'installed', 'memory_ok', 'required_gb', 'version')})
    pc=raw.get('worker')
    if isinstance(pc, dict):
        mem=pc.get('memory') if isinstance(pc.get('memory'),dict) else {}
        result['worker']=dict(configured=pc.get('configured') is True,online=pc.get('online') is True,
            memory={k:mem.get(k) for k in ('total_gb','available_gb')})
    return result


def diagnose():
    try:
        raw = control_client.call(dict(op='status'))
    except (OSError, ValueError):
        raw = None
    manifest = read(MANIFEST)
    return dict(checked=time.time(), panel_revision=revision(read(TRACK)),
                control_revision=revision(manifest), control_files_match=integrity(manifest),
                units=unit_states(), controller=sanitized_status(raw, time.time()))


def text_report(report):
    c = report['controller']
    lines = ['Диагностика моделей · службы не перезапускались',
             'Версия панели: ' + (report['panel_revision'] or 'не зарегистрирована'),
             'Версия управления: ' + (report['control_revision'] or 'не установлено'),
             'Файлы управления: ' + {True: 'совпадают с установленной версией', False: 'отличаются', None: 'нет записи установки'}[report['control_files_match']],
             'Контроллер: ' + ('отвечает' if c['available'] and c['fresh'] else 'нет свежего ответа')]
    for unit, s in report['units'].items():
        lines.append(unit + ': ' + s['load'] + ' / ' + s['active'])
    if c['memory']:
        lines.append('RAM: всего ' + str(c['memory']['total_gb']) + ' ГБ; доступно ' + str(c['memory']['available_gb']) + ' ГБ')
    if c.get('worker'):
        pc=c['worker'];mem=pc['memory']
        lines.append('Мой ПК: '+('подключён' if pc['online'] else 'нет свежего ответа')+
            ' · настроен: '+str(pc['configured'])+' · RAM исполнителя: '+str(mem.get('total_gb'))+' ГБ')
    for row in c['models']:
        position = ('позиция по последнему сохранённому снимку' if row['has_position'] else 'позиция не подтверждена') if not row['fresh'] else 'есть позиция' if row['has_position'] else 'нет позиции'
        lines.append('Модель ' + row['id'] + ': ' + str(row['phase']) + ' · ' + position)
    for row in c['engines']:
        lines.append(row['id'] + ': ' + str(row['phase']) + ' · подготовлен: ' + str(row['installed'])
                     + ' · память подходит: ' + str(row['memory_ok']) + ' · требуется RAM: ' + str(row['required_gb']) + ' ГБ')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    report = diagnose()
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) if args.json else text_report(report))
    return 0 if report['controller']['available'] and report['controller']['fresh'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
