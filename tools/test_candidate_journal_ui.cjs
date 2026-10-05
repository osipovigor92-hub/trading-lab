/* Historical source evidence, bounded pagination, errors and read-only navigation. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18797;
async function until(fn,label='condition'){const end=Date.now()+15000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error('Journal: '+label+' was not met');}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}/`).then(r=>r.ok).catch(()=>false),'preview');
  const seed=await fetch(`http://127.0.0.1:${port}/api/candidate-journal?period=all`).then(r=>r.json());
  assert.equal(seed.status,'ok');const template=seed.rows.find(r=>r.kind==='candidate'&&r.symbol==='BTCUSDT'),signal=seed.rows.find(r=>r.kind==='signal');assert.ok(template&&signal);
  const original=structuredClone(template.evidence),now=Date.now()/1000;
  const rows=Array.from({length:42},(_,i)=>{const evidence=structuredClone(original),symbol=i%2?'ETHUSDT':'BTCUSDT',rejected=i%3!==1;
   evidence.status=rejected?'rejected':'passed';evidence.readiness=rejected?'waiting':'ready';evidence.checks.forEach(c=>c.state='pass');if(rejected){const c=evidence.checks.find(c=>c.key==='rvol');Object.assign(c,{value:.5,state:'fail',min:1});const volume=evidence.rating.components.find(c=>c.key==='volume');Object.assign(volume,{points:6,label:'Объём ниже среднего',values:{rvol:.5}});evidence.rating.score=evidence.rating.components.reduce((sum,c)=>sum+c.points,0);}
   return {...template,id:42-i,symbol,status:evidence.status,first_seen:now-100-i*10,last_seen:now-20,samples:3,evidence};});
  rows.unshift({...signal,id:43,symbol:'BTCUSDT',first_seen:now-90000,last_seen:now-90000,evidence:{...signal.evidence,event:{...signal.evidence.event,detail:'<img src=x onerror="window.journalInjected=1"> Историческое событие'}}});
  const manualRows=Array.from({length:25},(_,i)=>({id:'stored-manual-'+(25-i),cursor:25-i,symbol:'BTCUSDT',side:1,opened:now-1000-i*200,closed:now-900-i*200,entry:100,exit:101,quantity:1,net:i===0?1000:1,complete:i!==0,gross:1,entry_fee:.05,exit_fee:.05,reason:'Поддержка и VWAP',exit_reason:'Цель 1',observation_gap:i===0?'Перезапуск; непрерывность не подтверждена':'',stop:99,target:102,risk:1.1,quote_time:now-1000-i*200}));
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[],posts=[];let mode='normal',delay=false;
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());});
   await page.route('**/api/candidate-journal?*',async route=>{
    const requestMode=mode,url=new URL(route.request().url()),p=url.searchParams;
    if(delay){delay=false;await new Promise(r=>setTimeout(r,900));}
    if(requestMode==='html')return route.fulfill({contentType:'text/html',body:'<html>No journal</html>'});
    const since=now-(p.get('period')==='all'?now:p.get('period')==='week'?7*86400:86400),s=p.get('status')||'all',search=p.get('search')||'';
    let selected=rows.filter(r=>r.last_seen>=since&&r.symbol.startsWith(search)&&(s==='all'||r.status===s));
    const total=selected.length,counts={};for(const r of selected)counts[r.status]=(counts[r.status]||0)+1;
    if(p.get('before'))selected=selected.filter(r=>r.id<+p.get('before'));const limit=+(p.get('limit')||20),items=selected.slice(0,limit);
    const packet={...seed,updated:Date.now()/1000,rows:items,total,next_before:selected.length>limit?items.at(-1).id:0,
     collector:{...seed.collector,collecting:requestMode!=='partial',last_cycle:now,error:requestMode==='partial'?'Нет свежих котировок; решения за пропуск не восстанавливаются':''},
     query:{anchor:+p.get('anchor')||Math.floor(now)+1},summary:{counts,reasons:counts.rejected?[{key:'rvol',label:'Объём · 5 / 20 закрытых минут',count:counts.rejected}]:[]}};
    await route.fulfill({contentType:'application/json',body:JSON.stringify(packet)});
   });
   await page.route('**/api/manual-journal?*',async route=>{
    const p=new URL(route.request().url()).searchParams,selected=manualRows.filter(r=>!p.get('before')||r.cursor<+p.get('before')),items=selected.slice(0,20);
    await route.fulfill({contentType:'application/json',body:JSON.stringify({status:'ok',updated:now,rows:items,total:25,next_before:selected.length>20?items.at(-1).cursor:0})});
   });
   await page.goto(`http://127.0.0.1:${port}/`);await page.evaluate(()=>LabNavigation.activate('journals'));
   const box=page.locator('#candidate-journal');await until(()=>box.locator('.journal-entry').count().then(n=>n===20),'first page');
   assert.match(await box.locator('.journal-health').textContent(),/Сервер сохраняет/);assert.equal(await page.locator('#model-journals').count(),1);assert.equal(await page.locator('#research-journals').count(),1);
   const first=box.locator('.journal-entry').first();await first.locator('>summary').click();await first.locator('.journal-context>summary').click();
   assert.equal(await first.locator('.journal-check').count(),12);assert.match(await first.textContent(),/Значение: 0,5/);assert.match(await first.textContent(),/Порог: от 1/);assert.match(await first.textContent(),/Версия|версия/);
   assert.equal(await first.locator('time').textContent(),new Date(rows[1].first_seen*1000).toLocaleString('ru-RU'));
   await box.getByRole('button',{name:'Раньше',exact:true}).click();await until(()=>box.locator('.journal-entry').first().getAttribute('data-id').then(id=>id==='22'),'older page');
   assert.match(await box.getByText('CSV этой страницы',{exact:true}).getAttribute('href'),/before=23/);
   await box.getByRole('button',{name:'Назад',exact:true}).click();await until(()=>box.locator('.journal-entry').first().getAttribute('data-id').then(id=>id==='42'),'back');
   await page.getByLabel('Решение',{exact:true}).selectOption('rejected');await page.getByLabel('Монета в журнале').fill('btc');await box.getByRole('button',{name:'Показать',exact:true}).click();
   await until(()=>box.locator('.journal-entry').count().then(n=>n===14),'filtered rejects');assert.equal(await page.getByLabel('Монета в журнале').inputValue(),'BTC');
   await box.locator('.journal-learning>summary').click();assert.match(await box.locator('.journal-learning').textContent(),/14 из 14/);
   await box.locator('.journal-entry').first().locator('>summary').click();await box.screenshot({path:path.join(root,'artifacts',`candidate-journal-${width}.png`)});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no horizontal overflow '+width);
   const manual=page.locator('#manual-journal');await manual.locator('>summary').click();await until(()=>manual.locator('.journal-entry').count().then(n=>n===20),'manual full history page');
   assert.match(await manual.locator('.journal-health').textContent(),/25/);assert.match(await manual.textContent(),/Net точных закрытий: 19 USDT/);assert.doesNotMatch(await manual.locator('summary').first().textContent(),/1000/);
   await manual.locator('.journal-entry').first().locator('>summary').click();assert.match(await manual.textContent(),/Net не подтверждён/);assert.match(await manual.textContent(),/Перезапуск/);
   await manual.screenshot({path:path.join(root,'artifacts',`manual-journal-${width}.png`)});
   await manual.getByRole('button',{name:'Раньше',exact:true}).click();await until(()=>manual.locator('.journal-entry').count().then(n=>n===5),'manual earlier than last twenty');assert.match(await manual.getByText('CSV этой страницы',{exact:true}).getAttribute('href'),/before=6/);
   await page.getByLabel('Решение',{exact:true}).selectOption('signal');await page.getByLabel('Период',{exact:true}).selectOption('all');await box.getByRole('button',{name:'Показать',exact:true}).click();await until(()=>box.locator('.journal-entry').count().then(n=>n===1),'archive beyond 24 hours');
   await box.locator('.journal-entry>summary').click();assert.match(await box.textContent(),/onerror/);assert.equal(await box.locator('img').count(),0);assert.equal(await page.evaluate(()=>window.journalInjected||0),0);
   await page.waitForTimeout(900);mode='html';await box.getByRole('button',{name:'Обновить',exact:true}).click();await until(()=>box.locator('.journal-health').textContent().then(t=>t.includes('недоступен')),'HTML failure');assert.equal(await box.locator('.journal-entry').count(),0);assert.equal(await box.getByText('CSV этой страницы',{exact:true}).getAttribute('aria-disabled'),'true');
   await page.waitForTimeout(900);mode='partial';await box.getByRole('button',{name:'Обновить',exact:true}).click();await until(()=>box.locator('.journal-entry').count().then(n=>n===1),'partial storage still readable');assert.match(await box.locator('.journal-health').textContent(),/Нет свежих котировок/);
   await page.waitForTimeout(900);mode='normal';delay=true;await box.getByRole('button',{name:'Обновить',exact:true}).click();await page.getByLabel('Решение',{exact:true}).selectOption('rejected');
   await page.evaluate(()=>document.querySelector('.journal-controls').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
   await until(()=>box.locator('.journal-entry').count().then(n=>n===14),'new filter response');await page.waitForTimeout(1000);assert.equal(await box.locator('.journal-entry').count(),14,'late previous page discarded');
   await page.getByLabel('Монета в журнале').fill('ZZZ');await box.getByRole('button',{name:'Показать',exact:true}).click();await until(()=>box.locator('.journal-empty').count().then(n=>n===1),'empty explanation');
   await page.reload();await page.evaluate(()=>LabNavigation.activate('journals'));await until(()=>page.locator('#candidate-journal .journal-entry').count().then(n=>n===20),'reload retained server history');
   await page.locator('#candidate-journal .journal-entry').first().locator('>summary').click();await page.locator('#candidate-journal .journal-entry').first().getByRole('button',{name:'Карточка BTCUSDT',exact:true}).click();
   await until(()=>page.locator('#page-market').isVisible(),'coin card');assert.equal(await page.locator('#screener-detail').getAttribute('data-symbol'),'BTCUSDT');assert.equal(await page.locator('#screener-detail').getAttribute('data-interval'),'1');
   assert.deepEqual(errors,[],'browser errors '+width);assert.deepEqual(posts,[],'journal never changes account');await page.close();
  }
  console.log('Candidate journal UI passed: 1280/390/320, first evidence, filters, stable cursor/CSV, missing net, history beyond twenty, reload, late response, errors and read-only coin navigation.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
