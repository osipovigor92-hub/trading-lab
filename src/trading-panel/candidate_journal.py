"""Durable evidence from cached selection decisions. Never modifies a PAPER account."""
from contextlib import contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import selection
from market_alerts import measure, usable

VERSION = 1
INTERVAL = 10
MAX_RECORDS = 20_000
SYMBOL = re.compile(r'^[A-Z0-9]{2,24}USDT$')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def scope_id(filters, search):
    return hashlib.sha256(json.dumps([filters, search], sort_keys=True).encode()).hexdigest()[:20]


def parse_query(query, now):
    """One bounded, stable cursor page; the same parameters apply to CSV."""
    allowed = {'before', 'limit', 'status', 'search', 'period', 'scope', 'anchor'}
    if set(query) - allowed or any(len(v) != 1 for v in query.values()):
        raise ValueError('Некорректные параметры журнала')
    result = dict(before=0, limit=20, status='all', search='', period='day', scope='all', anchor=int(now)+1)
    for key in ('before', 'limit', 'anchor'):
        if key in query:
            raw = query[key][0]
            if not re.fullmatch(r'[0-9]{1,12}', raw):
                raise ValueError('Некорректная страница журнала')
            result[key] = int(raw)
    if not 1 <= result['limit'] <= 50 or not 0 <= result['before'] <= 2**53 or not 0 < result['anchor'] <= now+2:
        raise ValueError('Страница журнала вне допустимых границ')
    for key in ('status', 'search', 'period', 'scope'):
        if key in query:
            result[key] = query[key][0]
    if (result['status'] not in ('all', 'passed', 'rejected', 'pending', 'signal') or
            result['period'] not in ('day', 'week', 'all') or result['scope'] not in ('all', 'default') or
            not re.fullmatch(r'[A-Z0-9]{0,24}', result['search'])):
        raise ValueError('Некорректный фильтр журнала')
    result['since'] = result['anchor'] - {'day': 86400, 'week': 7*86400, 'all': result['anchor']}[result['period']]
    return result


def evidence(row, tickers, chart, book, history, filters, search, now):
    """Unknown/error sources cannot become a measured rejection or a passed candidate."""
    symbol = row['symbol']
    chart_ok = (usable(chart, now, 75) and chart.get('symbol') == symbol and chart.get('interval') == '1'
                and selection.fresh(chart.get('candle_end'), now, 120))
    book_ok = (usable(book, now, 8) and book.get('symbol') == symbol and
               selection.fresh(book.get('fetched'), now, 8) and selection.finite(book.get('mid')) and
               book['mid'] > 0 and abs(row['price']/book['mid']-1)*100 <= .1)
    safe_chart = chart if chart_ok else {}
    safe_book = book if book_ok else {}
    safe_history = [b for b in history[-5:] if b.get('symbol') == symbol and
                    not b.get('error') and not b.get('refresh_error')] if book_ok else []
    measured = measure(row, tickers, safe_chart, safe_book, safe_history, filters, now)
    verdict = selection.evaluate(row, tickers['updated'], safe_chart, safe_history, filters, now)
    checks = verdict['checks']
    status = ('rejected' if any(c['state'] == 'fail' for c in checks) else
              'passed' if measured['state'] == 'ready' else 'pending')
    # Retain original times, including invalid/stale ones, as historical evidence.
    sources = dict(quote=tickers.get('updated'), chart=chart.get('updated'), candle=chart.get('candle_end'),
                   book=book.get('updated'), fetched=book.get('fetched'))
    source_status = dict(quote='ok', chart='ok' if chart_ok else 'unavailable', book='ok' if book_ok else 'unavailable')
    return dict(version=VERSION, filters=dict(filters), search=search, status=status,
                readiness=measured['state'], price=row['price'], checks=checks,
                rating=verdict['rating'] if measured['state'] != 'unavailable' else dict(status='pending', score=None),
                sources=sources, source_status=source_status, book_samples=verdict['samples'],
                funding_interval_hours=row.get('funding_interval_hours'),
                source_errors={k:str(p.get('refresh_error') or p.get('error') or '')[:180]
                               for k,p in (('quote',tickers),('chart',chart),('book',book))},
                note=('Полное подтверждение текущих источников отсутствует; известные проверки сохранены отдельно'
                      if measured['state']=='unavailable' else 'Все измерения подтверждены на момент записи'))


class CandidateJournal:
    def __init__(self, root=Path('/var/lib/trading-candidate-journal'), clock=time.time, max_records=MAX_RECORDS):
        self.root, self.clock, self.max_records = Path(root), clock, max_records
        self.path = self.root/'candidates.sqlite3'
        self.lock = threading.RLock()
        self.error = ''
        self.installed = False
        self.last_cycle = self.last_quote = 0
        self.gap_active = False
        try:
            if not self.root.is_dir() or self.root.is_symlink() or self.path.is_symlink():
                raise OSError('Постоянный журнал ещё не установлен')
            with self.connect(write=True) as db:
                # A corrupt or incompatible database is preserved, never recreated.
                if db.execute('PRAGMA user_version').fetchone()[0] not in (0, VERSION):
                    raise ValueError('Версия хранилища журнала не поддерживается')
                db.execute('CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, '
                           'scope TEXT NOT NULL, symbol TEXT NOT NULL, status TEXT NOT NULL, '
                           'first_seen REAL NOT NULL, last_seen REAL NOT NULL, samples INTEGER NOT NULL, '
                           'signature TEXT NOT NULL, source_key TEXT NOT NULL, failed TEXT NOT NULL, '
                           'event_key TEXT UNIQUE, body TEXT NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS entry_head ON entries(kind, scope, symbol, id)')
                db.execute('CREATE INDEX IF NOT EXISTS entry_time ON entries(last_seen)')
                db.execute('CREATE TABLE IF NOT EXISTS monitor (id INTEGER PRIMARY KEY, last_cycle REAL, last_quote REAL, gap_active INTEGER)')
                db.execute('INSERT OR IGNORE INTO monitor VALUES (1, 0, 0, 0)')
                self.last_cycle, self.last_quote, self.gap_active = db.execute('SELECT last_cycle, last_quote, gap_active FROM monitor WHERE id=1').fetchone()
                db.execute('PRAGMA user_version=1')
            self.installed = True
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.error = str(exc)

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path if write else self.path.as_uri()+'?mode=ro', uri=not write, timeout=.5)
        try:
            if write:
                db.execute('PRAGMA synchronous=FULL')
                # 128 MiB at SQLite's default page size; no automatic history deletion.
                size = db.execute('PRAGMA page_size').fetchone()[0]
                db.execute('PRAGMA max_page_count='+str(128*1024*1024//size))
                db.execute('BEGIN IMMEDIATE')
            else:
                db.execute('BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def capacity(self, db):
        if db.execute('SELECT COUNT(*) FROM entries').fetchone()[0] >= self.max_records:
            raise ValueError('Лимит журнала достигнут; сбор остановлен, сохранённая история доступна')

    def cycle(self, tickers, charts, books, histories, scopes, now=None):
        now = self.clock() if now is None else now
        if not self.installed:
            return
        if now < self.last_cycle-2:
            self.error = 'Системное время вернулось назад; сбор ждёт согласованного времени'
            return
        try:
            with self.lock, self.connect(write=True) as db:
                self.capacity(db)
                if self.last_cycle and now-self.last_cycle > 30:
                    self._gap(db, self.last_cycle+INTERVAL, now, 'Пауза между сохранениями; решения за пропуск не восстанавливались')
                good = usable(tickers, now, 45)
                if good:
                    rows = [r for r in tickers.get('rows', [])[:100] if isinstance(r, dict) and
                            isinstance(r.get('symbol'), str) and SYMBOL.fullmatch(r['symbol']) and
                            selection.finite(r.get('price')) and r['price'] > 0]
                    for filters, search in scopes[:5]:
                        scope = scope_id(filters, search)
                        for row in rows:
                            if search not in row['symbol']:
                                continue
                            value = evidence(row, tickers, charts.get(row['symbol'], {}), books.get(row['symbol'], {}),
                                             histories.get(row['symbol'], []), filters, search, now)
                            self._decision(db, scope, row['symbol'], value, now)
                else:
                    self._gap(db, now, now, 'Нет свежих котировок; решения за пропуск не восстанавливались')
                db.execute('UPDATE monitor SET last_cycle=?, last_quote=?, gap_active=? WHERE id=1',
                           (now, tickers['updated'] if good else self.last_quote, int(not good)))
            self.last_cycle = now
            self.gap_active = not good
            if good:
                self.last_quote = tickers['updated']
            self.error = '' if good else 'Нет свежих котировок; решения за этот пропуск не восстанавливаются'
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
            self.error = 'Сбор журнала остановлен: '+str(exc)[:180]

    def _gap(self, db, start, end, detail):
        previous = db.execute("SELECT id,last_seen,signature FROM entries WHERE kind='gap' ORDER BY id DESC LIMIT 1").fetchone()
        if self.gap_active and previous and previous[2] == detail and 0 <= start-previous[1] <= 30:
            db.execute('UPDATE entries SET last_seen=? WHERE id=?', (end, previous[0]))
            return
        self.capacity(db)
        db.execute('INSERT INTO entries(kind,scope,symbol,status,first_seen,last_seen,samples,signature,source_key,failed,body) '
                   'VALUES (?,?,?,?,?,?,1,?,?,?,?)',
                   ('gap', scope_id(selection.DEFAULT_FILTERS, ''), 'SYSTEM', 'gap', start, end, detail, '', '[]',
                    encode(dict(version=VERSION, detail=detail))))

    def _decision(self, db, scope, symbol, value, now):
        failed = [dict(key=c['key'], label=c['label']) for c in value['checks'] if c['state'] == 'fail']
        signature = encode([value['status'], value['readiness'], [(c['key'], c['state']) for c in value['checks']]])
        source_key = encode([value['sources'], value['source_status']])
        previous = db.execute('SELECT id, signature, source_key, last_seen FROM entries '
                              "WHERE kind='candidate' AND scope=? AND symbol=? ORDER BY id DESC LIMIT 1", (scope, symbol)).fetchone()
        if previous:
            if now < previous[3]:
                return
            old, old_status = json.loads(previous[2])
            group = dict(quote='quote', chart='chart', candle='chart', book='book', fetched='book')
            if any(old_status.get(group[k]) == value['source_status'].get(group[k]) == 'ok' and
                   selection.finite(v) and selection.finite(old.get(k)) and v < old[k]
                   for k, v in value['sources'].items()):
                return
            if previous[1] == signature and previous[2] == source_key:
                return
            if previous[1] == signature and now-previous[3] <= 30:
                db.execute('UPDATE entries SET last_seen=?, samples=samples+1, source_key=? WHERE id=?',
                           (now, source_key, previous[0]))
                return
        self.capacity(db)
        db.execute('INSERT INTO entries(kind,scope,symbol,status,first_seen,last_seen,samples,signature,source_key,failed,body) '
                   'VALUES (?,?,?,?,?,?,1,?,?,?,?)',
                   ('candidate', scope, symbol, value['status'], now, now, signature, source_key, encode(failed), encode(value)))

    def event(self, event, filters, search, measured):
        """Called at the original alert transition, before its 30-second expiry."""
        if not self.installed:
            return
        scope = scope_id(filters, search)
        # Independent of browser polling and monitor epoch; replay of the same evidence is idempotent.
        key = hashlib.sha256(encode([scope, event['symbol'], event['kind'], event['sources'], event.get('level')]).encode()).hexdigest()
        try:
            with self.lock, self.connect(write=True) as db:
                if db.execute('SELECT 1 FROM entries WHERE event_key=?', (key,)).fetchone():
                    return
                self.capacity(db)
                body = dict(version=VERSION, filters=dict(filters), search=search, event=dict(event),
                            checks=measured['checks'], readiness=measured['state'], price=measured['price'],
                            sources=dict(measured['sources']), score=measured['score'])
                db.execute('INSERT INTO entries(kind,scope,symbol,status,first_seen,last_seen,samples,signature,source_key,failed,event_key,body) '
                           'VALUES (?,?,?,?,?,?,1,?,?,?,?,?)',
                           ('signal', scope, event['symbol'], 'signal', event['time'], event['time'], event['kind'],
                            encode(event['sources']), '[]', key, encode(body)))
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            self.error = 'Событие не сохранено: '+str(exc)[:180]

    def page(self, params):
        now = self.clock()
        base = dict(updated=now, collector=dict(installed=self.installed, interval=INTERVAL,
                    last_cycle=self.last_cycle, last_quote=self.last_quote,
                    collecting=self.installed and not self.error and selection.fresh(self.last_cycle, now, 30), error=self.error),
                    rows=[], total=0, next_before=0, summary=dict(counts={}, reasons=[]), coverage=None,
                    query={k:v for k,v in params.items() if k != 'since'})
        if not self.installed:
            return dict(base, status='unavailable')
        clauses = ['last_seen>=?', 'first_seen<=?', 'symbol LIKE ?']
        values = [params['since'], params['anchor'], params['search']+'%']
        if params['status'] != 'all':
            clauses.append('status=?');values.append(params['status'])
        if params['scope'] == 'default':
            clauses.append('scope=?');values.append(scope_id(selection.DEFAULT_FILTERS, ''))
        where = ' AND '.join(clauses)
        try:
            with self.lock, self.connect() as db:
                total = db.execute('SELECT COUNT(*) FROM entries WHERE '+where, values).fetchone()[0]
                coverage = db.execute('SELECT MIN(first_seen), MAX(last_seen) FROM entries').fetchone()
                counts = dict(db.execute('SELECT status,COUNT(*) FROM entries WHERE '+where+' GROUP BY status', values))
                causes = {}
                for (raw,) in db.execute("SELECT failed FROM entries WHERE status='rejected' AND "+where, values):
                    for reason in json.loads(raw):
                        item = causes.setdefault(reason['key'], dict(key=reason['key'], label=reason['label'], count=0))
                        item['count'] += 1
                page_where, page_values = where, list(values)
                if params['before']:
                    page_where += ' AND id<?';page_values.append(params['before'])
                rows = db.execute('SELECT id,kind,scope,symbol,status,first_seen,last_seen,samples,body FROM entries WHERE '+
                                  page_where+' ORDER BY id DESC LIMIT ?', page_values+[params['limit']+1]).fetchall()
            entries = [dict(zip(('id','kind','scope','symbol','status','first_seen','last_seen','samples','evidence'),
                       (*r[:-1], json.loads(r[-1])))) for r in rows[:params['limit']]]
            return dict(base, status='partial' if self.error else 'ok', rows=entries, total=total,
                        next_before=entries[-1]['id'] if len(rows)>params['limit'] else 0,
                        coverage=dict(first=coverage[0], last=coverage[1]),
                        summary=dict(counts=counts, reasons=sorted(causes.values(), key=lambda r:(-r['count'], r['key']))))
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            base['collector']['error'] = 'История недоступна: '+str(exc)[:180]
            base['collector']['collecting'] = False
            return dict(base, status='unavailable')


def csv_page(packet, manual=False):
    """CSV exports exactly the bounded page shown; JSON evidence remains lossless."""
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    columns = ('id','symbol','opened','closed','side','entry','exit','quantity','gross','entry_fee','exit_fee','net','complete','reason','exit_reason','observation_gap') if manual else ('id','kind','scope','symbol','status','first_seen','last_seen','samples','evidence_json')
    writer.writerow(columns)
    def safe(value):
        text = '' if value is None else str(value)
        # Text supplied by clients/upstream cannot execute a spreadsheet formula.
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) and not selection.finite(value) else text
    for row in packet.get('rows', []):
        writer.writerow([safe(encode(row['evidence']) if key == 'evidence_json' else row.get(key)) for key in columns])
    return ('\ufeff'+stream.getvalue()).encode()
