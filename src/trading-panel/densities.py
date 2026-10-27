"""Bounded observations of public order-book densities; no private trading API."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

EXCHANGES = ('binance', 'bybit', 'okx', 'gate', 'bitget')
SYMBOL = re.compile(r'^[A-Z0-9]{1,28}USDT$')
TRACK_MIN = 50_000.0
SCAN_LIMIT = 20
MAX_ROWS = 500
HISTORY_LIMIT = 200
FRESH_SECONDS = 25
MAX_OBSERVATION_GAP = 30
STABLE_SECONDS = 3600


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def decimal(value):
    if isinstance(value, bool):
        raise ValueError('Invalid book number')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Invalid book number') from None
    if not result.is_finite() or result <= 0 or not math.isfinite(float(result)):
        raise ValueError('Invalid book number')
    return result


def price_text(value):
    return format(decimal(value).normalize(), 'f')


def density_id(exchange, symbol, side, price):
    text = '\0'.join((exchange, symbol, side, price_text(price)))
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def parse_exchanges(value=None):
    if value is not None and not isinstance(value, (str, list, tuple)):
        raise ValueError('Invalid exchange list')
    values = value.split(',') if isinstance(value, str) else list(value) if value is not None else list(EXCHANGES)
    if (not values or len(values) > len(EXCHANGES) or any(not isinstance(v,str) for v in values) or
            len(set(values)) != len(values) or any(v not in EXCHANGES for v in values)):
        raise ValueError('Choose supported exchanges once each')
    return values


def parse_pairs(value=None):
    """Watch accepts canonical symbols or explicit exchange:canonical-symbol pairs."""
    if value is not None and not isinstance(value, (str, list, tuple)):
        raise ValueError('Invalid watched symbols')
    values = value.split(',') if isinstance(value, str) and value else list(value) if value is not None and not isinstance(value, str) else []
    if len(values) > SCAN_LIMIT or any(not isinstance(v,str) for v in values) or len(set(values)) != len(values):
        raise ValueError('Up to 20 different watched contracts')
    result = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError('Invalid watched symbol')
        parts = raw.split(':')
        if len(parts) == 1 and SYMBOL.fullmatch(raw):
            result.append((None, raw))
        elif len(parts) == 2 and parts[0] in EXCHANGES and SYMBOL.fullmatch(parts[1]):
            result.append(tuple(parts))
        else:
            raise ValueError('Invalid watched symbol')
    return result


class DensityMonitor:
    """Shares the adapter's bounded cache/workers; creates no network worker pool.

    One scheduler visits two contracts per second in round-robin order. A full
    20-contract scan normally takes ten seconds; latency and exchange limits can
    leave an observation unavailable, rather than extending its lifetime.
    """
    def __init__(self, adapter, clock=time.time, state_path=None, background=False):
        self.adapter, self.clock = adapter, clock
        self.lock = threading.RLock()
        self.rows = OrderedDict()
        self.history = []
        self.books = {}
        self.catalogs = {}
        self.selected = list(EXCHANGES)
        self.symbols, self.watch = [], []
        self.overlay_watch = {}
        self.targets = []
        self.cursor = 0
        self.catalog_cursor = 0
        self.sequence = 0
        self.epoch = uuid.uuid4().hex
        self.state_path = Path(state_path) if state_path is not None else None
        self.persistence_error = ''
        self.last_saved = float('-inf')
        self.stop_event = threading.Event()
        self.thread = None
        self._restore()
        if background:
            self.start_background()

    def start_background(self):
        if self.thread:
            return
        def run():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    # Every cache read is isolated in tick; a scheduler failure
                    # must never turn previously observed age into fresh proof.
                    with self.lock:
                        self._expire(self.clock())
                self.stop_event.wait(1)
        self.thread = threading.Thread(target=run, name='density-cache-observer', daemon=True)
        self.thread.start()

    def request(self, exchanges=None, symbols=None, watch=None, *, overlay=False):
        selected, wanted, watched = parse_exchanges(exchanges), parse_pairs(symbols), parse_pairs(watch)
        with self.lock:
            if overlay:
                pairs = [(venue, symbol) for venue, symbol in watched + wanted if venue in selected]
                for pair in pairs[:13]:
                    self.overlay_watch[pair] = self.clock() + 15
                while len(self.overlay_watch) > 13:
                    del self.overlay_watch[next(iter(self.overlay_watch))]
            else:
                self.selected, self.symbols, self.watch = selected, wanted, watched
            self._targets()
        return self.snapshot({'exchanges': selected} if overlay else None)

    def _targets(self):
        self.overlay_watch = {pair: until for pair, until in self.overlay_watch.items() if until > self.clock()}
        selected = list(dict.fromkeys(self.selected + [venue for venue, _ in self.overlay_watch]))
        targets = []
        # Explicit priority is bounded even while a catalog is warming up. The
        # adapter verifies contract existence before performing a public fetch.
        for exchange, symbol in list(self.overlay_watch) + self.watch + self.symbols:
            for candidate in ([exchange] if exchange else selected):
                if candidate in selected and (candidate, symbol) not in targets:
                    targets.append((candidate, symbol))
        for exchange in selected:
            packet = self.catalogs.get(exchange, {})
            catalog_source = packet.get('source_ts', packet.get('updated'))
            # Cache TTL expiry does not erase its verified contract universe.
            # Keep it briefly during refresh to preserve scan continuity.
            catalog_usable = ((packet.get('status') == 'ok' and not packet.get('stale') or
                               packet.get('status') == 'pending') and not packet.get('error') and
                              not packet.get('refresh_error') and finite(catalog_source) and
                              -2 <= self.clock()-catalog_source <= 90)
            if not catalog_usable:
                continue
            rows = [row for row in packet.get('rows', []) if isinstance(row, dict) and
                    isinstance(row.get('symbol'), str) and SYMBOL.fullmatch(row['symbol'])]
            rows.sort(key=lambda row: -(row.get('turnover24', row.get('turnover', 0))
                                       if finite(row.get('turnover24', row.get('turnover'))) else 0))
            for row in rows[:2]:
                pair = (exchange, row['symbol'])
                if pair not in targets:
                    targets.append(pair)
        self.targets = targets[:SCAN_LIMIT]
        # A catalog refresh must not erase replay protection for book snapshots.
        # Keep bounded recent book state until its venue is deselected/evicted.
        self.books = {key: value for key, value in self.books.items() if key[0] in selected}

    def tick(self):
        """Observe at most two cached books; adapter owns all REST scheduling."""
        now = self.clock()
        with self.lock:
            selected = list(dict.fromkeys(self.selected + [venue for venue, until in self.overlay_watch.items() if until > now]))
        # Rotate catalogs and alternate admission priority. A five-second catalog
        # TTL must not monopolize the one shared non-chart worker forever.
        with self.lock:
            turn = self.catalog_cursor
            self.catalog_cursor += 1
        if selected:
            offset = turn % len(selected)
            selected = selected[offset:] + selected[:offset]
        def catalogs():
            packets = {}
            for exchange in selected:
                try:
                    packets[exchange] = self.adapter.exchange_snapshot(exchange)
                except Exception as exc:
                    packets[exchange] = dict(status='error', updated=0, error=str(exc)[:160])
            with self.lock:
                self.catalogs.update(packets)
                self._targets()
        if turn % 2 == 0:
            catalogs()
        with self.lock:
            self._targets()
            self._expire(now)
            count = min(2, len(self.targets))
            pairs = [self.targets[(self.cursor+index) % len(self.targets)] for index in range(count)]
            self.cursor += count
            targets = list(self.targets)
        for exchange, symbol in pairs:
            try:
                packet = self.adapter.book_snapshot(exchange, symbol)
            except Exception as exc:
                packet = dict(status='error', updated=0, error=str(exc)[:160])
            self.observe(exchange, symbol, packet, now)
        if turn % 2:
            catalogs()
        # Harvest already completed books every second, not once per 20-pair
        # rotation. This adds no network requests and preserves source ages.
        if hasattr(self.adapter, 'peek_book'):
            for exchange, symbol in targets:
                try:
                    packet = self.adapter.peek_book(exchange, symbol)
                except Exception:
                    continue
                self.observe(exchange, symbol, packet, now)

    def _record(self, row, now, reason):
        self.sequence += 1
        item = dict(self._public(row), event_id=self.epoch+':'+str(self.sequence), density_id=row['id'],
                    observed_at=now, reason=reason)
        if row['status'] != 'active':
            item['age_seconds'] = row.get('episode_age_seconds', 0)
            item['stable'] = False
        self.history.insert(0, item)
        self.history = self.history[:HISTORY_LIMIT]

    def _interrupt(self, row, status, now, reason):
        if row['status'] == 'active':
            # Historical duration is the last verified episode, while current
            # qualification resets immediately at the first uncertain sample.
            row['episode_age_seconds'] = row['age_seconds']
        if row['status'] != status:
            row['status'] = status
            row['stable'] = False
            self._record(row, now, reason)
        row['continuous_since'] = None
        row['age_seconds'] = 0
        row['stable'] = False

    def _expire(self, now):
        for row in self.rows.values():
            if row['status'] == 'active' and not -2 <= now-row['last_seen'] <= FRESH_SECONDS:
                self._interrupt(row, 'unavailable', now, 'Нет свежего наблюдения стакана')

    def observe(self, exchange, symbol, packet, now=None):
        """Accept only a new, fresh successful book; replay cannot advance age."""
        if exchange not in EXCHANGES or not SYMBOL.fullmatch(symbol):
            raise ValueError('Invalid contract')
        now = self.clock() if now is None else now
        with self.lock:
            key = (exchange, symbol)
            previous = self.books.get(key, {})
            if not finite(previous.get('source_ts')):
                known = [row['last_seen'] for row in self.rows.values() if (row['exchange'],row['symbol']) == key]
                if known:
                    previous = dict(previous, source_ts=max(known))
            source = packet.get('source_ts') if isinstance(packet, dict) else None
            updated = packet.get('updated') if isinstance(packet, dict) else None
            # Adapter TTL (5s) is shorter than a full density scan (up to10s).
            # Pending refresh may retain a verified response. Only its actual
            # bounded source/receipt times count, never this polling time.
            state_usable = isinstance(packet, dict) and (packet.get('status') == 'ok' and not packet.get('stale') or
                                                         packet.get('status') == 'pending' and packet.get('stale') is True)
            valid = (state_usable and not packet.get('error') and not packet.get('refresh_error') and
                     packet.get('exchange') == exchange and packet.get('symbol') == symbol and
                     finite(source) and finite(updated) and -2 <= now-source <= FRESH_SECONDS and
                     -2 <= now-updated <= FRESH_SECONDS)
            if not valid:
                failure = packet if isinstance(packet, dict) else {}
                pending = failure.get('status') == 'pending'
                self.books[key] = dict(previous, status='pending' if pending else 'unavailable',
                                       error='' if pending else str(failure.get('error') or 'Нет свежего стакана')[:160])
                for row in self.rows.values():
                    if (row['exchange'], row['symbol']) == key and row['status'] != 'missing':
                        row['misses'] = 0
                        self._interrupt(row, 'unavailable', now, 'Стакан недоступен; срок наблюдения прерван')
                self._save()
                return False
            if finite(previous.get('source_ts')) and source <= previous['source_ts']:
                if source < previous['source_ts']:
                    for row in self.rows.values():
                        if (row['exchange'], row['symbol']) == key and row['status'] != 'missing':
                            row['misses'] = 0
                            self._interrupt(row, 'unavailable', now, 'Время источника откатилось')
                self._expire(now)
                return False
            try:
                levels = {}
                ladders = {}
                for side, field in (('bid', 'bids'), ('ask', 'asks')):
                    values = packet.get(field)
                    if not isinstance(values, list) or not 1 <= len(values) <= 1000:
                        raise ValueError('Invalid book depth')
                    parsed = [(decimal(pair[0]), decimal(pair[1])) for pair in values if isinstance(pair, (list, tuple)) and len(pair) == 2]
                    if len(parsed) != len(values) or any((a[0] <= b[0] if side == 'bid' else a[0] >= b[0])
                                                        for a, b in zip(parsed, parsed[1:])):
                        raise ValueError('Invalid book order')
                    ladders[side] = parsed
                    for price, quantity in parsed:
                        notional = float(price * quantity)
                        if not math.isfinite(notional):
                            raise ValueError('Invalid book notional')
                        levels[(side, price_text(price))] = notional
                if ladders['bid'][0][0] >= ladders['ask'][0][0]:
                    raise ValueError('Crossed book')
                mid = (ladders['bid'][0][0] + ladders['ask'][0][0]) / 2
                coverage = packet.get('coverage', {})
                bid_min, ask_max = decimal(coverage.get('bid_min')), decimal(coverage.get('ask_max'))
                if bid_min != ladders['bid'][-1][0] or ask_max != ladders['ask'][-1][0]:
                    raise ValueError('Invalid book coverage')
            except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation):
                return self.observe(exchange, symbol, dict(status='error', error='Некорректный стакан'), now)
            self.books[key] = dict(status='ok', source_ts=source, updated=updated, error='',
                                   timestamp_origin=packet.get('timestamp_origin', 'exchange'))
            while len(self.books) > SCAN_LIMIT:
                self.books.pop(next(iter(self.books)))
            averages = {}
            for side in ('bid', 'ask'):
                values = [v for (s, _), v in levels.items() if s == side]
                total = sum(values)
                for level, value in levels.items():
                    if level[0] == side:
                        mean = (total-value)/(len(values)-1) if len(values)>=21 else None
                        averages[level] = (mean, value/mean if mean and mean>0 else None, len(values)-1)
            qualified = {level for level, value in levels.items()
                         if value >= TRACK_MIN or (averages[level][1] is not None and averages[level][1]>=10)}
            for level, notional in levels.items():
                side, price = level
                if level not in qualified:
                    continue
                identity = density_id(exchange, symbol, side, price)
                row = self.rows.get(identity)
                if row is None:
                    row = dict(id=identity, exchange=exchange, symbol=symbol, side=side,
                               price=float(decimal(price)), price_text=price, notional=notional,
                               first_seen=source, last_seen=source, continuous_since=max(source, now),
                               age_seconds=0, episode_age_seconds=0, status='active', stable=False, misses=0)
                    self.rows[identity] = row
                else:
                    uninterrupted = (row['status'] == 'active' and finite(row.get('continuous_since')) and
                                     0 < source-row['last_seen'] <= MAX_OBSERVATION_GAP)
                    if not uninterrupted:
                        # A still-fresh cached packet may predate restart or
                        # recovery. Its old source time cannot backdate a new
                        # observation episode before this local observation.
                        row['continuous_since'] = max(source, now)
                    row.update(status='active', last_seen=source, notional=notional, misses=0)
                    row['age_seconds'] = max(0, source-row['continuous_since'])
                    row['stable'] = row['age_seconds'] >= STABLE_SECONDS
                row.update(baseline_notional=averages[level][0], size_multiple=averages[level][1], baseline_levels=averages[level][2])
                row['distance_pct'] = float(abs(decimal(price)/mid-1)*100)
                row['timestamp_origin'] = packet.get('timestamp_origin', 'exchange')
                self.rows.move_to_end(identity)
            for row in self.rows.values():
                if (row['exchange'], row['symbol']) != key:
                    continue
                level = (row['side'], row['price_text'])
                if level in qualified:
                    continue
                price = decimal(row['price_text'])
                covered = (bid_min <= price < mid if row['side'] == 'bid' else mid < price <= ask_max)
                if not covered:
                    row['misses'] = 0
                    if row['status'] != 'missing':
                        self._interrupt(row, 'unobserved', now, 'Уровень за пределами полученной глубины')
                    continue
                row['misses'] += 1
                if row['misses'] >= 2:
                    self._interrupt(row, 'missing', now, 'Нет плотности в двух свежих снимках с покрытием уровня')
                elif row['status'] != 'missing':
                    self._interrupt(row, 'unobserved', now, 'Нет плотности в одном снимке; ждём подтверждение')
            while len(self.rows) > MAX_ROWS:
                victim = next((identity for identity, row in self.rows.items() if row['status'] != 'active'), next(iter(self.rows)))
                self.rows.pop(victim)
            self._save()
            return True

    @staticmethod
    def _public(row):
        return {key:value for key, value in row.items() if key not in ('continuous_since', 'misses', 'episode_age_seconds')}

    def snapshot(self, filters=None):
        now = self.clock()
        with self.lock:
            self._expire(now)
            selected = filters.get('exchanges', self.selected) if filters else self.selected
            exchanges = []
            for exchange in selected:
                catalog = self.catalogs.get(exchange, {})
                total = catalog.get('eligible', len(catalog.get('rows', [])))
                total = total if type(total) is int and total >= 0 else 0
                books = [packet for (venue, _), packet in self.books.items() if venue == exchange]
                scanned = sum(packet.get('status') == 'ok' and finite(packet.get('source_ts')) and
                              -2 <= now-packet['source_ts'] <= FRESH_SECONDS for packet in books)
                errors = list(dict.fromkeys(str(packet['error']) for packet in books if packet.get('error')))
                if catalog.get('error'):
                    errors.insert(0, str(catalog['error']))
                status = 'ok' if scanned else 'error' if errors or catalog.get('status') == 'error' else 'pending'
                updated = max((packet.get('updated', 0) for packet in books if finite(packet.get('updated'))),
                              default=catalog.get('updated', 0))
                exchanges.append(dict(id=exchange, status=status, updated=updated,
                                      error='; '.join(errors)[:160], total=total, scanned=scanned))
            scanned = sum(exchange['scanned'] for exchange in exchanges)
            return dict(status='ok' if scanned else 'error' if any(exchange['status']=='error' for exchange in exchanges) else 'pending', updated=now,
                        rows=[self._public(row) for row in self.rows.values() if row['exchange'] in selected],
                        history=[dict(row) for row in self.history if row['exchange'] in selected],
                        coverage=dict(total=sum(exchange['total'] for exchange in exchanges), scanned=scanned,
                                      limit=SCAN_LIMIT, selected=len(self.targets), min_notional=TRACK_MIN,
                                      stable_seconds=STABLE_SECONDS, poll_seconds=10), exchanges=exchanges,
                        error=self.persistence_error,
                        note='Периодические снимки; наблюдаемый срок не доказывает непрерывность между снимками')

    def _restore(self):
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            if self.state_path.stat().st_size > 1_000_000:
                raise ValueError('Density state exceeds bound')
            data = json.loads(self.state_path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('rows'), list):
                raise ValueError('Invalid density state')
            now = self.clock()
            for raw in data['rows'][-MAX_ROWS:]:
                exchange, symbol, side = raw['exchange'], raw['symbol'], raw['side']
                if exchange not in EXCHANGES or not SYMBOL.fullmatch(symbol) or side not in ('bid', 'ask'):
                    continue
                price = price_text(raw.get('price_text', raw['price']))
                identity = density_id(exchange, symbol, side, price)
                if (any(not finite(raw.get(field)) for field in ('first_seen','last_seen','notional','distance_pct')) or
                        raw['first_seen'] > raw['last_seen'] or raw['last_seen'] > now+2 or
                        raw['notional'] < TRACK_MIN or raw['distance_pct'] < 0):
                    continue
                row = dict(raw, id=identity, price=float(decimal(price)), price_text=price,
                           status='unavailable', stable=False, age_seconds=0, episode_age_seconds=0,
                           continuous_since=None, misses=0)
                self.rows[identity] = row
            self.history = [dict(row) for row in data.get('history', [])[:HISTORY_LIMIT] if isinstance(row, dict) and
                            row.get('exchange') in EXCHANGES and isinstance(row.get('symbol'), str) and
                            SYMBOL.fullmatch(row['symbol']) and row.get('side') in ('bid', 'ask') and
                            isinstance(row.get('id'), str) and
                            all(finite(row.get(field)) for field in ('price','notional','first_seen','last_seen','distance_pct'))]
            self.sequence = data.get('sequence', 0) if type(data.get('sequence')) is int else 0
        except (OSError, ValueError, KeyError, TypeError):
            self.persistence_error = 'Не удалось прочитать историю плотностей'

    def _save(self, force=False):
        now = self.clock()
        if self.state_path is None or not force and now-self.last_saved < 30:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.state_path.with_name(self.state_path.name + '.tmp')
            temporary.write_text(json.dumps(dict(version=1, rows=list(self.rows.values()), history=self.history,
                                                  sequence=self.sequence), ensure_ascii=False, allow_nan=False), encoding='utf-8')
            os.replace(temporary, self.state_path)
            self.last_saved = now
            self.persistence_error = ''
        except (OSError, ValueError, TypeError):
            self.persistence_error = 'История плотностей пока не сохранена на диск'

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self._save(force=True)

