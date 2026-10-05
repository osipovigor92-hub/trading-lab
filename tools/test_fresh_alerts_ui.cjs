/* Offline transition feed, source failures, reload and request-generation checks. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18796;
async function until(fn,label='condition'){const end=Date.now()+15000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('Fresh alerts: '+label+' was not met');}
const labels={ready:'Кандидат готов',almost:'Почти готов',cancelled:'Условие отменено',book_worse:'Стакан ухудшился',near_level:'Цена у уровня'};
const event=(kind,sequence,symbol,now=Date.now()/1000)=>({id:'ui:'+sequence,sequence,symbol,kind,label:labels[kind],detail:kind==='near_level'?'Поддержка 1м: 99,4–99,5 · зона ±0,25 ATR':kind==='ready'?'Все 12 проверок отбора пройдены. Проверьте направление и вход в PAPER-плане.':'Не выполнено: Глубина каждой стороны ±0,1%',score:80,time:now,expires:now+8,sources:{quote:now,chart:now,candle:now-20,book:now,fetched:now},price:100});
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}/`).then(r=>r.ok).catch(()=>false),'preview');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[],posts=[];let mode='normal',events=Object.keys(labels).map((k,i)=>event(k,i+1,['BTCUSDT','ETHUSDT','SOLUSDT','ONDOUSDT','LINKUSDT'][i])),cursor=5,delay=false;
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
   await page.addInitScript(()=>{window.alertBeeps=0;window.alertNotifications=[];window.permissionRequests=0;
    if(!localStorage.getItem('lab-alert-history-v2'))localStorage.setItem('lab-alert-history-v2',JSON.stringify({events:[{time:Date.now()/1000-300,text:'B · сохранённое наблюдение',tone:'neutral'}],states:[['B:BTCUSDT','entry:LONG']]}));
    window.AudioContext=class {currentTime=0;destination={};resume(){return Promise.resolve();}createOscillator(){return {connect(){},frequency:{value:0},start(){window.alertBeeps++;},stop(){}};}createGain(){return {connect(){},gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}}};}};
    window.Notification=class {static permission='granted';static requestPermission(){window.permissionRequests++;return Promise.resolve('granted');}constructor(title,options){window.alertNotifications.push({title,...options});}close(){}};
   });
   await page.route('**/api/market-alerts?*',async route=>{
    const requestedMode=mode,url=new URL(route.request().url()),scope=url.searchParams.get('rvol_min')==='1.5'?'changed':'default',now=Date.now()/1000;
    if(requestedMode==='html')return route.fulfill({contentType:'text/html',body:'<html>unavailable</html>'});
    let outgoing=events.map(e=>({...e,sources:{...e.sources}})),outCursor=cursor;
    if(scope==='changed'){outgoing=[event('ready',20,'ETHUSDT')];outCursor=20;}
    else if(requestedMode==='late'){outgoing=[event('ready',1,'OLDUSDT')];outCursor=1;}
    if(requestedMode==='stale')for(const e of outgoing)e.sources.book=now-100;
    const packet={status:'ok',epoch:'ui',scope,updated:now,cursor:outCursor,events:outgoing,search:'',rows:outgoing.map(e=>({symbol:e.symbol,state:e.kind==='ready'?'ready':e.kind==='almost'?'almost':'waiting',score:80,reasons:[],sources:{quote:now,chart:now,candle:now-20,book:now,fetched:now}}))};
    if(delay&&scope==='default'){delay=false;packet.events=[event('ready',19,'OLDUSDT')];packet.cursor=19;await new Promise(r=>setTimeout(r,800));}
    await route.fulfill({contentType:'application/json',json:packet});
   });
   await page.goto(`http://127.0.0.1:${port}/`);await until(()=>page.locator('#screener-alerts .compact-alert[data-kind]').count().then(n=>n===3),'compact feed');
   await page.getByRole('button',{name:'Алерты',exact:true}).click();const feed=page.locator('#fresh-alert-events'),history=page.locator('#fresh-alert-history');
   await until(()=>feed.locator('.fresh-event').count().then(n=>n===5),'all five event types');
   assert.match(await page.locator('.fresh-alerts-head').textContent(),/направление и вход проверяются в PAPER-плане/);
   assert.equal(await page.locator('.model-alert-diagnostics').getByText('Прежняя история моделей',{exact:true}).count(),1);assert.match(await page.locator('.model-alert-diagnostics').textContent(),/сохранённое наблюдение/);
   assert.equal(await page.evaluate(()=>permissionRequests),0,'no implicit notification permission request');assert.equal(await page.evaluate(()=>alertBeeps),0,'initial events stay silent');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);
   for(const b of await feed.locator('button').all())assert.equal(await b.evaluate(n=>n.getBoundingClientRect().height>=44),true,'touch target');
   await page.screenshot({path:path.join(root,'artifacts',`fresh-alerts-${width}.png`),fullPage:true});
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
   await page.locator('.fresh-alert-history>summary').click();await page.getByRole('button',{name:'Очистить историю',exact:true}).click();await page.waitForTimeout(2200);assert.equal(await history.locator('.fresh-event').count(),0,'clear keeps duplicate cursor');
   events=[event('ready',21,'ETHUSDT')];cursor=21;await page.evaluate(()=>{localStorage.setItem('lab-selection-v1',JSON.stringify({rvol_min:1}));document.dispatchEvent(new CustomEvent('lab-selection-changed'));});await until(()=>feed.locator('.fresh-event[data-id="ui:21"]').count().then(n=>n===1),'new event after clear');await feed.getByRole('button',{name:'Карточка ETHUSDT',exact:true}).click();await until(()=>page.locator('#page-market').isVisible(),'open coin card');assert.match(await page.locator('#screener-detail').getAttribute('data-symbol'),/ETHUSDT/);assert.equal(await page.locator('#screener-detail').getAttribute('data-interval'),'1','alert opens its own analysis timeframe');
   assert.deepEqual(errors,[],'browser errors '+width);assert.deepEqual(posts,[],'alerts never post commands');await page.close();
  }
  console.log('Fresh alerts UI passed: 1280/390/320, five types, source failure, history/reload/clear, dedup, explicit sound/notifications, late filter response and coin card.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
