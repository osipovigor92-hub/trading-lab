"""Bounded public large-print and order-book observations; no trader attribution."""
from collections import OrderedDict
import json
import math
from pathlib import Path
import threading
import time
import uuid
import alert_state
from market_data import public_api, SYMBOL

FLOOR = 50_000


def numeric(v):
    return type(v) in (int, float) and math.isfinite(v)


def trades(result, stamp, symbol, now):
    if not numeric(stamp) or not -2 <= now-stamp <= 15:
        raise ValueError('Устаревший ответ ленты')
    rows = result.get('list')
    if not isinstance(rows, list) or len(rows) > 1000 or result.get('category', 'linear') != 'linear':
        raise ValueError('Некорректная лента')
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get('symbol') != symbol or row.get('side') not in ('Buy','Sell'):
            raise ValueError('Другая монета или сторона сделки')
        identity = row.get('execId')
        if not isinstance(identity,str) or not 1 <= len(identity) <= 128:
            raise ValueError('Нет идентификатора исполнения')
        for k in ('price','size','time'):
            if isinstance(row.get(k),bool):raise ValueError('Некорректная сделка')
        price, size, source = float(row['price']), float(row['size']), float(row['time'])/1000
        if not all(math.isfinite(v) and v>0 for v in (price,size,source)) or source > stamp+2 or not math.isfinite(price*size):
            raise ValueError('Некорректные числа сделки')
        out.append(dict(id=symbol+':'+identity,execution_id=identity,symbol=symbol,side=row['side'],price=price,
                        quantity=size,notional=price*size,time=source,exchange='bybit',
                        block_trade=row.get('isBlockTrade') is True))
    return sorted(out,key=lambda r:(r['time'],r['id']))


class WhaleMonitor:
    def __init__(self, market, densities, clock=time.time, api=public_api, state_path=None, background=False):
        self.market, self.densities, self.clock, self.api = market,densities,clock,api
        self.lock = threading.RLock()
        self.seen, self.walls = OrderedDict(), OrderedDict()
        self.events, self.coverage, self.targets = [], {}, []
        self.watermarks = {}
        self.epoch, self.sequence, self.cursor = uuid.uuid4().hex,0,0
        self.path = Path(state_path) if state_path else None
        self.storage_error, self.load_failed, self.saved = '',False,None
        self.stop = threading.Event()
        self.thread = None
        self._restore()
        if background:
            self.thread = threading.Thread(target=self.run,name='large-public-observer',daemon=True)
            self.thread.start()

    def _restore(self):
        if not self.path:return
        try:
            if self.path.is_symlink():raise ValueError('Ссылка вместо состояния')
            if not self.path.exists():return
            if self.path.stat().st_size>1_000_000:raise ValueError('Слишком большой файл состояния')
            data=json.loads(self.path.read_text())
            seen,walls=data['seen'],data['walls']
            if data['version']!=1 or not isinstance(seen,list) or len(seen)>2000 or not isinstance(walls,list) or len(walls)>500:
                raise ValueError('Некорректное состояние наблюдений')
            if any(not isinstance(k,str) or len(k)>160 or not numeric(v) for k,v in seen):raise ValueError('Некорректный ID')
            if any(not isinstance(k,str) or len(k)>160 or type(v) is not bool for k,v in walls):raise ValueError('Некорректная заявка')
            marks=data.get('watermarks',{})
            if not isinstance(marks,dict) or len(marks)>100 or any(not isinstance(k,str) or not SYMBOL.fullmatch(k) or not numeric(v) for k,v in marks.items()):raise ValueError('Некорректные отметки времени')
            self.seen,self.walls,self.watermarks=OrderedDict(seen),OrderedDict(walls),marks
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
            self.storage_error,self.load_failed=str(exc),True

    def _save(self):
        if not self.path or self.load_failed:return
        try:
            body=json.dumps(dict(version=1,seen=list(self.seen.items()),walls=list(self.walls.items()),watermarks=self.watermarks),allow_nan=False)
            if body!=self.saved:alert_state.write(self.path,body);self.saved=body
            self.storage_error=''
        except (OSError,ValueError) as exc:self.storage_error=str(exc)

    def _emit(self, kind, row, now):
        self.sequence+=1
        self.events.insert(0,dict(row,id=self.epoch+':'+str(self.sequence),kind=kind,detected_at=now))
        self.events=self.events[:100]

    def observe_trades(self, symbol, result, stamp, now):
        rows=trades(result,stamp,symbol,now)
        with self.lock:
            previous=self.coverage.get(symbol,{})
            watermark=self.watermarks.get(symbol,0)
            latest=max((r['time'] for r in rows),default=previous.get('source',0))
            if latest < previous.get('source',0):raise ValueError('Откат времени ленты')
            gap=bool(len(rows)==1000 and previous.get('source') and rows[0]['time']>previous['source'])
            self.coverage[symbol]=dict(status='ok',checked=now,source=latest,window_full=len(rows)==1000,gap=gap,error='')
            emitted=False
            for row in rows:
                if row['time']<=watermark or row['notional'] < FLOOR or not -2 <= now-row['time'] <= 30:continue
                if row['id'] in self.seen:continue
                self.seen[row['id']]=row['time']
                self._emit('large_trade',row,now)
                emitted=True
            if emitted:self.watermarks[symbol]=max(watermark,latest)
            self.watermarks=dict(sorted(self.watermarks.items(),key=lambda item:item[1])[-100:])
            self.seen=OrderedDict((k,v) for k,v in self.seen.items() if now-v<=120)
            while len(self.seen)>2000:self.seen.popitem(last=False)
            self._save()

    def observe_walls(self, packet, now):
        with self.lock:
            missing={r.get('density_id'):r for r in packet.get('history',[]) if r.get('status')=='missing' and numeric(r.get('observed_at')) and -2<=now-r['observed_at']<=25}
            for row in packet.get('rows',[])[:500]:
                identity=row.get('id')
                if not isinstance(identity,str):continue
                active=row.get('status')=='active' and numeric(row.get('last_seen')) and -2<=now-row['last_seen']<=25
                qualifies=(active and numeric(row.get('notional')) and row['notional']>=FLOOR and
                           numeric(row.get('distance_pct')) and row['distance_pct']<=1 and
                           numeric(row.get('age_seconds')) and row['age_seconds']>=10)
                if qualifies and not self.walls.get(identity,False):
                    self.walls[identity]=True
                    self._emit('large_wall',dict(row,time=row['last_seen']),now)
                elif row.get('status')=='missing' and self.walls.get(identity,False) and identity in missing:
                    self.walls[identity]=False
                    self._emit('wall_missing',dict(row,time=missing[identity]['observed_at']),now)
                # Unknown/out-of-depth/stale data never imply removal or rearm.
            while len(self.walls)>500:self.walls.popitem(last=False)
            self._save()

    def tick(self):
        now=self.clock()
        self.observe_walls(self.densities.snapshot(),now)
        with self.market.selection_lock:watch=list(self.market.selection_watch)
        latest=self.market.alerts.latest() or {}
        pinned=[s for s in latest.get('watch','').split(',') if SYMBOL.fullmatch(s)]
        targets=list(dict.fromkeys(pinned+watch))[:8] or ['BTCUSDT','ETHUSDT']
        with self.lock:
            self.targets=targets
            self.coverage={k:v for k,v in self.coverage.items() if k in targets}
            symbol=targets[self.cursor%len(targets)];self.cursor+=1
        try:
            result,stamp=self.api('recent-trade',symbol=symbol,limit=1000)
            self.observe_trades(symbol,result,stamp,self.clock())
        except Exception as exc:
            with self.lock:self.coverage[symbol]=dict(status='error',checked=self.clock(),error=str(exc)[:160])

    def run(self):
        while not self.stop.is_set():
            try:self.tick()
            except Exception as exc:
                with self.lock:self.storage_error=str(exc)[:160]
            self.stop.wait(1)

    def snapshot(self):
        now=self.clock()
        with self.lock:
            coverage={k:dict(v,fresh=v['status']=='ok' and -2<=now-v['checked']<=30) for k,v in self.coverage.items()}
            return dict(status='ok',updated=now,epoch=self.epoch,cursor=self.sequence,
                        events=[dict(e,current=-2<=now-e['time']<=30) for e in self.events if -2<=now-e['detected_at']<=300],
                        targets=list(self.targets),coverage=coverage,min_notional=FLOOR,
                        persistence_error=self.storage_error,
                        note='Крупный объём не определяет владельца. Лента Bybit: последние 1000 исполнений на запрос, возможны пропуски. Заявки: снимки стакана, исчезновение не доказывает сделку.')
