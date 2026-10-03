"""Isolated dashboard preview. Synthetic data only, no network feeds or disk state."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
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

def market_fixture(path, query):
    now=time.time()
    prices={'BTCUSDT':60000,'ETHUSDT':2300,'SOLUSDT':145,'ONDOUSDT':.5}
    if path=='/api/screener':
        rows=[dict(symbol=s,price=p,turnover=(4-i)*80e6,change=(4-i*2.5),range24=5+i,
                   spread=.008+i*.008,open_interest=20e6,funding=.0001) for i,(s,p) in enumerate(prices.items())]
        return dict(status='ok',updated=now,rows=rows,eligible=4,rejected=0,limit=100)
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
      equity=600.2,peak=600.6,fees=.22,funding=0,closed=2,wins=1,losses=1,position=None,events=[],cooldown_until=0)
    grid=dict(paper,server_time=now,last_seen=now,halted=False,position=0,fills=0,average=0,
              funding_estimate=0,orders=[],levels=[])
    observations=[]
    for symbol,signal,side,reasons in [('DEMO-LONG','LONG',1,[]),('DEMO-SHORT','SHORT',-1,[]),('DEMO-WATCH','WAIT',1,['Нет пробоя локального экстремума последних секунд'])]:
        observations.append(dict(symbol=symbol,signal=signal,time=now,price=10,spread=.012,ready=True,
          trade_age=.2,warmup_remaining=0,roundtrip_pct=.222,reasons=reasons,
          bands={k:dict(bid=32000*f,ask=26000*f,covered=True,imbalance=.1) for k,f in [('0.0002',.1),('0.0005',.4),('0.001',1)]},
          chart=dict(end=now-30,side=side,atr_pct=.3,rvol5=1.8),chart_error='',ofi5=side*5000,
          **{f'flow{n}':dict(buy=10000,sell=3000,count=25,ratio=side*.54) for n in (5,15,60)}))
    data={'/api/state':grid,'/api/paper':paper,
      '/api/model-b':dict(paper,trades=[dict(t,side=1 if t['side']=='LONG' else -1) for t in trades],observations=observations,started=now-600),
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
    def log_message(self,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8788)
    args=parser.parse_args()
    print(f'DEMO: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
