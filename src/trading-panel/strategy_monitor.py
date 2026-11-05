"""Read-only, bounded strategy monitor; never sends trading commands."""
import copy
import json
import threading
import time
from pathlib import Path
from alert_state import write
from bot_signals import level_break, signal_outcome


class StrategyMonitor:
    def __init__(self, exchange, favorites, builder, path=None, background=False):
        self.exchange,self.favorites,self.builder=exchange,favorites,builder
        self.path=Path(path) if path else None
        self.lock=threading.RLock()
        self.events=[];self.seen=[];self.error=None;self.updated=0;self.coverage=[];self.state="not_configured"
        try:
            if self.path and self.path.exists():
                if self.path.is_symlink() or self.path.stat().st_size>500000:raise ValueError('Invalid strategy storage')
                state=json.loads(self.path.read_text())
                if not isinstance(state,dict) or not isinstance(state.get('events'),list) or not isinstance(state.get('seen'),list):raise ValueError('Invalid strategy storage')
                self.events=state['events'][:100];self.seen=state['seen'][-500:]
        except (OSError,ValueError) as exc:self.error=str(exc)
        self.storage_error=self.error
        if background:threading.Thread(target=self.run,daemon=True,name='strategy-monitor').start()

    def cycle(self,now=None):
        if self.storage_error:return
        now=time.time() if now is None else now
        settings=self.builder.snapshot()
        if settings['status']!='ok':
            with self.lock:self.error=settings.get('error') or 'Настройки недоступны';self.state='unavailable'
            return
        config=settings['drafts'].get('level_break')
        if not config:
            with self.lock:self.state='not_configured';self.coverage=[];self.updated=now;self.error=None
            return
        if config['scope']=='market':
            with self.lock:self.state='unsupported_scope';self.coverage=[];self.error='Весь рынок пока не подключён. Выберите пару или избранное.'
            return
        favorites=self.favorites.snapshot()
        if config['scope']=='favorites' and favorites['status']!='ok':
            with self.lock:self.state='unavailable';self.error='Избранное недоступно'
            return
        groups=favorites['groups']
        selected=list(dict.fromkeys(groups['lab-favorites-v1']+[p.split(':',1)[1] for p in groups['lab-exchange-favorites-v1'] if p.startswith('bybit:')]))
        symbols=[config['symbol']] if config['scope']=='pair' else selected[:8]
        rows=[]
        for symbol in symbols:
            packet=self.exchange.chart_snapshot('bybit',symbol,'1')
            bars=packet.get('candles',[])
            if len(bars)<22:
                rows.append(dict(symbol=symbol,status='blocked',reason='incomplete_history'));continue
            # Fixed preceding 20-bar range. The crossing bar is excluded entirely.
            prior=bars[-21:-1]
            results=[]
            for field in ('high','low'):
                level=dict(exchange='bybit',symbol=symbol,price=(max(b[field] for b in prior) if field=='high' else min(b[field] for b in prior)),confirmed_at=bars[-1]['t'])
                result=level_break(packet,level,now=now,direction=config['side'])
                results.append(result)
                if result['status']!='triggered':continue
                sign=1 if result['side']=='long' else -1
                price=result['signal_price']
                event=dict(result,id=result['event_key'],exchange='bybit',symbol=symbol,strategy='level_break',timeframe='1',time=now,expires=result['closed_at']+60,
                           stop=price*(1-sign*config['stop_pct']/100),target=price*(1+sign*config['take_pct']/100),
                           detail='Закрытие за диапазоном предыдущих 20 минут; объём не менее 1,5× среднего. Цена сигнала не является ценой исполнения.')
                with self.lock:
                    if event['id'] in self.seen:continue
                    events=([event]+self.events)[:100];seen=(self.seen+[event['id']])[-500:]
                    if self.path:write(self.path,json.dumps(dict(events=events,seen=seen),ensure_ascii=False,allow_nan=False))
                    self.events,self.seen=events,seen
            with self.lock:
                resolved=[signal_outcome(e,packet,now) if e.get('symbol')==symbol else e for e in self.events]
                if resolved!=self.events:
                    if self.path:write(self.path,json.dumps(dict(events=resolved,seen=self.seen),ensure_ascii=False,allow_nan=False))
                    self.events=resolved
            best=max(results,key=lambda r: {'blocked':0,'waiting':1,'triggered':2}[r['status']])
            rows.append(dict(symbol=symbol,status=best['status'],reason=best['reason'],
                             source_updated=packet.get('updated'),candle_end=packet.get('candle_end')))
        with self.lock:
            self.coverage=rows;self.updated=now;self.error=None
            self.state='empty_scope' if not rows else 'waiting_data' if all(r['status']=='blocked' for r in rows) else 'monitoring'

    def snapshot(self):
        with self.lock:return copy.deepcopy(dict(status='unavailable' if self.error else 'ok',error=self.error,state=self.state,monitored=len(self.coverage),ready=sum(r['status']!='blocked' for r in self.coverage),updated=self.updated,events=self.events,coverage=self.coverage))

    def run(self):
        while True:
            try:self.cycle()
            except Exception as exc:
                with self.lock:self.error=str(exc)[:180]
            time.sleep(5)
