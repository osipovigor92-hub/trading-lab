const test=require('node:test'),assert=require('node:assert/strict');
const {keyOf,validSource,parseMessage,subscriptions,create}=require('../src/trading-panel/chart-stream.js');

// Native public exchange fixtures: an in-progress bar must never become REST proof.
const NOW=1800000134,PERIODS={'1':60,'5':300,'15':900,'60':3600,'240':14400,'1440':86400};
const units={'1':'1m','5':'5m','15':'15m','60':'1h','240':'4h','1440':'1d'};
const candleUnits={'1':'1m','5':'5m','15':'15m','60':'1H','240':'4H','1440':'1Dutc'};
function source(exchange='bybit',symbol='BTCUSDT',interval='5'){
 const base=symbol.slice(0,-4),native_symbol=exchange==='okx'?base+'-USDT-SWAP':exchange==='gate'?base+'_USDT':symbol;
 return {exchange,symbol,interval,native_symbol};
}
function candle(s=source(),now=NOW){
 const start=Math.floor(now/PERIODS[s.interval])*PERIODS[s.interval],ms=now*1000;
 if(s.exchange==='bybit')return {topic:'kline.'+(s.interval==='1440'?'D':s.interval)+'.'+s.symbol,type:'snapshot',ts:ms,data:[{start:start*1000,end:(start+PERIODS[s.interval])*1000-1,interval:s.interval==='1440'?'D':s.interval,open:'100',high:'104',low:'99',close:'103',volume:'2',turnover:'205',confirm:false,timestamp:ms}]};
 if(s.exchange==='binance')return {stream:s.symbol.toLowerCase()+'@kline_'+units[s.interval],data:{e:'kline',E:ms,s:s.symbol,k:{t:start*1000,T:(start+PERIODS[s.interval])*1000-1,s:s.symbol,i:units[s.interval],o:'100',h:'104',l:'99',c:'103',v:'2',q:'205',x:false}}};
 if(s.exchange==='okx')return {arg:{channel:'candle'+candleUnits[s.interval],instId:s.native_symbol},data:[[String(start*1000),'100','104','99','103','200','2','205','0']]};
 if(s.exchange==='gate')return {time:now,time_ms:ms,channel:'futures.candlesticks',event:'update',result:[{t:start,o:'100',h:'104',l:'99',c:'103',v:'200',a:'205',n:units[s.interval]+'_'+s.native_symbol,w:false}]};
 return {action:'snapshot',arg:{instType:'USDT-FUTURES',channel:'candle'+candleUnits[s.interval],instId:s.native_symbol},ts:ms,data:[[String(start*1000),'100','104','99','103','2','205','205']]};
}
function quote(s=source(),now=NOW){
 const ms=now*1000;
 if(s.exchange==='bybit')return {topic:'tickers.'+s.symbol,type:'snapshot',ts:ms,data:{symbol:s.symbol,lastPrice:'103.5'}};
 if(s.exchange==='binance')return {stream:s.symbol.toLowerCase()+'@miniTicker',data:{e:'24hrMiniTicker',E:ms,s:s.symbol,c:'103.5'}};
 if(s.exchange==='okx')return {arg:{channel:'tickers',instId:s.native_symbol},data:[{instId:s.native_symbol,last:'103.5',ts:String(ms)}]};
 if(s.exchange==='gate')return {time:now,time_ms:ms,channel:'futures.tickers',event:'update',result:[{contract:s.native_symbol,last:'103.5',t:ms}]};
 return {arg:{instType:'USDT-FUTURES',channel:'ticker',instId:s.native_symbol},action:'snapshot',ts:ms,data:[{symbol:s.symbol,instId:s.native_symbol,lastPr:'103.5',ts:String(ms)}]};
}
function role(s,kind='candle'){return s.exchange==='okx'?(kind==='candle'?'candles':'quotes'):'all';}
function parsed(s,kind,packet,now=NOW){return parseMessage(s.exchange,role(s,kind),packet,[s],now);}

test('canonical identity includes venue and period; only supported public perpetual sources are valid',()=>{
 assert.equal(keyOf(source()),'bybit:BTCUSDT:5');
 assert.notEqual(keyOf(source()),keyOf(source('binance')));
 assert.notEqual(keyOf(source()),keyOf(source('bybit','BTCUSDT','1')));
 for(const exchange of ['bybit','binance','okx','gate','bitget'])for(const interval of Object.keys(PERIODS))assert.equal(validSource(source(exchange,'BTCUSDT',interval)),true,exchange+' '+interval);
 for(const bad of [null,{},source('unknown'),source('bybit','BTCUSD'),source('bybit','BTCUSDT','2'),{...source(),symbol:'BTCUSDT\n'},{...source(),native_symbol:'ETHUSDT'},{...source('okx'),native_symbol:'BTC-USDT'},{...source('gate'),native_symbol:'BTC_USD'}])assert.equal(validSource(bad),false);
});

for(const exchange of ['bybit','binance','okx','gate','bitget']){
 test(exchange+' parses native forming OHLC and last traded price with their source identity',()=>{
  const s=source(exchange),bars=parsed(s,'candle',candle(s)),prices=parsed(s,'quote',quote(s));
  assert.equal(bars.length,1);assert.equal(bars[0].key,keyOf(s));assert.equal(bars[0].kind,'candle');
  for(const [key,value]of Object.entries({t:Math.floor(NOW/300)*300,open:100,high:104,low:99,close:103}))assert.equal(bars[0].value[key],value);
  assert.equal(prices.length,1);assert.equal(prices[0].key,keyOf(s));assert.equal(prices[0].kind,'quote');assert.equal(prices[0].value.price,103.5);
  if(exchange==='okx')assert.equal(bars[0].value.source_ts,null,'opening timestamp cannot pretend to be source generation time');
 });
 test(exchange+' does not route another instrument or period into the selected chart',()=>{
  const s=source(exchange);
  assert.deepEqual(parsed(s,'candle',candle(source(exchange,'ETHUSDT'))),[]);
  assert.deepEqual(parsed(s,'quote',quote(source(exchange,'ETHUSDT'))),[]);
  assert.deepEqual(parsed(s,'candle',candle(source(exchange,'BTCUSDT','1'))),[]);
 });
 test(exchange+' rejects stale source messages, invalid OHLC, and off-grid opening times',()=>{
  const s=source(exchange);
  assert.deepEqual(parsed(s,'quote',quote(s,NOW-120)),[]);
  assert.deepEqual(parsed(s,'quote',quote(s,NOW+30)),[],'future source time cannot refresh the last price');
  if(exchange!=='okx')assert.deepEqual(parsed(s,'candle',candle(s,NOW-120)),[]);
  const wrong=structuredClone(candle(s));
  if(exchange==='bybit')wrong.data[0].low='105';
  else if(exchange==='binance')wrong.data.k.l='105';
  else if(exchange==='gate')wrong.result[0].l='105';
  else wrong.data[0][3]='105';
  assert.deepEqual(parsed(s,'candle',wrong),[]);
  const offgrid=structuredClone(candle(s));
  if(exchange==='bybit')offgrid.data[0].start+=1000;
  else if(exchange==='binance')offgrid.data.k.t+=1000;
  else if(exchange==='gate')offgrid.result[0].t+=1;
  else offgrid.data[0][0]=String(Number(offgrid.data[0][0])+1000);
  assert.deepEqual(parsed(s,'candle',offgrid),[]);
 });
}

test('UTC daily and uppercase hourly channels preserve the REST interval mapping',()=>{
 for(const exchange of ['bybit','binance','okx','gate','bitget'])for(const interval of ['60','240','1440']){
  const s=source(exchange,'BTCUSDT',interval),items=parsed(s,'candle',candle(s));
  assert.equal(items.length,1,exchange+' '+interval);assert.equal(items[0].value.t%PERIODS[interval],0);
 }
 const s=source('okx','BTCUSDT','1440'),p=candle(s);p.arg.channel='candle1D';assert.deepEqual(parsed(s,'candle',p),[],'UTC+8 daily candles cannot replace UTC history');
});
test('Bybit ticker deltas without lastPrice do not fabricate a quote; zero or nonfinite prices are refused',()=>{
 const s=source(),p=quote(s);p.type='delta';delete p.data.lastPrice;assert.deepEqual(parsed(s,'quote',p),[]);
 for(const price of ['0','-1','NaN','Infinity','',null]){const bad=quote(s);bad.data.lastPrice=price;assert.deepEqual(parsed(s,'quote',bad),[]);}
});
test('OKX public and business messages cannot cross socket roles',()=>{
 const s=source('okx');assert.deepEqual(parseMessage('okx','quotes',candle(s),[s],NOW),[]);assert.deepEqual(parseMessage('okx','candles',quote(s),[s],NOW),[]);
});
test('acknowledgements, unknown topics, and malformed top-level frames create no chart update',()=>{
 const s=source();for(const value of [null,[],{},'pong',{op:'subscribe',success:true},{topic:'orderbook.1.BTCUSDT',ts:NOW*1000,data:{lastPrice:'100'}},{topic:'tickers.BTCUSDT',ts:NOW*1000,data:null}])assert.deepEqual(parsed(s,'quote',value),[]);
});

function harness(options={}){
 let time=(options.startAt??NOW)*1000,id=0;const timers=new Map(),sockets=[],updates=[];
 const schedule=(fn,delay,repeat=0)=>{const key=++id;timers.set(key,{fn,at:time+delay,repeat});return key;};
 class FakeWebSocket{
  static CONNECTING=0;static OPEN=1;static CLOSING=2;static CLOSED=3;
  constructor(url){this.url=url;this.readyState=0;this.sent=[];this.closeCalls=0;sockets.push(this);}
  send(value){assert.equal(this.readyState,1);this.sent.push(value);}
  close(){this.closeCalls++;this.readyState=3;}
  open(){this.readyState=1;this.onopen?.({});}
  receive(value){this.onmessage?.({data:typeof value==='string'?value:JSON.stringify(value)});}
  disconnect(){this.readyState=3;this.onclose?.({code:1006});}
 }
 const api=create({onUpdate:(...args)=>updates.push(args),WebSocketImpl:FakeWebSocket,now:()=>time/1000,setTimeoutFn:(fn,delay)=>schedule(fn,delay),clearTimeoutFn:key=>timers.delete(key),setIntervalFn:(fn,delay)=>schedule(fn,delay,delay),clearIntervalFn:key=>timers.delete(key),random:()=>0,...options});
 function advance(ms){const end=time+ms;let steps=0;while(true){const next=[...timers].filter(([,v])=>v.at<=end).sort((a,b)=>a[1].at-b[1].at||a[0]-b[0])[0];if(!next)break;assert.ok(++steps<10000,'timers must remain bounded');const [key,value]=next;time=value.at;if(value.repeat)value.at+=value.repeat;else timers.delete(key);value.fn();}time=end;}
 return {api,sockets,updates,timers,advance,now:()=>time/1000};
}

test('subscriptions deduplicate ticker channels across intervals and route OKX candle and quote sockets separately',()=>{
 const a=source(),b=source('bybit','BTCUSDT','1');assert.deepEqual(subscriptions('bybit','all',[a,a,b]),['kline.5.BTCUSDT','tickers.BTCUSDT','kline.1.BTCUSDT']);
 const o=source('okx');assert.deepEqual(subscriptions('okx','candles',[o]),[{channel:'candle5m',instId:'BTC-USDT-SWAP'}]);assert.deepEqual(subscriptions('okx','quotes',[o]),[{channel:'tickers',instId:'BTC-USDT-SWAP'}]);
 for(const interval of ['60','240','1440'])assert.deepEqual(subscriptions('gate','candles',[source('gate','BTCUSDT',interval)]),[{channel:'futures.candlesticks',payload:[units[interval],'BTC_USDT']}]);
});
test('source cap is 13 distinct keys, with one bounded socket for each venue role',()=>{
 const h=harness(),items=Array.from({length:20},(_,i)=>source('bybit','COIN'+i+'USDT'));h.api.setSources([...items,items[0],source('unknown')]);
 assert.equal(h.sockets.length,1);h.sockets[0].open();const request=JSON.parse(h.sockets[0].sent[0]);assert.equal(request.args.length,26);
 assert.ok(h.api.get(items[12]));assert.equal(h.api.get(items[13]),null);
 const five=['bybit','binance','okx','gate','bitget'].map(e=>source(e));h.api.setSources(five);assert.equal(h.sockets.length,6,'OKX needs two roles, other four venues one each');
 assert.equal(h.sockets.filter(s=>s.url.startsWith('wss://ws.okx.com/')).length,2);h.api.dispose();
});
test('each venue opens the native public endpoint and sends the expected wire subscription',()=>{
 const expected={bybit:'wss://stream.bybit.com/v5/public/linear',binance:'wss://fstream.binance.com/market/stream',gate:'wss://fx-ws.gateio.ws/v4/ws/usdt',bitget:'wss://ws.bitget.com/v2/ws/public'};
 for(const exchange of Object.keys(expected)){
  const h=harness(),s=source(exchange);h.api.setSources([s]);assert.equal(h.sockets[0].url,expected[exchange]);h.sockets[0].open();
  const frames=h.sockets[0].sent.map(v=>JSON.parse(v));assert.ok(frames.length>=1);
  if(exchange==='binance'){assert.equal(frames[0].method,'SUBSCRIBE');assert.deepEqual(frames[0].params,['btcusdt@kline_5m','btcusdt@miniTicker']);}
  else if(exchange==='gate'){assert.equal(frames[0].event,'subscribe');assert.equal(frames[0].channel,'futures.candlesticks');assert.deepEqual(frames[0].payload,['5m','BTC_USDT']);assert.equal(frames[1].channel,'futures.tickers');}
  else {assert.equal(frames[0].op,'subscribe');assert.deepEqual(frames[0].args,subscriptions(exchange,'all',[s]));}
  h.api.dispose();
 }
});
test('unchanged and duplicate source sets do not reopen or resubscribe, while removed topics are unsubscribed',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();h.advance(1000);const before=socket.sent.length;
 for(let i=0;i<10;i++)h.api.setSources([s,s]);h.advance(1000);assert.equal(h.sockets.length,1);assert.equal(socket.sent.length,before);
 const next=source('bybit','ETHUSDT');h.api.setSources([next]);const messages=socket.sent.slice(before).map(v=>JSON.parse(v));assert.deepEqual(messages.map(m=>m.op),['unsubscribe','subscribe']);assert.deepEqual(messages[0].args,['kline.5.BTCUSDT','tickers.BTCUSDT']);
 socket.receive(quote(s,h.now()));assert.equal(h.api.get(s),null,'removed identity cannot resurrect a sample');assert.equal(h.api.get(next).quote,null);h.api.dispose();
});
test('a message burst coalesces callbacks and retains the last accepted quote',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();h.advance(250);h.updates.length=0;
 for(let i=0;i<50;i++){const p=quote(s,h.now());p.data.lastPrice=String(103+i/100);socket.receive(p);}
 assert.equal(h.updates.length,0);h.advance(249);assert.equal(h.updates.length,0);h.advance(1);assert.equal(h.updates.length,1);assert.equal(h.api.get(s).quote.price,103.49);h.api.dispose();
});
test('older source messages cannot roll back a received price or forming candle',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();socket.receive(quote(s,h.now()));socket.receive(candle(s,h.now()));h.advance(1000);
 const newer=quote(s,h.now());newer.data.lastPrice='104';socket.receive(newer);const older=quote(s,h.now()-1);older.data.lastPrice='1';socket.receive(older);assert.equal(h.api.get(s).quote.price,104);
 const update=candle(s,h.now());update.data[0].close='102';socket.receive(update);const rollback=candle(s,h.now()-1);rollback.data[0].close='101';socket.receive(rollback);assert.equal(h.api.get(s).candle.close,102);h.api.dispose();
});
test('quote expiry uses original source and receipt times; fresh pongs cannot refresh market data',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();socket.receive(quote(s,h.now()));assert.equal(h.api.get(s).status,'connected');
 h.advance(10000);assert.ok(h.api.get(s).quote);socket.receive('pong');h.advance(1);assert.equal(h.api.get(s).quote,null);assert.notEqual(h.api.get(s).status,'connected');h.api.dispose();
});
test('disconnect drops live samples immediately, retries with bounded backoff, and rejects callbacks from the old socket',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const first=h.sockets[0];first.open();first.receive(quote(s,h.now()));assert.ok(h.api.get(s).quote);first.disconnect();assert.equal(h.api.get(s).quote,null);assert.equal(h.api.get(s).status,'unavailable');
 h.advance(1999);assert.equal(h.sockets.length,1);h.advance(1);assert.equal(h.sockets.length,2);const second=h.sockets[1];second.open();first.receive(quote(s,h.now()));assert.equal(h.api.get(s).quote,null);
 second.disconnect();h.advance(3999);assert.equal(h.sockets.length,2);h.advance(1);assert.equal(h.sockets.length,3);h.sockets[2].open();h.sockets[2].receive(quote(s,h.now()));assert.ok(h.api.get(s).quote);h.sockets[2].disconnect();h.advance(2000);assert.equal(h.sockets.length,4,'accepted market data resets retry backoff');h.api.dispose();
});
test('empty sources close sockets and cancel reconnects so a hidden screener has no network activity',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();socket.disconnect();h.api.setSources([]);h.advance(60000);assert.equal(h.sockets.length,1);assert.equal(h.api.get(s),null);
 h.api.setSources([s]);assert.equal(h.sockets.length,2);h.api.dispose();
});
test('disabled synthetic mode opens no network connection, and dispose is idempotent with no remaining timers',()=>{
 const h=harness({disabled:true}),s=source();h.api.setSources([s]);h.advance(30000);assert.equal(h.sockets.length,0);assert.equal(h.api.get(s).status,'unavailable');h.api.dispose();h.api.dispose();assert.equal(h.timers.size,0);h.api.setSources([s]);assert.equal(h.sockets.length,0);
});
test('application heartbeat uses each provider protocol rather than fake quote updates',()=>{
 for(const exchange of ['bybit','gate','okx','bitget']){
  const h=harness(),s=source(exchange);h.api.setSources([s]);for(const socket of h.sockets)socket.open();h.advance(20000);
  for(const socket of h.sockets){const last=socket.sent.at(-1);if(exchange==='okx'||exchange==='bitget')assert.equal(last,'ping');else if(exchange==='bybit')assert.equal(JSON.parse(last).op,'ping');else assert.equal(JSON.parse(last).channel,'futures.ping');}
  assert.equal(h.api.get(s).quote,null);h.api.dispose();
 }
});
test('stalled connection and server rejection retry instead of claiming a connected chart',()=>{
 for(const mode of ['stalled','rejected']){
  const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];if(mode==='rejected'){socket.open();socket.receive({op:'subscribe',success:false,ret_msg:'unsupported'});}else h.advance(16000);
  assert.equal(h.api.get(s).status,'unavailable');h.advance(2000);assert.equal(h.sockets.length,2);h.api.dispose();
 }
});
test('malformed JSON, nontext frames, and oversized frames never supply live proof',()=>{
 const h=harness(),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();for(const frame of ['{','x'.repeat(262145)])socket.receive(frame);socket.onmessage({data:new Uint8Array([1,2,3])});assert.equal(h.api.get(s).candle,null);assert.equal(h.api.get(s).quote,null);h.api.dispose();
});
test('OKX subscription roles keep their samples independent when only one connection fails',()=>{
 const h=harness(),s=source('okx');h.api.setSources([s]);const bars=h.sockets.find(v=>v.url.endsWith('/business')),prices=h.sockets.find(v=>v.url.endsWith('/public'));bars.open();prices.open();bars.receive(candle(s,h.now()));prices.receive(quote(s,h.now()));assert.ok(h.api.get(s).candle);assert.ok(h.api.get(s).quote);
 bars.disconnect();assert.equal(h.api.get(s).candle,null);assert.ok(h.api.get(s).quote);h.api.dispose();
});
test('a forming candle disappears at the next period boundary rather than remaining labelled live for 75 seconds',()=>{
 const boundary=(Math.floor(NOW/300)+1)*300,h=harness({startAt:boundary-1}),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();socket.receive(candle(s,h.now()));assert.ok(h.api.get(s).candle);
 h.advance(2000);assert.equal(h.api.get(s).candle,null,'prior open candle is no longer the current period');h.api.dispose();
});
test('a native closing-bar overlay is limited to its ten-second close window',()=>{
 const boundary=(Math.floor(NOW/300)+1)*300,h=harness({startAt:boundary+5}),s=source();h.api.setSources([s]);const socket=h.sockets[0];socket.open();const p=candle(s,h.now());p.data[0].start=(boundary-300)*1000;p.data[0].end=boundary*1000-1;p.data[0].confirm=true;socket.receive(p);assert.ok(h.api.get(s).candle);
 h.advance(6000);assert.equal(h.api.get(s).candle,null,'closing overlay cannot outlive its publication grace');h.api.dispose();
});
test('rapid timeframe changes remain below the documented hourly subscription request limits',()=>{
 for(const [exchange,cap]of [['bitget',240],['okx',480]]){
  const h=harness(),s=source(exchange);h.api.setSources([s]);for(const socket of h.sockets)socket.open();
  for(let i=0;i<260;i++){for(const socket of h.sockets)socket.receive('pong');h.advance(600);h.api.setSources([source(exchange,'BTCUSDT',i%2?'5':'1')]);}
  for(const socket of h.sockets){const requests=socket.sent.filter(v=>v!=='ping').map(v=>JSON.parse(v)).filter(v=>v.op==='subscribe'||v.op==='unsubscribe');assert.ok(requests.length<=cap,exchange+' sent '+requests.length+' requests against '+cap+'/hour cap');}
  h.api.dispose();
 }
});
test('provided malformed volume or turnover cannot silently become an unknown valid candle',()=>{
 for(const exchange of ['bybit','binance','okx','gate','bitget'])for(const field of ['volume','turnover']){
  if(exchange==='gate'&&field==='volume')continue; // Gate contracts are deliberately absent from the base-coin volume overlay.
  const s=source(exchange),p=candle(s);
  if(exchange==='bybit')p.data[0][field]='NaN';
  else if(exchange==='binance')p.data.k[field==='volume'?'v':'q']='NaN';
  else if(exchange==='gate')p.result[0].a='NaN';
  else p.data[0][exchange==='okx'?(field==='volume'?6:7):(field==='volume'?5:6)]='NaN';
  assert.deepEqual(parsed(s,'candle',p),[],exchange+' '+field);
 }
 const s=source('gate'),items=parsed(s,'candle',candle(s));assert.equal(items[0].value.volume,null,'contract count never masquerades as base-coin volume');
});
test('Bybit payload interval must agree with the subscribed topic',()=>{
 const s=source(),p=candle(s);p.data[0].interval='1';assert.deepEqual(parsed(s,'candle',p),[]);
});
test('Gate nested protocol errors discard samples immediately and schedule reconnect',()=>{
 const h=harness(),s=source('gate');h.api.setSources([s]);const socket=h.sockets[0];socket.open();socket.receive(quote(s,h.now()));assert.ok(h.api.get(s).quote);
 socket.receive({time:h.now(),time_ms:h.now()*1000,channel:'futures.tickers',event:'subscribe',error:{code:2,message:'Unknown contract'},result:null});assert.equal(h.api.get(s).quote,null);assert.equal(h.api.get(s).status,'unavailable');h.advance(2000);assert.equal(h.sockets.length,2);h.api.dispose();
});
