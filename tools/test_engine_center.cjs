/* Exercise the working center against the isolated synthetic controller. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const port=18791,root=path.resolve(__dirname,'..');
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[],requests=[];
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/models-control')&&r.method()==='POST')requests.push(r.postDataJSON());});
   await page.goto(`http://127.0.0.1:${port}/`);await page.getByRole('button',{name:'Модели',exact:true}).click();
   const center=page.locator('#engine-test-center'),worker=page.locator('#pc-worker-status'),launch=center.getByRole('button',{name:/^(Запустить|Повторить) выбранный тест$/}),stop=center.getByRole('button',{name:'Остановить текущий тест',exact:true});
   await worker.getByText('Мой ПК подключён',{exact:true}).waitFor();assert.equal(await page.getByLabel('Исполнитель внешнего теста').inputValue(),'pc');
   assert.equal(await launch.isEnabled(),true);assert.equal(await stop.isDisabled(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'initial overflow at '+width);
   if(width!==320)await page.locator('.engine-workbench').screenshot({path:path.join(root,'artifacts',`engine-center-${width}.png`)});
   await launch.click();await center.locator('.engine-session-title').filter({hasText:/Freqtrade.*Мой ПК.*Работает/}).waitFor();
   assert.equal(requests.at(-1).execution,'pc');assert.equal(requests.at(-1).target,'freqtrade');assert.equal(await stop.isEnabled(),true);assert.equal(await launch.isDisabled(),true);
   assert.equal(await center.locator('.engine-test-stages [aria-current="step"]').textContent(),'Расчёт');
   await page.getByLabel('Движок внешнего теста').selectOption('jesse');assert.equal(await launch.isDisabled(),true);assert.match(await center.locator('.engine-launch-note').textContent(),/Слот занят: Freqtrade.*Мой ПК/);
   await stop.click();await center.locator('.engine-result-stamp').filter({hasText:'Тест отменён'}).waitFor();
   assert.equal(requests.at(-1).target,'freqtrade');assert.equal(requests.at(-1).action,'stop');assert.equal(requests.at(-1).execution,'pc');
   assert.equal(await center.locator('.engine-result-metrics dd').count(),0,'cancelled run must not inherit earlier metrics');assert.equal(await stop.isDisabled(),true);
   const csv=await page.request.get(`http://127.0.0.1:${port}/api/engine-journal?engine=freqtrade`);assert.match(await csv.text(),/,pc,cancelled,/);
   await page.reload();await worker.getByText('Мой ПК подключён',{exact:true}).waitFor();assert.equal(await page.getByLabel('Исполнитель внешнего теста').inputValue(),'pc');
   let mode='ready',acceptOnly=false;
   await page.route('**/api/models-control',async route=>{
    if(route.request().method()==='POST'){
     if(acceptOnly)return route.fulfill({contentType:'application/json',body:JSON.stringify({status:'accepted',id:'ACCEPTED-FIXTURE'})});
     return route.continue();
    }
    if(mode==='html')return route.fulfill({status:502,contentType:'text/html',body:'<html>Gateway fixture</html>'});
    const response=await route.fetch(),data=await response.json();
    if(mode==='small-vds'){data.memory={total_gb:.94,available_gb:.2};for(const e of data.engines)Object.assign(e.executors.vds,{memory_ok:false,reason:'На VDS недостаточно памяти для внешнего теста',actions:{}});}
    if(mode==='offline'||mode==='lost'){
     data.worker.online=false;data.worker.last_seen=Date.now()/1000-20;
     for(const e of data.engines)Object.assign(e.executors.pc,{memory_ok:false,actions:{},reason:'ПК не отвечает'});
    }
    if(mode==='lost'){
     const ft=data.engines.find(e=>e.id==='freqtrade');ft.test_active=true;Object.assign(ft.executors.pc,{phase:'lost',test_active:true,actions:{stop:true}});
     data.worker.job={engine:'freqtrade',phase:'lost'};
    }
    if(mode==='stale')data.updated-=20;
    await route.fulfill({response,json:data});
   });
   const refresh=worker.getByRole('button',{name:'Проверить связь',exact:true});
   mode='small-vds';await page.getByLabel('Исполнитель внешнего теста').selectOption('vds');await refresh.click();
   await center.locator('.engine-launch-note').filter({hasText:'На VDS недостаточно памяти'}).waitFor();assert.equal(await launch.isDisabled(),true);
   await page.getByLabel('Исполнитель внешнего теста').selectOption('pc');assert.equal(await launch.isEnabled(),true,'the PC remains usable on a small VDS');
   mode='offline';await refresh.click();await worker.getByText('Мой ПК не подключён',{exact:true}).waitFor();assert.equal(await launch.isDisabled(),true);assert.match(await worker.textContent(),/ПК уже привязан/);assert.equal(await worker.locator('dd').nth(1).textContent(),'—');
   await worker.locator('.worker-help>summary').click();assert.match(await worker.locator('code').textContent(),/integrations\/worker\/agent.py/);await worker.locator('.worker-help>summary').click();
   mode='lost';await refresh.click();await center.locator('.engine-session-title').filter({hasText:'ПК потерял связь'}).waitFor();assert.equal(await stop.isEnabled(),true);assert.equal(await launch.isDisabled(),true);assert.match(await center.locator('.engine-session>p').textContent(),/удерживает слот/);
   mode='stale';await refresh.click();await center.locator('.engine-session-title').filter({hasText:'Состояние слота не подтверждено'}).waitFor();assert.equal(await stop.isDisabled(),true);assert.equal(await launch.isDisabled(),true);
   assert.doesNotMatch(await page.locator('#models-ops-overview').textContent(),/Свободно|Подключён/);assert.match(await worker.textContent(),/Связь с ПК не подтверждена/);
   mode='html';await refresh.click();assert.equal(await launch.isDisabled(),true);assert.equal(await stop.isDisabled(),true);assert.match(await worker.textContent(),/Связь с ПК не подтверждена/);
   mode='ready';await refresh.click();await worker.getByText('Мой ПК подключён',{exact:true}).waitFor();assert.equal(await launch.isEnabled(),true);
   acceptOnly=true;await launch.click();await center.locator('.control-response').filter({hasText:'Команда принята'}).waitFor();
   assert.equal(await launch.isDisabled(),true,'accepted request is not yet an executed process');assert.equal(await stop.isDisabled(),true,'no cancel action is invented before the broker advertises one');
   assert.match(await center.locator('.engine-session-title').textContent(),/Freqtrade.*Мой ПК.*Применяет команду/);
   await page.getByLabel('Движок внешнего теста').selectOption('jesse');assert.equal(await launch.isDisabled(),true,'accepted request keeps the other engine from starting');
   assert.equal(await page.locator('.managed-card[data-model="jesse"] button[data-action="start"]').isDisabled(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'state overflow at '+width);assert.deepEqual(errors,[]);await page.close();
  }
  console.log('ENGINE CENTER OK: 320/390/1280 px; PC launch/cancel/CSV, pending confirmation, single slot, RAM, lost/stale/HTML responses, recovery and reload');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
