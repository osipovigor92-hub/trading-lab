"""Bounded server-side strategy drafts. This module never submits orders."""
import copy
import json
import math
import re
import threading
from pathlib import Path
from alert_state import write

CATALOG = [
    ('density_bounce', 'Отскок от плотности', 'Стакан', 'Удержание крупной заявки и подтверждённый отскок цены.'),
    ('density_break', 'Пробой плотности', 'Стакан', 'Исполнение плотности и движение цены за её границу.'),
    ('level_bounce', 'Отскок от уровня', 'Уровни', 'Касание подтверждённого уровня и возврат цены.'),
    ('level_break', 'Пробой уровня', 'Уровни', 'Закрытие свечи за уровнем с подтверждением объёма.'),
    ('structure_break', 'Слом структуры', 'Уровни', 'Нарушение последовательности подтверждённых экстремумов.'),
    ('trend_bounce', 'Отскок от наклонки', 'Наклонки', 'Отскок от линии по подтверждённым экстремумам.'),
    ('trend_break', 'Пробой наклонки', 'Наклонки', 'Закрытие свечи за трендовой линией.'),
    ('impulse_fade', 'Затухание импульса', 'Импульс', 'Ослабление движения и подтверждение разворота.'),
    ('impulse_follow', 'Продолжение импульса', 'Импульс', 'Возобновление движения после ограниченного отката.'),
    ('dca', 'DCA · усреднение', 'Усреднение', 'Ограниченное число добавлений с общим стопом и бюджетом.'),
]
DEFAULTS = dict(strategy='density_bounce', scope='favorites', symbol='BTCUSDT', side='both',
                notional=50, stop_pct=.3, take_pct=.8, daily_loss=20, max_positions=2,
                density_multiple=10, dca_steps=3)


def validate(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULTS):
        raise ValueError('Неполные или неизвестные настройки')
    for key, values in dict(strategy=[v[0] for v in CATALOG], scope=['favorites', 'pair', 'market'],
                            side=['long', 'short', 'both']).items():
        if config[key] not in values:
            raise ValueError('Неверное поле: ' + key)
    if not isinstance(config['symbol'], str) or not re.fullmatch(r'[A-Z0-9]{1,24}USDT', config['symbol']):
        raise ValueError('Укажите пару, например BTCUSDT')
    for key, low, high in [('notional', 5, 100000), ('stop_pct', .01, 20), ('take_pct', .01, 100),
                           ('daily_loss', 1, 10000), ('max_positions', 1, 10),
                           ('density_multiple', 10, 1000), ('dca_steps', 1, 5)]:
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Значение вне диапазона: ' + key)
        if key in ('max_positions', 'dca_steps') and int(value) != value:
            raise ValueError('Требуется целое число: ' + key)
    return copy.deepcopy(config)


class BotBuilder:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.error = None
        self.state = dict(revision=0, drafts={})
        try:
            if self.path and self.path.is_symlink():
                raise ValueError('Недопустимое хранилище ботов')
            if self.path and self.path.exists():
                if self.path.stat().st_size > 100000:
                    raise ValueError('Хранилище ботов превышает лимит')
                state = json.loads(self.path.read_text())
                if (not isinstance(state, dict) or set(state) != {'revision', 'drafts'} or
                        type(state['revision']) is not int or state['revision'] < 0 or
                        not isinstance(state['drafts'], dict) or len(state['drafts']) > 10):
                    raise ValueError('Повреждено хранилище ботов')
                for key, config in state['drafts'].items():
                    validate(config)
                    if key != config['strategy']:
                        raise ValueError('Неверный ключ стратегии')
                self.state = state
        except (OSError, ValueError, TypeError) as exc:
            self.error = str(exc)

    def snapshot(self):
        with self.lock:
            return dict(copy.deepcopy(self.state), status='unavailable' if self.error else 'ok',
                        error=self.error, execution_ready=False, defaults=DEFAULTS.copy(),
                        catalog=[dict(id=i, name=n, group=g, description=d) for i,n,g,d in CATALOG])

    def command(self, command):
        if not isinstance(command, dict) or set(command) != {'revision', 'config'} or type(command['revision']) is not int:
            raise ValueError('Неверная команда конструктора')
        config = validate(command['config'])
        with self.lock:
            if self.error:
                raise OSError(self.error)
            # A lost response can be retried without a second mutation.
            if self.state['drafts'].get(config['strategy']) == config:
                return dict(self.snapshot(), status='accepted')
            if command['revision'] != self.state['revision']:
                raise ValueError('Настройки изменены на другом устройстве. Загрузите сохранённые настройки перед изменением.')
            state = copy.deepcopy(self.state)
            state['drafts'][config['strategy']] = config
            state['revision'] += 1
            if self.path:
                write(self.path, json.dumps(state, ensure_ascii=False, allow_nan=False))
            self.state = state
            return dict(self.snapshot(), status='accepted')
