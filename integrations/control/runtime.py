"""Cooperative PAPER lifecycle. No account resets, synthetic exits, or network calls."""
import json
import time
from pathlib import Path

COMMANDS = Path('/var/lib/trading-control/commands')


class Runtime:
    def __init__(self, model, warmup=10):
        self.model, self.warmup = model, warmup
        self.reset = False

    def request(self):
        try:
            r = json.loads((COMMANDS / (self.model + '.json')).read_text())
            if (r['action'] not in ('start', 'stop', 'restart') or
                    type(r['generation']) is not int or r['generation'] < 1):
                raise ValueError('Invalid lifecycle request')
            return r
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError):
            # An unreadable control file cannot authorize new entries.
            return dict(action='stop', generation=-1, error='Файл управления недоступен')

    def prepare(self, s, now=None):
        now = time.time() if now is None else now
        r = self.request()
        if r is None:
            return
        c = s.setdefault('control', {})
        c.update(requested=r['action'], request_generation=r['generation'])
        newer = r['generation'] != c.get('generation')
        if newer and not s.get('position'):
            if r['action'] == 'restart':
                config = s.get('config', {})
                floor = config.get('capital', 600) - config.get('max_loss', 18)
                if s.get('equity', floor) <= floor:
                    c['error'] = 'Лимит потерь: перезапуск не сбрасывает эксперимент'
                    return
                s['phase'], s['reason'] = 'waiting', ''
            elif s.get('phase') == 'halted' and r['action'] == 'start':
                c['error'] = 'Нужен явный перезапуск после проверки причины остановки'
                return
            c.update(generation=r['generation'], enabled=r['action'] != 'stop',
                     applied=now, warmup_until=now + self.warmup if r['action'] != 'stop' else 0,
                     error=r.get('error', ''))
            self.reset = True
        elif newer and s.get('position'):
            # start may cancel a requested drain; restart waits for a genuine close.
            if r['action'] == 'start' and s.get('phase') != 'halted':
                c.update(generation=r['generation'], enabled=True, applied=now,
                         warmup_until=now + self.warmup, error='')

    def entries(self, s, *caches, now=None):
        self.prepare(s, now)
        if self.reset:
            for cache in caches:
                cache.clear()
            self.reset = False
        r = self.request()
        if r is None:
            return True
        c = s.get('control', {})
        now = time.time() if now is None else now
        return (r['action'] != 'stop' and c.get('enabled') is True and
                c.get('generation') == r['generation'] and
                now >= c.get('warmup_until', now + 1) and not c.get('error'))

    def decorate(self, s, now=None):
        self.prepare(s, now)
        r = self.request()
        if r is None or s.get('phase') == 'halted':
            return
        now = time.time() if now is None else now
        c = s.get('control', {})
        pending = c.get('generation') != r['generation']
        if (r['action'] == 'stop' or (pending and r['action'] == 'restart')):
            s['phase'] = 'draining' if s.get('position') else 'paused'
            s['reason'] = ('Новые входы отключены; позиция завершается по прежним правилам'
                           if s.get('position') else 'Модель отключена пользователем')
        elif now < c.get('warmup_until', 0):
            s['phase'], s['reason'] = 'warming', 'Повторное накопление условий входа'


def blocked_cycle(runtime, s, callback, now):
    """Keep normal position management, but gate entries through the existing cooldown."""
    allowed = runtime.entries(s, now=now)
    old = s.get('cooldown_until', 0)
    block = now + 365 * 86400
    if not allowed:
        s['cooldown_until'] = block
    try:
        return callback()
    finally:
        if not allowed and s.get('cooldown_until') == block:
            s['cooldown_until'] = old
        runtime.decorate(s, now)
