"""C/D PAPER executor. Reads local B snapshots; has no exchange/network client."""
import csv
import io
import fcntl
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

ROOT = Path('/var/lib/trading-research')
FEED = Path('/var/lib/scalp-model-b/state.json')
VERSION = '2026-10-02.paper1'
CONFIG = dict(capital=600., notional=100., fee=.00055, slippage=.0005,
              stop=.4, target=.6, hold=180, cooldown=120, max_loss=18., gap=6)


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def fresh(t, now, age):
    return number(t) and -1 <= now-t <= age


def evaluate(model, source, r, now):
    c = r.get('chart') or {}
    checks = []
    def add(name, ok): checks.append(dict(label=name, pass_=bool(ok)))
    price = r.get('price')
    valid = number(price) and price > 0
    chart = all(number(c.get(k)) and c[k] > 0 for k in ('price','ema20','ema50','atr','vwap60'))
    chart = chart and number(c.get('rvol5')) and c['rvol5'] >= 0
    cost = r.get('roundtrip_pct')
    cost_ok = number(cost) and cost > 0
    b = (r.get('bands') or {}).get('0.0005') or {}
    depth = all(number(b.get(k)) and b[k] >= 0 for k in ('bid','ask'))
    depth = depth and b['bid']+b['ask'] > 0
    imbalance = (b['bid']-b['ask'])/(b['bid']+b['ask']) if depth else 0
    def flow(seconds):
        f = r.get('flow'+str(seconds)) or {}
        if not all(number(f.get(k)) and f[k] >= 0 for k in ('buy','sell','count')): return None
        total = f['buy']+f['sell']
        if total <= 0 or int(f['count']) != f['count']: return None
        return dict(total=total, ratio=(f['buy']-f['sell'])/total, count=f['count'])
    f5, f15 = flow(5), flow(15)
    add('Свежий источник и стакан', source.get('phase') == 'running' and fresh(source.get('updated'),now,8) and fresh(r.get('time'),now,3))
    add('Прогрев и свежая лента', r.get('ready') is True and number(r.get('trade_age')) and r['trade_age'] >= 0 and number(source.get('updated')) and r['trade_age']+max(0,now-source['updated']) <= 10)
    add('Закрытые свечи и корректные метрики', valid and chart and not r.get('chart_error') and fresh(c.get('end'),now,120))
    add('Спред и расходы', number(r.get('spread')) and 0 <= r['spread'] <= .025 and cost_ok)
    add('Глубина ±0,05% ≥5000 с обеих сторон', depth and b.get('covered') is True and min(b['bid'],b['ask']) >= 5000)
    add('Лента 15с ≥1500 USDT и 10 сделок', f15 and f15['total'] >= 1500 and f15['count'] >= 10)
    add('До funding больше 300с', number(c.get('next_funding')) and c['next_funding']-now > 300)
    side = 0
    if model == 'C':
        side = c.get('side') if c.get('side') in (-1,1) else 0
        add('Тренд EMA/VWAP', valid and chart and side and side*(c['ema20']-c['ema50']) > 0 and side*(price-c['vwap60']) > 0)
        add('RVOL5 ≥1,5', chart and c['rvol5'] >= 1.5)
        add('Импульс 0,15–1 ATR', valid and chart and .15 <= side*(price-c['price'])/c['atr'] <= 1)
        add('Масштаб ATR ≥1,5 расходов', valid and chart and cost_ok and c['atr']/price*100 >= 1.5*cost)
    elif model == 'D':
        if valid and chart: side = 1 if price < c['vwap60'] else -1 if price > c['vwap60'] else 0
        add('Боковик EMA/RVOL', chart and abs(c['ema20']-c['ema50']) <= .25*c['atr'] and c['rvol5'] <= 1.2)
        add('Отклонение VWAP 0,75–2 ATR', valid and chart and .75 <= abs(price-c['vwap60'])/c['atr'] <= 2)
        add('Начало возврата к VWAP', valid and chart and side*(price-c['price']) > 0)
        add('Дистанция VWAP ≥2 расходов', valid and chart and cost_ok and abs(price-c['vwap60'])/price*100 >= 2*cost)
    else: raise ValueError('Unknown model')
    add('Перевес стакана ≥15%', depth and side and side*imbalance >= .15)
    add('OFI5', number(r.get('ofi5')) and side*r['ofi5'] > 0)
    add('Перевес ленты 5/15с', f5 and f15 and side*f5['ratio'] >= .3 and side*f15['ratio'] >= .2)
    return dict(side=side, checks=checks, passed=all(x['pass_'] for x in checks))


def initial(now):
    return dict(version=VERSION, config=CONFIG.copy(), started=now, updated=now,
                models={m:dict(phase='waiting',reason='',balance=CONFIG['capital'],equity=CONFIG['capital'],peak=CONFIG['capital'],max_drawdown=0.,fees=0.,closed=0,wins=0,losses=0,net=0.,positive=0.,negative=0.,position=None,cooldown_until=0.,last_tick=0.,last_observation=0.,confirmations={},observations=[]) for m in ('C','D')})


def execution(r, side):
    return r['price']*(1+side*r['spread']/200)*(1+side*CONFIG['slippage'])


def quote_ok(r, now):
    if not isinstance(r,dict) or not fresh(r.get('time'),now,3): return False
    if not number(r.get('price')) or r['price'] <= 0 or not number(r.get('spread')) or not 0 <= r['spread'] < 1: return False
    b = (r.get('bands') or {}).get('0.0005') or {}
    return b.get('covered') is True and all(number(b.get(k)) and b[k] >= CONFIG['notional']*2 for k in ('bid','ask'))


def mark(p, r):
    exit_price = execution(r,-p['side'])
    gross = p['side']*p['quantity']*(exit_price-p['entry'])
    fee = p['quantity']*exit_price*CONFIG['fee']
    return exit_price,gross,fee,gross-fee-p['entry_fee']


def halt(m, reason):
    m.update(phase='halted',reason=reason,confirmations={})


def cycle(state, source, now):
    """One observed feed tick; returns closed records for the same DB transaction."""
    records=[]
    source = source if isinstance(source,dict) else {}
    rows = {r['symbol']:r for r in source.get('observations',[]) if isinstance(r,dict) and isinstance(r.get('symbol'),str)}
    tick = source.get('updated')
    usable = source.get('phase') == 'running' and fresh(tick,now,8)
    for model,m in state['models'].items():
        if m['phase'] == 'halted': continue
        if not usable:
            m['confirmations']={}
            m['observations']=[]
            if m['position']: halt(m,'DATA_GAP: нет свежего источника; позиция не закрыта')
            else: m.update(phase='waiting',reason='Ожидание свежего источника B')
            continue
        if m['position'] and (not fresh(m['last_tick'],now,CONFIG['gap']) or tick < m['last_tick']):
            halt(m,'DATA_GAP: пропуск наблюдений; оценка позиции устарела');continue
        if tick <= m['last_tick']: continue
        if m['last_tick'] and tick-m['last_tick'] > CONFIG['gap']: m['confirmations']={}
        m.update(phase='running',reason='',last_tick=tick)
        p=m['position']
        if p:
            r=rows.get(p['symbol'])
            if not quote_ok(r,now) or r['time'] < p['quote_time']:
                halt(m,'DATA_GAP: нет достоверной котировки выхода');continue
            if now >= p['funding_time']:
                halt(m,'FUNDING_GAP: граница funding пересечена; учёт неполон');continue
            price,gross,fee,net=mark(p,r)
            p['quote_time']=r['time'];p['mfe_net']=max(p['mfe_net'],net);p['mae_net']=min(p['mae_net'],net)
            m['equity']=m['balance']+gross-fee
            reason=('Лимит потерь' if m['equity']<=CONFIG['capital']-CONFIG['max_loss'] else 'Стоп' if net<=-CONFIG['stop'] else 'Цель' if net>=CONFIG['target'] else 'Лимит времени' if now-p['opened']>=CONFIG['hold'] else '')
            if reason:
                record=dict(p, model=model,version=VERSION,closed=now,exit=price,exit_fee=fee,gross=gross,net=net,reason=reason,exit_quote_time=r['time'],funding=0.)
                records.append(record)
                m['balance']+=gross-fee;m['fees']+=fee;m['net']+=net;m['closed']+=1
                m['wins']+=int(net>0);m['losses']+=int(net<0);m['positive']+=max(0,net);m['negative']+=min(0,net)
                m.update(position=None,equity=m['balance'],cooldown_until=now+CONFIG['cooldown'],confirmations={})
        m['peak']=max(m['peak'],m['equity']);m['max_drawdown']=max(m['max_drawdown'],m['peak']-m['equity'])
        if m['equity'] <= CONFIG['capital']-CONFIG['max_loss']:
            halt(m,'Лимит потерь эксперимента');continue
        candidates=[];observations=[];seen=set()
        for symbol,r in sorted(rows.items()):
            result=evaluate(model,source,r,now);seen.add(symbol)
            old=m['confirmations'].get(symbol,{});book_time=r.get('time')
            if not result['passed'] or m['position'] or now<m['cooldown_until']:
                new=dict(side=0,count=0,start=0,last=book_time)
            elif old.get('last')==book_time:
                new=old
            else:
                keep=old.get('side')==result['side'] and number(old.get('last')) and 0<book_time-old['last']<=6
                new=dict(side=result['side'],count=old.get('count',0)+1 if keep else 1,start=old['start'] if keep else book_time,last=book_time)
            m['confirmations'][symbol]=new
            confirmed=result['passed'] and new.get('count',0)>=3 and book_time-new['start']>=4
            observations.append(dict(symbol=symbol,side=result['side'],checks=result['checks'],confirmations=new.get('count',0),confirmed=confirmed,time=book_time))
            if confirmed:
                candidates.append((min(r['bands']['0.0005']['bid'],r['bands']['0.0005']['ask']),symbol,result['side'],r))
        m['confirmations']={k:v for k,v in m['confirmations'].items() if k in seen}
        m['observations']=observations
        if m['position'] is None and now>=m['cooldown_until'] and candidates:
            _,symbol,side,r=max(candidates,key=lambda x:(x[0],x[1]))
            if quote_ok(r,now):
                entry=execution(r,side);quantity=CONFIG['notional']/entry;fee=CONFIG['notional']*CONFIG['fee']
                p=dict(id=f'{model}:{now:.9f}:{symbol}',symbol=symbol,side=side,entry=entry,quantity=quantity,entry_fee=fee,opened=now,quote_time=r['time'],funding_time=r['chart']['next_funding'],features=r,mfe_net=0.,mae_net=0.)
                m['balance']-=fee;m['fees']+=fee;m['position']=p
                _,gross,exit_fee,net=mark(p,r);p['mfe_net']=p['mae_net']=net;m['equity']=m['balance']+gross-exit_fee;m['confirmations']={}
        m['last_observation']=now
        m['peak']=max(m['peak'],m['equity']);m['max_drawdown']=max(m['max_drawdown'],m['peak']-m['equity'])
    state['updated']=now
    return records


def connect(path):
    db=sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
    db.execute('CREATE TABLE IF NOT EXISTS state(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,model TEXT NOT NULL,closed REAL NOT NULL,data TEXT NOT NULL)')
    db.commit();return db


def persist(db,state,records):
    with db:
        for r in records: db.execute('INSERT INTO trades VALUES(?,?,?,?)',(r['id'],r['model'],r['closed'],json.dumps(r,allow_nan=False)))
        db.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(json.dumps(state,allow_nan=False),))


def report(db,state):
    out=json.loads(json.dumps(state))
    for model,m in out['models'].items():
        m.pop('confirmations',None)
        if m['position']: m['position'].pop('features',None)
        m['trades']=[json.loads(v[0]) for v in db.execute('SELECT data FROM trades WHERE model=? ORDER BY closed DESC,id DESC LIMIT 100',(model,))]
        for trade in m['trades']: trade.pop('features',None)
        m['average']=m['net']/m['closed'] if m['closed'] else None
        m['profit_factor']=m['positive']/abs(m['negative']) if m['negative']<0 else None
    return out


def atomic(path,data):
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.research-')
    try:
        with os.fdopen(fd,'w') as f: json.dump(data,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def resume(state):
    if state['version'] != VERSION or state['config'] != CONFIG: raise RuntimeError('Saved version/config differs; migration required')
    for m in state['models'].values():
        m['confirmations']={}
        if m['position']: halt(m,'RESTART_GAP: перезапуск с открытой позицией; автоматическое закрытие запрещено')


def export_csv(db,root):
    fields=['id','model','version','symbol','side','opened','closed','entry','exit','quantity','entry_fee','exit_fee','gross','net','funding','reason','mfe_net','mae_net']
    for model in ('C','D'):
        buffer=io.StringIO();writer=csv.DictWriter(buffer,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for row in db.execute('SELECT data FROM trades WHERE model=? ORDER BY closed,id',(model,)):
            record=json.loads(row[0])
            # Prevent spreadsheet formulas in string fields from an invalid source packet.
            writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in record.items()})
        path=root/('journal-'+model.lower()+'.csv');fd,tmp=tempfile.mkstemp(dir=root,prefix='.csv-')
        try:
            with os.fdopen(fd,'w') as f:f.write(buffer.getvalue());f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)


def main():
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        db=connect(ROOT/'journal.sqlite')
        row=db.execute('SELECT data FROM state WHERE id=1').fetchone()
        state=json.loads(row[0]) if row else initial(time.time());resume(state)
        persist(db,state,[]);atomic(ROOT/'report.json',report(db,state));export_csv(db,ROOT)
        exported=time.monotonic()
        while True:
            try: source=json.loads(FEED.read_text())
            except (OSError,ValueError): source={}
            records=cycle(state,source,time.time());persist(db,state,records)
            atomic(ROOT/'report.json',report(db,state))
            if records or time.monotonic()-exported>=30:
                export_csv(db,ROOT);exported=time.monotonic()
            for r in records: print(r['model'],'CLOSE',r['symbol'],r['reason'],round(r['net'],6),flush=True)
            time.sleep(1)

if __name__=='__main__':main()
