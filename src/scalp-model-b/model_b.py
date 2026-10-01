"""Independent Bybit PAPER research model. No authenticated endpoints or orders."""
import fcntl
import json
import math
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path('/var/lib/scalp-model-b')
STATE = ROOT / 'state.json'
URL = 'wss://stream.bybit.com/v5/public/linear'
C = dict(version='B1', capital=600., notional=100., fee=.00055,
         residual_slippage=.0005, max_hold=180, cooldown=120,
         max_loss=18., max_spread=.025, min_depth=5000.,
         min_flow15=1500., max_gap=5.)

def number(v):
    v = float(v)
    if not math.isfinite(v):
        raise ValueError('Non-finite number')
    return v

def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def api(endpoint, **params):
    url = 'https://api.bybit.com/v5/market/' + endpoint + '?' + urlencode(params)
    with urlopen(url, timeout=8) as f:
        data = json.load(f)
    stamp = number(data['time']) / 1000
    if data.get('retCode') != 0 or abs(time.time()-stamp) > 10:
        raise ValueError('API error or incorrect clock')
    return data['result'], stamp

def ema(values, n):
    result = [values[0]]
    a = 2 / (n+1)
    for v in values[1:]:
        result.append(a*v+(1-a)*result[-1])
    return result

def chart_from_bars(raw, stamp):
    bars = sorted([[number(v) for v in row] for row in raw], key=lambda r:r[0])
    bars = [r for r in bars if r[0]/1000+60 <= stamp][-120:]
    if len(bars) != 120 or any(b[0]-a[0] != 60000 for a,b in zip(bars,bars[1:])):
        raise ValueError('Need 120 continuous closed minute candles')
    end = bars[-1][0]/1000+60
    if not 0 <= stamp-end < 60:
        raise ValueError('Stale candles')
    if any(min(r[1:5]) <= 0 or r[2] < max(r[1],r[4],r[3]) or
           r[3] > min(r[1],r[4]) or min(r[5:7]) < 0 for r in bars):
        raise ValueError('Invalid OHLCV')
    closes = [r[4] for r in bars]
    e20, e50 = ema(closes,20), ema(closes,50)
    trs = [max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4]))
           for a,b in zip(bars,bars[1:])]
    atr = sum(trs[:14])/14
    for tr in trs[14:]:
        atr = (atr*13+tr)/14
    vol60 = sum(r[5] for r in bars[-60:])
    if vol60 <= 0 or atr <= 0:
        raise ValueError('No usable volume or volatility')
    # For linear USDT contracts: turnover USDT / volume in base units.
    vwap = sum(r[6] for r in bars[-60:])/vol60
    recent = sum(r[6] for r in bars[-5:])/5
    baseline = sum(r[6] for r in bars[-65:-5])/60
    side = (1 if closes[-1] > vwap and e20[-1] > e50[-1] and e20[-1] > e20[-6]
            else -1 if closes[-1] < vwap and e20[-1] < e50[-1] and e20[-1] < e20[-6]
            else 0)
    return dict(end=end, price=closes[-1], ema20=e20[-1], ema50=e50[-1],
                atr=atr, atr_pct=atr/closes[-1]*100, vwap60=vwap,
                rvol5=recent/baseline if baseline else 0., side=side)

class Charts:
    def __init__(self, symbols):
        self.symbols = symbols
        self.data = {}
        self.errors = {}
        self.lock = threading.Lock()
    def run(self):
        while True:
            for symbol in self.symbols:
                try:
                    data, stamp = api('kline',category='linear',symbol=symbol,interval='1',limit=125)
                    chart = chart_from_bars(data['list'],stamp)
                    ticker, _ = api('tickers',category='linear',symbol=symbol)
                    row = ticker['list'][0]
                    if row['symbol'] != symbol:
                        raise ValueError('Wrong ticker')
                    chart['next_funding'] = number(row['nextFundingTime'])/1000
                    if chart['next_funding'] <= time.time():
                        raise ValueError('Funding time unavailable')
                    chart['fetched'] = time.time()
                    with self.lock:
                        self.data[symbol] = chart
                        self.errors.pop(symbol,None)
                except Exception as exc:
                    with self.lock:
                        self.errors[symbol] = str(exc)[:160]
                time.sleep(.3)
            time.sleep(30)
    def get(self, symbol):
        with self.lock:
            return dict(self.data.get(symbol,{})), self.errors.get(symbol,'')

def ofi(previous, current):
    """Cont best-quote OFI, base units. Aggregated feed events, not individual orders."""
    bp,bq,ap,aq = previous
    nb,nq,na,nqa = current
    return ((nq if nb >= bp else 0)-(bq if nb <= bp else 0)
            -(nqa if na <= ap else 0)+(aq if na >= ap else 0))

def walk(levels, quantity):
    remaining, cost = quantity, 0.
    for price, size in levels:
        take = min(remaining,size)
        cost += take*price
        remaining -= take
        if remaining <= quantity*1e-10:
            return cost/quantity
    return None

class Book:
    def __init__(self, symbol):
        self.symbol = symbol
        self.b, self.a = {}, {}
        self.u = self.seq = 0
        self.ts = self.trade_ts = 0.
        self.started = time.time()
        self.flows = deque()
        self.ofis = deque()
        self.seen = {}
        self.last_cleanup = 0.
        self.prices = deque(maxlen=90)
        self.armed = None
    def reset(self):
        self.__init__(self.symbol)
    def top(self):
        bp,ap = max(self.b),min(self.a)
        return bp,self.b[bp],ap,self.a[ap]
    def book(self, msg):
        d = msg['data']
        if d['s'] != self.symbol:
            raise ValueError('Wrong symbol')
        ts = number(msg.get('cts',msg['ts']))/1000
        if not -1 <= time.time()-ts <= 3:
            raise ValueError('Stale book event')
        snapshot = msg['type'] == 'snapshot' or int(d['u']) == 1
        if snapshot:
            self.reset()
        else:
            if not self.u:
                raise ValueError('Delta before snapshot')
            if int(d['u']) == self.u:
                return
            if int(d['u']) < self.u or int(d['seq']) < self.seq or ts < self.ts:
                raise ValueError('Out-of-order book')
            if ts-self.ts > C['max_gap']:
                raise ValueError('Book observation gap; resynchronization required')
        previous = self.top() if self.b and self.a else None
        for target, key in ((self.b,'b'),(self.a,'a')):
            for p,q in d[key]:
                p,q = number(p),number(q)
                if p <= 0 or q < 0:
                    raise ValueError('Invalid level')
                if q == 0:
                    target.pop(p,None)
                else:
                    target[p] = q
        if not self.b or not self.a or max(self.b) >= min(self.a):
            raise ValueError('Empty/crossed book')
        if max(len(self.b),len(self.a)) > 1000:
            raise ValueError('Unexpected book size')
        top = self.top()
        if previous:
            self.ofis.append((ts,ofi(previous,top)))
        self.ts,self.u,self.seq = ts,int(d['u']),int(d['seq'])
        while self.ofis and self.ofis[0][0] < ts-60:
            self.ofis.popleft()
    def trades(self, msg):
        now = time.time()
        for r in msg['data']:
            if r['s'] != self.symbol:
                raise ValueError('Wrong trade symbol')
            t = number(r['T'])/1000
            if not -1 <= now-t <= 5:
                raise ValueError('Stale trade event')
            key = r['i']
            if key in self.seen:
                continue
            self.seen[key] = t
            if r.get('BT',False):
                continue
            p,q = number(r['p']),number(r['v'])
            if min(p,q) <= 0 or r['S'] not in ('Buy','Sell'):
                raise ValueError('Invalid trade')
            self.trade_ts = max(self.trade_ts,t)
            self.flows.append((t,p*q,1 if r['S']=='Buy' else -1))
        if now-self.last_cleanup >= 1:
            self.flows = deque(x for x in self.flows if x[0] >= now-60)
            self.seen = {k:v for k,v in self.seen.items() if v >= now-120}
            self.last_cleanup = now
        if len(self.seen) > 100000 or len(self.flows) > 50000:
            raise ValueError('Trade buffer overflow')
    def levels(self, side):
        return sorted((self.a if side==1 else self.b).items(), reverse=side==-1)
    def execution(self, quantity, side):
        price = walk(self.levels(side),quantity)
        return None if price is None else price*(1+side*C['residual_slippage'])
    def metrics(self, now):
        if not self.b or not self.a or not -1 <= now-self.ts <= 3:
            raise ValueError('Missing/stale book '+self.symbol)
        bp,bq,ap,aq = self.top()
        mid = (bp+ap)/2
        result = dict(symbol=self.symbol, time=self.ts, price=mid,
                      spread=(ap-bp)/mid*100, bands={})
        for width in (.0002,.0005,.001):
            bv = sum(p*q for p,q in self.b.items() if p >= mid*(1-width))
            av = sum(p*q for p,q in self.a.items() if p <= mid*(1+width))
            result['bands'][str(width)] = dict(
                bid=bv,ask=av,imbalance=(bv-av)/(bv+av) if bv+av else 0.,
                covered=min(self.b)<=mid*(1-width) and max(self.a)>=mid*(1+width))
        for seconds in (5,15,60):
            f = [x for x in self.flows if now-seconds <= x[0] <= now]
            buy = sum(v for _,v,s in f if s==1)
            sell = sum(v for _,v,s in f if s==-1)
            result['flow'+str(seconds)] = dict(buy=buy,sell=sell,count=len(f),
                ratio=(buy-sell)/(buy+sell) if buy+sell else 0.)
            result['ofi'+str(seconds)] = sum(v for t,v in self.ofis if now-seconds<=t<=now)
        result['ofi5_depth'] = result['ofi5']/max((bq+aq)/2,1e-12)
        result['ready'] = now-self.started >= 60 and 0 <= now-self.trade_ts <= 10
        # MODEL_B_DIAGNOSTICS_V1
        result['warmup_remaining'] = max(0., 60-(now-self.started))
        result['trade_age'] = now-self.trade_ts if self.trade_ts else None
        qty = C['notional']/mid
        buy,sell = self.execution(qty,1),self.execution(qty,-1)
        result['roundtrip_pct'] = ((buy-sell)/mid+C['fee']*(buy+sell)/mid)*100 if buy and sell else None
        result['impact_buy_pct'] = ((walk(self.levels(1),qty)/ap-1)*100 if buy else None)
        result['impact_sell_pct'] = ((1-walk(self.levels(-1),qty)/bp)*100 if sell else None)
        if not self.prices or self.ts > self.prices[-1][0]:
            self.prices.append((self.ts,mid))
        return result

def signal(book, m, chart, now):
    reasons = []
    if not m['ready']:
        reasons.append('Накопление потока или нет свежих сделок')
    if not chart or not 0 <= now-chart['end'] <= 120:
        book.armed = None
        return 0,['Нет свежих закрытых минутных свечей']
    side = chart['side']
    atr = chart['atr']
    if not side:
        book.armed = None
        reasons.append('Нет согласованного тренда EMA/VWAP')
    elif abs(m['price']-chart['ema20']) <= .35*atr:
        if not book.armed or book.armed['side'] != side:
            book.armed = dict(time=now,side=side)
    if book.armed and (book.armed['side'] != side or now-book.armed['time'] > 120):
        book.armed = None
    if not book.armed or now-book.armed['time'] < 3:
        reasons.append('Откат к EMA20 ещё не подтверждён')
    if side*(m['price']-chart['ema20']) <= .1*atr or abs(m['price']-chart['ema20']) > atr:
        reasons.append('Нет возобновления движения после отката')
    prices = [p for t,p in book.prices if 2 <= now-t <= 12]
    if len(prices) < 5 or (side==1 and m['price']<=max(prices)) or (side==-1 and m['price']>=min(prices)):
        reasons.append('Нет пробоя локального экстремума последних секунд')
    if m['spread'] > C['max_spread']:
        reasons.append('Широкий спред')
    band = m['bands']['0.001']
    if min(band['bid'],band['ask']) < C['min_depth']:
        reasons.append('Недостаточная глубина')
    if side*m['bands']['0.0005']['imbalance'] < .15:
        reasons.append('Ближний стакан не подтверждает направление')
    if side*m['ofi5'] <= 0:
        reasons.append('OFI не подтверждает направление')
    if side*m['flow5']['ratio'] < .3 or side*m['flow15']['ratio'] < .2:
        reasons.append('Лента 5/15 секунд не подтверждает направление')
    if m['flow15']['buy']+m['flow15']['sell'] < C['min_flow15'] or m['flow15']['count'] < 10:
        reasons.append('Мало исполненных сделок')
    if chart['rvol5'] < 1:
        reasons.append('Активность последних 5 минут ниже базы')
    if m['roundtrip_pct'] is None or 2*chart['atr_pct'] < 2*m['roundtrip_pct']:
        reasons.append('Масштаб движения мал относительно расходов')
    if chart['next_funding']-now <= C['max_hold']+120:
        reasons.append('Близко funding: новые входы пропускаются')
    return (side if not reasons else 0),reasons

def initial():
    return dict(config=C, mode='PAPER', phase='warming', reason='', updated=0.,
                balance=C['capital'], equity=C['capital'], peak=C['capital'],
                fees=0., position=None, trades=[], observations=[], cooldown_until=0.,
                started=time.time(), market_time=0.)

def mark_position(p, book):
    price = book.execution(p['quantity'],-p['side'])
    if price is None:
        raise ValueError('Insufficient exit book depth')
    gross = p['side']*p['quantity']*(price-p['entry'])
    fee = p['quantity']*price*C['fee']
    return price,gross,fee,gross-fee-p['entry_fee']

def close(s, book, now, reason):
    p = s['position']
    price,gross,fee,net = mark_position(p,book)
    s['balance'] += gross-fee
    s['fees'] += fee
    s['trades'].append(dict(**p,closed=now,exit=price,exit_fee=fee,gross=gross,
                           net=net,reason=reason,exit_quote_time=book.ts))
    s['position'] = None
    s['equity'] = s['balance']
    s['cooldown_until'] = now+C['cooldown']
    print('B CLOSE',p['symbol'],reason,round(net,5),flush=True)

def cycle(s, books, charts, now):
    p = s['position']
    if p:
        b = books[p['symbol']]
        if now-s['market_time'] > C['max_gap'] or not -1 <= now-b.ts <= 3:
            raise ValueError('DATA_GAP with open position; no fabricated close')
        price,gross,fee,net = mark_position(p,b)
        p['mfe_net'] = max(p['mfe_net'],net)
        p['mae_net'] = min(p['mae_net'],net)
        p['observations'] += 1
        s['equity'] = s['balance']+gross-fee
        if now >= p['funding_time']:
            raise ValueError('Funding boundary crossed; accounting incomplete')
        reason = ('Лимит потерь' if s['equity']<=C['capital']-C['max_loss'] else
                  'Стоп' if net<=-p['stop_usdt'] else
                  'Цель' if net>=p['target_usdt'] else
                  'Лимит времени' if now-p['opened']>=C['max_hold'] else '')
        if reason:
            close(s,b,now,reason)
    if s['equity'] <= C['capital']-C['max_loss']:
        s['phase'],s['reason'] = 'halted','Достигнут лимит потерь'
        return
    candidates,observations = [],[]
    for symbol,b in books.items():
        try:
            m = b.metrics(now)
            ch,error = charts.get(symbol)
            side,reasons = signal(b,m,ch,now)
            m.update(chart=ch,chart_error=error,reasons=reasons,
                     signal='LONG' if side==1 else 'SHORT' if side==-1 else 'WAIT')
            observations.append(m)
            if side:
                candidates.append((min(m['bands']['0.001']['bid'],m['bands']['0.001']['ask']),symbol,side,m,ch))
        except ValueError as exc:
            b.armed = None
            observations.append(dict(symbol=symbol,signal='WAIT',reasons=[str(exc)]))
    s['observations'] = observations
    if not s['position'] and now >= s['cooldown_until'] and candidates:
        _,symbol,side,m,ch = max(candidates,key=lambda x:x[0])
        b = books[symbol]
        # Solve quantity approximately to spend the fixed nominal at depth VWAP.
        qty = C['notional']/m['price']
        for _ in range(4):
            entry = b.execution(qty,side)
            if entry is None:
                break
            qty = C['notional']/entry
        entry = b.execution(qty,side)
        if entry is not None:
            entry_fee = qty*entry*C['fee']
            # Exit limits in net USDT; not forecasts, not guaranteed fill bounds.
            stop = max(.4,min(.8,C['notional']*ch['atr_pct']/100))
            target = max(.6,1.5*stop)
            s['balance'] -= entry_fee
            s['fees'] += entry_fee
            p = dict(symbol=symbol,side=side,quantity=qty,entry=entry,
                     entry_fee=entry_fee,opened=now,funding_time=ch['next_funding'],
                     stop_usdt=stop,target_usdt=target,features=m,
                     mfe_net=0.,mae_net=0.,observations=0)
            s['position'] = p
            _,gross,fee,net = mark_position(p,b)
            p['mfe_net'] = p['mae_net'] = net
            s['equity'] = s['balance']+gross-fee
            print('B OPEN',symbol,side,entry,flush=True)
            for market in books.values():
                market.armed = None
    if s['position'] is None:
        s['equity'] = s['balance']
    s['peak'] = max(s['peak'],s['equity'])
    s['market_time'] = now
    s['phase'],s['reason'] = 'running',''

def select_symbols():
    source = json.loads(Path('/var/lib/trading-live/live.json').read_text())
    if source['status'] != 'live' or not 0 <= time.time()-source['updated'] <= 10:
        raise ValueError('Existing LIVE is not fresh')
    symbols = [r['symbol'] for r in source['rows'] if r.get('ready')][:3]
    if not symbols or any(not x.isalnum() or not x.endswith('USDT') for x in symbols):
        raise ValueError('No usable LIVE symbols')
    return symbols

def main():
    import websocket
    lock = (ROOT/'lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    s = json.loads(STATE.read_text()) if STATE.exists() else initial()
    if s['config'] != C:
        raise RuntimeError('Saved configuration differs; do not reset experiment')
    if s['position'] or s['phase']=='halted':
        s['phase']='halted'
        s['reason']=s['reason'] or 'Restart with open position; valuation incomplete'
        s['updated']=time.time()
        atomic(STATE,s)
        return
    while True:
        try:
            symbols = s.get('symbols') or select_symbols()
            break
        except Exception as exc:
            s.update(phase='waiting',reason=str(exc),updated=time.time())
            atomic(STATE,s)
            time.sleep(5)
    s['symbols']=symbols
    charts=Charts(symbols)
    threading.Thread(target=charts.run,daemon=True).start()
    db=sqlite3.connect(ROOT/'history.sqlite')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS samples(t REAL PRIMARY KEY,data TEXT)')
    backoff=3
    while True:
        ws=None
        books={sym:Book(sym) for sym in symbols}
        try:
            s.update(phase='warming',reason='New connection: collecting 60 seconds',updated=time.time())
            atomic(STATE,s)
            ws=websocket.create_connection(URL,timeout=8)
            ws.settimeout(.5)
            ws.send(json.dumps(dict(op='subscribe',args=[p+'.'+sym for sym in symbols
                               for p in ('orderbook.200','publicTrade')])))
            start=received=ping=time.monotonic()
            written=history=cleaned=0.
            subscribed=False
            while True:
                raw=None
                try:
                    raw=ws.recv()
                    if not raw:
                        raise ValueError('WebSocket closed')
                    received=time.monotonic()
                except websocket.WebSocketTimeoutException:
                    pass
                if raw:
                    msg=json.loads(raw)
                    if msg.get('op')=='subscribe':
                        if msg.get('success') is not True:
                            raise ValueError('Subscription rejected')
                        subscribed=True
                    topic=msg.get('topic','')
                    if topic.startswith('orderbook.'):
                        market=books[topic.rsplit('.',1)[-1]]
                        if market.u and (msg.get('type')=='snapshot' or int(msg['data']['u'])==1) and s['position']:
                            raise ValueError('Book reset with open position; continuity unknown')
                        market.book(msg)
                    elif topic.startswith('publicTrade.'):
                        books[topic.rsplit('.',1)[-1]].trades(msg)
                mono,now=time.monotonic(),time.time()
                if mono-received>10 or (not subscribed and mono-start>10):
                    raise ValueError('Feed timeout')
                if mono-start>15 and any(not b.ts or now-b.ts>5 for b in books.values()):
                    raise ValueError('A subscribed book is stale; reconnecting')
                if mono-ping>=20:
                    ws.send(json.dumps(dict(op='ping')))
                    ping=mono
                if mono-written>=1:
                    if subscribed:
                        cycle(s,books,charts,now)
                    s['updated']=now
                    atomic(STATE,s)
                    written=mono
                    if s['phase']=='halted':
                        return
                    if mono-history>=5:
                        db.execute('INSERT INTO samples VALUES(?,?)',(now,json.dumps(dict(
                            observations=s['observations'],equity=s['equity'],phase=s['phase']),allow_nan=False)))
                        if mono-cleaned>=300:
                            db.execute('DELETE FROM samples WHERE t < ?',(now-48*3600,))
                            cleaned=mono
                        db.commit()
                        history=mono
                    if mono-start>60:
                        backoff=3
        except Exception as exc:
            s.update(phase='halted' if s['position'] else 'waiting',reason=str(exc)[:240],updated=time.time())
            atomic(STATE,s)
            print('B',s['phase'],s['reason'],flush=True)
            if s['position']:
                return
        finally:
            if ws:
                ws.close()
        time.sleep(backoff)
        backoff=min(30,backoff*2)

if __name__=='__main__':
    main()
