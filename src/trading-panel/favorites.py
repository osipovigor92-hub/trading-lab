"""Shared favorites: atomic deltas, durable retries, no trading state changes."""
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
from alert_state import write

LIMITS = {'lab-favorites-v1': 8, 'lab-exchange-favorites-v1': 24,
          'lab-density-watch-v1': 20}


def valid(key, value):
    pattern = (r'[A-Z0-9]{2,24}USDT' if key == 'lab-favorites-v1' else
               r'(bybit|binance|okx|gate|bitget):[A-Z0-9]{1,28}USDT')
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


class Favorites:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.error = None
        self.state = dict(revision=0, groups={key: [] for key in LIMITS}, commands={})
        try:
            if self.path and self.path.is_symlink():
                raise ValueError('Недопустимое хранилище избранного')
            if self.path and self.path.exists():
                if self.path.stat().st_size > 500_000:
                    raise ValueError('Хранилище избранного превышает лимит')
                state = json.loads(self.path.read_text())
                if (type(state.get('revision')) is not int or state['revision'] < 0 or
                        set(state.get('groups', {})) != set(LIMITS) or
                        not isinstance(state.get('commands'), dict) or len(state['commands']) > 256):
                    raise ValueError('Неверное хранилище избранного')
                for key, limit in LIMITS.items():
                    values = state['groups'][key]
                    if (not isinstance(values, list) or len(values) > limit or
                            not all(valid(key, v) for v in values) or len(set(values)) != len(values)):
                        raise ValueError('Неверные монеты в избранном')
                self.state = state
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.error = str(exc)

    def snapshot(self):
        with self.lock:
            return dict(status='unavailable' if self.error else 'ok', error=self.error,
                        revision=self.state['revision'], groups=copy.deepcopy(self.state['groups']))

    def command(self, command):
        if (not isinstance(command, dict) or set(command) != {'id', 'changes'} or
                not isinstance(command['id'], str) or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', command['id']) or
                not isinstance(command['changes'], list) or not 1 <= len(command['changes']) <= 104):
            raise ValueError('Неверная команда избранного')
        for change in command['changes']:
            if (not isinstance(change, dict) or set(change) != {'key', 'value', 'present'} or
                    not isinstance(change['key'], str) or change['key'] not in LIMITS or
                    not valid(change['key'], change['value']) or type(change['present']) is not bool):
                raise ValueError('Неверная монета избранного')
        digest = hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.error:
                raise OSError(self.error)
            previous = self.state['commands'].get(command['id'])
            if previous:
                if previous != digest:
                    raise ValueError('Идентификатор команды уже использован')
                return dict(self.snapshot(), status='accepted')
            state = copy.deepcopy(self.state)
            for change in command['changes']:
                group = state['groups'][change['key']]
                value = change['value']
                if change['present'] and value not in group:
                    group.append(value)
                elif not change['present'] and value in group:
                    group.remove(value)
            for key, limit in LIMITS.items():
                if len(state['groups'][key]) > limit:
                    raise ValueError(f'Лимит избранного: {limit}. Уберите лишние монеты на синхронизированном устройстве.')
            state['revision'] += 1
            state['commands'][command['id']] = digest
            state['commands'] = dict(list(state['commands'].items())[-256:])
            if self.path:
                write(self.path, json.dumps(state, ensure_ascii=False))
            self.state = state
            return dict(self.snapshot(), status='accepted')
