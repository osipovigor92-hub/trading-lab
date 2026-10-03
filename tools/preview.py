"""Isolated dashboard preview. Synthetic data only, no network feeds or disk state."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT/'src/trading-panel'
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
        self.models = {m: dict(phase='running', generation=0) for m in 'ABCD'}
        self.engines = {e: dict(phase='idle' if e != 'hummingbot' else 'not_installed',
                              generation=0, runs=[]) for e in ('freqtrade', 'hummingbot', 'jesse')}
        self.audit = []

    def status(self, data, now):
        with self.lock:
            rows = []
            for model, c in self.models.items():
                if c.get('until', 0) and now >= c['until']:
                    c.update(phase='running', until=0)
                source = data['/api/paper'] if model == 'A' else data['/api/model-b'] if model == 'B' else data['/api/research']['models'][model]
                source['phase'] = c['phase']
                position = source.get('position')
                rows.append(dict(id=model, kind='model', installed=True, phase=c['phase'],
                    generation=c['generation'], fresh=True, equity=source['equity'],
                    closed=source['closed'], position=position, pending=False,
                    reason='ДЕМОНСТРАЦИЯ · реальная модель не изменяется',
                    actions=dict(start=c['phase']=='paused', stop=c['phase']!='paused', restart=True)))
            engines = []
            for engine, c in self.engines.items():
                if c.get('until', 0) and now >= c['until']:
                    c['phase'] = 'completed'; c['until'] = 0
                    c['runs'].append(dict(id='DEMO-'+str(c['generation']), started=c['started'],
                        finished=now, phase='completed', reason='СИНТЕТИЧЕСКИЙ ПРИМЕР · не результат бота',
                        metrics=dict(count=12, net=-.8), settings=dict(strategy='LabEMATest')))
                installed = engine != 'hummingbot'
                engines.append(dict(id=engine, kind='engine', installed=installed, phase=c['phase'],
                    generation=c['generation'], memory_ok=True, version='DEMO' if installed else None,
                    reason='ДЕМОНСТРАЦИЯ · реальный движок не подключён',
                    metrics=c['runs'][-1].get('metrics') if c['runs'] else None,
                    runs=c['runs'][::-1], actions=dict(start=installed and c['phase']!='running',
                        stop=installed and c['phase']=='running', restart=installed and c['phase']!='running')))
            return dict(status='ok', token=self.token, updated=now, models=rows, engines=engines,
                        memory=dict(total_gb=8, available_gb=7), audit=self.audit[::-1])

    def command(self, request):
        with self.lock:
            if not isinstance(request, dict) or set(request) != {'target', 'action', 'generation'}:
                raise ValueError('Недопустимая команда')
            target, action, generation = (request[k] for k in ('target', 'action', 'generation'))
            if target not in (*self.models, *self.engines) or action not in ('start', 'stop', 'restart'):
                raise ValueError('Недопустимая команда')
            c = self.models.get(target, self.engines.get(target))
            if type(generation) is not int or generation != c['generation']:
                raise ValueError('Состояние изменилось. Обновите карточку')
            if target == 'hummingbot':
                raise ValueError('Движок не подготовлен')
            if target in self.engines and action != 'stop' and any(v['phase']=='running' for v in self.engines.values()):
                raise ValueError('Другой тест ещё работает')
            c['generation'] += 1
            now=time.time()
            if target in self.models:
                c.update(phase='paused' if action=='stop' else 'warming', until=0 if action=='stop' else now+2)
            elif action=='stop':
                c.update(phase='cancelled', until=0)
                c['runs'].append(dict(id='DEMO-'+str(c['generation']), started=c.get('started', now),
                    finished=now, phase='cancelled', reason='Тест отменён в демонстрации', metrics=None))
            else:
                c.update(phase='running', started=now, until=now+5)
            self.audit.append(dict(time=now, target=target, action=action, outcome='applied', message='ДЕМО'))
            return dict(status='accepted', id='DEMO-'+str(c['generation']))

CONTROL = DemoControl()

def market_fixture(path, query):
    now=time.time()
    prices={'BTCUSDT':60000,'ETHUSDT':2300,'SOLUSDT':145,'ONDOUSDT':.5,'LINKUSDT':14.2,'AVAXUSDT':11.1}
    if path=='/api/screener':
        rows=[dict(symbol=s,price=p,turnover=(4-i)*80e6 if i<4 else (6-i)*12e6,
                   change=(4-i*2.5),range24=5+i,spread=.008+i*.008 if i<4 else .03,
                   open_interest=20e6,funding=.0001) for i,(s,p) in enumerate(prices.items())]
        return dict(status='ok',updated=now,rows=rows,eligible=len(prices),rejected=0,limit=100)
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
    return market.orderbook_analysis(symbol,dict(s=symbol,ts=now*1000,b=bids,a=asks),now)

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

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path
        data=fixtures()
        if path in ('/api/screener','/api/market-chart','/api/market-book'):
            body=json.dumps(market_fixture(path,parse_qs(urlsplit(self.path).query)),ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in data:
            body=json.dumps(data[path],ensure_ascii=False).encode();kind='application/json; charset=utf-8'
        elif path in ('/journal-a.csv','/journal-b.csv','/journal-c.csv','/journal-d.csv'):
            body=b'\xef\xbb\xbfsymbol,net\nDEMOUSDT,0.6\nDEMOUSDT,-0.4\n';kind='text/csv; charset=utf-8'
        elif path=='/api/engine-journal':
            engine=parse_qs(urlsplit(self.path).query).get('engine', [''])[0]
            if engine not in CONTROL.engines:
                self.send_error(400);return
            body=('\ufeffrun_id,engine,phase,net_usdt\n'+''.join(
                f"{r['id']},{engine},{r['phase']},{(r.get('metrics') or {}).get('net', '')}\n"
                for r in CONTROL.engines[engine]['runs'])).encode();kind='text/csv; charset=utf-8'
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
        if self.path != '/api/models-control':
            self.send_error(404);return
        if self.headers.get('X-Lab-Control') != CONTROL.token or self.headers.get('Content-Type')!='application/json':
            self.send_error(403);return
        try:
            length=int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096: raise ValueError('Invalid length')
            value=CONTROL.command(json.loads(self.rfile.read(length)))
            status=202
        except (ValueError, KeyError, TypeError) as exc:
            value=dict(status='error', error=str(exc));status=409
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8788)
    args=parser.parse_args()
    print(f'DEMO: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
