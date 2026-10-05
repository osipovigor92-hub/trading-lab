/* Isolated synthetic planning UI; no market or trading services are started. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const {fixture}=require('./paper_plan_fixture.cjs');
const root=path.resolve(__dirname,'..'),port=18794;
async function until(predicate){const end=Date.now()+15000;while(Date.now()<end){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw Error('PAPER-plan condition was not met within 15 seconds');}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:1100}}),errors=[],posts=[];let mode='ready',revision=0;const setMode=next=>{mode=next;revision++;};
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
   await page.route(/\/api\/(paper|model-b|research)(?:\?|$)/,async route=>{try{const res=await route.fetch(),data=await res.json();data.position=null;if(data.models)for(const model of Object.values(data.models))model.position=null;await route.fulfill({response:res,json:data});}catch{try{await route.abort();}catch{}}});
   await page.route(/\/api\/(screener|market-chart|market-book|market-selection)(?:\?|$)/,async route=>{
    try{
     const active=mode,url=new URL(route.request().url()),kind=url.pathname.split('/').at(-1),symbol=url.searchParams.get('symbol')||'BTCUSDT',interval=url.searchParams.get('interval')||'5',now=Math.floor(Date.now()/5000)*5+revision*.0001;
     if(active==='html')return route.fulfill({contentType:'text/html',body:'<html>temporarily unavailable</html>'});
     if(active==='race'&&kind==='market-chart'&&symbol==='BTCUSDT')await new Promise(r=>setTimeout(r,800));
     const f=fixture(active==='short'?-1:1,interval,now);f.symbol=symbol;f.chart.symbol=symbol;f.book.symbol=symbol;
     if(active==='watch'||active==='crossed'){const price=active==='watch'?100:98.8;f.snapshot.rows[0].price=f.book.mid=price;f.book.top.bid[0].price=price*.9999;f.book.top.ask[0].price=price*1.0001;}
     if(active==='neutral')f.chart.vwap=100;
     if(active==='one_target')f.chart.levels.pop();
     if(active==='shallow')f.book.top.ask[0].quantity=.001;
     if(active==='partial')f.book.bands['0.001'].covered=false;
     if(active==='wrong'){f.chart.symbol='SOLUSDT';f.book.symbol='SOLUSDT';}
     const verdict=f.selectionPacket.rows[0].selection;
     if(active==='missing'){f.snapshot.rows[0].open_interest=null;verdict.status='pending';verdict.checks.find(c=>c.key==='oi').state='pending';verdict.checks.find(c=>c.key==='oi').value=null;}
     if(active==='rejected'){verdict.status='rejected';verdict.checks[0].state='fail';}
     let data=kind==='screener'?{...f.snapshot,rows:['BTCUSDT','ETHUSDT'].map(s=>({...f.snapshot.rows[0],symbol:s}))}:kind==='market-selection'?{...f.selectionPacket,rows:['BTCUSDT','ETHUSDT'].map(s=>({symbol:s,selection:verdict})),analysis_limit:8}:kind==='market-chart'?f.chart:f.book;
     if(active==='stale_'+kind)data.updated=now-100;
     await route.fulfill({contentType:'application/json',json:data});
    }catch{try{await route.abort();}catch{}}
   });
   const plan=page.locator('#screener-plan'),value=key=>plan.locator(`[data-plan-field=${key}] dd`),state=async()=>await plan.getAttribute('data-state'),ready=()=>state().then(s=>s==='ready');
   await page.goto(`http://127.0.0.1:${port}/`);await until(ready);
   assert.equal(await plan.locator('[data-plan-field]').count(),8);assert.equal(await value('direction').textContent(),'LONG');assert.match(await value('size').textContent(),/BTC$/);assert.notEqual(await value('entry').textContent(),'—');assert.notEqual(await value('target2').textContent(),'—');
   await plan.locator('[data-plan-field=risk]').evaluate(el=>el.dataset.kept='yes');
   for(const [interval,name]of [['1','1 минута'],['5','5 минут'],['15','15 минут'],['60','1 час']]){await page.getByRole('button',{name,exact:true}).click();await until(ready);assert.equal(await plan.getAttribute('data-interval'),interval);}
   await page.getByRole('button',{name:'5 минут',exact:true}).click();await until(ready);await plan.scrollIntoViewIfNeeded();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow at '+width);
   await plan.screenshot({path:path.join(root,'artifacts',`paper-plan-${width}.png`)});
   await plan.locator('.paper-plan-controls>summary').click();await plan.screenshot({path:path.join(root,'artifacts',`paper-plan-settings-${width}.png`)});const riskInput=page.getByLabel('Риск на план, % капитала',{exact:true});await riskInput.fill('.01');assert.equal(await state(),'settings_error');assert.equal(await value('size').textContent(),'—');
   await riskInput.press('Enter');await until(ready);assert.match(await plan.locator('[data-plan-field=risk] small').textContent(),/0,06 USDT/);
   await riskInput.evaluate(el=>el.dataset.kept='yes');await page.waitForTimeout(2200);assert.equal(await riskInput.getAttribute('data-kept'),'yes');assert.equal(await plan.locator('.paper-plan-controls').getAttribute('open'),'');assert.equal(await plan.locator('[data-plan-field=risk]').getAttribute('data-kept'),'yes');
   await page.reload();await until(ready);await plan.locator('.paper-plan-controls>summary').click();assert.equal(await riskInput.inputValue(),'0.01');
   await page.getByLabel('Виртуальный капитал, USDT',{exact:true}).fill('50');await page.getByRole('button',{name:'Применить расчёт',exact:true}).click();assert.equal(await state(),'settings_error');assert.match(await plan.locator('.paper-plan-message').textContent(),/Лимит входа/);
   await page.getByLabel('Лимит входа, USDT',{exact:true}).fill('25');await page.getByRole('button',{name:'Применить расчёт',exact:true}).click();await until(ready);assert.match(await plan.locator('.paper-plan-context').textContent(),/капитал 50 USDT/);
   await page.getByLabel('Комиссия на сторону, %',{exact:true}).fill('-1');await page.getByRole('button',{name:'Применить расчёт',exact:true}).click();assert.equal(await page.getByLabel('Комиссия на сторону, %',{exact:true}).getAttribute('aria-invalid'),'true');assert.equal(await value('risk').textContent(),'—');
   await page.getByRole('button',{name:'Сбросить расчёт',exact:true}).click();await until(ready);assert.equal(await riskInput.inputValue(),'0.5');
   assert.equal(await plan.locator('.paper-plan-actions button').evaluateAll(nodes=>nodes.every(n=>n.getBoundingClientRect().height>=44)),true);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await plan.locator('.paper-plan-controls>summary').click();
   for(const [next,expected]of [['short','ready'],['watch','watch'],['crossed','invalidated'],['rejected','rejected'],['missing','pending'],['neutral','neutral'],['shallow','rejected'],['partial','pending'],['wrong','pending']]){setMode(next);await until(async()=>await plan.evaluate((el,{expected,next})=>el.dataset.state===expected&&(next!=='short'||el.querySelector('[data-plan-field=direction] dd').textContent==='SHORT')&&(!['pending','neutral'].includes(expected)||el.querySelector('[data-plan-field=size] dd').textContent==='—'),{expected,next}));}
   setMode('one_target');await until(async()=>await state()==='ready'&&await value('target2').textContent()==='—');assert.match(await plan.locator('[data-plan-field=target2] small').textContent(),/Нет второй/);
   for(const key of ['screener','market-chart','market-book']){setMode('stale_'+key);await until(async()=>await state()==='pending'&&await value('size').textContent()==='—');setMode('ready');await until(ready);}
   setMode('race');await page.getByRole('button',{name:'BTCUSDT',exact:true}).click();await page.getByRole('button',{name:'ETHUSDT',exact:true}).click();await page.waitForTimeout(1200);
   await until(async()=>await plan.evaluate(el=>el.dataset.symbol==='ETHUSDT'&&el.dataset.state==='ready'&&/ETH$/.test(el.querySelector('[data-plan-field=size] dd').textContent)));assert.equal(await plan.getAttribute('data-symbol'),'ETHUSDT');
   setMode('html');await until(async()=>await state()==='pending'&&await page.locator('#screener-detail [data-state=cached]').count()>0);assert.equal(await value('risk').textContent(),'—');assert.match(await plan.locator('.paper-plan-status').textContent(),/ошибка обновления/);
   await page.evaluate(()=>{const realNow=Date.now;Date.now=()=>realNow()+90000;});await until(async()=>await page.locator('#screener-detail [data-state=stale]').count()===3);assert.equal(await value('size').textContent(),'—');
   setMode('ready');await page.reload();await until(ready);assert.equal(await plan.getAttribute('data-symbol'),'ETHUSDT');assert.deepEqual(posts,[],'planning cannot send trading/control POST requests');assert.deepEqual(errors,[],'browser errors at '+width);
   await page.unrouteAll({behavior:'wait'});await page.close();
  }
  console.log('PAPER plan UI passed: 1280/390/320, four timeframes, LONG/SHORT, entry/wait/cancel, inputs/persistence, partial/stale/error data and delayed coin switch');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
