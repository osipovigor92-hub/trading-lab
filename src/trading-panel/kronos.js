/* Optional Kronos screener. Only the explicit batch action admits model work. */
(function(scope){
 'use strict';
 const LIMIT=15,HORIZON=6,SCENARIOS=5,PERIODS=new Set(['1','5','15','60','240','1440']),EXCHANGES=new Set(['bybit','binance','okx','gate','bitget']);
 const finite=n=>typeof n==='number'&&Number.isFinite(n),positive=n=>finite(n)&&n>0;
 const symbolOK=s=>typeof s==='string'&&/^[A-Z0-9]{1,28}USDT$/.test(s),hashOK=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
 const nativeSymbol=(exchange,symbol)=>exchange==='okx'?symbol.slice(0,-4)+'-USDT-SWAP':exchange==='gate'?symbol.slice(0,-4)+'_USDT':symbol;
 const textError=value=>typeof value==='string'&&value.trim()?value.replace(/[\u0000-\u001f\u007f]/g,' ').replace(/\s+/g,' ').trim().slice(0,180):'Сервис не ответил.';
 const requestError=(message,status)=>Object.assign(Error(textError(message)),{kronosRequestError:true,httpStatus:status});
 const requestFailure=error=>error?.name==='AbortError'?'Время запроса истекло.':error?.kronosRequestError?textError(error.message):'Сетевая ошибка: не удалось связаться с панелью.';
 async function readResponse(response){
  // Keep the HTTP status even when a proxy returns HTML or an empty body.
  if(!response.ok){let value;try{value=JSON.parse(await response.text());}catch(error){}const supplied=value&&typeof value==='object'&&!Array.isArray(value)?value.error||value.message:null,standard={400:'Некорректные параметры запроса.',401:'Требуется авторизация.',403:'Доступ к запросу отклонён.',404:'Маршрут Kronos не найден.',405:'Метод запроса не разрешён.',502:'Промежуточный сервер не получил ответ панели.',503:'Сервис временно недоступен.',504:'Промежуточный сервер не дождался ответа.'}[response.status]||'Запрос завершился ошибкой.';throw requestError('HTTP '+response.status+' · '+(typeof supplied==='string'&&supplied.trim()?supplied:standard),response.status);}
  const raw=await response.text();let value;try{value=JSON.parse(raw);}catch(error){throw requestError('Сервис вернул некорректный JSON.');}
  if(!value||typeof value!=='object'||Array.isArray(value))throw requestError('Некорректный ответ Kronos.');return value;
 }
 function candidatePage(exchange,interval,symbols,page=0){
  const empty={candidates:[],symbols:[],total:0,pages:0,page:0,from:0,to:0};
  if(!EXCHANGES.has(exchange)||!PERIODS.has(String(interval))||!Array.isArray(symbols)||!Number.isSafeInteger(page)||page<0)return empty;
  const unique=[...new Set(symbols.filter(symbolOK))],total=unique.length,pages=Math.ceil(total/LIMIT),start=page*LIMIT,selected=unique.slice(start,start+LIMIT);
  return {candidates:selected.map(symbol=>({exchange,symbol,interval:String(interval)})),symbols:unique,total,pages,page,from:selected.length?start+1:0,to:selected.length?start+selected.length:0};
 }
 const candidates=(exchange,interval,symbols,page=0)=>candidatePage(exchange,interval,symbols,page).candidates;
 const sourceKey=source=>source?[source.exchange,source.symbol,source.interval].join(':'):'';
 function currentSource(source,expected,now=Date.now()/1000){
  if(!source||sourceKey(source)!==sourceKey(expected)||!EXCHANGES.has(source.exchange)||!symbolOK(source.symbol)||!PERIODS.has(source.interval)||source.native_symbol!==nativeSymbol(source.exchange,source.symbol)||!hashOK(source.input_hash))return false;
  const step=Number(source.interval)*60;
  return finite(now)&&positive(source.candle_end)&&Number.isInteger(source.candle_end)&&source.candle_end===Math.floor((now-2)/step)*step&&positive(source.updated)&&source.updated<=now+2;
 }
 const binding=packet=>packet?.source?[sourceKey(packet.source),packet.source.candle_end,packet.source.input_hash,packet.model_revision,packet.tokenizer_revision,packet.code_revision||'',packet.job_id||''].join('|'):'';
 function validReady(packet,expected,now=Date.now()/1000,expectedBinding=''){
  if(!packet||packet.status!=='ready'||packet.enabled!==true||packet.demo===true||packet.device!=='cpu'||!['Kronos-mini','NeoQuasar/Kronos-mini'].includes(packet.model)||!hashOK(packet.source?.input_hash)||!currentSource(packet.source,expected,now)||expectedBinding&&binding(packet)!==expectedBinding)return false;
  const proof=packet.current_source_updated??packet.source.updated,expiry=packet.source.candle_end+Number(expected.interval)*60+2;
  if(!positive(proof)||now-proof>75||proof>now+2||packet.expires_at!=null&&packet.expires_at!==expiry||now>=expiry)return false;
  if(typeof packet.model_revision!=='string'||!packet.model_revision||typeof packet.tokenizer_revision!=='string'||!packet.tokenizer_revision||packet.horizon!==HORIZON||packet.scenarios!==SCENARIOS||!finite(packet.inference_ms)||packet.inference_ms<0||!positive(packet.input_last_close)||!Array.isArray(packet.end_close_samples)||packet.end_close_samples.length!==SCENARIOS||!packet.end_close_samples.every(positive)||!Array.isArray(packet.forecast)||packet.forecast.length!==HORIZON)return false;
  const step=Number(expected.interval)*60;
  if(!packet.forecast.every((bar,i)=>bar&&bar.time===packet.source.candle_end+i*step&&positive(bar.low)&&positive(bar.median)&&positive(bar.high)&&bar.low<=bar.median&&bar.median<=bar.high))return false;
  const end=packet.forecast.at(-1),sorted=packet.end_close_samples.slice().sort((a,b)=>a-b),same=(a,b)=>Math.abs(a-b)<=Math.max(1,Math.abs(a),Math.abs(b))*1e-10;
  return same(end.low,sorted[0])&&same(end.median,sorted[2])&&same(end.high,sorted[4]);
 }
 function measure(packet){
  const base=packet.input_last_close,end=packet.forecast.at(-1),change=(end.median/base-1)*100,sign=Math.sign(change),agreement=packet.end_close_samples.filter(close=>Math.sign(close-base)===sign).length;
  return {packet,source:packet.source,symbol:packet.source.symbol,change,low:(end.low/base-1)*100,high:(end.high/base-1)*100,agreement};
 }
 function rank(rows,direction='growth',agreedOnly=false){
  return rows.filter(row=>!agreedOnly||row.agreement>=4).slice().sort((a,b)=>{
   const x=direction==='movement'?Math.abs(a.change):direction==='decline'?-a.change:a.change,y=direction==='movement'?Math.abs(b.change):direction==='decline'?-b.change:b.change;
   return y-x||b.agreement-a.agreement||a.symbol.localeCompare(b.symbol);
  });
 }
 const api={LIMIT,HORIZON,SCENARIOS,candidatePage,candidates,sourceKey,nativeSymbol,currentSource,binding,validReady,measure,rank,readResponse,requestFailure};
 if(typeof module!=='undefined')module.exports=api;if(typeof document==='undefined')return;scope.LabKronos=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-market'),viewbar=page?.querySelector('.screener-viewbar');if(!viewbar)return;
  const el=(tag,cls='',text='')=>{const node=document.createElement(tag);node.className=cls;node.textContent=text;return node;},button=(text,handler,cls='screener-order')=>{const node=el('button',cls,text);node.type='button';node.addEventListener('click',handler);return node;};
  const demo=document.body.dataset.demo==='true',panel=el('details','kronos-panel');panel.id='kronos-screener';
  const summary=el('summary','kronos-summary'),title=el('strong','','Kronos · Отбор монет'),badge=el('span','kronos-summary-note muted',demo?'Kronos выключен в демо':'До 15 монет · 6 свечей');summary.append(title,badge);panel.append(summary);viewbar.after(panel);
  const content=el('div','kronos-content'),toolbar=el('div','kronos-toolbar'),sourceLine=el('p','kronos-source muted'),start=button('Оценить монеты',run,'primary-button'),stop=button('Остановить отбор',()=>cancel('Отбор остановлен.',false));stop.hidden=true;
  const selectionBar=el('div','kronos-selection'),pages=el('div','kronos-pages'),previous=button('Предыдущие 15',()=>changePage(-1)),next=button('Оценить следующие 15',()=>changePage(1,true));pages.setAttribute('role','group');pages.setAttribute('aria-label','Группы монет Kronos');pages.append(previous,next);selectionBar.append(sourceLine,pages);
  const controls=el('div','kronos-controls'),sortLabel=el('label','','Отбор по'),sort=el('select');sort.setAttribute('aria-label','Порядок отбора Kronos');for(const [value,text]of [['growth','Росту модели'],['decline','Снижению модели'],['movement','Величине движения']]){const option=el('option','',text);option.value=value;sort.append(option);}sortLabel.append(sort);
  const agreeLabel=el('label','kronos-agree'),agree=el('input');agree.type='checkbox';agree.setAttribute('aria-label','Совпадение направления минимум 4 из 5');agreeLabel.append(agree,el('span','','Направление ≥4 из 5'));controls.append(sortLabel,agreeLabel);toolbar.append(start,stop,controls);
  const progress=el('p','kronos-progress muted');progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');progress.textContent=demo?'Kronos выключен в демо.':'Откройте панель и запустите оценку выбранных монет.';
  const scroll=el('div','kronos-table-scroll');scroll.setAttribute('tabindex','0');scroll.setAttribute('aria-label','Результаты отбора Kronos');scroll.hidden=true;
  const table=el('table','kronos-table');table.setAttribute('aria-label','Завершённые оценки Kronos');const head=el('thead'),headRow=el('tr');for(const text of ['Монета','Медиана, 6 свечей','Разброс сценариев','Направление','Закрытие · UTC','Расчёт']){const cell=el('th','',text);cell.scope='col';headRow.append(cell);}head.append(headRow);const tbody=el('tbody');table.append(head,tbody);scroll.append(table);
  const empty=el('p','kronos-empty muted');empty.hidden=true;
  const note=el('p','kronos-note muted','Медиана и минимум–максимум 5 сценариев Kronos-mini на 6 свечей. Совпадение направления — число сценариев, а не вероятность. Результат модели служит для сравнения монет; торговое решение остаётся за вами.');
  const metadata=el('p','kronos-metadata muted');metadata.hidden=true;content.append(selectionBar,toolbar,progress,scroll,empty,note,metadata);panel.append(content);
  let generation=0,pageIndex=0,snapshot=null,worker=null,lastStatus=0,statusPromise=null,rows=new Map(),active=null,running=false,completed=0,total=0,failures=0,failureNotes=[],retired=0,readController=null,statusController=null,timer=null,suspended=false,cacheBusy=false,cacheCursor=0;
  const visible=()=>!suspended&&!document.hidden&&!page.hidden&&panel.open;
  const displayNames={bybit:'Bybit',binance:'Binance',okx:'OKX',gate:'Gate',bitget:'Bitget'},periodNames={'1':'1м','5':'5м','15':'15м','60':'1ч','240':'4ч','1440':'1д'};
  function selection(){
   const chartView=page.classList.contains('chart-grid-active'),exchange=chartView?page.querySelector('[aria-label="Биржа графиков"]')?.value:'bybit',interval=chartView?page.querySelector('[aria-label="Период графиков"]')?.value:'5',nodes=page.querySelectorAll(chartView?'.chart-grid-workspace .chart-tile[data-symbol]':'#screener-table tbody tr[data-symbol]'),symbols=Array.from(nodes).filter(node=>!node.hidden).map(node=>node.dataset.symbol),selected=candidatePage(exchange,interval,symbols,pageIndex);
   const controls=Array.from(page.querySelectorAll(chartView?'.chart-grid-controls input,.chart-grid-controls select,.chart-grid-controls button[aria-pressed]':'.screener-controls input,.screener-controls select,.screener-filter-details input,.screener-meta select,#screener-column-filters input')).map(node=>[node.getAttribute('aria-label')||'',node.value??'',node.getAttribute('aria-pressed')||''].join(':'));
   const scopeIdentity=[chartView?'charts':'table',exchange,interval,...controls,...selected.symbols].join('|');
   return {view:chartView?'charts':'table',exchange,interval,...selected,visible:selected.total,scopeIdentity,identity:scopeIdentity+'|group:'+pageIndex};
  }
  function workerOK(){return !demo&&worker?.enabled===true&&worker.demo!==true&&['idle','ready','queued'].includes(worker.status)&&typeof worker.token==='string'&&worker.token.length>=16;}
  function buttons(){start.disabled=!visible()||!workerOK()||running||!snapshot?.candidates.length;previous.disabled=!visible()||running||!snapshot?.page;next.disabled=!visible()||!workerOK()||running||!snapshot?.pages||snapshot.page+1>=snapshot.pages;stop.hidden=!running;panel.setAttribute('aria-busy',String(running));}
  function sourceText(){sourceLine.textContent=(snapshot?.from?snapshot.from+'–'+snapshot.to:'0')+' из '+(snapshot?.visible||0)+' видимых монет · '+(displayNames[snapshot?.exchange]||'Источник недоступен')+' · '+(periodNames[snapshot?.interval]||'—')+' · горизонт 6 свечей.';}
  function cancel(message,clear=true){generation++;running=false;active=null;readController?.abort();readController=null;if(clear){rows.clear();completed=0;total=0;failures=0;failureNotes=[];retired=0;}if(message)progress.textContent=message;renderResults();buttons();}
  function syncSelection(message='Источник или список монет изменён. Запустите новую оценку.'){let selected=selection();if(snapshot&&snapshot.scopeIdentity!==selected.scopeIdentity){pageIndex=0;selected=selection();}if(snapshot&&snapshot.identity!==selected.identity)cancel(message);snapshot=selected;sourceText();buttons();}
  function changePage(delta,assess=false){if(running||!visible()||!snapshot||assess&&!workerOK())return;const target=pageIndex+delta;if(target<0||target>=snapshot.pages)return;pageIndex=target;syncSelection('Группа монет изменена. Нажмите «Оценить монеты».');if(assess)run();}
  async function json(url,options={}){
   const controller=new AbortController();readController=controller;const timeout=setTimeout(()=>controller.abort(),8000);
   try{return await readResponse(await fetch(url,{...options,cache:'no-store',credentials:'same-origin',signal:controller.signal}));}finally{clearTimeout(timeout);if(readController===controller)readController=null;}
  }
  async function status(force=false){
   if(demo||!visible()||statusPromise||!force&&Date.now()-lastStatus<10000)return statusPromise;
   const mine=generation,controller=new AbortController();statusController=controller;lastStatus=Date.now();const timeout=setTimeout(()=>controller.abort(),8000);
   statusPromise=(async()=>{try{const response=await fetch('/api/kronos/status',{cache:'no-store',credentials:'same-origin',signal:controller.signal}),value=await readResponse(response);if(typeof value.enabled!=='boolean')throw requestError('Некорректный статус Kronos.');if(!visible()||mine!==generation)return;worker=value;badge.textContent=workerOK()?'Kronos-mini · CPU':worker.status==='loading'?'Kronos загружается':'Kronos не подключён';if(!running&&!rows.size&&!total)progress.textContent=workerOK()?'Готов к оценке. Нажмите «Оценить монеты».':worker.status==='loading'?'Модель загружается. Оценка станет доступна после запуска.':'Kronos не подключён. Запуск расчёта недоступен.';if(!workerOK()&&running)cancel('Kronos недоступен. Повторите оценку после подключения.');}catch(error){if(mine!==generation||!visible())return;worker=null;badge.textContent='Статус Kronos не проверен';const reason='Не удалось проверить Kronos: '+requestFailure(error);if(running)cancel(reason);else progress.textContent=reason;}finally{clearTimeout(timeout);if(statusController===controller)statusController=null;statusPromise=null;buttons();}})();return statusPromise;
  }
  const pct=value=>(value>0?'+':'')+value.toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'%';
  const utc=stamp=>new Date(stamp*1000).toLocaleString('ru-RU',{timeZone:'UTC',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).replace(',', '');
  function renderResults(){
   const now=Date.now()/1000;for(const [key,row]of rows)if(!validReady(row.packet,row.source,now,row.binding)){rows.delete(key);retired++;}
   const ranked=rank([...rows.values()],sort.value,agree.checked);tbody.replaceChildren();for(const row of ranked){const tr=el('tr');tr.dataset.symbol=row.symbol;tr.dataset.inputHash=row.source.input_hash;tr.dataset.change=String(row.change);
    const coin=el('td');coin.append(el('strong','',row.symbol.replace(/USDT$/,'')),el('small','muted',' / USDT'));const median=el('td',row.change>0?'positive':row.change<0?'negative':'',pct(row.change)),spread=el('td','',pct(row.low)+' … '+pct(row.high)),agreement=el('td','',row.agreement+' из 5'),close=el('td','',utc(row.source.candle_end)),inference=el('td','',(row.packet.inference_ms/1000).toLocaleString('ru-RU',{maximumFractionDigits:1})+' с');close.title='Источник получен '+utc(row.source.updated)+' UTC';tr.append(coin,median,spread,agreement,close,inference);tbody.append(tr);
   }scroll.hidden=!ranked.length;empty.hidden=!!ranked.length||!rows.size;empty.textContent='Нет завершённых оценок с совпадением направления ≥4 из 5. Снимите фильтр.';
   metadata.hidden=!rows.size;if(rows.size){const packet=rows.values().next().value.packet;metadata.textContent='Kronos-mini · CPU · модель '+packet.model_revision.slice(0,8)+' · токенизатор '+packet.tokenizer_revision.slice(0,8)+' · 5 сценариев. Изменение от закрытия входной свечи.';}
   if(!running&&retired&&!rows.size&&total)progress.textContent='Оценки потеряли текущее подтверждение данных. Запустите новый отбор.';
  }
  function progressText(){const base='Завершено '+completed+' / '+total;return base+(active?' · '+active.source.symbol.replace('USDT','')+' · '+active.label:'')+(failures?' · недоступно '+failures:'')+(retired?' · устарело '+retired:'');}
  function fail(message){failures++;failureNotes.push((active?.source.symbol.replace('USDT','')||'Монета')+' · '+message);active=null;progress.textContent=progressText()+' · '+message;}
  async function run(){
   syncSelection();if(!visible()||!workerOK()||running||!snapshot.candidates.length)return;
   cancel('',true);const mine=generation,identity=snapshot.identity,queue=snapshot.candidates.slice();total=queue.length;running=true;buttons();progress.textContent='Подготовка '+total+' монет…';
   const valid=()=>mine===generation&&visible()&&snapshot.identity===identity;
   for(const source of queue){
    if(!valid())break;active={source,label:'проверяем закрытые свечи',binding:'',started:Date.now(),pendingStart:Date.now(),lastPacket:null,submissions:1,warming:false};progress.textContent=progressText();let packet;
    try{packet=await json('/api/kronos/forecast',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':worker.token},body:JSON.stringify(source)});}catch(error){if(!valid())break;fail(requestFailure(error));continue;}
    if(!valid())break;active.modelStarting=packet.status==='loading'&&packet.accepted===false;active.warming=packet.status==='pending'||active.modelStarting;
    while(valid()){
     if(packet.status==='ready'){
      if(validReady(packet,source,Date.now()/1000,active.binding)){const row=measure(packet);row.binding=binding(packet);rows.set(sourceKey(source),row);completed++;active=null;renderResults();progress.textContent=progressText();}else fail('Ответ модели не подтверждён для текущих свечей.');break;
     }
     if(packet.demo===true){fail('Kronos не подключён.');break;}
     if(['error','unavailable','stale','disabled','busy'].includes(packet.status)){fail(packet.status==='busy'?'Очередь занята. Повторите оценку.':textError(packet.error||'Оценка недоступна.'));break;}
     if(packet.enabled===false&&packet.status!=='pending'&&!(packet.status==='idle'&&active.warming)){fail('Kronos не подключён.');break;}
     if(!['queued','loading','pending','idle'].includes(packet.status)){fail('Некорректный статус оценки.');break;}
     if(packet.source){if(!currentSource(packet.source,source)||active.binding&&binding(packet)!==active.binding){fail('Закрытые свечи изменились. Повторите оценку.');break;}if(['queued','loading'].includes(packet.status)&&packet.job_id&&packet.accepted!==false)active.binding=binding(packet);}
     if(Date.now()-active.started>150000||['pending','idle'].includes(packet.status)&&Date.now()-active.pendingStart>30000){fail('Оценка не завершена. Повторите её вручную.');break;}
     if(packet.status==='idle'&&active.modelStarting){
      try{const state=await json('/api/kronos/status');if(!valid())break;worker=state;active.modelStarting=state.status!=='idle';if(active.modelStarting)packet={...packet,status:'pending',enabled:true};}catch(error){if(!valid())break;fail(requestFailure(error));break;}
     }
     if(packet.status==='idle'&&active.warming&&active.submissions===1&&currentSource(packet.source,source)){
      active.submissions++;active.warming=false;active.label='запускаем оценку';progress.textContent=progressText();
      try{packet=await json('/api/kronos/forecast',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':worker.token},body:JSON.stringify(source)});}catch(error){if(!valid())break;fail(requestFailure(error));break;}
      if(!valid())break;continue;
     }
     active.label=active.modelStarting?'модель загружается':packet.status==='queued'?'в очереди':packet.status==='loading'?'считаем 5 сценариев':'ждём подтверждённые свечи';active.lastPacket=packet;progress.textContent=progressText();
     await refreshCached();if(!valid())break;await new Promise(resolve=>setTimeout(resolve,2000));if(!valid())break;
     // Ordinary chart reads schedule bounded REST revalidation; model GETs only read its proof.
     try{await json('/api/exchange-chart?'+new URLSearchParams(source));if(!valid())break;packet=await json('/api/kronos/forecast?'+new URLSearchParams(source));}catch(error){if(!valid())break;fail(requestFailure(error));break;}
    }
   }
   if(valid()){running=false;active=null;renderResults();progress.textContent=progressText()+'.'+(failureNotes.length?' '+failureNotes.slice(0,2).join('; ')+(failureNotes.length>2?'…':''):'')+(completed?'':' Завершённых оценок нет.');buttons();}
  }
  async function refreshCached(){
   if(!visible()||cacheBusy||readController||!rows.size)return;const mine=generation;cacheBusy=true;
   // Two sequential rows keep fifteen results within the existing 75s proof
   // while the 30s chart TTL revalidates asynchronously; model GET never renews it.
   try{for(let count=0,limit=Math.min(2,rows.size);count<limit;count++){
    if(mine!==generation||!visible()||readController||!rows.size)return;const keys=[...rows.keys()],key=keys[cacheCursor++%keys.length],row=rows.get(key);
    try{const query=new URLSearchParams({exchange:row.source.exchange,symbol:row.source.symbol,interval:row.source.interval});await json('/api/exchange-chart?'+query);if(mine!==generation||!visible())return;const packet=await json('/api/kronos/forecast?'+query);if(mine!==generation||!visible())return;if(validReady(packet,row.source,Date.now()/1000,row.binding)){const refreshed=measure(packet);refreshed.binding=row.binding;rows.set(key,refreshed);}else{rows.delete(key);retired++;}renderResults();}catch(error){if(mine===generation&&visible()){rows.delete(key);retired++;renderResults();if(!running)progress.textContent='Подтверждение оценки недоступно. Запустите отбор повторно.';}}
   }}finally{cacheBusy=false;}
  }
  function tick(){if(!visible())return;syncSelection();renderResults();if(!running){status();refreshCached();}}
  panel.addEventListener('toggle',()=>{if(panel.open){syncSelection();if(demo)progress.textContent='Kronos выключен в демо.';else status(true);timer??=setInterval(tick,2000);}else{clearInterval(timer);timer=null;statusController?.abort();if(running||rows.size)cancel('Панель закрыта. Запустите новый отбор после открытия.');}buttons();});
  sort.addEventListener('change',renderResults);agree.addEventListener('change',renderResults);
  const scopeChange=()=>{syncSelection();if(!visible()){statusController?.abort();if(running||rows.size)cancel('Отбор остановлен при смене страницы. Запустите его повторно.');}else status();};
  for(const event of ['lab-screener-view','lab-tab','lab-selection-changed'])document.addEventListener(event,scopeChange);
  document.addEventListener('visibilitychange',()=>{if(document.hidden){statusController?.abort();cancel('Отбор остановлен, пока страница скрыта. Запустите его повторно.');}else scopeChange();});
  page.addEventListener('change',event=>{if(!panel.contains(event.target))syncSelection();});page.addEventListener('input',event=>{if(!panel.contains(event.target))queueMicrotask(syncSelection);});page.addEventListener('click',event=>{if(!panel.contains(event.target))queueMicrotask(syncSelection);});
  const observer=new MutationObserver(()=>{if(visible())syncSelection();});for(const node of page.querySelectorAll('.chart-tiles,#screener-table tbody'))observer.observe(node,{childList:true,attributes:true,attributeFilter:['data-symbol','hidden']});
  window.addEventListener('pagehide',()=>{suspended=true;statusController?.abort();cancel('',true);clearInterval(timer);timer=null;});window.addEventListener('pageshow',()=>{suspended=false;if(panel.open){timer??=setInterval(tick,2000);scopeChange();}});
  syncSelection();buttons();
 });
})(typeof window!=='undefined'?window:globalThis);
