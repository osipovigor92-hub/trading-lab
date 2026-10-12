/* Public exchange charts. Tile positions stay fixed until an explicit re-sort. */
(function(scope){
 'use strict';
 const EXCHANGES={bybit:'Bybit',binance:'Binance',okx:'OKX',gate:'Gate',bitget:'Bitget'},PERIODS={'1':60,'5':300,'15':900,'60':3600,'240':14400,'1440':86400};
 const finite=n=>typeof n==='number'&&Number.isFinite(n),symbolOK=s=>typeof s==='string'&&/^[A-Z0-9]{1,28}USDT$/.test(s),fresh=(t,now,ttl)=>finite(t)&&now-t>=-2&&now-t<=ttl;
 function validChart(p,exchange,symbol,interval,now=Date.now()/1000){
  if(!p||p.exchange!==exchange||p.symbol!==symbol||p.interval!==interval||p.status!=='ok'||p.error||p.stale||p.refresh_error||!fresh(p.updated,now,75))return false;
  const period=PERIODS[interval],bars=p.candles;if(!period||!Array.isArray(bars)||bars.length<60||bars.length>180)return false;
  if(!fresh(p.candle_end,now,period+75)||p.candle_end!==Math.floor((now-2)/period)*period||p.updated-p.candle_end<0||p.updated-p.candle_end>=period+2)return false;
  return bars.every((b,i)=>b&&[b.t,b.open,b.high,b.low,b.close,b.volume,b.turnover].every(finite)&&b.t%period===0&&b.t+period<=now&&b.low>0&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&b.volume>=0&&b.turnover>=0&&(!i||b.t-bars[i-1].t===period))&&bars.at(-1).t+period===p.candle_end;
 }
 function awaitingClose(p,exchange,symbol,interval,now=Date.now()/1000){
  const period=PERIODS[interval],expected=Math.floor((now-2)/period)*period;
  if(!p||!period||!['ok','pending'].includes(p.status)||p.error||p.refresh_error||!fresh(p.updated,now,75)||now-expected<2||now-expected>10||p.candle_end!==expected-period)return false;
  return validChart({...p,status:'ok',stale:false},exchange,symbol,interval,Math.max(p.updated,p.candle_end+2));
 }
 function refreshDue(p,exchange,symbol,interval,last,now=Date.now()/1000,failed=false){
  if(!last)return true;
  if(failed)return now-last>=5;
  if(p?.error||p?.refresh_error)return now-last>=Math.max(1,Math.min(30,finite(p?.retry_after_seconds)?p.retry_after_seconds:5));
  if(awaitingClose(p,exchange,symbol,interval,now))return now-last>=1;
  if(!validChart(p,exchange,symbol,interval,now))return now-last>=2;
  const boundary=p.candle_end+PERIODS[interval]+2;
  const hint=finite(p.next_refresh_at)&&p.next_refresh_at>=p.updated&&p.next_refresh_at<=p.updated+30?p.next_refresh_at:boundary;
  return now>=Math.max(last+1,Math.min(last+15,boundary,hint));
 }
 function natr(bars,period){
  if(!Array.isArray(bars)||bars.length<period+1)return null;
  const tr=bars.slice(1).map((b,i)=>Math.max(b.high-b.low,Math.abs(b.high-bars[i].close),Math.abs(b.low-bars[i].close)));
  if(tr.some(v=>!finite(v)||v<0)||!finite(bars.at(-1).close)||bars.at(-1).close<=0)return null;
  let atr=tr.slice(0,period).reduce((a,b)=>a+b,0)/period;for(const value of tr.slice(period))atr=(atr*(period-1)+value)/period;
  return 100*atr/bars.at(-1).close;
 }
 function metricValue(row,key,packets,exchange,now){
  if(key==='turnover')return finite(row.turnover24)?row.turnover24:null;
  if(key==='change24')return finite(row.change24)?row.change24:null;
  if(key==='trades24')return finite(row.trades24)?row.trades24:null;
  const interval=key==='natr5_14'?'5':'1',p=packets.get(exchange+':'+row.symbol+':'+interval);
  if(!validChart(p,exchange,row.symbol,interval,now))return null;
  if(key==='change5'){const b=p.candles;return 100*(b.at(-1).close/b.at(-6).close-1);}
  return natr(p.candles,key==='natr1_30'?30:14);
 }
 function rankRows(rows,key,packets,exchange,now){return rows.slice().sort((a,b)=>{const x=metricValue(a,key,packets,exchange,now),y=metricValue(b,key,packets,exchange,now);return (x===null)-(y===null)||(y??0)-(x??0)||(b.turnover24||0)-(a.turnover24||0)||a.symbol.localeCompare(b.symbol);});}
 function formatPrice(n){if(!finite(n))return '—';return Math.abs(n)<.00001&&n!==0?n.toLocaleString('ru-RU',{notation:'scientific',maximumSignificantDigits:6}):n.toLocaleString('ru-RU',{maximumFractionDigits:n<1?7:n<100?4:2,minimumFractionDigits:n<1?7:n<100?4:2});}
 const api={validChart,awaitingClose,refreshDue,natr,metricValue,rankRows,formatPrice};if(typeof module!=='undefined')module.exports=api;if(typeof document==='undefined')return;scope.LabChartGrid=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-market');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;},button=(text,handler,cls='screener-order')=>{const b=el('button',cls,text);b.type='button';b.addEventListener('click',handler);return b;};
  const read=(k,f)=>{try{return JSON.parse(localStorage.getItem(k))??f;}catch{return f;}},write=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch{notice.textContent='Настройки действуют до закрытия страницы · хранилище недоступно';}};
  const old=el('div','assistant-table-view');while(page.firstChild)old.append(page.firstChild);
  const viewbar=el('div','screener-viewbar'),viewbuttons={};let view=read('lab-screener-view-v1','charts');
  for(const [key,label]of [['charts','Графики'],['table','Таблица']]){viewbuttons[key]=button(label,()=>setView(key));viewbar.append(viewbuttons[key]);}viewbar.append(el('span','muted','Скринер · USDT perpetual'));page.append(viewbar,old);
  const area=el('section','chart-grid-workspace');area.setAttribute('aria-label','Сетка графиков');page.append(area);
  const saved=read('lab-chart-grid-v1',{});let exchange=Object.hasOwn(EXCHANGES,saved.exchange)?saved.exchange:'bybit',interval=Object.hasOwn(PERIODS,saved.interval)?saved.interval:'5',metric=['turnover','natr5_14','natr1_30','change24','change5','trades24'].includes(saved.metric)?saved.metric:'natr5_14',count=[4,6,9,12].includes(saved.count)?saved.count:9,onlyWatch=false,catalog=null,catalogError='',order=[],requestGeneration=0,busy=false,chartsBusy=0;
  const inFlight=new Set(),failures=new Map(),forced=new Set(),packets=new Map(),attempts=new Map(),nodes=new Map(),pairWatch=new Set((Array.isArray(read('lab-exchange-favorites-v1',[]))?read('lab-exchange-favorites-v1',[]):[]).filter(p=>/^\w+:[A-Z0-9]{1,28}USDT$/.test(p)&&Object.hasOwn(EXCHANGES,p.split(':')[0])).slice(0,24));
  const densityStore='lab-grid-densities-v1',densitySaved=read(densityStore,[]),densityEnabled=new Set((Array.isArray(densitySaved)?densitySaved:[]).filter(p=>typeof p==='string'&&/^(bybit|binance|okx|gate|bitget):[A-Z0-9]{1,28}USDT$/.test(p)).slice(-48)),densityPackets=new Map(),densityErrors=new Map();
  let densityScope='',densitySources=[],densityGeneration=0,densityController=null,densityTimer,lastDensityRead=0,pageSuspended=false;
  const controls=el('form','chart-grid-controls'),select=(label,items,value)=>{const n=el('select');n.setAttribute('aria-label',label);for(const [v,t]of items){const o=el('option','',t);o.value=v;n.append(o);}n.value=String(value);return n;};
  const exchangeInput=select('Биржа графиков',Object.entries(EXCHANGES),exchange),frameInput=select('Период графиков',[['1','1м'],['5','5м'],['15','15м'],['60','1ч'],['240','4ч'],['1440','1д']],interval),metricLabels={turnover:'Оборот 24ч',natr5_14:'NATR 5м / 14',natr1_30:'NATR 1м / 30',change24:'Изменение 24ч',change5:'Изменение 5м',trades24:'Сделки 24ч'},metricInput=select('Метрика графиков',Object.entries(metricLabels),metric),countInput=select('Количество графиков',[[4,'4 · 2 × 2'],[6,'6 · 3 × 2'],[9,'9 · 3 × 3'],[12,'12 · 4 × 3']],count),search=el('input');search.type='search';search.placeholder='BTC, ETH, SOL…';search.setAttribute('aria-label','Поиск в графиках');search.maxLength=24;
  const watchButton=button('Мои монеты',()=>{onlyWatch=!onlyWatch;watchButton.setAttribute('aria-pressed',String(onlyWatch));order=[];render();}),resort=button('Пересортировать',()=>{order=[];render();}),refresh=button('Обновить',()=>{for(const r of selectedRows()){forced.add(exchange+':'+r.symbol+':'+interval);const m=metric==='natr5_14'?'5':(['natr1_30','change5'].includes(metric)?'1':null);if(m)forced.add(exchange+':'+r.symbol+':'+m);}attempts.clear();loadCatalog(true);pump();});watchButton.setAttribute('aria-pressed','false');
  controls.append(exchangeInput,frameInput,metricInput,countInput,search,watchButton,resort,refresh);area.append(controls);
  const statusline=el('div','chart-grid-status'),notice=el('span','muted','Загружаем список монет…'),coverage=el('span','muted');notice.setAttribute('role','status');statusline.append(notice,coverage);area.append(statusline);
  const tiles=el('div','chart-tiles');area.append(tiles);area.append(el('p','chart-grid-note muted','Порядок графиков закреплён. NATR измеряет волатильность; расчёт только по закрытым свечам. Сортировка NATR и изменения 5м доступна для загруженных монет. Остальные идут по обороту.'));
  function save(){write('lab-chart-grid-v1',{exchange,interval,metric,count});}
  function setView(key){view=key==='table'?'table':'charts';write('lab-screener-view-v1',view);old.hidden=view!=='table';area.hidden=view!=='charts';page.classList.toggle('chart-grid-active',view==='charts');for(const [k,b]of Object.entries(viewbuttons)){b.classList.toggle('selected',view===k);b.setAttribute('aria-pressed',String(view===k));}document.dispatchEvent(new CustomEvent('lab-screener-view',{detail:view}));if(view==='charts'){render();loadCatalog();pump();}syncStreams();syncDensityScope();}
  const visible=()=>!document.hidden&&!page.hidden&&view==='charts';
  function watched(s){if(pairWatch.has(exchange+':'+s))return true;const saved=read('lab-favorites-v1',[]);return exchange==='bybit'&&Array.isArray(saved)&&saved.includes(s);}
  function toggleWatch(s){const pair=exchange+':'+s,on=!watched(s);if(on&&pairWatch.size>=24){notice.textContent='Уже 24 монеты · уберите одну из наблюдения';return;}if(on)pairWatch.add(pair);else pairWatch.delete(pair);write('lab-exchange-favorites-v1',[...pairWatch]);if(exchange==='bybit')document.dispatchEvent(new CustomEvent('lab-watch-toggle',{detail:{symbol:s,on}}));render();}
  function selectedRows(){if(!catalog||catalog.exchange!==exchange)return [];const q=search.value.toUpperCase(),rows=(catalog.rows||[]).filter(r=>symbolOK(r.symbol)&&r.symbol.includes(q)&&(!onlyWatch||watched(r.symbol)));const ranked=rankRows(rows,metric,packets,exchange,Date.now()/1000),map=new Map(ranked.map(r=>[r.symbol,r]));const next=order.filter(s=>map.has(s));for(const r of ranked)if(!next.includes(r.symbol))next.push(r.symbol);order=next.slice(0,300);return order.slice(0,count).map(s=>map.get(s));}
  function toggleDensity(symbol){const key=exchange+':'+symbol;if(densityEnabled.has(key))densityEnabled.delete(key);else{densityEnabled.add(key);while(densityEnabled.size>48)densityEnabled.delete(densityEnabled.values().next().value);}write(densityStore,[...densityEnabled]);render();}
  function densitySettings(symbol,now){return {densities:densityEnabled.has(exchange+':'+symbol)?scope.LabChartLevels.densityLevels(densityPackets.get(exchange+':'+symbol),{exchange,symbol},now):[]};}
  function renderDensity(n,symbol,settings,now){
   const key=exchange+':'+symbol,on=densityEnabled.has(key),packet=densityPackets.get(key),levels=settings.densities,confirmed=levels.filter(level=>level.confirmed).length,packetOK=packet&&!packet.error&&!packet.refresh_error&&['ok','partial'].includes(packet.status)&&fresh(packet.updated,now,30);
   n.density.setAttribute('aria-pressed',String(on));n.density.classList.toggle('selected',on);n.box.dataset.densities=on?'on':'off';n.densityNote.hidden=!on;
   n.densityNote.dataset.status=confirmed===levels.length&&confirmed?'ok':packetOK&&!levels.length?'empty':packet?'unavailable':'pending';
   n.densityNote.textContent=densityErrors.get(key)?'Плотности не подтверждены · '+densityErrors.get(key):!packet?'Загружаем плотности…':confirmed?'Плотности: '+confirmed+' подтверждены'+(confirmed<levels.length?' · '+(levels.length-confirmed)+' без подтверждения':'')+' · от 100 000 USDT':levels.length?'Последние плотности без подтверждения · проверяем стакан':packetOK?'Подтверждённых плотностей от 100 000 USDT пока нет':'Стакан не подтверждён · повторяем запрос';
  }
  function syncDensityScope(){
   const symbols=visible()&&!dialog.open&&!pageSuspended?selectedRows().filter(row=>densityEnabled.has(exchange+':'+row.symbol)).map(row=>row.symbol).sort().slice(0,12):[],next=symbols.length?exchange+':'+symbols.join(','):'';
   if(next===densityScope)return;densityGeneration++;densityController?.abort();densityController=null;clearTimeout(densityTimer);densityScope=next;densitySources=symbols.map(symbol=>({exchange,symbol}));lastDensityRead=0;
   // One short debounce groups neighbouring tile clicks into one monitor scope.
   if(next)densityTimer=setTimeout(()=>pollDensity(true),120);
  }
  async function pollDensity(force=false){
   syncDensityScope();if(!densityScope||densityController||!force&&Date.now()-lastDensityRead<2000)return;
   const mine=densityGeneration,identity=densityScope,sources=densitySources.slice(),controller=new AbortController();densityController=controller;lastDensityRead=Date.now();const timer=setTimeout(()=>controller.abort(),8000);
   try{
    const next=await scope.labJson('/api/densities?'+new URLSearchParams({exchanges:sources[0].exchange,symbols:sources.map(source=>source.symbol).join(','),watch:sources.map(source=>source.exchange+':'+source.symbol).join(',')}),{fresh:force,signal:controller.signal},'Плотности графиков');
    if(mine!==densityGeneration||identity!==densityScope)return;
    if(!Array.isArray(next.rows)||!finite(next.updated)||!['ok','partial','pending','unavailable','error'].includes(next.status))throw Error('Некорректный ответ стакана');
    const packetOK=!next.error&&!next.refresh_error&&['ok','partial'].includes(next.status)&&fresh(next.updated,Date.now()/1000,30);
    for(const source of sources){
     const key=source.exchange+':'+source.symbol,prior=densityPackets.get(key),incoming=next.rows.filter(row=>row&&row.exchange===source.exchange&&row.symbol===source.symbol);
     // A failed or expired read cannot prove that an old level disappeared.
     const rows=packetOK?incoming.filter(row=>row.status!=='missing'):[...new Map([...(prior?.rows||[]),...incoming.filter(row=>row.status!=='missing')].map(row=>[row.id,{...row,status:'unavailable'}])).values()];
     densityPackets.delete(key);densityPackets.set(key,{...next,rows});densityErrors.delete(key);if(next.error)densityErrors.set(key,String(next.error).slice(0,120));
    }
    while(densityPackets.size>48){const key=densityPackets.keys().next().value;densityPackets.delete(key);densityErrors.delete(key);}
   }catch(error){if(mine!==densityGeneration||identity!==densityScope)return;for(const source of sources){const key=source.exchange+':'+source.symbol,prior=densityPackets.get(key);if(prior)densityPackets.set(key,{...prior,status:'unavailable'});densityErrors.set(key,error.name==='AbortError'?'Истёк срок запроса · повторяем':String(error.message||'Нет ответа биржи').slice(0,120));}while(densityErrors.size>48)densityErrors.delete(densityErrors.keys().next().value);}
   finally{clearTimeout(timer);if(densityController===controller)densityController=null;if(mine===densityGeneration&&visible())render();}
  }
  const fmt=(n,d=2)=>finite(n)?n.toLocaleString('ru-RU',{maximumFractionDigits:d,minimumFractionDigits:d}):'—',price=formatPrice,pct=n=>finite(n)?(n>0?'+':'')+fmt(n)+'%':'—';
  function metricText(v){return v===null?'—':metric==='turnover'?fmt(v/1e6,1)+' млн':metric==='trades24'?fmt(v,0):fmt(v,2)+'%';}
  function render(){const now=Date.now()/1000,rows=selectedRows(),quoteOK=catalog?.status==='ok'&&!catalog.stale&&!catalog.refresh_error&&fresh(catalog.updated,now,60)&&fresh(catalog.source_ts??catalog.updated,now,60),keep=new Set(rows.map(r=>r.symbol));
   notice.textContent=catalogError||(!quoteOK?'Котировки недоступны · последние данные сохранены':EXCHANGES[exchange]+' · '+new Date(catalog.updated*1000).toLocaleTimeString('ru-RU')+' · порядок закреплён');notice.dataset.status=quoteOK?'ok':'unavailable';
   const measured=(catalog?.rows||[]).filter(r=>metricValue(r,metric,packets,exchange,now)!==null).length;const confirmed=rows.filter(r=>validChart(packets.get(exchange+':'+r.symbol+':'+interval),exchange,r.symbol,interval,now)).length;coverage.textContent='Графики '+confirmed+' / '+rows.length+' · метрика '+measured+' монет';tiles.dataset.count=count;tiles.querySelector('.chart-grid-empty')?.remove();
   for(const [s,n]of nodes)if(!keep.has(s)){n.widget.dispose();n.box.remove();nodes.delete(s);}
   for(const [i,row]of rows.entries()){
    let n=nodes.get(row.symbol);
    if(!n){
     const box=el('article','chart-tile'),head=el('div','chart-tile-head'),name=button(row.symbol,()=>openChart({exchange,symbol:row.symbol,interval}),'chart-symbol'),star=button('',()=>toggleWatch(row.symbol),'screener-star'),density=button('Плотности',()=>toggleDensity(row.symbol),'screener-order chart-tile-density'),expand=button('',()=>openChart({exchange,symbol:row.symbol,interval}),'chart-expand');
     density.setAttribute('aria-label','Плотности '+EXCHANGES[exchange]+' '+row.symbol);density.title='Плотности этой биржи · от 100 000 USDT, до 5% от цены, до 3 на сторону';
     name.title=row.symbol;expand.append(scope.LabUI.icon('expand'));expand.setAttribute('aria-label','Развернуть');expand.title='Развернуть график';
     const badges=el('div','chart-tile-metrics'),measurement=el('span','chart-measurement'),change=el('span','chart-change');badges.append(measurement,change);head.append(star,name,badges,density,expand);
     const host=el('div','exchange-chart-host'),note=el('p','chart-tile-note muted');host.setAttribute('aria-label','График '+row.symbol+' · '+EXCHANGES[exchange]);
     const densityNote=el('p','chart-tile-density-note muted');densityNote.hidden=true;densityNote.setAttribute('role','status');box.dataset.symbol=row.symbol;box.append(head,host,densityNote,note);n={box,star,density,densityNote,measurement,change,host,note,widget:scope.LabExchangeChart.create(host,{exchange,symbol:row.symbol,interval,volume:false,indicators:false})};nodes.set(row.symbol,n);
    }
    n.star.replaceChildren(scope.LabUI.icon('star'));n.star.classList.toggle('selected',watched(row.symbol));n.star.setAttribute('aria-pressed',String(watched(row.symbol)));n.star.setAttribute('aria-label',(watched(row.symbol)?'Убрать ':'Наблюдать ')+EXCHANGES[exchange]+' '+row.symbol);
    n.change.textContent=quoteOK?pct(row.change24):'—';n.change.title='Изменение за 24 часа';n.change.className='chart-change '+(quoteOK?(row.change24>=0?'positive':'negative'):'muted');
    const value=metricValue(row,metric,packets,exchange,now),shortLabel={turnover:'Оборот',natr5_14:'NATR',natr1_30:'NATR',change24:'24ч',change5:'5м',trades24:'Сделки'};
    n.measurement.title=metricLabels[metric];n.measurement.textContent=shortLabel[metric]+(metric==='turnover'&&row.turnover_estimated?' ≈':'')+': '+(['turnover','change24','trades24'].includes(metric)&&!quoteOK?'—':metricText(value));
    const p=packets.get(exchange+':'+row.symbol+':'+interval),ok=validChart(p,exchange,row.symbol,interval,now);n.box.dataset.status=ok?'ok':'unavailable';
    n.note.textContent=chartStatus(p,exchange,row.symbol,interval,ok);
    const overlays=densitySettings(row.symbol,now);renderDensity(n,row.symbol,overlays,now);n.widget.setPacket(p||{exchange,symbol:row.symbol,interval,status:'pending',candles:[]},{confirmed:ok,updating:awaitingClose(p,exchange,row.symbol,interval,now),...overlays,volume:false,indicators:false});if(tiles.children[i]!==n.box)tiles.insertBefore(n.box,tiles.children[i]||null);
   }
   if(!rows.length)tiles.append(el('p','chart-grid-empty',catalog?'Нет монет по этим условиям. Измените поиск или добавьте монеты в наблюдение.':'Ждём публичные данные биржи…'));syncStreams();syncDensityScope();renderLive();
  }
  let lastCatalog=0,lastCatalogExchange='';
  async function loadCatalog(force=false){if(busy||!visible()||!force&&lastCatalogExchange===exchange&&Date.now()-lastCatalog<5000)return;busy=true;lastCatalog=Date.now();lastCatalogExchange=exchange;const e=exchange,g=requestGeneration;try{const p=await scope.labJson('/api/exchange-screener?'+new URLSearchParams({exchange:e}),{fresh:force},'Список биржи');if(e!==exchange||g!==requestGeneration)return;if(p.exchange!==e||!Array.isArray(p.rows))throw Error('Некорректный список биржи');catalog=p;catalogError=p.status==='ok'?'':'Биржа недоступна · повторяем запрос';}catch(err){if(g===requestGeneration)catalogError=err.message;}finally{busy=false;render();pump();}}
  function chartStatus(packet,e,s,i,ok=validChart(packet,e,s,i)){
   if(ok)return (packet.refreshing?'Проверяем обновление · ':'Свечи подтверждены · ')+new Date(packet.updated*1000).toLocaleTimeString('ru-RU');
   const key=e+':'+s+':'+i,error=failures.get(key)||packet?.refresh_error||packet?.error;
   if(error)return 'Нет свежего подтверждения · '+String(error).slice(0,160)+' · повторяем запрос';
   if(awaitingClose(packet,e,s,i))return 'Свеча закрылась · получаем новый снимок';
   if(packet?.candles?.length)return (packet.candle_end!==Math.floor((Date.now()/1000-2)/PERIODS[i])*PERIODS[i]?'Ждём новую закрытую свечу':'Проверяем актуальность свечей')+' · последний график не подтверждён';
   return inFlight.has(key)||packet?.pending?'Загружаем свечи '+EXCHANGES[e]+'…':'Свечи в очереди загрузки…';
  }
  async function requestChart(e,s,i){
   const key=e+':'+s+':'+i;if(inFlight.has(key))return;inFlight.add(key);attempts.set(key,Date.now());chartsBusy++;
   try{let p=await scope.labJson('/api/exchange-chart?'+new URLSearchParams({exchange:e,symbol:s,interval:i}),{fresh:forced.delete(key)},'Свечи');
    if(p.exchange!==e||p.symbol!==s||p.interval!==i)throw Error('Ответ другой монеты или биржи');
    failures.delete(key);const prior=packets.get(key);if(!validChart(p,e,s,i)&&prior?.candles?.length)p={...prior,status:p.status==='pending'?'pending':'unavailable',stale:true,pending:p.pending,refreshing:p.refreshing,error:p.error||p.refresh_error||'',refresh_error:p.refresh_error,refresh_reason:p.refresh_reason,retry_after_seconds:p.retry_after_seconds,next_refresh_at:p.next_refresh_at};
    packets.delete(key);packets.set(key,p);while(packets.size>60)packets.delete(packets.keys().next().value);
   }catch(error){failures.set(key,error.message||'Биржа не ответила');const p=packets.get(key);if(p)packets.set(key,{...p,status:'unavailable'});}
   finally{chartsBusy--;inFlight.delete(key);if(visible())render();if(dialog.open)renderDialog();pump();}
  }
  function pump(){
   if(document.hidden)return;
   const jobs=new Map(),now=Date.now();
   const add=(e,s,i,priority)=>{const key=e+':'+s+':'+i,p=packets.get(key);if(inFlight.has(key))return;const valid=validChart(p,e,s,i);if(!forced.has(key)&&!refreshDue(p,e,s,i,(attempts.get(key)||0)/1000,now/1000,failures.has(key)))return;const rank=priority+(valid?3:0);if(!jobs.has(key)||rank<jobs.get(key).priority)jobs.set(key,{e,s,i,priority:rank,last:attempts.get(key)||0});};
   if(dialog.open&&detail)add(detail.exchange,detail.symbol,detail.interval,0);
   if(visible()){
    const selected=selectedRows();for(const r of selected)add(exchange,r.symbol,interval,1);
    const m=metric==='natr5_14'?'5':(['natr1_30','change5'].includes(metric)?'1':null);if(m&&m!==interval)for(const r of selected)add(exchange,r.symbol,m,2);
   }
   for(const {e,s,i}of [...jobs.values()].sort((a,b)=>a.priority-b.priority||a.last-b.last)){if(chartsBusy>=2)break;requestChart(e,s,i);}
  }
  const dialog=el('dialog','exchange-chart-dialog'),dialogHead=el('div','exchange-chart-heading'),dialogTitle=el('h2'),close=button('Закрыть',()=>dialog.close()),dialogFrames=el('div','screener-timeframes'),dialogHost=el('div','exchange-chart-host exchange-chart-detail'),dialogNote=el('p','muted'),dialogTools=el('div','exchange-chart-tools'),tableLink=button('Анализ Bybit и риск',()=>{if(detail?.exchange==='bybit'){dialog.close();setView('table');document.dispatchEvent(new CustomEvent('lab-coin',{detail:{symbol:detail.symbol}}));}});
  let volumeVisible=false,indicatorsVisible=false;
  const volumeToggle=button('Объём',()=>{volumeVisible=!volumeVisible;renderDialog();}),indicatorsToggle=button('EMA / VWAP',()=>{indicatorsVisible=!indicatorsVisible;renderDialog();});
  volumeToggle.setAttribute('aria-pressed','false');indicatorsToggle.setAttribute('aria-pressed','false');
  const zoomIn=button('',()=>dialogWidget.zoom(.75),'chart-tool'),zoomOut=button('',()=>dialogWidget.zoom(1.3),'chart-tool'),reset=button('К последним свечам',()=>dialogWidget.reset()),fitLevels=button('Показать уровни',()=>dialogWidget.fitLevels());
  zoomIn.append(scope.LabUI.icon('zoom-in'));zoomIn.setAttribute('aria-label','Приблизить график');zoomOut.append(scope.LabUI.icon('zoom-out'));zoomOut.setAttribute('aria-label','Отдалить график');dialogTools.append(volumeToggle,indicatorsToggle,zoomIn,zoomOut,reset,fitLevels);
  dialogTitle.id='exchange-chart-title';dialog.setAttribute('aria-labelledby',dialogTitle.id);dialogHead.append(dialogTitle,close);dialog.append(dialogHead,dialogFrames,dialogTools,dialogHost,dialogNote,tableLink);document.body.append(dialog);
  let detail=null,returnFocus=null;const dialogWidget=scope.LabExchangeChart.create(dialogHost,{symbol:'BTCUSDT',exchange:'bybit',interval:'5',volume:false,indicators:false,onPriceClick:value=>levelTools.placePrice(value)});const levelTools=scope.LabChartLevels.create({tools:dialogTools,after:dialogHost,widget:dialogHost,onChange:renderDialog});
  const streamDisabled=document.body.dataset.demo==='true',stream=scope.LabChartStream.create({disabled:streamDisabled,onUpdate:renderLive});let streamIdentity='';
  function syncStreams(){
   const wanted=[];
   const add=(e,s,i,row)=>{const packet=packets.get(e+':'+s+':'+i),native=row?.native_symbol||packet?.native_symbol,source={exchange:e,symbol:s,interval:i,native_symbol:native};if(scope.LabChartStream.validSource(source))wanted.push(source);};
   if(!document.hidden){if(visible())for(const row of selectedRows())add(exchange,row.symbol,interval,row);if(dialog.open&&detail){const row=catalog?.exchange===detail.exchange?catalog.rows?.find(r=>r.symbol===detail.symbol):null;add(detail.exchange,detail.symbol,detail.interval,row);}}
   const identity=wanted.map(s=>scope.LabChartStream.keyOf(s)).sort().join('|');if(identity===streamIdentity)return;streamIdentity=identity;stream.setSources(wanted);
  }
  function renderLive(){
   const note=(p,e,s,i,live)=>{const text=chartStatus(p,e,s,i);if(streamDisabled||!live)return text;const sample=live.quote||live.candle;return text+' · '+(sample?'Поток '+new Date((sample.source_ts??sample.received_at)*1000).toLocaleTimeString('ru-RU'):live.status==='connecting'?'Подключаем поток…':'Поток недоступен · проверяем через API');};
   for(const [symbol,n]of nodes){const live=visible()?stream.get({exchange,symbol,interval}):null;n.widget.setLive(live);n.box.dataset.stream=streamDisabled?'disabled':live?.status||'unavailable';n.note.textContent=note(packets.get(exchange+':'+symbol+':'+interval),exchange,symbol,interval,live);}
   if(dialog.open&&detail){const live=document.hidden?null:stream.get(detail);dialogWidget.setLive(live);dialogNote.textContent=note(packets.get(detail.exchange+':'+detail.symbol+':'+detail.interval),detail.exchange,detail.symbol,detail.interval,live);}
  }
  for(const [i,label]of [['1','1м'],['5','5м'],['15','15м'],['60','1ч'],['240','4ч'],['1440','1д']]){const b=button(label,()=>{detail.interval=i;renderDialog();syncStreams();renderLive();pump();});b.dataset.interval=i;dialogFrames.append(b);}
  function openChart(d){if(!d||!Object.hasOwn(EXCHANGES,d.exchange)||!symbolOK(d.symbol))return;detail={exchange:d.exchange,symbol:d.symbol,interval:Object.hasOwn(PERIODS,d.interval)?d.interval:'5',density:d.density};returnFocus=document.activeElement;if(!dialog.open)dialog.showModal();syncDensityScope();document.dispatchEvent(new CustomEvent('lab-chart-overlay',{detail:{open:true}}));levelTools.open({...detail,isOpen:()=>dialog.open});renderDialog();pump();syncStreams();}
  function renderDialog(){if(!detail||!dialog.open)return;const p=packets.get(detail.exchange+':'+detail.symbol+':'+detail.interval),ok=validChart(p,detail.exchange,detail.symbol,detail.interval);dialog.dataset.exchange=detail.exchange;dialog.dataset.symbol=detail.symbol;dialogTitle.textContent=EXCHANGES[detail.exchange]+' · '+detail.symbol;dialogHost.setAttribute('aria-label','Свечи '+detail.symbol+' на '+EXCHANGES[detail.exchange]);dialogNote.textContent=chartStatus(p,detail.exchange,detail.symbol,detail.interval,ok);dialogNote.dataset.status=ok?'ok':'unavailable';tableLink.hidden=detail.exchange!=='bybit'||!/^[A-Z0-9]{2,24}USDT$/.test(detail.symbol);for(const b of dialogFrames.children){const selected=b.dataset.interval===detail.interval;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',String(selected));}volumeToggle.setAttribute('aria-pressed',String(volumeVisible));volumeToggle.classList.toggle('selected',volumeVisible);indicatorsToggle.setAttribute('aria-pressed',String(indicatorsVisible));indicatorsToggle.classList.toggle('selected',indicatorsVisible);dialogWidget.setPacket(p||{exchange:detail.exchange,symbol:detail.symbol,interval:detail.interval,candles:[]},{confirmed:ok,updating:awaitingClose(p,detail.exchange,detail.symbol,detail.interval),...levelTools.settings(),volume:volumeVisible,indicators:indicatorsVisible});}
  dialog.addEventListener('close',()=>{levelTools.close();detail=null;syncStreams();dialogWidget.setLive(null);document.dispatchEvent(new CustomEvent('lab-chart-overlay',{detail:{open:false}}));syncDensityScope();returnFocus?.focus();});window.addEventListener('lab-exchange-chart',e=>openChart(e.detail));document.addEventListener('lab-exchange-chart',e=>openChart(e.detail));
  for(const input of [exchangeInput,frameInput,metricInput,countInput])input.addEventListener('change',()=>{const e=exchangeInput.value;if(e!==exchange){exchange=e;catalog=null;catalogError='';for(const n of nodes.values())n.widget.dispose();nodes.clear();tiles.replaceChildren();requestGeneration++;}interval=frameInput.value;metric=metricInput.value;count=Number(countInput.value);order=[];save();render();loadCatalog();pump();});search.addEventListener('input',()=>{search.value=search.value.toUpperCase().replace(/[^A-Z0-9]/g,'');order=[];render();pump();});controls.addEventListener('submit',e=>{e.preventDefault();order=[];render();pump();});
  document.addEventListener('lab-selection-changed',()=>{if(visible())render();});document.addEventListener('lab-screener-table',()=>setView('table'));document.addEventListener('lab-tab',()=>{if(visible()){render();loadCatalog();pump();}syncStreams();syncDensityScope();renderLive();});document.addEventListener('visibilitychange',()=>{if(visible()){render();loadCatalog();pump();}syncStreams();syncDensityScope();renderLive();});setInterval(()=>{if(visible()){render();loadCatalog();pollDensity();}if(!document.hidden&&(visible()||dialog.open))pump();if(!document.hidden&&dialog.open){levelTools.render();levelTools.poll();renderDialog();syncStreams();renderLive();}},1000);window.addEventListener('pagehide',()=>{pageSuspended=true;syncDensityScope();streamIdentity='';stream.setSources([]);renderLive();});window.addEventListener('pageshow',()=>{pageSuspended=false;syncStreams();syncDensityScope();renderLive();});setView(view);
 });
})(typeof window==='undefined'?globalThis:window);
