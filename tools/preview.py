"""Isolated dashboard preview. Synthetic data only, no network feeds or disk state."""
import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class PreviewHTTPServer(ThreadingHTTPServer):
    request_queue_size = 64

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT/'src/trading-panel'
sys.path.insert(0, str(PANEL))
import selection
from market_alerts import ASSISTANT_KINDS, MarketAlerts
from manual_paper import ManualPaper
from densities import EXCHANGES, density_id
from exchange_data import INTERVALS as EXCHANGE_INTERVALS
spec = importlib.util.spec_from_file_location('lab_report', ROOT/'src/trading-report/report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
spec2=importlib.util.spec_from_file_location('research_engine',ROOT/'integrations/research/engine.py')
research=importlib.util.module_from_spec(spec2);spec2.loader.exec_module(research)
spec3=importlib.util.spec_from_file_location('market_data',PANEL/'market_data.py')
market=importlib.util.module_from_spec(spec3);spec3.loader.exec_module(market)

# In-memory, synthetic lifecycle. This preview never reads production control files.
class DemoControl:
    token = 'isolated-preview-token'

    def __init__(self):
        self.lock = threading.RLock()
        self.models = {m: dict(phase='running', generation=0,
                               settings=dict(capital=600.,notional=100.,max_loss=18.),archived=0)
                       for m in 'ABCD'}
        self.engines = {e: dict(phase='idle' if e != 'hummingbot' else 'not_installed',
                              generation=0, runs=[]) for e in ('freqtrade', 'hummingbot', 'jesse')}
        self.pc_engines = {e: dict(phase='idle' if e != 'hummingbot' else 'not_installed',
                                 generation=0, runs=[]) for e in self.engines}
        self.audit = []

    def engine_item(self, engine, c, now, execution):
        if c.get('until', 0) and now >= c['until']:
            c.update(phase='completed', until=0)
            c['runs'].append(dict(id='DEMO-'+execution+'-'+str(c['generation']),started=c['started'],
                finished=now,phase='completed',execution=execution,reason='СИНТЕТИЧЕСКИЙ ПРИМЕР · не результат бота',
                metrics=dict(count=12,net=-.8),settings=dict(strategy='LabEMATest')))
        installed=engine!='hummingbot'
        return dict(id=engine,kind='engine',execution=execution,installed=installed,phase=c['phase'],
            generation=c['generation'],memory_ok=True,version='DEMO' if installed else None,
            required_gb=5 if engine=='hummingbot' else 3,test_active=c['phase']=='running',
            reason='ДЕМОНСТРАЦИЯ · реальный движок не подключён',
            metrics=c['runs'][-1].get('metrics') if c['runs'] else None,runs=c['runs'][::-1],
            actions=dict(start=installed and c['phase']!='running',stop=installed and c['phase']=='running',
                         restart=installed and c['phase']!='running'))

    def status(self, data, now):
        with self.lock:
            rows = []
            for model, c in self.models.items():
                if c.get('until', 0) and now >= c['until']:
                    c.update(phase='running', until=0)
                source = data['/api/paper'] if model == 'A' else data['/api/model-b'] if model == 'B' else data['/api/research']['models'][model]
                source['phase'] = c['phase']
                position = source.get('position')
                settings=c['settings']
                rows.append(dict(id=model, kind='model', installed=True, phase=c['phase'],
                    generation=c['generation'], fresh=True, equity=source['equity'],
                    closed=source['closed'], position=position, pending=False,
                    reason='ДЕМОНСТРАЦИЯ · реальная модель не изменяется',
                    experiment=dict(group='CD' if model in 'CD' else model,id='DEMO-'+model+'-20261003T120000-1234abcd',created=now,settings=settings,archived=c['archived']),
                    new_run_note='готов к новому тесту; прошлый журнал будет сохранён' if c['phase']=='paused' else 'сначала нажми «Отключить», чтобы запретить новые входы',
                    actions=dict(start=c['phase']=='paused', stop=c['phase']!='paused', restart=True,new_run=c['phase']=='paused')))
            engines = []
            for engine, c in self.engines.items():
                local=self.engine_item(engine,c,now,'vds')
                pc=self.engine_item(engine,self.pc_engines[engine],now,'pc')
                engines.append(dict(local,executors=dict(vds=dict(local),pc=pc),test_active=local['test_active'] or pc['test_active']))
            return dict(status='ok', token=self.token, updated=now, models=rows, engines=engines,
                        memory=dict(total_gb=8, available_gb=7), audit=self.audit[::-1],
                        worker=dict(configured=True,online=True,memory=dict(total_gb=8,available_gb=7)))

    def command(self, request):
        with self.lock:
            if not isinstance(request, dict):
                raise ValueError('Недопустимая команда')
            new_run=request.get('action')=='new_run'
            fields={'target','action','generation','experiment'} if new_run else {'target','action','generation'}
            fields_ok=set(request)==fields if new_run else set(request) in (fields,fields|{'execution'})
            if not fields_ok:
                raise ValueError('Недопустимая команда')
            target, action, generation = (request[k] for k in ('target', 'action', 'generation'))
            execution=request.get('execution','vds')
            if target not in (*self.models, *self.engines) or action not in ('start', 'stop', 'restart', 'new_run'):
                raise ValueError('Недопустимая команда')
            if execution not in ('pc','vds') or target in self.models and 'execution' in request:
                raise ValueError('Недопустимый исполнитель')
            if action=='new_run' and target not in self.models:
                raise ValueError('Новый тест доступен только для моделей')
            c = self.models[target] if target in self.models else (self.pc_engines if execution=='pc' else self.engines)[target]
            if type(generation) is not int or generation != c['generation']:
                raise ValueError('Состояние изменилось. Обновите карточку')
            if target == 'hummingbot':
                raise ValueError('Движок не подготовлен')
            if target in self.engines and action != 'stop' and any(v['phase']=='running' for v in (*self.engines.values(),*self.pc_engines.values())):
                raise ValueError('Другой тест ещё работает')
            c['generation'] += 1
            now=time.time()
            if target in self.models:
                if action=='new_run':
                    settings=request.get('experiment',{})
                    if not all(isinstance(settings.get(key),(int,float)) for key in ('capital','notional','max_loss')) or not 10<=settings['capital']<=1e6 or not 1<=settings['notional']<=settings['capital'] or not 0<settings['max_loss']<settings['capital']:
                        raise ValueError('Некорректные PAPER-настройки')
                    c.update(settings={key:float(settings[key]) for key in ('capital','notional','max_loss')},archived=c['archived']+1,phase='warming',until=now+2)
                else:c.update(phase='paused' if action=='stop' else 'warming', until=0 if action=='stop' else now+2)
            elif action=='stop':
                c.update(phase='cancelled', until=0)
                c['runs'].append(dict(id='DEMO-'+str(c['generation']), started=c.get('started', now),
                    finished=now, phase='cancelled', execution=execution,reason='Тест отменён в демонстрации', metrics=None))
            else:
                c.update(phase='running', started=now, until=now+(20 if execution=='pc' else 5))
            uid='DEMO-'+execution+'-'+target+'-'+str(c['generation'])
            self.audit.append(dict(id=uid,time=now,target=target,action=action,outcome='applied',message='ДЕМО'))
            return dict(status='accepted',id=uid)

CONTROL = DemoControl()
PAPER_TEST = False
ALERTS = MarketAlerts()

def exchange_fixture(path, query):
    """Five venues and densities are explicit synthetic UI fixtures, never REST."""
    now = time.time()
    exchange = query.get('exchange', ['bybit'])[0]
    if exchange not in EXCHANGES:
        return dict(status='error', updated=now, error='Invalid demo exchange', demo=True)
    if path == '/api/densities':
        selected = query.get('exchanges', [','.join(EXCHANGES)])[0].split(',')
        selected = [value for value in selected if value in EXCHANGES]
        rows, history = [], []
        examples = [('BTCUSDT', 'bid', 59730, 520000, 3900, 'active'),
                    ('ETHUSDT', 'ask', 2310, 285000, 5700, 'active'),
                    ('SOLUSDT', 'bid', 144.1, 165000, 920, 'active'),
                    ('LINKUSDT', 'ask', 14.28, 112000, 4400, 'unavailable'),
                    ('AVAXUSDT', 'bid', 11.04, 84000, 85, 'unobserved')]
        prices = {'BTCUSDT':60000, 'ETHUSDT':2300, 'SOLUSDT':145, 'LINKUSDT':14.2, 'AVAXUSDT':11.1}
        for index, venue in enumerate(selected):
            for symbol, side, price, notional, age, status in examples:
                row = dict(id=density_id(venue,symbol,side,str(price)), exchange=venue, symbol=symbol,
                           side=side, price=price, price_text=str(price), notional=notional*(1+index*.18),
                           distance_pct=abs(price/prices[symbol]-1)*100, first_seen=now-age,
                           last_seen=now if status=='active' else now-45,
                           age_seconds=age if status=='active' else 0, status=status,
                           stable=status=='active' and age>=3600, timestamp_origin='demo', demo=True)
                rows.append(row)
            missing = dict(rows[-1], id=density_id(venue,'ONDOUSDT','ask','.506'),symbol='ONDOUSDT',side='ask',
                           price=.506,price_text='.506',notional=175000,distance_pct=1.2,
                           status='missing',stable=False,age_seconds=0,first_seen=now-700,last_seen=now-120,
                           observed_at=now-90,reason='ДЕМО: отсутствует в двух снимках',event_id='demo-'+venue)
            history.append(missing)
        return dict(status='ok',updated=now,rows=rows,history=history,demo=True,
                    coverage=dict(total=len(selected)*100,scanned=len(selected)*2,selected=len(selected)*2,
                                  limit=20,min_notional=50000,stable_seconds=3600,poll_seconds=10),
                    exchanges=[dict(id=venue,status='ok',updated=now,error='',total=100,scanned=2) for venue in selected],
                    error='',note='ДЕМО: синтетические уровни и срок жизни; не наблюдения биржи')
    packet = market_fixture('/api/screener', {})
    if path == '/api/exchange-screener':
        rows = [dict(row, exchange=exchange, native_symbol=row['symbol'], turnover24=row['turnover'],
                     change24=row['change'], price=row['price'], quote='USDT') for row in packet['rows']]
        rows = [dict(row, id=exchange+':'+row['symbol'], range24=row['range24'], trades24=120000 if exchange=='binance' else None,
                     turnover_estimated=False, funding_rate=row.get('funding'), quote_volume=row['turnover']) for row in rows]
        return dict(packet,exchange=exchange,rows=rows,demo=True,source='Synthetic preview',
                    source_ts=packet['updated'],timestamp_origin='demo',stale=False)
    interval = query.get('interval', ['5'])[0]
    symbol = query.get('symbol', ['BTCUSDT'])[0]
    quote = next((row['price'] for row in packet['rows'] if row['symbol'] == symbol), None)
    if interval not in EXCHANGE_INTERVALS or quote is None:
        return dict(status='error',exchange=exchange,symbol=symbol,interval=interval,updated=now,
                    error='Invalid demo symbol or interval',demo=True)
    if interval in market.INTERVALS:
        chart = market_fixture('/api/market-chart', query)
    else:
        bars = demo_candles(symbol,quote,interval,now)
        chart = dict(status='ok',symbol=symbol,interval=interval,updated=now,
                     candle_end=bars[-1]['time']+int(interval)*60,candles=bars)
    metrics = dict(natr5_14=None, natr1_30=None, change5=None)
    if chart.get('status') == 'ok' and interval in ('1', '5'):
        bars = chart['candles']
        period = 30 if interval == '1' else 14
        ranges = [max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])) for a,b in zip(bars,bars[1:])]
        atr = sum(ranges[:period])/period
        for value in ranges[period:]:
            atr = (atr*(period-1)+value)/period
        metrics['natr1_30' if interval=='1' else 'natr5_14'] = atr/bars[-1]['close']*100
        metrics['change5'] = (bars[-1]['close']/bars[-6 if interval=='1' else -2]['close']-1)*100
    return dict(chart, exchange=exchange, native_symbol=query.get('symbol',['BTCUSDT'])[0],
                candles=[dict(bar,t=bar['time']) for bar in chart.get('candles',[])],
                metrics=metrics,metrics_interval=interval,demo=True,source='Synthetic preview',
                source_ts=chart.get('candle_end'),timestamp_origin='demo',stale=False)


def demo_candles(symbol, price, interval, now):
    """Deterministic, invented OHLC paths for visual checks, never market history."""
    # Distinct regimes make chart scales, pullbacks and volume bars testable.
    profiles = {
        'BTCUSDT': ((-.024,-.013,-.020,.008,.018,.011,.023,.018,.029), .0021, 4, ((62,1.8),(121,1.1))),
        'ETHUSDT': ((.038,.028,.037,.008,-.005,.003,-.018,-.004,0), .0030, 95, ((76,1.3),(139,1.7))),
        'SOLUSDT': ((-.033,-.025,-.031,-.027,-.018,.004,.019,.008,.021), .0040, 3000, ((110,2.5),(146,1.2))),
        'ONDOUSDT': ((.001,-.018,.007,.052,.072,.043,.006,-.028,-.009), .0062, 330000, ((74,2.8),(124,1.8))),
        'LINKUSDT': ((.006,-.009,.009,-.007,.005,-.010,.006,-.004,.001), .0019, 58000, ((42,.9),(153,1.1))),
        'AVAXUSDT': ((.058,.048,.058,.027,.039,.019,-.012,.009,.016), .0045, 41000, ((123,2.1),(153,1.5))),
    }
    anchors, noise, minute_volume, bursts = profiles[symbol]
    step = int(interval)*60
    end = (now-2)//step*step
    phase = sum((i+1)*ord(char) for i,char in enumerate(symbol))*.013
    scale = min(4., max(.65, (step/300.)**.35))
    paths = []
    for i in range(180):
        position = i*(len(anchors)-1)/179
        index = min(len(anchors)-2, int(position))
        fraction = position-index
        trend = anchors[index]*(1-fraction)+anchors[index+1]*fraction
        jitter = noise*(.38*math.sin(i*.27+phase)+.21*math.sin(i*.79+phase)
                        +.14*math.sin(i*1.61+phase)+.09*math.cos(i*2.37+phase))
        paths.append((trend+jitter)*scale)
    # Final synthetic close agrees with the synthetic screener quote.
    closes = [price*math.exp(value-paths[-1]) for value in paths]
    previous = closes[0]*(1-.0004*math.sin(phase))
    bars = []
    for i,close in enumerate(closes):
        opening = previous
        move = abs(math.log(close/opening))
        wick = noise*scale*(.13+.17*abs(math.sin(i*1.37+phase)))
        high = max(opening,close)*(1+wick*(.65+.5*abs(math.sin(i*.93+phase))))
        low = min(opening,close)*(1-wick*(.65+.5*abs(math.cos(i*1.17+phase))))
        burst = sum(strength*math.exp(-((i-center)/4.)**2) for center,strength in bursts)
        activity = .68+.55*abs(math.sin(i*.71+phase))+.28*math.sin(i*1.43+phase)
        activity += .4*min(3.5,move/(noise*scale))+burst
        volume = minute_volume*(step/60)*max(.25,activity)
        bars.append(dict(time=end-(180-i)*step,open=opening,close=close,high=high,low=low,
                         volume=volume,turnover=volume*(opening+close+high+low)/4))
        previous = close
    return bars


def market_fixture(path, query):
    now=time.time()
    prices={'BTCUSDT':60000,'ETHUSDT':2300,'SOLUSDT':145,'ONDOUSDT':.5,'LINKUSDT':14.2,'AVAXUSDT':11.1}
    if PAPER_TEST:
        prices['BTCUSDT'] = 99.5
        prices['ETHUSDT'] = 99.5
    if path=='/api/screener':
        rows=[dict(symbol=s,price=p,turnover=(4-i)*80e6 if i<4 else (6-i)*12e6,
                   change=(4-i*2.5),range24=5+i,spread=.008+i*.008 if i<4 else .03,
                   open_interest=20e6,funding=.0001,next_funding=now+3600,volume24=1e6,funding_interval_hours=8) for i,(s,p) in enumerate(prices.items())]
        return dict(status='ok',updated=now//5*5,rows=rows,eligible=len(prices),rejected=0,limit=100)
    if path=='/api/market-alerts':
        filters=selection.parse_filters({k:v[0] for k,v in query.items() if k not in ('search','watch')})
        key=ALERTS.register(filters,query.get('search',[''])[0],now,query.get('watch',[''])[0],priority='activity')
        tickers=market_fixture('/api/screener',{});charts={};books={};histories={}
        for row in tickers['rows']:
            symbol=row['symbol'];charts[symbol]=market_fixture('/api/market-chart',dict(symbol=[symbol],interval=['1']))
            books[symbol]=market_fixture('/api/market-book',dict(symbol=[symbol]))
            histories[symbol]=[dict(books[symbol],updated=books[symbol]['updated']-8+i*2,seq=i+1) for i in range(5)]
        ALERTS.update(key,tickers,charts,books,histories,now)
        packet=ALERTS.snapshot(key,now)
        packet['events']=[event for event in packet['events'] if event['kind'] in ASSISTANT_KINDS or event['kind']=='near_level']
        return packet
    if path=='/api/market-selection':
        filters=selection.parse_filters({k:v[0] for k,v in query.items() if k not in ('search','watch')})
        tickers=market_fixture('/api/screener',{});rows=[]
        for row in tickers['rows']:
            symbol=row['symbol'];chart=market_fixture('/api/market-chart',dict(symbol=[symbol],interval=['1']))
            book=market_fixture('/api/market-book',dict(symbol=[symbol]))
            books=[dict(book,updated=now-8+i*2,seq=i+1) for i in range(5)]
            rows.append(dict(symbol=symbol,selection=selection.evaluate(row,tickers['updated'],chart,books,filters,now),
                             assistant=selection.assistant(row,tickers['updated'],chart,now,True,filters)))
        return dict(status='ok',source_time=tickers['updated'],rows=rows,filters=filters,analysis_limit=8,
                    counts={state:sum(r['selection']['status']==state for r in rows) for state in ('passed','pending','rejected')})
    symbol=query.get('symbol',['BTCUSDT'])[0];interval=query.get('interval',['5'])[0]
    if symbol not in prices or interval not in market.INTERVALS:
        return dict(status='error',updated=now,error='Invalid demo symbol')
    price=prices[symbol]
    if path=='/api/market-chart':
        bars=demo_candles(symbol,price,interval,now)
        return market.chart_analysis(symbol,interval,bars,now)
    bids=[[str(price*(1-.00005-i*.00002)),str((30+i%5)*100/price)] for i in range(80)]
    asks=[[str(price*(1+.00005+i*.00002)),str((35+i%5)*100/price)] for i in range(80)]
    return market.orderbook_analysis(symbol,dict(s=symbol,ts=now*1000,seq=int(now*1000),b=bids,a=asks),now)

def fixtures():
    now = time.time()
    config = dict(version=1,capital=600,notional=100,fee=.00055,slippage=.0005,
                  take_profit=.6,stop_loss=.4,max_hold=180,max_loss=18,trailing=.05,
                  symbol='LINKUSDT',lower=12,upper=16,quantity=6.2,max_position=31)
    trades=[]
    for i,net in enumerate((.6,-.4)):
        trades.append(dict(symbol='DEMOUSDT',side='LONG' if i==0 else 'SHORT',
          opened=now-500+i*200,closed=now-400+i*200,seconds=100,entry=10,exit=10.071 if i==0 else 10.029,
          quantity=10,entry_fee=.055,exit_fee=.055,gross=net+.11,net=net,funding=0,reason='ТЕСТОВЫЙ ПРИМЕР'))
    summary=report.stats(trades)
    paper=dict(config=config,updated=now,phase='running',reason='ДЕМОНСТРАЦИЯ',balance=600.2,
      equity=600.2,peak=600.6,fees=.22,funding=0,closed=2,wins=1,losses=1,
      position=dict(symbol='ONDOUSDT',side=1,entry=.496,quantity=100/.496,opened=now-40),events=[],cooldown_until=0)
    grid=dict(paper,server_time=now,last_seen=now,halted=False,position=0,fills=0,average=0,
              funding_estimate=0,orders=[],levels=[])
    observations=[]
    for symbol,signal,side,reasons in [('BTCUSDT','LONG',1,[]),('SOLUSDT','SHORT',-1,[]),('ONDOUSDT','WAIT',1,['Нет пробоя локального экстремума последних секунд'])]:
        observations.append(dict(symbol=symbol,signal=signal,time=now,price=10,spread=.012,ready=True,
          trade_age=.2,warmup_remaining=0,roundtrip_pct=.222,reasons=reasons,
          bands={k:dict(bid=32000*f,ask=26000*f,covered=True,imbalance=.1) for k,f in [('0.0002',.1),('0.0005',.4),('0.001',1)]},
          chart=dict(end=now-30,side=side,atr_pct=.3,rvol5=1.8),chart_error='',ofi5=side*5000,
          **{f'flow{n}':dict(buy=10000,sell=3000,count=25,ratio=side*.54) for n in (5,15,60)}))
    data={'/api/state':grid,'/api/paper':paper,
      '/api/model-b':dict(paper,position=None,trades=[dict(t,side=1 if t['side']=='LONG' else -1) for t in trades],observations=observations,started=now-600),
      '/api/live':dict(status='live',updated=now,message='ДЕМОНСТРАЦИЯ: поток не подключён',rows=[]),
      '/api/signals':dict(status='ok',updated=now,rows=[]),
      '/api/scanner':dict(status='ok',server_time=now,finished=now,quote_time=now,universe=0,eligible=0,selected=0,analyzed=0,candidates=0,rows=[],errors=[]),
      '/api/scalp':dict(status='ok',finished=now,minute_checked=0,universe=0,selected=0,rows=[],errors=[]),
      '/api/journal':dict(updated=now,recorded=2,legacy_closed=0,net=.2,average=.1,profit_factor=1.5),
      '/api/lab-report':dict(updated=now,status='ok',start=now-600,end=now,errors=[],legacy_a=0,
          models={m:dict(summary,crossing_excluded=0) for m in 'AB'},positions={'A':None,'B':None},
          diagnostics=dict(start=now-600,end=now,rows=[]))}
    for m in 'AB':
        data['/api/journal-'+m.lower()]=dict(model=m,updated=now,source_updated=now,status='ok',errors=[],phase='running',
          reason='СИНТЕТИЧЕСКИЕ ДАННЫЕ',position=None,summary=summary,legacy_closed=0,
          first_opened=trades[0]['opened'],last_closed=trades[-1]['closed'],rows=trades[::-1],shown=2)
    rs=research.initial(now-600);rs['updated']=now
    for model,m in rs['models'].items():
        m.update(phase='running',balance=600.2,equity=600.2,net=.2,fees=.22,closed=2,wins=1,losses=1,last_observation=now,average=.1,profit_factor=1.5)
        m['trades']=[dict(t,side=1 if t['side']=='LONG' else -1) for t in trades[::-1]]
        for r in observations:
            v=research.evaluate(model,data['/api/model-b'],r,now)
            m['observations'].append(dict(symbol=r['symbol'],time=now,side=v['side'],checks=v['checks'],confirmations=0,confirmed=False))
    data['/api/research']=rs
    data['/api/models-control']=CONTROL.status(data, now)
    return data


class DemoMarket:
    def get(self, kind, symbol='', interval='5'):
        return market_fixture({'screener':'/api/screener', 'book':'/api/market-book', 'chart':'/api/market-chart'}[kind], dict(symbol=[symbol], interval=[interval]))


# Temporary ledger is isolated from every production account; wiped with preview.
MANUAL_ROOT = tempfile.TemporaryDirectory(prefix='lab-preview-paper-')
MANUAL = ManualPaper(DemoMarket(), MANUAL_ROOT.name, background=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path
        data=fixtures()
        if path == '/api/manual-paper':
            body=json.dumps(dict(MANUAL.snapshot(),token=CONTROL.token),ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in ('/api/exchange-screener','/api/exchange-chart','/api/densities'):
            body=json.dumps(exchange_fixture(path,parse_qs(urlsplit(self.path).query)),ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in ('/api/screener','/api/market-chart','/api/market-book','/api/market-selection','/api/market-alerts'):
            body=json.dumps(market_fixture(path,parse_qs(urlsplit(self.path).query)),ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in data:
            body=json.dumps(data[path],ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in ('/journal-a.csv','/journal-b.csv','/journal-c.csv','/journal-d.csv'):
            body=b'\xef\xbb\xbfsymbol,net\nDEMOUSDT,0.6\nDEMOUSDT,-0.4\n';kind='text/csv; charset=utf-8'
        elif path=='/api/engine-journal':
            engine=parse_qs(urlsplit(self.path).query).get('engine', [''])[0]
            if engine not in CONTROL.engines:
                self.send_error(400);return
            body=('\ufeffrun_id,engine,execution,phase,net_usdt\n'+''.join(
                f"{r['id']},{engine},{r.get('execution','vds')},{r['phase']},{(r.get('metrics') or {}).get('net', '')}\n"
                for r in CONTROL.engines[engine]['runs']+CONTROL.pc_engines[engine]['runs'])).encode();kind='text/csv; charset=utf-8'
        else:
            name='index.html' if path=='/' else path.lstrip('/')
            allowed={p.name:p for p in PANEL.iterdir() if p.suffix in ('.html','.js','.css')}
            if name not in allowed:
                self.send_error(404);return
            body=allowed[name].read_bytes()
            kind={'.html':'text/html','.js':'text/javascript','.css':'text/css'}[allowed[name].suffix]+'; charset=utf-8'
            if name=='index.html':
                body=body.replace(b'<body class="lab-shell">', '<body class="lab-shell" data-demo="true"><aside class="notice bad">ДЕМО · СИНТЕТИЧЕСКИЕ ДАННЫЕ · НЕ СЕРВЕР</aside>'.encode())
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        chart = path == '/chart.html'
        self.send_header('Content-Security-Policy',
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src https://www.tradingview-widget.com https://s.tradingview.com; img-src 'self' data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            if chart else "default-src 'self'; frame-src 'self'; frame-ancestors 'none'; connect-src 'self' wss://stream.bybit.com wss://fstream.binance.com wss://ws.okx.com wss://fx-ws.gateio.ws wss://ws.bitget.com; base-uri 'none'; form-action 'none'; object-src 'none'")
        self.end_headers();self.wfile.write(body)

    def do_POST(self):
        if self.path not in ('/api/models-control','/api/manual-paper'):
            self.send_error(404);return
        if self.headers.get('X-Lab-Control') != CONTROL.token or self.headers.get('Content-Type')!='application/json':
            self.send_error(403);return
        try:
            length=int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096: raise ValueError('Invalid length')
            command=json.loads(self.rfile.read(length))
            value=(MANUAL.command(command) if self.path=='/api/manual-paper' else CONTROL.command(command))
            status=202
        except (ValueError, KeyError, TypeError) as exc:
            value=dict(status='error', error=str(exc));status=409
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8788)
    parser.add_argument('--paper-test',action='store_true',help='Fixed synthetic coin price for isolated PAPER UI tests')
    args=parser.parse_args()
    PAPER_TEST=args.paper_test
    print(f'DEMO: http://127.0.0.1:{args.port}',flush=True)
    PreviewHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
