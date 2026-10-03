import collections
import json
import math
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path('/var/lib/trading-report')
A = Path('/var/lib/scalp-paper/state.json')
B = Path('/var/lib/scalp-model-b/state.json')
HISTORY = Path('/var/lib/scalp-model-b/history.sqlite')

def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v REAL);
    CREATE TABLE IF NOT EXISTS buckets(t INTEGER,s TEXT,n INTEGER,ready INTEGER,signals INTEGER,PRIMARY KEY(t,s));
    CREATE TABLE IF NOT EXISTS reasons(t INTEGER,s TEXT,r TEXT,n INTEGER,PRIMARY KEY(t,s,r));
    CREATE TABLE IF NOT EXISTS trades(model TEXT,id TEXT,opened REAL,closed REAL,data TEXT,PRIMARY KEY(model,id));
    CREATE INDEX IF NOT EXISTS trades_time ON trades(closed);
    ''')
    return db

def finite(x):
    x=float(x)
    if not math.isfinite(x):raise ValueError('Nonfinite value')
    return x

def archive(db,model,rows):
    with db:
        for r in rows:
            opened,closed=finite(r['opened']),finite(r['closed'])
            if closed<opened:raise ValueError('Trade time reversed')
            for k in ('net','gross','entry_fee','exit_fee'):finite(r[k])
            key=str(r.get('id') or f"{r['symbol']}:{opened:.9f}:{r['side']}")
            data=json.dumps(r,ensure_ascii=False,allow_nan=False,sort_keys=True)
            old=db.execute('SELECT data FROM trades WHERE model=? AND id=?',(model,key)).fetchone()
            if old and old[0]!=data:raise ValueError('Archived trade changed: '+model+' '+key)
            db.execute('INSERT OR IGNORE INTO trades VALUES(?,?,?,?,?)',(model,key,opened,closed,data))

def ingest(db,path):
    row=db.execute("SELECT v FROM meta WHERE k='cursor'").fetchone()
    cursor=row[0] if row else 0
    src=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)
    src.execute('PRAGMA query_only=ON')
    count=0
    try:
        with db:
            for t,data in src.execute('SELECT t,data FROM samples WHERE t>? ORDER BY t LIMIT 40000',(cursor,)):
                state=json.loads(data); t=finite(t)
                bucket=int(t//60)*60
                db.execute("INSERT OR IGNORE INTO meta VALUES('first_sample',?)",(t,))
                db.execute("INSERT INTO meta VALUES('last_sample',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(t,))
                for r in state.get('observations',[]):
                    # Only valid, fresh books. Missing observations are not invented.
                    age=t-finite(r.get('time',0))
                    if state.get('phase')!='running' or not -1<=age<=3:continue
                    symbol=r['symbol']; ready=bool(r.get('ready'))
                    sig=int(ready and r.get('signal') in ('LONG','SHORT'))
                    db.execute('INSERT INTO buckets VALUES(?,?,?,?,?) ON CONFLICT(t,s) DO UPDATE SET n=n+1,ready=ready+excluded.ready,signals=signals+excluded.signals',
                               (bucket,symbol,1,int(ready),sig))
                    reasons=set(r.get('reasons',[]))
                    if not ready and 'Накопление потока или нет свежих сделок' in reasons:
                        if 'warmup_remaining' in r:
                            reasons.remove('Накопление потока или нет свежих сделок')
                            reasons.add('Прогрев потока' if r['warmup_remaining']>0 else 'Нет свежих сделок')
                    for reason in reasons:
                        db.execute('INSERT INTO reasons VALUES(?,?,?,1) ON CONFLICT(t,s,r) DO UPDATE SET n=n+1',(bucket,symbol,reason))
                db.execute("INSERT INTO meta VALUES('cursor',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(t,))
                count+=1
    finally:src.close()
    return count

def stats(rows):
    n=len(rows); net=sum(r['net'] for r in rows)
    wins=sum(r['net']>0 for r in rows); losses=sum(r['net']<0 for r in rows)
    positive=sum(max(0,r['net']) for r in rows); negative=-sum(min(0,r['net']) for r in rows)
    by=collections.defaultdict(list)
    for r in rows:by[r['symbol']].append(r)
    return dict(count=n,net=net,gross=sum(r['gross'] for r in rows),
                fees=sum(r['entry_fee']+r['exit_fee'] for r in rows),
                funding=sum(r.get('funding',0) for r in rows),wins=wins,losses=losses,
                average=net/n if n else None,win_rate=100*wins/n if n else None,
                profit_factor=positive/negative if negative else None,
                symbols=[dict(symbol=k,count=len(v),net=sum(r['net'] for r in v)) for k,v in sorted(by.items())])

def comparison(db,start,end):
    result={}
    for model in ('A','B'):
        rows=[json.loads(r[0]) for r in db.execute('SELECT data FROM trades WHERE model=? AND opened>=? AND closed<=? ORDER BY closed',(model,start,end))]
        result[model]=stats(rows)
        result[model]['crossing_excluded']=db.execute('SELECT count(*) FROM trades WHERE model=? AND opened<? AND closed>=? AND closed<=?',(model,start,start,end)).fetchone()[0]
    return result

def diagnostics(db,start,end):
    # Only whole calendar minutes inside the comparison interval.
    lo=math.ceil(start/60)*60; hi=math.floor(end/60)*60
    rows=[]
    for symbol,n,ready,signals in db.execute('SELECT s,sum(n),sum(ready),sum(signals) FROM buckets WHERE t>=? AND t<? GROUP BY s ORDER BY s',(lo,hi)):
        reasons=[dict(reason=r,n=c,percent=100*c/n) for r,c in db.execute('SELECT r,sum(n) AS c FROM reasons WHERE s=? AND t>=? AND t<? GROUP BY r ORDER BY c DESC',(symbol,lo,hi))]
        rows.append(dict(symbol=symbol,samples=n,ready=ready,signals=signals,reasons=reasons))
    meta=dict(db.execute('SELECT k,v FROM meta'))
    return dict(start=lo,end=hi,rows=rows,first_sample=meta.get('first_sample'),last_sample=meta.get('last_sample'))

def save(data):
    path=ROOT/'report.json'; tmp=ROOT/'report.tmp'
    with tmp.open('w') as f:
        json.dump(data,f,ensure_ascii=False,allow_nan=False)
        f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def issue_for(error):
    """Turn known collection failures into a safe, actionable UI message.

    The raw error remains in ``errors`` for an operator log, but no browser
    should have to explain SQLite or a service implementation detail to a user.
    """
    text = str(error)
    if text.startswith('История B:'):
        return dict(scope='B', code='history-b-unavailable',
                    title='Архив наблюдений B недоступен',
                    detail='Сделки B остаются в журнале, но диагностика потока и условия входа B не обновляются. Нужна проверка доступа к архиву B на сервере.')
    if text == 'Нет свежих архивных наблюдений B':
        return dict(scope='B', code='history-b-stale',
                    title='Архив наблюдений B не обновляется',
                    detail='Новые снимки B не поступали более 90 секунд. Текущий сигнал и статистика потока скрыты до восстановления источника.')
    if text.startswith(('A: состояние устарело', 'B: состояние устарело')):
        model = text[0]
        return dict(scope=model, code='state-stale-'+model.lower(),
                    title='Состояние модели '+model+' устарело',
                    detail='Показан последний сохранённый снимок. Текущие цена, позиция и P&L не подтверждены.')
    if ': эксперимент остановлен:' in text and text[:1] in ('A', 'B'):
        model, reason = text.split(': эксперимент остановлен:', 1)
        return dict(scope=model, code='halted-'+model.lower(),
                    title='Модель '+model+' остановлена по защите',
                    detail=reason.strip() or 'Новые входы остановлены до ручной проверки.')
    if text.startswith(('A:', 'B:')):
        model = text[0]
        return dict(scope=model, code='source-'+model.lower(),
                    title='Не удалось прочитать данные модели '+model,
                    detail='Отчёт использует последний доступный снимок. Проверьте службу модели и её файл состояния.')
    return dict(scope='all', code='report-source', title='Данные требуют внимания', detail=text)


def issues_for(errors, model=None):
    rows = [issue_for(error) for error in errors]
    return rows if model is None else [row for row in rows if row['scope'] in ('all', model)]


def errors_for(errors, model):
    return [error for error in errors if issue_for(error)['scope'] in ('all', model)]

def main():
    now=time.time(); db=connect(ROOT/'archive.sqlite')
    errors=[]; states={}
    for model,path,key in (('A',A,'journal_trades'),('B',B,'trades')):
        try:
            s=json.loads(path.read_text());states[model]=s
            archive(db,model,s.get(key,[]))
        except Exception as e:errors.append(model+': '+str(e)[:180])
    try:imported=ingest(db,HISTORY)
    except Exception as e:imported=0;errors.append('История B: '+str(e)[:180])
    write_model_journals(db,states,errors)
    if len(states)!=2:
        save(dict(updated=now,status='error',errors=errors,issues=issues_for(errors)));return
    a,b=states['A'],states['B']
    # Conservative coverage: journal installation instant is unknown; begin after
    # the first precisely recorded A closure, which intentionally excludes it.
    first=db.execute("SELECT min(closed) FROM trades WHERE model='A'").fetchone()[0]
    if first is None:
        errors += ['Нет точных закрытий A для определения начала покрытия.']
        save(dict(updated=now,status='waiting',errors=errors,issues=issues_for(errors)));return
    end=min(now,finite(a['updated']),finite(b['updated']))
    start=max(end-86400,finite(b['started']),first)
    for name,s in states.items():
        if not -3<=now-finite(s['updated'])<=15:errors.append(name+': состояние устарело; общий период заканчивается последним общим снимком')
        if s.get('phase')=='halted':errors.append(name+': эксперимент остановлен: '+s.get('reason',''))
    if start>end:
        errors += ['Общий период ещё не начался.']
        save(dict(updated=now,status='waiting',errors=errors,issues=issues_for(errors)));return
    diag=diagnostics(db,start,end)
    if not diag['last_sample'] or now-diag['last_sample']>90:errors.append('Нет свежих архивных наблюдений B')
    positions={k:dict(symbol=s['position']['symbol'],side=s['position']['side'],opened=s['position']['opened']) if s.get('position') else None for k,s in states.items()}
    result=dict(updated=now,status='partial' if errors else 'ok',start=start,end=end,
                models=comparison(db,start,end),diagnostics=diag,positions=positions,
                legacy_a=max(0,a['closed']-len(a.get('journal_trades',[]))),
                imported=imported,errors=errors,issues=issues_for(errors))
    save(result);db.close()
    print('REPORT',result['status'],'imported',imported,flush=True)

# MODEL_JOURNALS_V1

def write_model_journals(db,states,errors):
    import csv
    fields=['symbol','side','opened','closed','seconds','quantity','entry','exit',
            'gross','entry_fee','exit_fee','funding','net','reason','mfe_net','mae_net']
    for model in ('A','B'):
        state=states.get(model)
        if state is None:
            continue
        records=[]
        for data, in db.execute('SELECT data FROM trades WHERE model=? ORDER BY closed,id',(model,)):
            r=json.loads(data)
            side=r.get('side')
            r['side']='LONG' if side in (1,'LONG') else 'SHORT' if side in (-1,'SHORT') else str(side)
            r['seconds']=r['closed']-r['opened']
            r.setdefault('funding',0.)
            records.append(r)
        now=time.time()
        fresh=-3 <= now-state.get('updated',0) <= 15
        position=state.get('position')
        if position:
            position={k:position.get(k) for k in ('symbol','side','entry','quantity','opened','entry_fee','funding','mfe_net','mae_net')}
            position['side']='LONG' if position['side']==1 else 'SHORT'
        model_errors=errors_for(errors,model)
        report=dict(model=model,updated=now,source_updated=state.get('updated'),
                    status='ok' if fresh and not model_errors else 'partial',errors=model_errors,
                    issues=issues_for(errors,model),
                    phase=state.get('phase'),reason=state.get('reason',''),position=position,
                    summary=stats(records),legacy_closed=max(0,state.get('closed',0)-len(state.get('journal_trades',[]))) if model=='A' else 0,
                    first_opened=min((r['opened'] for r in records),default=None),
                    last_closed=max((r['closed'] for r in records),default=None),
                    rows=list(reversed(records[-200:])),shown=min(200,len(records)))
        name='journal-'+model.lower()
        tmp=ROOT/(name+'.csv.tmp')
        with tmp.open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader()
            for r in records:
                row={k:r.get(k,'') for k in fields}
                # Prevent spreadsheet formulas in string fields; preserve numeric signs.
                for k,v in row.items():
                    if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')):row[k]="'"+v
                writer.writerow(row)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,ROOT/(name+'.csv'))
        tmp=ROOT/(name+'.json.tmp')
        with tmp.open('w') as f:
            json.dump(report,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(tmp,ROOT/(name+'.json'))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        errors=[type(exc).__name__+': '+str(exc)[:200]]
        save(dict(updated=time.time(),status='error',errors=errors,issues=issues_for(errors)))
        raise
