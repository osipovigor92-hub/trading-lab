/* Regression: live snapshots must not replace drafts or recreate stable panels. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18973;
async function until(check,message){for(let i=0;i<100;i++){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error(message);}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  await until(async()=>{try{return (await fetch(`http://127.0.0.1:${port}/`)).ok;}catch{return false;}},'Preview not ready');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  const evidence=[];
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[],posts=[];
   let mode='ready',reads=0,generation=0,settings={capital:600,notional:100,max_loss:18},experiment='refresh-original',pending=null,audit=[],apply=false,delayLive=false;
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/models-control',async route=>{
    if(route.request().method()==='POST'){
     const request=route.request().postDataJSON();posts.push(request);
     assert.equal(request.target,'A');assert.equal(request.action,'new_run');assert.equal(request.generation,generation);
     pending={id:'refresh-command-'+(generation+1),settings:request.experiment};apply=false;
     audit=[{id:pending.id,time:Date.now()/1000,target:'A',action:'new_run',outcome:'accepted',message:'ISOLATED UI FIXTURE'}];
     return route.fulfill({contentType:'application/json',json:{status:'accepted',id:pending.id}});
    }
    reads++;
    if(mode==='html')return route.fulfill({status:502,contentType:'text/html',body:'<html>Temporary gateway failure</html>'});
    const response=await route.fetch(),data=await response.json();
    if(pending&&apply){generation++;settings={...pending.settings};experiment='refresh-run-'+generation;audit[0]={...audit[0],outcome:'applied'};}
    for(const m of data.models){
     m.phase='paused';m.position=null;m.pending=!!pending&&!apply;m.actions={start:true,stop:false,restart:true,new_run:!pending||apply};
     if(m.id==='A')Object.assign(m,{generation,equity:settings.capital,experiment:{...m.experiment,id:experiment,settings}});
    }
    data.audit=audit;
    if(pending&&apply){pending=null;apply=false;}
    if(mode==='stale')data.updated-=20;
    await route.fulfill({response,json:data});
   });
   await page.route('**/api/live',async route=>{if(delayLive)await new Promise(r=>setTimeout(r,1200));await route.continue();});
   await page.goto(`http://127.0.0.1:${port}/`);await page.getByRole('button',{name:'Модели',exact:true}).click();
   const card=id=>page.locator(`.managed-card[data-model="${id}"]`),field=(id,label)=>page.getByLabel(`${label}, USDT для модели ${id}`);
   const capital=field('A','Бюджет'),notional=field('A','Вход'),loss=field('A','Лимит потерь'),newRun=card('A').getByRole('button',{name:'Сохранить и начать новый тест',exact:true});
   await until(()=>newRun.isEnabled(),'Controller not ready');
   await page.locator('#research-paper-summary .research-card').first().waitFor({state:'attached'});
   for(const [i,id]of [...'ABCD'].entries()){await field(id,'Бюджет').fill(String(725+i));await field(id,'Вход').fill('50.25');await field(id,'Лимит потерь').fill('7.5');}
   await capital.focus();await capital.scrollIntoViewIfNeeded();
   const before=await page.evaluate(()=>{
    const selectors=['#model-controls .managed-metrics','#models-ops-overview .models-ops-grid','#research-paper-summary .research-live','#research-observations'];
    window.refreshNodes=selectors.map(s=>document.querySelector(s).firstElementChild);window.refreshRemoved=0;
    for(const s of selectors)new MutationObserver(records=>{for(const r of records)refreshRemoved+=[...r.removedNodes].filter(n=>n.nodeType===1).length;}).observe(document.querySelector(s),{childList:true,subtree:true});
    return {scrollY};
   });
   const startReads=reads;await page.waitForTimeout(7400);
   for(const [i,id]of [...'ABCD'].entries()){assert.equal(await field(id,'Бюджет').inputValue(),String(725+i));assert.equal(await field(id,'Вход').inputValue(),'50.25');assert.equal(await field(id,'Лимит потерь').inputValue(),'7.5');}
   assert.ok(reads>=startReads+2,'at least two real polling cycles');
   assert.equal(await capital.evaluate(n=>document.activeElement===n),true,'polling keeps input focus');
   const stable=await page.evaluate(()=>({removed:refreshRemoved,retained:refreshNodes.every(n=>n.isConnected),scrollY}));
   assert.equal(stable.removed,0,'stable display elements must not be removed');assert.equal(stable.retained,true);assert.ok(Math.abs(before.scrollY-stable.scrollY)<=2,'polling keeps scroll position');
   evidence.push({width,draft:await capital.inputValue(),polls:reads-startReads,...stable});
   await capital.fill('');await page.waitForTimeout(1200);assert.equal(await capital.inputValue(),'','an incomplete draft stays empty');
   await capital.pressSequentially('725',{delay:400});assert.equal(await capital.inputValue(),'725','slow typing survives the one-second renderer');
   await card('C').getByRole('button',{name:'1000 USDT',exact:true}).click();await page.waitForTimeout(3200);assert.equal(await field('C','Бюджет').inputValue(),'1000','preset stays selected');
   await page.getByRole('button',{name:'Алерты',exact:true}).click();await page.getByRole('button',{name:'Модели',exact:true}).click();assert.equal(await capital.inputValue(),'725','navigation preserves draft');
   await capital.focus();mode='html';await until(()=>card('A').locator('.managed-badge').textContent().then(t=>t==='Нет управления'),'Gateway error not shown');
   assert.equal(await capital.isEnabled(),true,'offline drafts remain editable');assert.equal(await capital.evaluate(n=>document.activeElement===n),true,'a read error must not blur the draft');assert.equal(await newRun.isDisabled(),true,'offline commands stay disabled');
   await capital.fill('850');mode='stale';await page.getByRole('button',{name:'Проверить связь',exact:true}).click();assert.equal(await newRun.isDisabled(),true);assert.equal(await capital.inputValue(),'850');
   mode='ready';await page.getByRole('button',{name:'Проверить связь',exact:true}).click();await until(()=>newRun.isEnabled(),'Recovery not shown');assert.equal(await capital.inputValue(),'850');assert.equal(posts.length,0,'typing and snapshots never launch a test');
   await capital.fill('9');await newRun.click();assert.match(await card('A').locator('.control-response').textContent(),/Бюджет: от 10/);assert.equal(posts.length,0);
   await capital.fill('850');page.once('dialog',d=>d.dismiss());await newRun.click();assert.equal(posts.length,0,'cancelling confirmation preserves the draft');
   page.once('dialog',d=>d.accept());await newRun.click();await until(()=>card('A').locator('.control-response').textContent().then(t=>t.includes('Новый прогон принят')),'New run not accepted');
   assert.deepEqual(posts.at(-1).experiment,{capital:850,notional:50.25,max_loss:7.5},'the submitted settings come from the typed draft');
   await until(()=>capital.isEnabled(),'Draft locked after submission');await capital.fill('900');apply=true;
   await page.getByRole('button',{name:'Проверить связь',exact:true}).click();await until(()=>card('A').locator('.control-response').textContent().then(t=>t.includes('Новый PAPER-тест запущен')),'Execution not confirmed');
   assert.equal(await capital.inputValue(),'900','confirmation must not overwrite edits made after sending');assert.equal(await card('A').locator('.managed-metric strong').first().textContent(),'850','running settings stay separate from the new draft');
   page.once('dialog',d=>d.accept());await newRun.click();await until(()=>capital.isEnabled(),'Second draft locked after submission');apply=true;
   await page.getByRole('button',{name:'Проверить связь',exact:true}).click();await until(()=>card('A').locator('.control-response').textContent().then(t=>t.includes('Новый PAPER-тест запущен')),'Second execution not confirmed');
   settings={...settings,capital:1007};await page.getByRole('button',{name:'Проверить связь',exact:true}).click();await until(()=>capital.inputValue().then(v=>v==='1007'),'an applied, untouched form must follow confirmed server settings');
   const advanced=page.locator('.models-analysis');await advanced.locator('>summary').click();
   const condition=page.locator('#research-observations details').first();await condition.locator('>summary').click();await condition.locator('>summary').focus();
   await condition.evaluate(n=>window.keptCondition=n);await page.waitForTimeout(2200);assert.equal(await condition.getAttribute('open'),'');assert.equal(await condition.evaluate(n=>n===keptCondition),true);assert.equal(await condition.locator('>summary').evaluate(n=>document.activeElement===n),true,'expanded condition keeps keyboard focus');
   await advanced.locator('>summary').click();
   if(width!==320)await card('A').screenshot({path:path.join(root,'artifacts',`model-draft-refresh-${width}.png`)});
   if(width===1280){
    await page.getByRole('button',{name:'Обзор',exact:true}).click();
    await page.evaluate(()=>{
     const heading=[...document.querySelectorAll('#page-overview h2')].find(n=>n.textContent==='Качество данных');window.healthPanel=heading.parentElement;window.healthCleared=false;
     new MutationObserver(()=>{if(healthPanel.children.length<4)healthCleared=true;}).observe(healthPanel,{childList:true});
    });
    delayLive=true;await page.waitForTimeout(11200);assert.equal(await page.evaluate(()=>healthCleared),false,'the data-quality panel must not clear while a request is pending');delayLive=false;
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow at '+width);assert.deepEqual(errors,[],'browser errors at '+width);await page.close();
  }
  fs.writeFileSync(path.join(root,'artifacts','refresh-regression.json'),JSON.stringify(evidence,null,2));
  console.log('REFRESH UI OK: 1280/390/320; four model drafts, slow/empty input, presets, focus/scroll, navigation, failed/stale reads, recovery, exact PAPER payload, later edits, confirmed settings, stable expanded conditions and delayed health reads.');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
