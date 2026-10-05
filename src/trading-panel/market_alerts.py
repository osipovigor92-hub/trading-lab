"""Bounded, read-only alerts from the existing selection cache; no trade execution."""
from collections import OrderedDict
import hashlib
import json
import threading
import uuid
import selection

KINDS = ('ready', 'almost', 'cancelled', 'book_worse', 'near_level')
LABELS = dict(ready='Кандидат готов', almost='Почти готов',
              cancelled='Условие отменено', book_worse='Стакан ухудшился',
              near_level='Цена у уровня')
BOOK_KEYS = ('depth', 'book_spread', 'impact', 'coverage')


def usable(packet, now, limit):
    return (isinstance(packet, dict) and packet.get('status') == 'ok' and
            not packet.get('error') and not packet.get('refresh_error') and
            selection.fresh(packet.get('updated'), now, limit))


def near_threshold(check):
    """Exactly one known failure, at most 20% short of a positive numeric threshold."""
    value = check.get('value')
    if not selection.finite(value) or value < 0:
        return False
    low, high = check.get('min'), check.get('max')
    return (selection.finite(low) and low > 0 and .8 * low <= value < low or
            selection.finite(high) and high > 0 and high < value <= 1.2 * high)


def measure(row, tickers, chart, book, history, filters, now):
    symbol = row['symbol']
    quote_ok = usable(tickers, now, 45) and selection.finite(row.get('price')) and row['price'] > 0
    chart_ok = (usable(chart, now, 75) and chart.get('symbol') == symbol and
                chart.get('interval') == '1' and selection.fresh(chart.get('candle_end'), now, 120))
    book_ok = (usable(book, now, 8) and book.get('symbol') == symbol and
               selection.fresh(book.get('fetched'), now, 8))
    aligned = (quote_ok and book_ok and selection.finite(book.get('mid')) and book['mid'] > 0 and
               abs(row['price'] / book['mid'] - 1) * 100 <= .1)
    verdict = selection.evaluate(row, tickers.get('updated'), chart, history, filters, now)
    checks = verdict['checks']
    failed = [c for c in checks if c['state'] == 'fail']
    complete = (quote_ok and chart_ok and book_ok and aligned and
                all(c['state'] in ('pass', 'fail') for c in checks) and
                verdict.get('book_time') == book.get('updated'))
    state = 'unavailable'
    if complete:
        state = ('ready' if not failed and verdict['rating']['status'] == 'ok' else
                 'almost' if len(failed) == 1 and near_threshold(failed[0]) else 'waiting')
    book_checks = [c for c in checks if c['key'] in BOOK_KEYS]
    book_known = (quote_ok and book_ok and aligned and verdict.get('book_time') == book.get('updated') and
                  all(c['state'] in ('pass', 'fail') for c in book_checks))
    book_good = all(c['state'] == 'pass' for c in book_checks) if book_known else None
    near = None
    atr = chart.get('atr')
    if quote_ok and chart_ok and book_ok and aligned and selection.finite(atr) and atr > 0:
        levels = [l for l in chart.get('levels', []) if isinstance(l, dict) and
                  l.get('side') in ('support', 'resistance') and
                  all(selection.finite(l.get(k)) and l[k] > 0 for k in ('low', 'price', 'high')) and
                  l['low'] <= l['price'] <= l['high']]
        candidates = [l for l in levels if l['low'] - .25 * atr <= row['price'] <= l['high'] + .25 * atr]
        if candidates:
            near = dict(min(candidates, key=lambda l: abs(l['price'] - row['price'])), atr=atr)
    sources = dict(quote=tickers.get('updated'), chart=chart.get('updated'),
                   candle=chart.get('candle_end'), book=book.get('updated'), fetched=book.get('fetched'))
    limits = dict(quote=45, chart=75, candle=120, book=8, fetched=8)
    expires = {key: sources[key] + limits[key] if selection.finite(sources[key]) else 0 for key in sources}
    return dict(symbol=symbol, state=state, reasons=[c['label'] for c in failed],
                score=verdict['rating'].get('score') if complete else None,
                checks=checks, book_good=book_good, near=near,
                near_known=quote_ok and chart_ok and book_ok and aligned,
                price=row['price'], sources=sources, expires=expires)


class MarketAlerts:
    """Four filter scopes, 100 tracked coins and 50 recent events per scope."""
    def __init__(self):
        self.lock = threading.RLock()
        self.epoch = uuid.uuid4().hex
        self.sequence = 0
        self.scopes = OrderedDict()

    def register(self, filters, search, now, watch=''):
        watched = selection.parse_watch(watch)
        key = hashlib.sha256(json.dumps([filters, search, watched], sort_keys=True).encode()).hexdigest()[:20]
        with self.lock:
            if key not in self.scopes:
                self.scopes[key] = dict(filters=dict(filters), search=search, watch=watched, touched=now,
                                        states={}, events=[], rows=[], analyzing=[])
            self.scopes[key]['touched'] = now
            self.scopes.move_to_end(key)
            while len(self.scopes) > 4:
                self.scopes.popitem(last=False)
        return key

    def active(self, now):
        with self.lock:
            return [(key, dict(s['filters']), s['search']) for key, s in self.scopes.items()
                    if -2 <= now - s['touched'] <= 30]

    def update(self, key, tickers, charts, books, histories, now):
        with self.lock:
            scope = self.scopes.get(key)
            if scope is None:
                return
            filters, search = scope['filters'], scope['search']
            quotes = {r['symbol']: r for r in tickers.get('rows', [])[:100]
                      if isinstance(r, dict) and isinstance(r.get('symbol'), str) and
                      (search in r['symbol'] or r['symbol'] in scope['watch'])}
            analyzing = selection.shortlist(list(quotes.values()), tickers.get('updated'), filters,
                                            search, scope['watch'], now) if usable(tickers, now, 45) else []
            symbols = list(dict.fromkeys(analyzing + list(scope['states'])))[:100]
            current = []
            for symbol in symbols:
                if symbol not in quotes:
                    # A missing row or a shorter response is not evidence of a cancelled condition.
                    scope['states'][symbol]['current'] = None
                    continue
                value = measure(quotes[symbol], tickers, charts.get(symbol, {}), books.get(symbol, {}),
                                histories.get(symbol, []), filters, now)
                previous = scope['states'].get(symbol, dict(state=None, book_good=None, near=None, sources={}))
                # Never turn a response from an older cache generation into a new transition.
                rollback = any(selection.finite(value['sources'].get(k)) and selection.finite(t) and
                               value['sources'][k] < t for k, t in previous['sources'].items())
                if rollback:
                    previous['current'] = None
                    scope['states'][symbol] = previous
                    continue
                current.append(value)
                if value['state'] != 'unavailable':
                    old = previous['state']
                    if old in ('ready', 'almost') and value['state'] != old and value['state'] != 'ready':
                        self._emit(scope, value, 'cancelled', now, 'Не выполнено: ' + ', '.join(value['reasons']))
                    if value['state'] in ('ready', 'almost') and old != value['state']:
                        detail = ('Все 12 проверок отбора пройдены. Проверьте направление и вход в PAPER-плане.'
                                  if value['state'] == 'ready' else
                                  'Одна проверка в пределах 20% от порога: ' + ', '.join(value['reasons']))
                        self._emit(scope, value, value['state'], now, detail)
                    previous['state'] = value['state']
                if value['book_good'] is not None:
                    if previous['book_good'] is True and value['book_good'] is False:
                        labels = [c['label'] for c in value['checks'] if c['key'] in BOOK_KEYS and c['state'] == 'fail']
                        self._emit(scope, value, 'book_worse', now, 'Не выполнено: ' + ', '.join(labels), ('quote', 'book', 'fetched'))
                    previous['book_good'] = value['book_good']
                if value['near_known']:
                    old_near, near = previous['near'], value['near']
                    held = old_near and old_near['low'] - .5 * old_near['atr'] <= value['price'] <= old_near['high'] + .5 * old_near['atr']
                    if near and not held:
                        label = 'Поддержка' if near['side'] == 'support' else 'Сопротивление'
                        self._emit(scope, value, 'near_level', now,
                                   label + ' 1м: ' + format(near['low'], '.8g') + '–' + format(near['high'], '.8g') +
                                   ' · зона ±0,25 ATR', level={k: near[k] for k in ('side', 'low', 'high')})
                    previous['near'] = old_near if held else near
                for k, t in value['sources'].items():
                    if selection.fresh(t, now, dict(quote=45, chart=75, candle=120, book=8, fetched=8)[k]):
                        previous['sources'][k] = t
                previous['current'] = value
                scope['states'][symbol] = previous
            scope['rows'], scope['analyzing'] = current, analyzing
            scope['events'] = [e for e in scope['events'] if -2 <= now - e['time'] <= 300][:50]

    def _emit(self, scope, value, kind, now, detail, required=None, level=None):
        for previous in scope['events']:
            if previous['symbol'] == value['symbol'] and previous['kind'] == kind:
                previous['superseded'] = True
        self.sequence += 1
        required = required or ('quote', 'chart', 'candle', 'book', 'fetched')
        event = dict(id=self.epoch + ':' + str(self.sequence), sequence=self.sequence,
                     symbol=value['symbol'], kind=kind, label=LABELS[kind], time=now,
                     expires=min(now + 30, *(value['expires'][k] for k in required)),
                     sources={k: value['sources'][k] for k in required},
                     detail=detail, score=value['score'], price=value['price'], level=level)
        scope['events'].insert(0, event)
        scope['events'] = scope['events'][:50]

    def snapshot(self, key, now):
        with self.lock:
            scope = self.scopes.get(key)
            if scope is None:
                return dict(status='pending', epoch=self.epoch, scope=key, updated=now,
                            cursor=self.sequence, rows=[], events=[], analyzing=[], analysis_limit=8)
            events = []
            for event in scope['events']:
                value = scope['states'].get(event['symbol'], {}).get('current')
                valid = value and not event.get('superseded') and event['expires'] >= now and -2 <= now - event['time'] <= 30
                if valid and event['kind'] in ('ready', 'almost'):
                    valid = value['state'] == event['kind']
                if valid and event['kind'] == 'cancelled':
                    valid = value['state'] in ('waiting', 'almost')
                if valid and event['kind'] == 'book_worse':
                    valid = value['book_good'] is False
                if valid and event['kind'] == 'near_level':
                    valid = value['near_known'] and value['near'] is not None
                # A failed refresh must immediately remove the previous positive event.
                if valid and event['kind'] in ('ready', 'almost', 'cancelled', 'near_level'):
                    valid = value['state'] != 'unavailable' if event['kind'] != 'near_level' else value['near_known']
                if valid:
                    events.append(dict(event))
            return dict(status='ok', epoch=self.epoch, scope=key, updated=now, cursor=self.sequence,
                        analyzing=list(scope['analyzing']), analysis_limit=8,
                        rows=[{k: v for k, v in row.items() if k not in ('expires', 'checks')} for row in scope['rows']],
                        events=events, filters=dict(scope['filters']), search=scope['search'], watch=list(scope['watch']))
