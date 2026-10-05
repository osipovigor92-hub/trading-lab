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

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT/'src/trading-panel'
sys.path.insert(0, str(PANEL))
import selection
from market_alerts import MarketAlerts
from manual_paper import ManualPaper
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
        key=ALERTS.register(filters,query.get('search',[''])[0],now,query.get('watch',[''])[0])
        tickers=market_fixture('/api/screener',{});charts={};books={};histories={}
        for row in tickers['rows']:
            symbol=row['symbol'];charts[symbol]=market_fixture('/api/market-chart',dict(symbol=[symbol],interval=['1']))
            books[symbol]=market_fixture('/api/market-book',dict(symbol=[symbol]))
            histories[symbol]=[dict(books[symbol],updated=books[symbol]['updated']-8+i*2,seq=i+1) for i in range(5)]
        ALERTS.update(key,tickers,charts,books,histories,now)
        return ALERTS.snapshot(key,now)
    if path=='/api/market-selection':
        filters=selection.parse_filters({k:v[0] for k,v in query.items() if k not in ('search','watch')})
        tickers=market_fixture('/api/screener',{});rows=[]
        for row in tickers['rows']:
            symbol=row['symbol'];chart=market_fixture('/api/market-chart',dict(symbol=[symbol],interval=['1']))
            book=market_fixture('/api/market-book',dict(symbol=[symbol]))
            books=[dict(book,updated=now-8+i*2,seq=i+1) for i in range(5)]
            rows.append(dict(symbol=symbol,selection=selection.evaluate(row,tickers['updated'],chart,books,filters,now)))
        return dict(status='ok',source_time=tickers['updated'],rows=rows,filters=filters,analysis_limit=8,
                    counts={state:sum(r['selection']['status']==state for r in rows) for state in ('passed','pending','rejected')})
    symbol=query.get('symbol',['BTCUSDT'])[0];interval=query.get('interval',['5'])[0]
    if symbol not in prices or interval not in market.INTERVALS:
        return dict(status='error',updated=now,error='Invalid demo symbol')
    price=prices[symbol]
    if path=='/api/market-chart':
        step=market.INTERVALS[interval];end=now//step*step;bars=[]
        for i in range(180):
            center=price*(1+.006*math.sin(i*.35)+.001*math.cos(i*.81))
            o=center*(1+.0005*math.sin(i));c=center*(1-.0005*math.sin(i))
            bars.append(dict(time=end-(180-i)*step,open=o,close=c,high=max(o,c)*1.0008,
                             low=min(o,c)*.9992,volume=1000,turnover=price*1000*(1+.2*math.sin(i))))
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
                body=body.replace(b'<body>', '<body><aside class="notice bad">ДЕМО · СИНТЕТИЧЕСКИЕ ДАННЫЕ · НЕ СЕРВЕР</aside>'.encode())
        self.send_response(200)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        chart = path == '/chart.html'
        self.send_header('Content-Security-Policy',
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src https://www.tradingview-widget.com https://s.tradingview.com; img-src 'self' data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            if chart else "default-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
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
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
