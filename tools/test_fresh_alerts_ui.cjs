const {resetFavorites}=require('./ui_favorites.cjs');
/* Offline transition feed, source failures, reload and request-generation checks. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18796;
const allWidths=[1280,390,320],widths=process.env.ALERT_TEST_WIDTHS?process.env.ALERT_TEST_WIDTHS.split(',').map(Number):allWidths;
assert.ok(widths.length&&new Set(widths).size===widths.length&&widths.every(width=>allWidths.includes(width)),'ALERT_TEST_WIDTHS must select unique supported widths');
async function until(fn,label='condition'){const end=Date.now()+15000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('Fresh alerts: '+label+' was not met');}
const labels={ready:'Кандидат готов',almost:'Почти готов',cancelled:'Условие отменено',book_worse:'Стакан ухудшился',near_level:'Цена у уровня'};
const event=(kind,sequence,symbol,now=Date.now()/1000)=>({id:'ui:'+sequence,sequence,symbol,kind,label:labels[kind],detail:kind==='near_level'?'Поддержка 1м: 99,4–99,5 · зона ±0,25 ATR':kind==='ready'?'Все 12 проверок отбора пройдены. Проверьте направление и вход в PAPER-плане.':'Не выполнено: Глубина каждой стороны ±0,1%',score:80,time:now,expires:now+8,sources:{quote:now,chart:now,candle:now-20,book:now,fetched:now},price:100});
const signalLabels={breakout_up:'Пробой вверх',breakout_down:'Пробой вниз',momentum_up:'Импульс вверх',momentum_down:'Импульс вниз'};
function sourceCapture(now){const candle=Math.floor((now-2)/60)*60;return {quote:now,chart:Math.min(now,candle+50),candle};}
function syntheticRecommendation(kind,symbol,sources,deadline=Infinity){
 const direction=kind.endsWith('_up')?'LONG':'SHORT',upward=direction==='LONG',candle_end=sources.candle,boundary=upward?'99.5':'100.5',ordering=upward?'close > EMA20 > EMA50 и close > VWAP60':'close < EMA20 < EMA50 и close < VWAP60';
 const reason=kind.startsWith('breakout_')?'Закрытие 1м 100 '+(upward?'выше ':'ниже ')+boundary+'; RVOL 5/20 2×.':ordering+'; RVOL 5/20 2×; изменение 5м '+(upward?'+0.4':'-0.4')+'%.';
 const invalidation=(kind.startsWith('breakout_')?'Новое закрытие 1м '+(upward?'на уровне или ниже ':'на уровне или выше ')+boundary+'; удаление от исходной границы пробоя больше 1,5 ATR14; RVOL 5/20 ниже 1,5; ':'На новой закрытой свече 1м перестало выполняться '+ordering+'; RVOL 5/20 ниже 1,5; диапазон 5м ниже 0,2%; изменение 5м '+(upward?'ниже +0,1%':'выше −0,1%')+'; измеренное удаление от исходного пробоя больше 1,5 ATR14; ')+'оборот 24ч ниже 20000000 USDT или спред выше 0.03%; нет свежего подтверждения котировки или закрытых свечей.';
 return {direction,timeframe:'1',exchange:'bybit',setup:kind,reason,invalidation,signal_id:[symbol,kind,'1',candle_end].join(':'),candle_end,expires:Math.min(deadline,sources.quote+45,sources.chart+75,candle_end+120)};
}
function signal(kind,sequence,symbol,now){
 const sources=sourceCapture(now),expires=now+24,recommendation=syntheticRecommendation(kind,symbol,sources,expires);
 return {...event('ready',sequence,symbol,now),kind,label:signalLabels[kind],detail:recommendation.reason,sources,expires,exchange:'bybit',interval:'1',timeframe:'1',signal_id:recommendation.signal_id,candle_end:recommendation.candle_end,recommendation};
}
function currentAssistant(kind,symbol,now,mode){
 const sources=sourceCapture(now);if(['stale_signal','stale_current'].includes(mode))sources.chart=now-76;
 const recommendation=syntheticRecommendation(kind,symbol,sources);
 return {status:'ok',eligible:true,exchange:'bybit',timeframe:'1',interval:'1',setup:kind,signal_id:recommendation.signal_id,candle_end:recommendation.candle_end,sources,reasons:[recommendation.reason],recommendation};
}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}/`).then(r=>r.ok).catch(()=>false),'preview');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  for(const width of widths){
   await resetFavorites(`http://127.0.0.1:${port}`);
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[],posts=[],failedRequests=[],scriptResponses=[];let mode='normal',events=Object.keys(labels).map((k,i)=>event(k,i+1,['BTCUSDT','ETHUSDT','SOLUSDT','ONDOUSDT','LINKUSDT'][i])),cursor=5,delay=false,modernPhase=false,clockOffset=0,storageError=false;
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname!=='/api/favorites')posts.push(r.url());});
   page.on('requestfailed',r=>failedRequests.push({url:r.url(),error:r.failure()?.errorText}));page.on('response',r=>{if(r.request().resourceType()==='script')scriptResponses.push({url:r.url(),status:r.status()});});
   await page.addInitScript(()=>{window.alertBeeps=0;window.alertNotifications=[];window.permissionRequests=0;window.alertClockOffset=0;const actualNow=Date.now.bind(Date);Date.now=()=>actualNow()+window.alertClockOffset;
    if(!localStorage.getItem('lab-alert-history-v2'))localStorage.setItem('lab-alert-history-v2',JSON.stringify({events:[{time:Date.now()/1000-300,text:'B · сохранённое наблюдение',tone:'neutral'}],states:[['B:BTCUSDT','entry:LONG']]}));
    window.AudioContext=class {currentTime=0;destination={};resume(){return Promise.resolve();}createOscillator(){return {connect(){},frequency:{value:0},start(){window.alertBeeps++;},stop(){}};}createGain(){return {connect(){},gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}}};}};
    window.Notification=class {static permission='granted';static requestPermission(){window.permissionRequests++;return Promise.resolve('granted');}constructor(title,options){window.alertNotifications.push({title,...options});}close(){}};
   });
   await page.route('**/api/market-alerts?*',async route=>{
    const requestedMode=mode,url=new URL(route.request().url()),scope=url.searchParams.get('rvol_min')==='1.5'?'changed':'default',now=(Date.now()+clockOffset)/1000;
    if(requestedMode==='html')return route.fulfill({contentType:'text/html',body:'<html>unavailable</html>'});
    let outgoing=events.map(e=>({...e,sources:{...e.sources}})),outCursor=cursor;
    if(scope==='changed'){outgoing=[event('ready',20,'ETHUSDT')];outCursor=20;}
    else if(requestedMode==='late'){outgoing=[event('ready',1,'OLDUSDT')];outCursor=1;}
    if(requestedMode==='stale')for(const e of outgoing)e.sources.book=now-100;
    if(['stale_signal','stale_current'].includes(requestedMode))for(const e of outgoing)e.sources.chart=now-100;
    const rows=outgoing.map(e=>({symbol:e.symbol,state:e.kind==='ready'?'ready':e.kind==='almost'?'almost':'waiting',score:80,reasons:[],sources:{quote:now,chart:now,candle:now-20,book:now,fetched:now},...(signalLabels[e.kind]?{assistant:currentAssistant(e.kind,e.symbol,now,requestedMode)}:{})}));
    if(modernPhase&&scope==='default'){
     const watch=currentAssistant('momentum_up','ADAUSDT',now,requestedMode),pending=currentAssistant('momentum_down','SUIUSDT',now,requestedMode);
     rows.push({symbol:'ADAUSDT',state:'waiting',assistant:{...watch,setup:'watch'}},{symbol:'SUIUSDT',state:'waiting',assistant:{...pending,status:'pending'}});
    }
    const packet={persistence:{status:storageError?'error':'durable'},status:'ok',epoch:'ui',scope,updated:now,cursor:outCursor,events:outgoing,search:'',rows};
    if(delay&&scope==='default'){delay=false;packet.events=[event('ready',19,'OLDUSDT')];packet.cursor=19;await new Promise(r=>setTimeout(r,800));}
    await route.fulfill({contentType:'application/json',json:packet});
   });
   try{
    await page.goto(`http://127.0.0.1:${port}/`);await until(()=>page.locator('.screener-events .screener-event[data-id]').count().then(n=>n>=1),'compact feed');
    await page.getByRole('button',{name:'Алерты',exact:true}).click();
   }catch(error){
    const state=await page.evaluate(()=>({url:location.href,readyState:document.readyState,title:document.title,navigationReady:!!window.LabNavigation,bodyText:document.body?.innerText.slice(0,2500),alertsButtons:Array.from(document.querySelectorAll('button[aria-controls="page-alerts"]')).map(button=>({label:button.getAttribute('aria-label'),text:button.textContent,visible:!!button.getClientRects().length})),mobileNavigation:Array.from(document.querySelectorAll('.mobile-nav')).map(nav=>({display:getComputedStyle(nav).display,html:nav.outerHTML.slice(0,1800)}))})).catch(e=>({diagnosticError:e.message}));
    console.error('Fresh alerts initial navigation diagnostics:',JSON.stringify({width,url:page.url(),errors,failedRequests,scriptResponses,state},null,2));throw error;
   }
   const feed=page.locator('#fresh-alert-events'),history=page.locator('#fresh-alert-history');
   await until(()=>feed.locator('.fresh-event').count().then(n=>n===5),'all five event types');
   assert.match(await page.locator('.fresh-alerts-head').textContent(),/Алерты и наблюдение/);
   assert.equal(await page.locator('.model-alert-diagnostics').count(),0,'legacy model diagnostics are removed');
   assert.equal(await page.evaluate(()=>permissionRequests),0,'no implicit notification permission request');assert.equal(await page.evaluate(()=>alertBeeps),0,'initial events stay silent');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);
   for(const b of await feed.locator('button').all())assert.equal(await b.evaluate(n=>n.getBoundingClientRect().height>=44),true,'touch target');

   await page.getByLabel('Тип события').selectOption('book_worse');assert.equal(await feed.locator('.fresh-event').count(),1);assert.match(await feed.textContent(),/Стакан ухудшился/);await page.getByLabel('Тип события').selectOption('all');
   await page.locator('.fresh-alert-history>summary').click();assert.equal(await history.locator('.fresh-event').count(),5);assert.match(await page.locator('.fresh-alert-history').textContent(),/прошлые наблюдения/);
   await page.getByRole('button',{name:'Звук: выключен',exact:true}).click();assert.equal(await page.evaluate(()=>alertBeeps),1);
   await page.waitForTimeout(2200);assert.equal(await page.evaluate(()=>alertBeeps),1,'unchanged conditions do not beep');assert.equal(await history.locator('.fresh-event').count(),5);
   events=[event('ready',6,'AVAXUSDT')];cursor=6;await until(()=>history.locator('.fresh-event').count().then(n=>n===6),'new transition');assert.equal(await page.evaluate(()=>alertBeeps),2);
   await page.getByRole('button',{name:'Уведомления: выключены',exact:true}).click();await page.evaluate(()=>Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}));events=[event('cancelled',7,'AVAXUSDT')];cursor=7;
   await until(()=>page.evaluate(()=>alertNotifications.length===1),'explicit background notification');assert.equal(await page.evaluate(()=>permissionRequests),0);
   await page.evaluate(()=>Object.defineProperty(document,'hidden',{configurable:true,get:()=>false}));
   await page.reload();await until(()=>history.locator('.fresh-event').count().then(n=>n===7),'history reload');assert.equal(await page.evaluate(()=>alertBeeps),0);assert.equal(await page.evaluate(()=>alertNotifications.length),0);
   await feed.locator('.fresh-event').first().evaluate(n=>n.dataset.retained='yes');mode='stale';await until(()=>feed.locator('.fresh-event[data-live="true"]').count().then(n=>n===0),'old source loses live status');assert.equal(await history.locator('.fresh-event').count(),7,'staleness does not fabricate cancellation');
   assert.equal(await feed.locator('[data-retained="yes"]').count(),1,'expiry preserves the event DOM node');mode='html';await until(()=>page.locator('.fresh-alert-health').textContent().then(t=>t.includes('недоступен')),'HTML failure');assert.equal(await feed.locator('.fresh-event').count(),7,'events remain visible through outage');assert.equal(await feed.locator('.fresh-event[data-live="true"]').count(),0);
   mode='normal';events=[event('ready',8,'BTCUSDT')];cursor=8;await until(()=>feed.locator('.fresh-event[data-id="ui:8"]').count().then(n=>n===1),'recovery');
   const retained=await history.locator('.fresh-event').count();mode='late';await page.waitForTimeout(2300);assert.equal(await history.locator('.fresh-event').count(),retained,'old cursor response rejected');assert.doesNotMatch(await feed.textContent(),/OLDUSDT/);
   mode='normal';delay=true;await page.evaluate(()=>document.dispatchEvent(new CustomEvent('lab-tab',{detail:'alerts'})));await page.waitForTimeout(100);
   await page.evaluate(()=>{localStorage.setItem('lab-selection-v1',JSON.stringify({rvol_min:1.5}));document.dispatchEvent(new CustomEvent('lab-selection-changed'));});
   await until(()=>feed.textContent().then(t=>t.includes('ETHUSDT')),'new filter generation');assert.doesNotMatch(await history.textContent(),/OLDUSDT/);
   await page.locator('.fresh-alert-history>summary').click();await page.getByRole('button',{name:'Звук: выключен',exact:true}).click();const beepsBeforeClear=await page.evaluate(()=>alertBeeps);
   await page.getByRole('button',{name:'Очистить историю',exact:true}).click();await page.waitForTimeout(2200);assert.equal(await history.locator('.fresh-event').count(),0,'clear keeps duplicate cursor');
   assert.equal(await feed.locator('.fresh-event').count(),1,'clear removes archive but keeps the active event');assert.equal(await feed.locator('.fresh-event[data-id="ui:20"][data-live="true"]').count(),1);
   assert.match(await page.locator('.fresh-alert-health').textContent(),/Свежих событий: 1/);storageError=true;await until(()=>page.locator('.fresh-alert-health').textContent().then(t=>t.includes('не сохраняется')),'storage failure is visible');storageError=false;await until(()=>page.locator('.fresh-alert-health').textContent().then(t=>t.includes('сохраняется на сервере')),'storage recovery is visible');assert.equal(await page.evaluate(()=>alertBeeps),beepsBeforeClear,'clear and repeated poll do not replay sound');
   await page.getByRole('button',{name:'Скринер',exact:true}).click();await until(()=>page.locator('.screener-events .screener-event[data-id="ui:20"][data-live="true"]').count().then(n=>n===1),'compact feed also keeps the active event');await page.getByRole('button',{name:'Алерты',exact:true}).click();
   events=[event('ready',21,'ETHUSDT')];cursor=21;await page.evaluate(()=>{localStorage.setItem('lab-selection-v1',JSON.stringify({rvol_min:1}));document.dispatchEvent(new CustomEvent('lab-selection-changed'));});await until(()=>feed.locator('.fresh-event[data-id="ui:21"]').count().then(n=>n===1),'new event after clear');await feed.getByRole('button',{name:'Карточка ETHUSDT',exact:true}).click();await until(()=>page.locator('#page-market').isVisible(),'open coin card');assert.match(await page.locator('.screener-detail').getAttribute('data-symbol'),/ETHUSDT/);assert.equal(await page.locator('.screener-detail').getAttribute('data-interval'),'1','alert opens its own analysis timeframe');
   await page.getByRole('button',{name:'Алерты',exact:true}).click();modernPhase=true;const now=Date.now()/1000;
   const modernEvents=Object.keys(signalLabels).map((kind,index)=>signal(kind,22+index,['BTCUSDT','ETHUSDT','SOLUSDT','LINKUSDT'][index],now));
   const misleading=(kind,sequence,symbol)=>{const proof=signal('breakout_up',sequence,symbol,now);return {...event(kind,sequence,symbol,now),exchange:proof.exchange,timeframe:proof.timeframe,interval:proof.interval,signal_id:proof.signal_id,candle_end:proof.candle_end,recommendation:proof.recommendation};};
   events=[...modernEvents,misleading('ready',26,'XRPUSDT'),misleading('near_level',27,'DOGEUSDT')];cursor=27;
   await until(()=>feed.locator('.fresh-event[data-current-recommendation="true"]').count().then(n=>n===4),'four recommendations need only captured quote and closed-candle sources');
   const conditions=page.locator('.fresh-alert-conditions');
   for(const e of modernEvents){const card=feed.locator('.fresh-event[data-id="'+e.id+'"]'),row=conditions.locator('.fresh-condition[data-symbol="'+e.symbol+'"]'),archived=history.locator('.fresh-event[data-id="'+e.id+'"]');assert.equal(await card.getAttribute('data-direction'),e.recommendation.direction);assert.equal(await card.locator('.fresh-direction').textContent(),'Рекомендация '+e.recommendation.direction);assert.equal(await card.locator('.fresh-event-detail').textContent(),e.recommendation.reason);assert.match(await card.locator('.fresh-invalidation').textContent(),/Отмена:/);assert.match(await card.locator('.fresh-event-price').textContent(),/закрытые свечи 1м/);assert.equal(await row.getAttribute('data-current-recommendation'),'true');assert.equal(await row.getAttribute('data-direction'),e.recommendation.direction);assert.equal(await archived.locator('.fresh-direction').textContent(),e.recommendation.direction+' · история');assert.equal(await archived.getAttribute('data-current-recommendation'),'false');assert.match(await archived.locator('.fresh-event-proof').textContent(),/история.*сохранённое наблюдение/);assert.doesNotMatch(await archived.textContent(),/рекомендация завершена|рекомендация закончена|сигнал завершён/,'an archive counterpart cannot declare its still-current event completed');}
   for(const id of ['ui:26','ui:27']){const card=feed.locator('.fresh-event[data-id="'+id+'"]');assert.equal(await card.getAttribute('data-direction'),'none','legacy liquidity/level event cannot inherit LONG');assert.equal(await card.getAttribute('data-current-recommendation'),'false');assert.equal(await card.locator('.fresh-direction').isVisible(),false);}
   for(const symbol of ['ADAUSDT','SUIUSDT']){const row=conditions.locator('.fresh-condition[data-symbol="'+symbol+'"]');assert.equal(await row.getAttribute('data-current-recommendation'),'false','watch/pending cannot become a recommendation');assert.doesNotMatch(await row.textContent(),/Рекомендация (LONG|SHORT)/);}
   const directionFilter=page.getByLabel('Направление алерта');await directionFilter.selectOption('LONG');assert.equal(await feed.locator('.fresh-event').count(),2);assert.equal(await feed.locator('.fresh-event:not([data-direction="LONG"])').count(),0);await directionFilter.selectOption('SHORT');assert.equal(await feed.locator('.fresh-event').count(),2);assert.equal(await feed.locator('.fresh-event:not([data-direction="SHORT"])').count(),0);await directionFilter.selectOption('none');assert.equal(await feed.locator('.fresh-event[data-live="true"]').count(),2);assert.equal(await feed.locator('.fresh-event:not([data-direction="none"])').count(),0);await directionFilter.selectOption('all');
   await page.getByLabel('Тип события').selectOption('breakout_up');assert.equal(await feed.locator('.fresh-event').count(),1);assert.match(await feed.textContent(),/Пробой вверх/);await page.getByLabel('Тип события').selectOption('all');
   await page.getByRole('button',{name:'Уведомления: выключены',exact:true}).click();await page.evaluate(()=>Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}));
   const notifyNow=Date.now()/1000;events.push(signal('momentum_up',28,'AVAXUSDT',notifyNow),signal('momentum_down',29,'TONUSDT',notifyNow));cursor=29;
   await until(()=>page.evaluate(()=>alertNotifications.length===2),'LONG and SHORT background notifications');const notifications=await page.evaluate(()=>alertNotifications);assert.equal(notifications[0].title,'Рекомендация LONG · AVAXUSDT');assert.equal(notifications[1].title,'Рекомендация SHORT · TONUSDT');await page.waitForTimeout(2200);assert.equal(await page.evaluate(()=>alertNotifications.length),2,'unchanged directional events do not replay notifications');await page.evaluate(()=>Object.defineProperty(document,'hidden',{configurable:true,get:()=>false}));
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'recommendations overflow '+width);await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(root,'artifacts',`recommendation-alerts-${width}.png`),fullPage:true});if(width===1280)await page.screenshot({path:path.join(root,'artifacts','recommendation-alerts-preview.png'),fullPage:false});
   const modernHistory=await history.locator('.fresh-event').count(),retainedCard=feed.locator('.fresh-event[data-id="ui:22"]');await retainedCard.evaluate(n=>n.dataset.recommendationRetained='yes');
   mode='stale_signal';await until(()=>feed.locator('.fresh-event[data-live="true"]').count().then(n=>n===0),'stale candle source disables current signal');assert.equal(await feed.locator('.fresh-event[data-current-recommendation="true"]').count(),0);assert.equal(await conditions.locator('.fresh-condition[data-current-recommendation="true"]').count(),0);assert.equal(await history.locator('.fresh-event').count(),modernHistory,'stale signals remain in retained history');assert.equal(await retainedCard.getAttribute('data-recommendation-retained'),'yes');assert.equal(await retainedCard.locator('.fresh-direction').textContent(),'LONG · история');
   mode='normal';await until(()=>retainedCard.getAttribute('data-current-recommendation').then(v=>v==='true'),'same captured event recovers without new notification');assert.equal(await page.evaluate(()=>alertNotifications.length),2);
   clockOffset=Math.ceil((modernEvents[0].expires+1)*1000-Date.now());await page.evaluate(offset=>{window.alertClockOffset=offset;document.dispatchEvent(new CustomEvent('lab-tab',{detail:'alerts'}));},clockOffset);
   await until(()=>retainedCard.getAttribute('data-live').then(v=>v==='false'),'event expires on the test clock');assert.equal(await retainedCard.getAttribute('data-recommendation-retained'),'yes','expiry patches the original event row');assert.equal(await retainedCard.getAttribute('data-current-recommendation'),'false');assert.equal(await retainedCard.locator('.fresh-direction').textContent(),'LONG · история');assert.match(await retainedCard.locator('.fresh-event-proof').textContent(),/история.*сохранённое наблюдение/);
   await until(()=>conditions.locator('.fresh-condition[data-symbol="BTCUSDT"][data-current-recommendation="true"]').count().then(n=>n===1),'ongoing current recommendation survives short event expiry');assert.equal(await conditions.locator('.fresh-condition[data-symbol="BTCUSDT"]').getAttribute('data-direction'),'LONG');assert.equal(await conditions.locator('.fresh-condition[data-symbol="ETHUSDT"]').getAttribute('data-direction'),'SHORT');
   mode='stale_current';await until(()=>conditions.locator('.fresh-condition[data-symbol="BTCUSDT"][data-current-recommendation="false"]').count().then(n=>n===1),'ongoing recommendation loses its own stale chart proof');assert.equal(await conditions.locator('.fresh-condition[data-current-recommendation="true"]').count(),0);assert.match(await conditions.locator('.fresh-condition[data-symbol="BTCUSDT"]').textContent(),/Ожидаем свежие данные/);assert.equal(await feed.locator('.fresh-event[data-current-recommendation="true"]').count(),0);
   mode='html';await until(()=>page.locator('.fresh-alert-health').textContent().then(t=>t.includes('недоступен')),'directional packet outage');assert.equal(await feed.locator('.fresh-event[data-current-recommendation="true"]').count(),0);assert.equal(await conditions.locator('.fresh-condition[data-current-recommendation="true"]').count(),0);assert.equal(await retainedCard.getAttribute('data-recommendation-retained'),'yes');assert.equal(await history.locator('.fresh-event').count(),modernHistory);
   assert.deepEqual(errors,[],'browser errors '+width);assert.deepEqual(posts,[],'alerts never post commands');await page.close();
  }
  console.log('Fresh alerts UI passed: '+widths.join('/')+', LONG/SHORT recommendations, direction filters, current-row/event expiry independence, no legacy/watch/pending recommendations, notifications/dedup, source failure, retained DOM/history/reload/clear, late filter response and coin card.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});

