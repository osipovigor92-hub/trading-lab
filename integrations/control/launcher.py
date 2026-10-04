"""Lifecycle wrappers for the imported, hash-checked engines. Original files stay intact."""
import ast
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
from runtime import Runtime, blocked_cycle

SOURCES = {'A': Path('/opt/scalp-paper/paper.py'),
           'B': Path('/opt/scalp-model-b/model_b.py'),
           'CD': Path('/opt/trading-research/engine.py')}
EXPERIMENTS = Path('/var/lib/trading-control/experiments')


def group(model):
    return 'CD' if model == 'CD' else model


def configured_experiment(model):
    """Load only the manager-written, bounded PAPER settings and fail closed on damage."""
    path = EXPERIMENTS / (group(model) + '.json')
    if path.is_symlink() or any(parent.is_symlink() for parent in (path.parent,)):
        raise RuntimeError('Недопустимая ссылка в настройках PAPER-теста')
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
        if (not isinstance(record, dict) or set(record) != {'version', 'id', 'created', 'settings'} or
                record['version'] != 1 or not isinstance(record['id'], str) or
                not re.fullmatch(r'[A-Z]{1,2}-[0-9T-]{15,32}-[0-9a-f]{8}', record['id']) or
                not isinstance(record['created'], (int, float)) or isinstance(record['created'], bool) or
                not isinstance(record['settings'], dict) or set(record['settings']) != {'capital', 'notional', 'max_loss'}):
            raise ValueError('Некорректный формат')
        settings = {}
        for key in ('capital', 'notional', 'max_loss'):
            value = record['settings'][key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('Некорректное число')
            settings[key] = float(value)
        if not 10 <= settings['capital'] <= 1_000_000 or not 1 <= settings['notional'] <= settings['capital'] or not 0 < settings['max_loss'] < settings['capital']:
            raise ValueError('Значение вне границ')
        return dict(id=record['id'], created=float(record['created']), settings=settings)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError('Настройки PAPER-теста недоступны: ' + str(exc)[:120])


def configure(model, namespace):
    record = configured_experiment(model)
    key = 'C' if model == 'B' else 'CONFIG'
    if record:
        updated = dict(namespace[key])
        updated.update(record['settings'])
        namespace[key] = updated
    namespace['_LAB_EXPERIMENT'] = record
    return record


def stamp_experiment(state, record):
    if record:
        state['experiment'] = dict(id=record['id'], created=record['created'],
                                   settings=dict(record['settings']))
    return state


def patch_a(source):
    """Add the entry gate and pre-start check at two unambiguous AST locations."""
    tree = ast.parse(source)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    entries = [n for n in ast.walk(main) if isinstance(n, ast.If) and
               ast.unparse(n.test) == "s['position'] is None and now >= s['cooldown_until']"]
    halted = [n for n in ast.walk(main) if isinstance(n, ast.If) and
              ast.unparse(n.test) == "s['phase'] == 'halted'"]
    if len(entries) != 1 or len(halted) != 1:
        raise RuntimeError('Неизвестная версия A: обёртка не установлена')
    entries[0].test = ast.BoolOp(op=ast.And(), values=[entries[0].test,
        ast.parse('_CONTROL.entries(s, history, confirmations)', mode='eval').body])
    class Insert(ast.NodeTransformer):
        def visit_If(self, node):
            self.generic_visit(node)
            return [ast.parse('_CONTROL.prepare(s)').body[0], node] if node is halted[0] else node
    tree = Insert().visit(tree)
    return ast.fix_missing_locations(tree)


def load(model, path=None):
    path = SOURCES[model] if path is None else Path(path)
    ns = {'__name__': 'managed_' + model, '__file__': str(path)}
    if model == 'A':
        ns['_CONTROL'] = Runtime('A', 12)
        code = compile(patch_a(path.read_text()), str(path), 'exec')
    else:
        code = compile(path.read_text(), str(path), 'exec')
    exec(code, ns)
    record = configure(model, ns)
    if model in ('B', 'CD'):
        initial = ns['initial']
        if model == 'B':
            def managed_initial():
                return stamp_experiment(initial(), record)
        else:
            def managed_initial(now):
                return stamp_experiment(initial(now), record)
        ns['initial'] = managed_initial
    if model == 'A':
        save = ns['save']
        def managed_save(s):
            stamp_experiment(s, record)
            ns['_CONTROL'].decorate(s)
            save(s)
        ns['save'] = managed_save
    elif model == 'B':
        ctl, cycle, atomic = Runtime('B', 60), ns['cycle'], ns['atomic']
        def managed_cycle(s, books, charts, now):
            ctl.prepare(s, now)
            if ctl.reset:
                for b in books.values():
                    b.armed = None
                ctl.reset = False
            result = blocked_cycle(ctl, s, lambda: cycle(s, books, charts, now), now)
            # C/D use the market feed even when B's PAPER entries are paused.
            s['feed_phase'] = 'running' if s['phase'] not in ('halted', 'waiting') else s['phase']
            s['feed_updated'] = now
            return result
        ns['cycle'] = managed_cycle
        def managed_atomic(path, s):
            if path == ns['STATE']:
                stamp_experiment(s, record)
                if s.get('updated') != s.get('feed_updated'):
                    s['feed_phase'] = 'halted' if s.get('phase') == 'halted' else 'waiting'
                ctl.prepare(s)
                ctl.decorate(s)
            atomic(path, s)
        ns['atomic'] = managed_atomic
        # prepare before the existing restart/halt guard, without bypassing a position.
        source = path.read_text()
        target = "    if s['position'] or s['phase']=='halted':"
        if source.count(target) != 1:
            raise RuntimeError('Неизвестная версия B')
        startup = source.replace(target, "    _CONTROL.prepare(s)\n" + target, 1)
        extra = dict(ns, _CONTROL=ctl)
        # Redefine main only; preserve the wrapped functions in its globals.
        main_node = next(n for n in ast.parse(startup).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        exec(compile(ast.Module(body=[main_node], type_ignores=[]), str(path), 'exec'), extra)
        ns.update(extra)
        ns['main'].__globals__.update(ns)
    else:
        controls = {m: Runtime(m, 12) for m in ('C', 'D')}
        cycle, evaluate = ns['cycle'], ns['evaluate']
        def feed(source):
            return dict(source, phase=source.get('feed_phase', source.get('phase'))) if isinstance(source, dict) else {}
        ns['evaluate'] = lambda model, source, r, now: evaluate(model, feed(source), r, now)
        def managed_cycle(state, source, now):
            stamp_experiment(state, record)
            olds, skipped = {}, set()
            for model, s in state['models'].items():
                ctl = controls[model]
                s['config'] = state['config']
                if not ctl.entries(s, s['confirmations'], now=now):
                    olds[model] = s['cooldown_until']
                    s['cooldown_until'] = now + 365 * 86400
                    if not s['position'] and s['phase'] != 'halted':
                        s['phase'] = 'halted'  # skip this model only during the native cycle
                        skipped.add(model)
            try:
                return cycle(state, feed(source), now)
            finally:
                for model, s in state['models'].items():
                    if model in olds and s['cooldown_until'] == now + 365 * 86400:
                        s['cooldown_until'] = olds[model]
                    if model in skipped:
                        s['phase'] = 'waiting'
                    controls[model].decorate(s, now)
                    s.pop('config', None)
        ns['cycle'] = managed_cycle
    return ns


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in SOURCES:
        raise SystemExit('Expected A, B, or CD')
    load(sys.argv[1])['main']()
