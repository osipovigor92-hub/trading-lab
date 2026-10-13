"""Bounded observations of public order-book densities; no private trading API."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import median
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
SCAN_SECONDS = 1
CATALOG_SECONDS = 30
# Transparent scanner heuristics, not calibrated bot probabilities. All size
# comparisons stay inside one venue, contract and side of a public snapshot.
SIGNIFICANT_MIN = 100_000.0
NEAR_DISTANCE_PCT = 0.5
RELATIVE_SIZE_MIN = 5.0
DEPTH_SHARE_MIN = 0.2
PRESSURE_SHARE_MIN = 0.6
NEIGHBOR_LIMIT = 12
EVIDENCE_WINDOW = 120
EVIDENCE_LIMIT = 12
PATTERN_PATH_LIMIT = 3
WALL_SIZE_TOLERANCE = 0.35
EVIDENCE_CANDIDATE_LIMIT = 6


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

    One scheduler asks for at most two book refreshes per second. Read-only cache
    drains observe completed jobs each second and on an HTTP snapshot, without
    waiting for the next ten-second refresh round or creating network work.
    """
    def __init__(self, adapter, clock=time.time, state_path=None, background=False):
        self.adapter, self.clock = adapter, clock
        self.lock = threading.RLock()
        self.rows = OrderedDict()
        self.history = []
        self.books = {}
        self.evidence = OrderedDict()
        self.catalogs = {}
        self.selected = list(EXCHANGES)
        self.symbols, self.watch = [], []
        self.targets = []
        self.scan_queue = OrderedDict()
        self.priorities = ()
        self.priority_retries = {}
        self.catalog_attempts = {}
        self.next_scan_at = float('-inf')
        self.sequence = 0
        self.epoch = uuid.uuid4().hex
        self.state_path = Path(state_path) if state_path is not None else None
        self.persistence_error = ''
        self.last_saved = float('-inf')
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = None
        self._restore()
        if background:
            self.start_background()

    def start_background(self):
        if self.thread:
            return
        def run():
            while not self.stop_event.is_set():
                self.wake_event.clear()
                try:
                    self.tick()
                except Exception:
                    # Every cache read is isolated in tick; a scheduler failure
                    # must never turn previously observed age into fresh proof.
                    with self.lock:
                        self._expire(self.clock())
                self.wake_event.wait(SCAN_SECONDS)
        self.thread = threading.Thread(target=run, name='density-cache-observer', daemon=True)
        self.thread.start()

    def request(self, exchanges=None, symbols=None, watch=None):
        selected, wanted, watched = parse_exchanges(exchanges), parse_pairs(symbols), parse_pairs(watch)
        with self.lock:
            changed = (self.selected, self.symbols, self.watch) != (selected, wanted, watched)
            self.selected, self.symbols, self.watch = selected, wanted, watched
            self._targets()
        if changed:
            self.wake_event.set()
        return self.snapshot()

    def _targets(self):
        targets = []
        # Explicit priority is bounded even while a catalog is warming up. The
        # adapter verifies contract existence before performing a public fetch.
        for exchange, symbol in self.watch + self.symbols:
            for candidate in ([exchange] if exchange else self.selected):
                if candidate in self.selected and (candidate, symbol) not in targets:
                    targets.append((candidate, symbol))
        priorities = list(targets)
        for exchange in self.selected:
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
        # Preserve rotation when rankings change, and move a newly requested
        # explicit pair to the front once. Repeating the same HTTP filter must
        # not continually restart the queue and starve the other contracts.
        urgent = [pair for pair in priorities if pair in self.targets and pair not in self.priorities]
        order = urgent + [pair for pair in self.scan_queue if pair in self.targets and pair not in urgent]
        order.extend(pair for pair in self.targets if pair not in order)
        self.scan_queue = OrderedDict((pair, None) for pair in order)
        self.priorities = tuple(pair for pair in priorities if pair in self.targets)
        self.priority_retries = {pair:value for pair, value in self.priority_retries.items()
                                 if pair in self.priorities}
        for pair in urgent:
            # A cold explicit book may be refused while metadata/catalog jobs
            # occupy the two shared slots. Retry next second, with both a three
            # retry budget and a four-second deadline; blocked pairs then rotate.
            self.priority_retries[pair] = [3, self.clock()+4]
        # A catalog refresh must not erase replay protection for book snapshots.
        # Keep bounded recent book state until its venue is deselected/evicted.
        self.books = {key: value for key, value in self.books.items() if key[0] in self.selected}
        self.evidence = OrderedDict((key, value) for key, value in self.evidence.items()
                                    if key[0] in self.selected)

    def tick(self):
        """Admit two book reads per second and drain already completed jobs."""
        now = self.clock()
        with self.lock:
            if now < self.next_scan_at:
                scan = False
            else:
                self.next_scan_at = now + SCAN_SECONDS
                scan = True
            selected = list(self.selected)
            catalogs = []
            if scan:
                for exchange in selected:
                    packet = self.catalogs.get(exchange, {})
                    delay = (CATALOG_SECONDS if packet.get('status') == 'ok' and not packet.get('stale') and
                             not packet.get('error') and not packet.get('refresh_error') else
                             5 if packet.get('status') == 'error' or packet.get('error') or packet.get('refresh_error') else 1)
                    if now - self.catalog_attempts.get(exchange, float('-inf')) >= delay:
                        self.catalog_attempts[exchange] = now
                        catalogs.append(exchange)
        packets = {}
        for exchange in catalogs:
            try:
                packets[exchange] = self.adapter.exchange_snapshot(exchange)
            except Exception as exc:
                packets[exchange] = dict(status='error', updated=0, error=str(exc)[:160])
        with self.lock:
            self.catalogs.update(packets)
            self._targets()
            self._expire(now)
            pairs = []
            if scan:
                for _ in range(min(2, len(self.scan_queue))):
                    pair, _ = self.scan_queue.popitem(last=False)
                    self.scan_queue[pair] = None
                    pairs.append(pair)
        retry_first = []
        for exchange, symbol in pairs:
            try:
                packet = self.adapter.book_snapshot(exchange, symbol)
            except Exception as exc:
                packet = dict(status='error', updated=0, error=str(exc)[:160])
            self.observe(exchange, symbol, packet, now)
            with self.lock:
                pair = (exchange, symbol)
                retry = self.priority_retries.get(pair)
                cold_refused = (isinstance(packet, dict) and packet.get('status') == 'pending' and
                                packet.get('queued') is False and packet.get('updated') is None and
                                packet.get('source_ts') is None and not packet.get('error') and
                                not packet.get('refresh_error'))
                if retry and cold_refused and retry[0] > 0 and now < retry[1]:
                    retry[0] -= 1
                    retry_first.append(pair)
                elif retry:
                    self.priority_retries.pop(pair, None)
        with self.lock:
            # Reverse insertion keeps the first requested pair first.
            for pair in reversed(retry_first):
                if pair in self.scan_queue:
                    self.scan_queue.move_to_end(pair, last=False)
        self._drain_ready()

    def _drain_ready(self):
        """Read existing cache entries only; no fetch admission or fake stamps."""
        peek = getattr(self.adapter, 'peek_book_snapshot', None)
        if not callable(peek):
            return
        with self.lock:
            pairs = list(self.targets)
        for exchange, symbol in pairs:
            try:
                packet = peek(exchange, symbol)
            except Exception:
                # A cache-inspection failure is not a new upstream observation.
                # Existing source age still expires normally in snapshot/tick.
                continue
            if (not isinstance(packet, dict) or
                    packet.get('updated') is None and packet.get('source_ts') is None and
                    not packet.get('error') and not packet.get('refresh_error')):
                continue
            with self.lock:
                if (exchange, symbol) not in self.targets:
                    continue
                self.observe(exchange, symbol, packet)

    @staticmethod
    def _assess_levels(ladders, mid):
        """Explain size using only this snapshot's visible same-side liquidity.

        Exclude the candidate from its nearby-level median. Sparse books have
        no ratio rather than treating one very large level as its own baseline.
        Depth/pressure shares explicitly describe returned depth, not all orders.
        """
        notionals = {side: [float(price*quantity) for price, quantity in ladder]
                     for side, ladder in ladders.items()}
        totals = {side: math.fsum(values) for side, values in notionals.items()}
        near_totals = {side: math.fsum(value for (price, _), value in zip(ladder, notionals[side])
                                     if float(abs(price/mid-1)*100) <= NEAR_DISTANCE_PCT)
                       for side, ladder in ladders.items()}
        near_total = math.fsum(near_totals.values())
        if not all(math.isfinite(value) for value in (*totals.values(), near_total)):
            raise ValueError('Invalid summed book notional')
        assessed = {}
        for side, ladder in ladders.items():
            for index, ((price, _), notional) in enumerate(zip(ladder, notionals[side])):
                if notional < TRACK_MIN:
                    continue
                nearby = [(other_price, notionals[side][other_index])
                          for other_index, (other_price, _) in enumerate(
                              ladder[max(0, index-NEIGHBOR_LIMIT):index+NEIGHBOR_LIMIT+1],
                              start=max(0, index-NEIGHBOR_LIMIT))
                          if other_index != index and
                          float(abs(other_price/price-1)*100) <= NEAR_DISTANCE_PCT]
                nearby.sort(key=lambda value: abs(value[0]-price))
                neighbors = [value for _, value in nearby[:NEIGHBOR_LIMIT]]
                baseline = median(neighbors) if len(neighbors) >= 3 else None
                baseline = baseline if baseline is not None and baseline > 0 else None
                relative = notional/baseline if baseline is not None else None
                relative = relative if relative is not None and math.isfinite(relative) else None
                distance = float(abs(price/mid-1)*100)
                share = notional/totals[side]
                large, near = notional >= SIGNIFICANT_MIN, distance <= NEAR_DISTANCE_PCT
                outlier = relative is not None and relative >= RELATIVE_SIZE_MIN
                concentrated = len(ladder) >= 5 and share >= DEPTH_SHARE_MIN
                significant = large and near and (outlier or concentrated)
                reasons = []
                reasons.append('large_notional' if large else 'below_size_threshold')
                reasons.append('near_price' if near else 'outside_near_zone')
                if outlier:
                    reasons.append('relative_outlier')
                if concentrated:
                    reasons.append('visible_depth_concentration')
                if baseline is None:
                    reasons.append('insufficient_neighbors')
                elif not outlier and not concentrated:
                    reasons.append('ordinary_local_size')
                assessed[(side, price_text(price))] = dict(
                    status='significant' if significant else 'ordinary',
                    kind='large_wall' if significant else None,
                    observed_kind='large_wall' if significant else None,
                    score=20*large+20*near+20*outlier+10*concentrated,
                    reasons=reasons, relative_size=relative, local_median_notional=baseline,
                    neighbor_count=len(neighbors), visible_depth_share=share,
                    side_depth_notional=totals[side], side_level_count=len(ladder),
                    distance_pct=distance,
                    near_pressure_share=near_totals[side]/near_total if near_total else None,
                    near_depth_notional=near_total,
                    observations=0, first_source_ts=None, last_source_ts=None,
                    source_stamps=[], confidence='single_snapshot',
                    pattern=dict(samples=0, repricings=0, side_pressure_observations=0,
                                 window_seconds=EVIDENCE_WINDOW, price_path=[], ambiguous=False))
        return assessed

    def _observe_evidence(self, key, source, ladders, levels, assessed, mid):
        """Bounded correspondence of visible walls, never an order/actor identity.

        A move requires the old large level to have shrunk in covered depth and
        a uniquely corresponding similar-size level at a new covered price.
        Added walls, ambiguous matches and movement of mid alone are insufficient.
        """
        prior = self.evidence.get(key, {})
        if not finite(prior.get('source_ts')) or not 0 < source-prior['source_ts'] <= MAX_OBSERVATION_GAP:
            prior = {}
        stamps = [stamp for stamp in prior.get('source_stamps', [])
                  if 0 <= source-stamp <= EVIDENCE_WINDOW]
        current = dict(source_ts=source, source_stamps=(stamps+[source])[-EVIDENCE_LIMIT:], sides={})
        for side, ladder in ladders.items():
            candidates = [(price, significance) for (candidate_side, price), significance in assessed.items()
                          if candidate_side == side and significance['status'] == 'significant']
            candidates.sort(key=lambda value: (-levels[(side, value[0])], value[1]['distance_pct']))
            overflow = len(candidates) > EVIDENCE_CANDIDATE_LIMIT
            candidates = candidates[:EVIDENCE_CANDIDATE_LIMIT]
            old_side = prior.get('sides', {}).get(side, {})
            old_candidates = old_side.get('candidates', [])
            lower, upper = ladder[-1][0], ladder[0][0]
            lower, upper = min(lower, upper), max(lower, upper)
            possible = []
            for price, significance in candidates:
                matches = []
                if not overflow and not old_side.get('overflow'):
                    for old_index, old in enumerate(old_candidates):
                        old_price, new_price = decimal(old['price_text']), decimal(price)
                        similar = 1-WALL_SIZE_TOLERANCE <= levels[(side, price)]/old['notional'] <= 1+WALL_SIZE_TOLERANCE
                        current_pressure = significance['near_pressure_share']
                        old_pressure = old['chain'][-1]['near_pressure_share']
                        pressure = (current_pressure is not None and old_pressure is not None and
                                    current_pressure >= PRESSURE_SHARE_MIN and old_pressure >= PRESSURE_SHARE_MIN)
                        if not similar or not pressure:
                            continue
                        if old_price == new_price:
                            matches.append((old_index, False))
                            continue
                        covered = (lower <= old_price <= upper and
                                   old_side['lower'] <= new_price <= old_side['upper'])
                        toward = ((new_price > old_price if side == 'bid' else new_price < old_price) and
                                  abs(new_price-mid) < abs(old_price-mid))
                        old_shrank = levels.get((side, old['price_text']), 0) < SIGNIFICANT_MIN
                        if covered and toward and old_shrank:
                            matches.append((old_index, True))
                possible.append(matches)
            used = {}
            for matches in possible:
                for old_index, _ in matches:
                    used[old_index] = used.get(old_index, 0)+1
            stored = []
            for (price, significance), matches in zip(candidates, possible):
                unique = len(matches) == 1 and used[matches[0][0]] == 1
                ambiguous = overflow or bool(old_side.get('overflow')) or bool(matches) and not unique
                chain = old_candidates[matches[0][0]]['chain'] if unique else []
                chain = [step for step in chain if 0 <= source-step['source_ts'] <= EVIDENCE_WINDOW]
                step = dict(source_ts=source, price_text=price, distance_pct=significance['distance_pct'],
                            near_pressure_share=significance['near_pressure_share'],
                            mid_price_text=price_text(mid), moved=unique and matches[0][1])
                chain = (chain+[step])[-EVIDENCE_LIMIT:]
                # The first retained source has no retained predecessor and
                # cannot by itself count as an observed repricing.
                repricings = sum(bool(item['moved']) for item in chain[1:])
                pressure_count = sum(item['near_pressure_share'] is not None and
                                     item['near_pressure_share'] >= PRESSURE_SHARE_MIN for item in chain)
                moves = [index for index, item in enumerate(chain) if index and item['moved']]
                proof = ([chain[moves[-2]-1], chain[moves[-2]], chain[moves[-1]]]
                         if len(moves) >= 2 else chain[-PATTERN_PATH_LIMIT:])
                pattern = dict(samples=len(chain), repricings=repricings,
                               side_pressure_observations=pressure_count, window_seconds=EVIDENCE_WINDOW,
                               price_path=[{field: item[field] for field in ('source_ts','price_text','distance_pct')}
                                           for item in proof], ambiguous=ambiguous)
                significance['pattern'] = pattern
                if ambiguous:
                    significance['reasons'].append('ambiguous_correspondence')
                if len(chain) >= 3 and repricings >= 2 and pressure_count == len(chain) and not ambiguous:
                    significance.update(kind='machine_pattern_suspect', observed_kind='machine_pattern_suspect',
                                        confidence='repeated_pattern', score=significance['score']+25)
                    significance['reasons'].extend(('repeated_repricing', 'near_side_pressure'))
                stored.append(dict(price_text=price, notional=levels[(side, price)], chain=chain))
            current['sides'][side] = dict(lower=lower, upper=upper, candidates=stored, overflow=overflow)
        self.evidence[key] = current
        self.evidence.move_to_end(key)
        while len(self.evidence) > SCAN_LIMIT:
            self.evidence.popitem(last=False)

    @staticmethod
    def _inactive_significance(row):
        significance = row.get('significance')
        if isinstance(significance, dict):
            row['significance'] = dict(significance, status='inactive', kind=None,
                                       observed_kind=significance.get('kind') or significance.get('observed_kind'))

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
            self._inactive_significance(row)
            self._record(row, now, reason)
        row['continuous_since'] = None
        row['age_seconds'] = 0
        row['stable'] = False

    def _expire(self, now):
        self.evidence = OrderedDict((key, value) for key, value in self.evidence.items()
                                    if finite(value.get('source_ts')) and
                                    -2 <= now-value['source_ts'] <= FRESH_SECONDS)
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
                self.evidence.pop(key, None)
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
                    self.evidence.pop(key, None)
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
                assessed = self._assess_levels(ladders, mid)
            except (ValueError, TypeError, KeyError, OverflowError, InvalidOperation):
                return self.observe(exchange, symbol, dict(status='error', error='Некорректный стакан'), now)
            self.books[key] = dict(status='ok', source_ts=source, updated=updated, error='',
                                   timestamp_origin=packet.get('timestamp_origin', 'exchange'))
            while len(self.books) > SCAN_LIMIT:
                self.books.pop(next(iter(self.books)))
            self._observe_evidence(key, source, ladders, levels, assessed, mid)
            for level, notional in levels.items():
                side, price = level
                if notional < TRACK_MIN:
                    continue
                identity = density_id(exchange, symbol, side, price)
                row = self.rows.get(identity)
                old_significance = row.get('significance', {}) if row is not None else {}
                previous_stamps = (old_significance.get('source_stamps', [])
                                   if row is not None and row['status'] == 'active' and
                                   0 < source-row['last_seen'] <= MAX_OBSERVATION_GAP else [])
                stamps = [stamp for stamp in previous_stamps if finite(stamp) and
                          0 <= source-stamp <= EVIDENCE_WINDOW]
                stamps = (stamps+[source])[-EVIDENCE_LIMIT:]
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
                row['distance_pct'] = float(abs(decimal(price)/mid-1)*100)
                row['timestamp_origin'] = packet.get('timestamp_origin', 'exchange')
                significance = assessed[level]
                significance.update(observations=len(stamps), first_source_ts=stamps[0],
                                    last_source_ts=source, source_stamps=stamps)
                if len(stamps) >= 2:
                    significance['score'] += 5
                    if significance['confidence'] != 'repeated_pattern':
                        significance['confidence'] = 'repeated_observations'
                row['significance'] = significance
                self.rows.move_to_end(identity)
            for row in self.rows.values():
                if (row['exchange'], row['symbol']) != key:
                    continue
                level = (row['side'], row['price_text'])
                if levels.get(level, 0) >= TRACK_MIN:
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
        self._drain_ready()
        now = self.clock()
        with self.lock:
            self._expire(now)
            exchanges = []
            for exchange in self.selected:
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
                        rows=[self._public(row) for row in self.rows.values() if row['exchange'] in self.selected],
                        history=[dict(row) for row in self.history if row['exchange'] in self.selected],
                        coverage=dict(total=sum(exchange['total'] for exchange in exchanges), scanned=scanned,
                                      limit=SCAN_LIMIT, selected=len(self.targets), min_notional=TRACK_MIN,
                                      stable_seconds=STABLE_SECONDS, poll_seconds=10,
                                      observe_seconds=SCAN_SECONDS,
                                      significance=dict(min_notional=SIGNIFICANT_MIN,
                                          near_distance_pct=NEAR_DISTANCE_PCT, relative_size_min=RELATIVE_SIZE_MIN,
                                          visible_depth_share_min=DEPTH_SHARE_MIN, min_neighbors=3,
                                          depth_share_min_levels=5, near_pressure_share_min=PRESSURE_SHARE_MIN,
                                          evidence_window_seconds=EVIDENCE_WINDOW, evidence_limit=EVIDENCE_LIMIT,
                                          score_kind='rule_priority', depth_basis='returned_same_side_levels',
                                          pressure_basis='returned_bid_and_ask_within_near_distance')),
                        exchanges=exchanges,
                        error=self.persistence_error,
                        note='Периодические снимки; виден объём на цене, а не отдельный участник. '
                             'Повторное смещение похожего объёма не доказывает бота, исполнение, спуфинг '
                             'или непрерывность между снимками; доли относятся только к полученной глубине')

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
                self._inactive_significance(row)
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
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self._save(force=True)
