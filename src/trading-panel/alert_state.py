"""Atomic bounded storage of alert edges, never cached market proof or live events.

Adapts the persisted rearm principle of Jakeschincariol/trader-skill
5189e79b9a480755a3733ac9713f5353981dbe18, trader-alerts (MIT).
"""
import json
import os
from pathlib import Path
import re
import tempfile
import selection

FIELDS = ('state', 'book_good', 'near')
ASSISTANT_FIELDS = ('setup', 'momentum_episode', 'last_breakout', 'last_momentum')


def encode(epoch, sequence, scopes):
    rows = []
    for key, scope in scopes.items():
        rows.append(dict(key=key, filters=scope['filters'], search=scope['search'],
                         watch=scope['watch'], priority=scope['priority'],
                         states={s: {k: v[k] for k in FIELDS} for s, v in scope['states'].items()},
                         assistant_states={s: {k: v.get(k) for k in ASSISTANT_FIELDS}
                                           for s, v in scope['assistant_states'].items()}))
    return json.dumps(dict(version=1, epoch=epoch, sequence=sequence, scopes=rows),
                      sort_keys=True, allow_nan=False, separators=(',', ':'))


def read(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Хранилище алертов является ссылкой')
    if not path.exists():
        return None
    if path.stat().st_size > 1_000_000:
        raise ValueError('Хранилище алертов превышает лимит')
    doc = json.loads(path.read_text())
    if (doc.get('version') != 1 or not re.fullmatch('[a-f0-9]{32}', doc.get('epoch', ''))
            or type(doc.get('sequence')) is not int or doc['sequence'] < 0
            or not isinstance(doc.get('scopes'), list) or len(doc['scopes']) > 4):
        raise ValueError('Неверный формат состояния алертов')
    seen = set()
    for scope in doc['scopes']:
        key = scope['key']
        if key in seen or not re.fullmatch('[a-f0-9]{20}', key):
            raise ValueError('Неверный набор правил алертов')
        seen.add(key)
        if selection.parse_filters(scope['filters']) != scope['filters']:
            raise ValueError('Неверные фильтры алертов')
        selection.parse_watch(','.join(scope['watch']))
        if not re.fullmatch('[A-Z0-9]{0,24}', scope['search']) or scope['priority'] not in ('activity','turnover'):
            raise ValueError('Неверные настройки алертов')
        for name in ('states', 'assistant_states'):
            states = scope[name]
            if not isinstance(states, dict) or len(states) > 100:
                raise ValueError('Превышен лимит состояний алертов')
            for symbol, edge in states.items():
                if not re.fullmatch('[A-Z0-9]{2,24}USDT', symbol) or not isinstance(edge, dict):
                    raise ValueError('Неверная монета алерта')
                if name == 'assistant_states':
                    if set(edge) != set(ASSISTANT_FIELDS) or any(v is not None and (not isinstance(v, str) or len(v)>512) for v in edge.values()):
                        raise ValueError('Неверное состояние сценария')
                else:
                    if set(edge) != set(FIELDS) or edge['state'] not in (None,'ready','almost','waiting') or edge['book_good'] not in (None,True,False):
                        raise ValueError('Неверное состояние условия')
                    near = edge['near']
                    if near is not None and (not isinstance(near,dict) or near.get('side') not in ('support','resistance') or
                        not all(selection.finite(near.get(k)) and near[k]>0 for k in ('low','high','atr'))):
                        raise ValueError('Неверный уровень алерта')
    return doc


def write(path, body):
    path = Path(path)
    if len(body.encode()) > 1_000_000 or path.is_symlink():
        raise ValueError('Небезопасное хранилище алертов')
    fd, temporary = tempfile.mkstemp(prefix='.alerts-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(body);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

# License for the upstream rearm design:
# MIT License
# 
# Copyright (c) 2026 Jake Schincariol
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
