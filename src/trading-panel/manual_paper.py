"""One durable manual PAPER position; public quotes only, no exchange orders."""
import hashlib
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time

CAPITAL = 600.0
HOLD = 180
SYMBOL = re.compile(r'[A-Z0-9]{2,24}USDT')
LIMITS = dict(capital=(10, 1e6), risk_pct=(.01, 5), max_notional=(1, 1e6),
              fee_pct=(0, 1), slippage_pct=(0, 5), min_rr=(1, 10))


def number(x):
    return type(x) in (int, float) and math.isfinite(x)


def fresh(t, now, age):
    return number(t) and -1 <= now-t <= age


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def quote(market, symbol, now):
    tickers, book = market.get('screener'), market.get('book', symbol)
    row = next((r for r in tickers.get('rows', []) if r.get('symbol') == symbol), None)
    if (tickers.get('status') != 'ok' or tickers.get('error') or not fresh(tickers.get('updated'), now, 12)
            or book.get('status') != 'ok' or book.get('error') or book.get('symbol') != symbol
            or not fresh(book.get('updated'), now, 5) or not fresh(book.get('fetched'), now, 8)
            or not row or not number(row.get('price')) or row['price'] <= 0
            or not number(book.get('mid')) or book['mid'] <= 0
            or abs(row['price']/book['mid']-1) > .001):
        raise ValueError('Нет согласованной свежей котировки и стакана; повторите после обновления')
    top = book.get('top', {})
    for name in ('bid', 'ask'):
        levels = top.get(name)
        if not isinstance(levels, list) or not 1 <= len(levels) <= 5:
            raise ValueError('Не подтверждена глубина стакана')
        if any(not isinstance(v, dict) or not number(v.get('price')) or v['price'] <= 0
               or not number(v.get('quantity')) or v['quantity'] <= 0 for v in levels):
            raise ValueError('Некорректный стакан')
        prices = [v['price'] for v in levels]
        if any((prices[i]-prices[i-1])*(1 if name == 'ask' else -1) <= 0 for i in range(1, len(prices))):
            raise ValueError('Некорректный порядок стакана')
    if top['bid'][0]['price'] >= top['ask'][0]['price']:
        raise ValueError('Пересечённый стакан')
    mid = (top['bid'][0]['price']+top['ask'][0]['price'])/2
    spread = (top['ask'][0]['price']-top['bid'][0]['price'])/mid
    if abs(mid/book['mid']-1) > 1e-6 or not 0 < spread < .01:
        raise ValueError('Стакан не согласован или спред слишком широк')
    return row, book, mid, spread


def execution(book, qty, side, slip):
    remaining, total = qty, 0.
    levels = book['top']['ask' if side == 1 else 'bid']
    for level in levels:
        take = min(remaining, level['quantity'])
        total += take*level['price']
        remaining -= take
    if remaining > qty*1e-10:
        raise ValueError('Недостаточно подтверждённой глубины для этого количества')
    price = total/qty
    if abs(price/levels[0]['price']-1) > slip+1e-10:
        raise ValueError('Impact превышает выбранный допуск')
    return price*(1+side*slip)


def prepare(plan, market, balance, now):
    fields = {'symbol', 'side', 'low', 'high', 'stop', 'target', 'stamp', 'interval', 'settings', 'reason'}
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError('Некорректный ручной PAPER-план')
    symbol, side, settings = plan['symbol'], plan['side'], plan['settings']
    if (not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or type(side) is not int
            or side not in (-1, 1) or plan['interval'] not in ('1', '5', '15', '60')
            or not isinstance(settings, dict) or set(settings) != set(LIMITS)
            or not isinstance(plan['reason'], str) or not 1 <= len(plan['reason'].strip()) <= 240):
        raise ValueError('Некорректные поля PAPER-плана')
    if any(not number(v) or not LIMITS[k][0] <= v <= LIMITS[k][1] for k, v in settings.items()):
        raise ValueError('Некорректные настройки риска')
    if settings['max_notional'] > settings['capital']:
        raise ValueError('Лимит входа превышает капитал расчёта')
    if any(not number(plan[k]) or plan[k] <= 0 for k in ('low', 'high', 'stop', 'target', 'stamp')):
        raise ValueError('Некорректные уровни плана')
    period = int(plan['interval'])*60
    if not fresh(plan['stamp'], now, period+75):
        raise ValueError('План устарел; обновите скринер')
    low, high, stop, target = (plan[k] for k in ('low', 'high', 'stop', 'target'))
    if not (low <= high and (stop < low <= high < target if side == 1 else target < low <= high < stop)):
        raise ValueError('Стоп и цель не соответствуют направлению')
    row, book, mid, spread = quote(market, symbol, now)
    if not low <= row['price'] <= high or not low <= mid <= high:
        raise ValueError('Цена вышла из зоны входа; обновите план')
    funding_time, rate = row.get('next_funding'), row.get('funding')
    if not number(rate) or not number(funding_time) or funding_time-now <= HOLD+120:
        raise ValueError('Нет времени funding или он слишком близко для входа на 180 секунд')
    fee, slip = settings['fee_pct']/100, settings['slippage_pct']/100
    worst = (high if side == 1 else low)*(1+side*spread/2)*(1+side*slip)**2
    exit_stop = stop*(1-side*spread/2)*(1-side*slip)**2
    exit_target = target*(1-side*spread/2)*(1-side*slip)**2
    reserve = max(worst, exit_stop, exit_target)*max(0, side*rate)
    loss = side*(worst-exit_stop)+fee*(worst+exit_stop)+reserve
    profit = side*(exit_target-worst)-fee*(worst+exit_target)-reserve
    if loss <= 0 or profit/loss < settings['min_rr']:
        raise ValueError('Прибыль / риск после издержек ниже выбранного минимума')
    budget = min(balance, settings['capital'])*settings['risk_pct']/100
    ceiling = high*(1+spread/2)*(1+slip)**2
    qty = min(budget/loss, settings['max_notional']/ceiling, balance/(ceiling*(1+fee)))*(1-1e-10)
    entry = execution(book, qty, side, slip)
    execution(book, qty, -side, slip)
    risk = qty*(side*(entry-exit_stop)+fee*(entry+exit_stop)+reserve)
    if (qty <= 0 or entry*qty > settings['max_notional']+1e-8 or risk > budget+1e-8
            or entry*qty*(1+fee) > balance+1e-8 or side*(target-entry) <= 0):
        raise ValueError('Размер входа не проходит серверную проверку риска')
    return dict(symbol=symbol, side=side, entry=entry, quantity=qty, entry_fee=qty*entry*fee,
                opened=now, stop=stop, target=target, reason=plan['reason'].strip(),
                settings=settings, risk=risk, budget=budget, funding_time=funding_time,
                quote_time=book['updated'], interval=plan['interval'], blocked='', last_tick=now)


class ManualPaper:
    def __init__(self, market, root=Path('/var/lib/trading-manual-paper'), clock=time.time, background=False):
        self.market, self.root, self.clock = market, Path(root), clock
        self.lock, self.error = threading.RLock(), ''
        self.path = self.root/'paper.sqlite3'
        self.stop = threading.Event()
        try:
            if not self.root.is_dir() or self.path.is_symlink():
                raise OSError('Каталог ручного PAPER ещё не установлен')
            with self.connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, body TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
                db.execute('CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL)')
                db.execute('INSERT OR IGNORE INTO account VALUES (1, ?)', (encode(dict(balance=CAPITAL, paused=False, generation=0, incomplete=False, position=None)),))
                account = self.read(db)
                if account['position']:
                    account['position']['blocked'] = 'Перезапуск с позицией: непрерывность наблюдений не подтверждена'
                    self.write(db, account)
        except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
            self.error = str(exc)
        if background and not self.error:
            threading.Thread(target=self.run, name='manual-paper-monitor', daemon=True).start()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def read(db):
        return json.loads(db.execute('SELECT body FROM account WHERE id=1').fetchone()[0])

    @staticmethod
    def write(db, account):
        db.execute('UPDATE account SET body=? WHERE id=1', (encode(account),))

    def mark(self, p, now):
        row, book, mid, _ = quote(self.market, p['symbol'], now)
        price = execution(book, p['quantity'], -p['side'], p['settings']['slippage_pct']/100)
        gross = p['side']*p['quantity']*(price-p['entry'])
        exit_fee = p['quantity']*price*p['settings']['fee_pct']/100
        boundary = min(p['funding_time'], row['next_funding']) if number(row.get('next_funding')) and row['next_funding'] > p['opened'] else p['funding_time']
        complete = now < boundary-5
        return dict(exit=price, gross=gross, exit_fee=exit_fee,
                    net=gross-exit_fee-p['entry_fee'] if complete else None,
                    quote_time=book['updated'], mid=mid, complete=complete, funding_time=boundary)

    def close_position(self, db, a, mark, now, reason):
        p = a['position']
        record = dict(p, **{k: v for k, v in mark.items() if k != 'funding_time'}, closed=now, exit_reason=reason)
        if p['blocked']:
            record['observation_gap'] = p['blocked']
        db.execute('INSERT INTO trades VALUES (?, ?)', (p['id'], encode(record)))
        a['balance'] += mark['gross']-mark['exit_fee']
        a['incomplete'] = a['incomplete'] or not mark['complete']
        a['position'] = None
        a['generation'] += 1

    def cycle(self):
        if self.error:
            return
        now = self.clock()
        with self.lock, self.connect() as db:
            a = self.read(db)
            p = a['position']
            if not p or p['blocked']:
                return
            if not fresh(p['last_tick'], now, 10):
                p['blocked'] = 'Пропуск наблюдений: автоматический выход остановлен'
            else:
                try:
                    mark = self.mark(p, now)
                    if not mark['complete']:
                        p['blocked'] = 'Граница funding: net не подтверждён'
                    else:
                        reason = ('Стоп' if p['side']*(mark['mid']-p['stop']) <= 0 else
                                  'Цель 1' if p['side']*(mark['mid']-p['target']) >= 0 else
                                  'Лимит 180 секунд' if now-p['opened'] >= HOLD else
                                  'Приближается funding' if mark['funding_time']-now <= 15 else '')
                        if reason:
                            self.close_position(db, a, mark, now, reason)
                        else:
                            p['last_tick'] = now
                except ValueError as exc:
                    if now-p['last_tick'] > 8:
                        p['blocked'] = str(exc)
            self.write(db, a)

    def run(self):
        while not self.stop.wait(1):
            try:
                self.cycle()
            except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
                self.error = 'Хранилище PAPER недоступно: '+str(exc)

    def snapshot(self):
        if self.error:
            return dict(status='unavailable', updated=self.clock(), error=self.error)
        with self.lock, self.connect() as db:
            a = self.read(db)
            now = self.clock()
            p = a['position']
            if p:
                p['mark'] = None
                try:
                    p['mark'] = self.mark(p, now)
                except ValueError as exc:
                    p['valuation_error'] = str(exc)
            trades = [json.loads(r[0]) for r in db.execute('SELECT body FROM trades ORDER BY rowid DESC LIMIT 20')]
            return dict(a, status='ok', updated=now, capital=CAPITAL, hold_seconds=HOLD, trades=trades)

    def journal(self, before=0, limit=20):
        """Read every stored closing through cursor pages, without account writes/valuation."""
        if type(before) is not int or before < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('Некорректная страница ручного PAPER')
        if self.error:
            return dict(status='unavailable', updated=self.clock(), error=self.error, rows=[], total=0, next_before=0)
        with self.lock:
            db = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True, timeout=.5)
            try:
                db.execute('BEGIN')
                total = db.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
                sql = 'SELECT rowid,body FROM trades'
                values = []
                if before:
                    sql += ' WHERE rowid<?';values.append(before)
                rows = db.execute(sql+' ORDER BY rowid DESC LIMIT ?', values+[limit+1]).fetchall()
                result = [dict(json.loads(body), cursor=cursor) for cursor, body in rows[:limit]]
                return dict(status='ok', updated=self.clock(), rows=result, total=total,
                            next_before=result[-1]['cursor'] if len(rows)>limit else 0)
            finally:
                db.close()

    def command(self, command):
        if self.error:
            raise ValueError(self.error)
        if not isinstance(command, dict) or set(command) not in ({'id', 'action', 'generation'}, {'id', 'action', 'generation', 'plan'}):
            raise ValueError('Некорректная команда PAPER')
        uid, action = command['id'], command['action']
        if not isinstance(uid, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', uid) or action not in ('open', 'close', 'pause', 'resume'):
            raise ValueError('Некорректная команда PAPER')
        if ('plan' in command) != (action == 'open'):
            raise ValueError('Некорректный план команды')
        digest = hashlib.sha256(encode(command).encode()).hexdigest()
        with self.lock, self.connect() as db:
            old = db.execute('SELECT digest, response FROM commands WHERE id=?', (uid,)).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError('Идентификатор команды уже использован')
                return json.loads(old[1])
            a, now = self.read(db), self.clock()
            if type(command['generation']) is not int or command['generation'] != a['generation']:
                raise ValueError('Состояние PAPER изменилось; обновите вкладку')
            if action == 'open':
                if a['paused'] or a['incomplete'] or a['position'] or a['balance'] <= 0:
                    raise ValueError('Новый вход недоступен: пауза, открытая позиция или неполный учёт')
                p = prepare(command['plan'], self.market, a['balance'], now)
                p['id'] = uid
                a['balance'] -= p['entry_fee']
                a['position'] = p
            elif action == 'close':
                if not a['position']:
                    raise ValueError('Нет ручной позиции для закрытия')
                self.close_position(db, a, self.mark(a['position'], now), now, 'Ручное закрытие')
            else:
                a['paused'] = action == 'pause'
            if action != 'close':
                a['generation'] += 1
            result = dict(status='accepted', id=uid, generation=a['generation'])
            self.write(db, a)
            db.execute('INSERT INTO commands VALUES (?, ?, ?)', (uid, digest, encode(result)))
            return result
