/* Public display-only streams. Closed REST evidence remains owned by chart-grid. */
(function(scope){
 'use strict';
 const PERIODS={'1':60,'5':300,'15':900,'60':3600,'240':14400,'1440':86400};
 const URLS={bybit:'wss://stream.bybit.com/v5/public/linear',binance:'wss://fstream.binance.com/market/stream',okx:{candles:'wss://ws.okx.com/ws/v5/business',quotes:'wss://ws.okx.com/ws/v5/public'},gate:'wss://fx-ws.gateio.ws/v4/ws/usdt',bitget:'wss://ws.bitget.com/v2/ws/public'};
 const FRAMES=262144,MAX_SOURCES=13,finite=n=>typeof n==='number'&&Number.isFinite(n),number=v=>(typeof v==='number'||typeof v==='string'&&v.trim()!=='')&&Number.isFinite(Number(v))?Number(v):null;
 const keyOf=s=>[s.exchange,s.symbol,s.interval].join(':'),nativeFor=s=>s.exchange==='okx'?s.symbol.slice(0,-4)+'-USDT-SWAP':s.exchange==='gate'?s.symbol.slice(0,-4)+'_USDT':s.symbol;
 function validSource(s){return !!s&&Object.hasOwn(URLS,s.exchange)&&typeof s.symbol==='string'&&/^[A-Z0-9]{1,28}USDT$/.test(s.symbol)&&typeof s.interval==='string'&&Object.hasOwn(PERIODS,s.interval)&&s.native_symbol===nativeFor(s);}
 const frame=(e,i)=>e==='bybit'?(i==='1440'?'D':i):['binance','gate'].includes(e)?({'1':'1m','5':'5m','15':'15m','60':'1h','240':'4h','1440':'1d'})[i]:({'1':'1m','5':'5m','15':'15m','60':'1H','240':'4H','1440':'1Dutc'})[i];
 function subscriptions(exchange,role,sources){
  const result=new Map();
  for(const s of sources.filter(s=>validSource(s)&&s.exchange===exchange)){
   const n=s.native_symbol,f=frame(exchange,s.interval);let candle,quote;
   if(exchange==='bybit'){candle='kline.'+f+'.'+n;quote='tickers.'+n;}
   if(exchange==='binance'){candle=n.toLowerCase()+'@kline_'+f;quote=n.toLowerCase()+'@miniTicker';}
   if(exchange==='okx'){candle={channel:'candle'+f,instId:n};quote={channel:'tickers',instId:n};}
   if(exchange==='gate'){candle={channel:'futures.candlesticks',payload:[f,n]};quote={channel:'futures.tickers',payload:[n]};}
   if(exchange==='bitget'){candle={instType:'USDT-FUTURES',channel:'candle'+f,instId:n};quote={instType:'USDT-FUTURES',channel:'ticker',instId:n};}
   for(const value of role==='candles'?[candle]:role==='quotes'?[quote]:[candle,quote])result.set(JSON.stringify(value),value);
  }
  return [...result.values()];
 }
 function stamp(raw,received,optional=false){
  if(raw===null||raw===undefined)return optional?{source_ts:null,received_at:received,timestamp_origin:'receipt'}:null;
  const t=number(raw);if(t===null||received-t>75||t-received>2)return null;
  return {source_ts:t,received_at:received,timestamp_origin:'exchange'};
 }
 function parseMessage(exchange,role,message,sources,now=Date.now()/1000){
  if(!finite(now)||!message||typeof message!=='object'||Array.isArray(message)||!Object.hasOwn(URLS,exchange))return [];
  const selected=sources.filter(s=>validSource(s)&&s.exchange===exchange).slice(0,MAX_SOURCES),out=[];
  const candle=(s,b,rawStamp,optional=false)=>{
   const t=number(b.t),open=number(b.open),high=number(b.high),low=number(b.low),close=number(b.close),volume=b.volume===null?null:number(b.volume),turnover=b.turnover===null?null:number(b.turnover),step=PERIODS[s.interval],current=Math.floor(now/step)*step,ts=stamp(rawStamp,now,optional);
   if(!ts||[t,open,high,low,close].some(v=>v===null)||b.volume!==null&&volume===null||b.turnover!==null&&turnover===null||t%step!==0||low<=0||low>Math.min(open,close)||high<Math.max(open,close)||volume!==null&&volume<0||turnover!==null&&turnover<0)return;
   if(!((t===current&&!b.closed)||(t===current-step&&b.closed===true&&now-current<=10)))return;
   out.push({key:keyOf(s),kind:'candle',value:{t,open,high,low,close,volume,turnover,closed:b.closed===true,...ts}});
  };
  const quote=(s,raw,rawStamp)=>{const price=number(raw),ts=stamp(rawStamp,now);if(price===null||price<=0||!ts||now-ts.source_ts>10)return;out.push({key:keyOf(s),kind:'quote',value:{price,...ts}});};
  if(exchange==='bybit'){
   for(const s of selected){const n=s.native_symbol;if(message.topic==='kline.'+frame(exchange,s.interval)+'.'+n&&Array.isArray(message.data))for(const b of message.data.slice(0,20))if(b?.interval===frame(exchange,s.interval))candle(s,{t:number(b.start)/1000,open:b.open,high:b.high,low:b.low,close:b.close,volume:b.volume,turnover:b.turnover,closed:b.confirm===true},number(message.ts)/1000);
    if(message.topic==='tickers.'+n&&message.data?.symbol===n&&Object.hasOwn(message.data,'lastPrice'))quote(s,message.data.lastPrice,number(message.ts)/1000);
   }
  }else if(exchange==='binance'){
   const m=message.data,k=m?.k;for(const s of selected){const n=s.native_symbol.toLowerCase();if(message.stream===n+'@kline_'+frame(exchange,s.interval)&&m?.s===s.native_symbol&&k?.s===s.native_symbol&&k?.i===frame(exchange,s.interval))candle(s,{t:number(k.t)/1000,open:k.o,high:k.h,low:k.l,close:k.c,volume:k.v,turnover:k.q,closed:k.x===true},number(m.E)/1000);
    if(message.stream===n+'@miniTicker'&&m?.s===s.native_symbol)quote(s,m.c,number(m.E)/1000);
   }
  }else if(exchange==='okx'){
   const arg=message.arg;for(const s of selected){if(arg?.instId!==s.native_symbol||!Array.isArray(message.data))continue;
    if(role==='candles'&&arg.channel==='candle'+frame(exchange,s.interval))for(const b of message.data.slice(0,20))if(Array.isArray(b)&&b.length>=9)candle(s,{t:number(b[0])/1000,open:b[1],high:b[2],low:b[3],close:b[4],volume:b[6],turnover:b[7],closed:b[8]==='1'},null,true);
    if(role==='quotes'&&arg.channel==='tickers')for(const b of message.data.slice(0,20))if(b?.instId===s.native_symbol)quote(s,b.last,number(b.ts)/1000);
   }
  }else if(exchange==='gate'&&message.event==='update'&&Array.isArray(message.result)){
   for(const s of selected)for(const b of message.result.slice(0,20)){
    if(message.channel==='futures.candlesticks'&&b?.n===frame(exchange,s.interval)+'_'+s.native_symbol)candle(s,{t:b.t,open:b.o,high:b.h,low:b.l,close:b.c,volume:null,turnover:b.a??null,closed:b.w===true},number(message.time_ms)/1000);
    if(message.channel==='futures.tickers'&&b?.contract===s.native_symbol)quote(s,b.last,number(b.t??message.time_ms)/1000);
   }
  }else if(exchange==='bitget'){
   const arg=message.arg;for(const s of selected){if(arg?.instType!=='USDT-FUTURES'||arg.instId!==s.native_symbol||!Array.isArray(message.data))continue;
    if(arg.channel==='candle'+frame(exchange,s.interval))for(const b of message.data.slice(0,20))if(Array.isArray(b)&&b.length>=7)candle(s,{t:number(b[0])/1000,open:b[1],high:b[2],low:b[3],close:b[4],volume:b[5],turnover:b[6],closed:false},number(message.ts)/1000);
    if(arg.channel==='ticker')for(const b of message.data.slice(0,20))if(b?.instId===s.native_symbol)quote(s,b.lastPr,number(b.ts??message.ts)/1000);
   }
  }
  return out;
 }
 function create(options={}){
  const WS=options.WebSocketImpl??scope.WebSocket,now=options.now??(()=>Date.now()/1000),later=options.setTimeoutFn??scope.setTimeout.bind(scope),cancel=options.clearTimeoutFn??scope.clearTimeout.bind(scope),every=options.setIntervalFn??scope.setInterval.bind(scope),cancelEvery=options.clearIntervalFn??scope.clearInterval.bind(scope),random=options.random??Math.random;
  const onUpdate=options.onUpdate??(()=>{}),disabled=options.disabled===true||typeof WS!=='function',sources=new Map(),views=new Map(),groups=new Map();let disposed=false,sequence=1,flushTimer=null;
  function emit(){if(disposed||flushTimer!==null)return;flushTimer=later(()=>{flushTimer=null;if(!disposed)onUpdate();},250);}
  function sourceGroup(s,role){return groups.get(s.exchange+':'+(s.exchange==='okx'?role:'all'));}
  function get(s){
   const key=typeof s==='string'?s:keyOf(s),source=sources.get(key);if(!source)return null;
   const candleGroup=sourceGroup(source,'candles'),quoteGroup=sourceGroup(source,'quotes'),view=views.get(key)||{},clock=now();
   const usable=(value,ttl)=>value&&clock-value.received_at>=-2&&clock-value.received_at<=ttl&&(value.source_ts===null||clock-value.source_ts>=-2&&clock-value.source_ts<=ttl);
   const ready=g=>g?.socket?.readyState===1&&g.active.size>0&&!g.rejected;
   const step=PERIODS[source.interval],bucket=Math.floor(clock/step)*step,b=view.candle,current=b&&(b.closed===false&&b.t===bucket||b.closed===true&&b.t===bucket-step&&clock-bucket<=10);
   const candle=ready(candleGroup)&&usable(b,75)&&current?b:null,quote=ready(quoteGroup)&&usable(view.quote,10)?view.quote:null;
   return {...source,status:disabled?'unavailable':candle||quote?'connected':ready(candleGroup)||ready(quoteGroup)||candleGroup?.socket?.readyState===0||quoteGroup?.socket?.readyState===0?'connecting':'unavailable',candle,quote};
  }
  function stop(g){g.generation++;if(g.retry!==null)cancel(g.retry);g.retry=null;if(g.socket){const socket=g.socket;g.socket=null;try{socket.close();}catch{}}g.active.clear();}
  function clearSamples(g){for(const [key,s]of sources)if(s.exchange===g.exchange){const old=views.get(key);if(old)views.set(key,{...old,...(g.role==='quotes'?{quote:null}:g.role==='candles'?{candle:null}:{candle:null,quote:null})});}emit();}
  function lost(g,generation){if(disposed||g.generation!==generation||!groups.has(g.id))return;stop(g);clearSamples(g);const delay=Math.min(30,2*Math.pow(2,Math.min(g.failures++,4)))+random();g.retry=later(()=>{g.retry=null;if(groups.has(g.id)&&!disposed)open(g);},delay*1000);}
  function send(g,message){if(g.socket?.readyState!==1)return false;try{g.socket.send(JSON.stringify(message));return true;}catch{lost(g,g.generation);return false;}}
  function messages(g,op,items){
   if(!items.length)return [];
   if(g.exchange==='binance')return [{method:op==='subscribe'?'SUBSCRIBE':'UNSUBSCRIBE',params:items,id:sequence++}];
   if(g.exchange==='gate'){const candles=items.filter(i=>i.channel==='futures.candlesticks'),quotes=items.filter(i=>i.channel==='futures.tickers');return [...candles.map(i=>({time:Math.floor(now()),channel:i.channel,event:op,payload:i.payload})),...(quotes.length?[{time:Math.floor(now()),channel:'futures.tickers',event:op,payload:quotes.flatMap(i=>i.payload)}]:[])];}
   return [{op,args:items}];
  }
  function reconcile(g){
   if(g.socket?.readyState!==1||g.rejected)return;
   const clock=now();g.requests=g.requests.filter(t=>clock-t<3600);
   // Bound protocol request rates; superseded desired sources never accept data.
   if(clock-g.lastChange<.5||g.requests.length>=(g.exchange==='okx'?480:g.exchange==='bitget'?240:600))return;
   const removes=[...g.active].filter(([id])=>!g.desired.has(id)).map(([,v])=>v),adds=[...g.desired].filter(([id])=>!g.active.has(id)).map(([,v])=>v);
   const limited=items=>g.exchange==='gate'?items.slice(0,2):items;
   for(const [op,items]of [['unsubscribe',limited(removes)],['subscribe',limited(adds)]]){
    if(!items.length)continue;const frames=messages(g,op,items);if(g.requests.length+frames.length>(g.exchange==='okx'?480:g.exchange==='bitget'?240:600))return;for(const frame of frames){if(!send(g,frame))return;g.requests.push(clock);}for(const item of items){const id=JSON.stringify(item);if(op==='subscribe')g.active.set(id,item);else g.active.delete(id);}
    g.lastChange=clock;emit();
   }
  }
  function open(g){
   if(disposed||disabled||!groups.has(g.id)||!g.desired.size)return;g.generation++;const generation=g.generation;g.rejected=false;g.lastReceived=now();g.lastPing=now();g.lastChange=-Infinity;
   try{g.socket=new WS(g.exchange==='okx'?URLS.okx[g.role]:URLS[g.exchange]);}catch{lost(g,generation);return;}
   const socket=g.socket;socket.onopen=()=>{if(g.generation!==generation)return;reconcile(g);emit();};
   socket.onmessage=event=>{
    if(disposed||g.generation!==generation||socket!==g.socket)return;
    if(typeof event.data!=='string'||event.data.length>FRAMES)return;g.lastReceived=now();
    if(event.data==='pong')return;let message;try{message=JSON.parse(event.data);}catch{return;}
    if(message?.event==='error'||message?.error||message?.op==='subscribe'&&message.success===false||message?.code&&message.code!==0&&message.code!=='0'){g.rejected=true;lost(g,generation);return;}
    const updates=parseMessage(g.exchange,g.role,message,[...sources.values()],now());
    if(updates.length){g.failures=0;for(const u of updates){const prior=views.get(u.key)||{},old=prior[u.kind];if(old&&u.value.source_ts!==null&&old.source_ts!==null&&u.value.source_ts<old.source_ts)continue;if(u.kind==='candle'&&old&&u.value.t<old.t)continue;views.set(u.key,{...prior,[u.kind]:u.value});}emit();}
   };
   socket.onerror=()=>lost(g,generation);socket.onclose=()=>lost(g,generation);
  }
  function setSources(input){
   if(disposed)return;sources.clear();for(const s of Array.isArray(input)?input:[])if(validSource(s)&&sources.size<MAX_SOURCES)sources.set(keyOf(s),{exchange:s.exchange,symbol:s.symbol,interval:s.interval,native_symbol:s.native_symbol});
   for(const key of views.keys())if(!sources.has(key))views.delete(key);
   const wanted=new Map();for(const s of sources.values())for(const role of s.exchange==='okx'?['candles','quotes']:['all'])wanted.set(s.exchange+':'+role,{exchange:s.exchange,role});
   for(const [id,g]of groups)if(!wanted.has(id)){stop(g);groups.delete(id);}
   if(!disabled)for(const [id,identity]of wanted){let g=groups.get(id);if(!g){g={id,...identity,socket:null,desired:new Map(),active:new Map(),generation:0,retry:null,failures:0,rejected:false,requests:[],lastChange:-Infinity};groups.set(id,g);}g.desired=new Map(subscriptions(g.exchange,g.role,[...sources.values()]).map(value=>[JSON.stringify(value),value]));if(!g.socket&&g.retry===null)open(g);else reconcile(g);}
   emit();
  }
  const heartbeat=every(()=>{
   if(disposed)return;const clock=now();for(const g of groups.values()){
    if(g.socket?.readyState===0&&clock-g.lastReceived>15){lost(g,g.generation);continue;}
    if(g.socket?.readyState!==1)continue;if(clock-g.lastReceived>45){lost(g,g.generation);continue;}
    reconcile(g);if(clock-g.lastPing>=20){g.lastPing=clock;try{if(g.exchange==='bybit')send(g,{op:'ping'});else if(g.exchange==='gate')send(g,{time:Math.floor(clock),channel:'futures.ping'});else if(g.exchange==='okx'||g.exchange==='bitget')g.socket.send('ping');}catch{lost(g,g.generation);}}
   }
   // Expiry is re-evaluated against original timestamps even during wire silence.
   if(sources.size)emit();
  },1000);
  function dispose(){if(disposed)return;disposed=true;for(const g of groups.values())stop(g);groups.clear();sources.clear();views.clear();if(flushTimer!==null)cancel(flushTimer);cancelEvery(heartbeat);}
  return {setSources,get,dispose};
 }
 const api={keyOf,validSource,parseMessage,subscriptions,create};if(typeof module!=='undefined')module.exports=api;scope.LabChartStream=api;
})(typeof window==='undefined'?globalThis:window);
