/* Real temporary PAPER ledger behind the UI; no production files or market feeds. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const {fixture}=require('./paper_plan_fixture.cjs');
const root=path.resolve(__dirname,'..'),port=18795;
async function until(predicate){const end=Date.now()+15000;while(Date.now()<end){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw Error('Positions condition was not met within 15 seconds');}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port),'--paper-test'],{cwd:root,stdio:['ignore','pipe','pipe']});let serverLog='';server.stderr.on('data',s=>serverLog+=s);let browser;
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}/api/manual-paper`).then(r=>r.ok).catch(()=>false));
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:950},deviceScaleFactor:1}),errors=[],posts=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push({path:new URL(r.url()).pathname,body:JSON.parse(r.postData())});});
   const opened=Math.floor(Date.now()/1000)-20;let stale=false,manualOffline=false,failOpenOnce=false;
   await page.route(/\/api\/(paper|model-b|research)(?:\?|$)/,async route=>{
    const res=await route.fetch(),data=await res.json(),kind=new URL(route.request().url()).pathname,now=Date.now()/1000;
    const position={symbol:'BTCUSDT',side:1,entry:99,quantity:1,entry_fee:.055,opened,quote_time:now,funding:0};
    if(kind==='/api/paper'){data.position={...position,symbol:'ONDOUSDT'};data.phase='running';data.updated=data.market_time=stale?now-100:now;data.balance=599.945;data.equity=600.4;}
    if(kind==='/api/model-b'){data.position={...position,side:-1,stop_usdt:.7,target_usdt:1.05};data.phase='halted';data.updated=now-100;}
    if(kind==='/api/research'){data.updated=now;for(const [id,m]of Object.entries(data.models)){m.phase='running';m.position=id==='C'?{...position,symbol:'ETHUSDT'}:null;m.balance=599.945;m.equity=600.4;}}
    await route.fulfill({response:res,json:data});
   });
   await page.route('**/api/models-control',async route=>{if(route.request().method()==='POST')return route.continue();const res=await route.fetch(),data=await res.json();for(const m of data.models){m.unit_active=m.id==='B'?'inactive':'active';if(m.id==='B'){m.fresh=false;m.phase='halted';}m.position=m.id==='D'?null:{symbol:m.id==='C'?'ETHUSDT':'BTCUSDT',side:m.id==='B'?-1:1,opened};}await route.fulfill({response:res,json:data});});
   await page.route(/\/api\/(screener|market-chart|market-book|market-selection)(?:\?|$)/,async route=>{const url=new URL(route.request().url()),kind=url.pathname.split('/').at(-1),now=Math.floor(Date.now()/5000)*5,f=fixture(1,url.searchParams.get('interval')||'5',now),symbol=url.searchParams.get('symbol')||'BTCUSDT';f.chart.symbol=f.book.symbol=symbol;let value=kind==='screener'?{...f.snapshot,rows:['BTCUSDT','ETHUSDT'].map(s=>({...f.snapshot.rows[0],symbol:s}))}:kind==='market-selection'?{...f.selectionPacket,rows:['BTCUSDT','ETHUSDT'].map(s=>({symbol:s,selection:f.selectionPacket.rows[0].selection}))}:kind==='market-chart'?f.chart:f.book;await route.fulfill({contentType:'application/json',json:value});});
   await page.route('**/api/manual-paper',async route=>{
    if(route.request().method()==='GET'&&manualOffline)return route.fulfill({contentType:'text/html',body:'<html>unavailable</html>'});
    if(route.request().method()==='POST'&&failOpenOnce&&JSON.parse(route.request().postData()).action==='open'){failOpenOnce=false;const res=await route.fetch();assert.equal(res.status(),202);return route.abort('failed');}
    await route.continue();
   });
   await page.goto(`http://127.0.0.1:${port}/`);
   await page.evaluate(()=>LabNavigation.activate('positions'));const positions=page.locator('#page-positions'),manual=page.locator('#manual-paper'),row=id=>positions.locator(`[data-model=${id}]`);
   await until(()=>row('B').locator('.position-symbol').textContent().then(t=>t.includes('сохранённая')));
   assert.equal(await positions.locator('[data-model]').count(),4);assert.equal(await row('B').locator('dd').nth(1).textContent(),'—');assert.equal(await row('B').locator('dd').nth(2).textContent(),'−0,7');assert.equal(await row('B').locator('dd').nth(3).textContent(),'+1,05');
   assert.match(await row('C').locator('.position-symbol').textContent(),/ETHUSDT/);assert.match(await row('D').locator('.position-symbol').textContent(),/нет/);assert.equal(await positions.getByRole('button',{name:'Пауза B',exact:true}).isDisabled(),true);
   await until(()=>manual.getByRole('button',{name:'Пауза ручных входов',exact:true}).isEnabled());
   if(width===1280){await until(()=>row('A').locator('dd').nth(1).textContent().then(t=>t!=='—'));await positions.getByRole('button',{name:'Пауза A',exact:true}).click();await until(()=>row('A').locator('.position-response').textContent().then(t=>t.includes('подтверждена')));const post=posts.find(p=>p.body.target==='A');assert.deepEqual(Object.keys(post.body).sort(),['action','generation','target']);assert.equal(post.body.action,'stop');stale=true;await until(()=>row('A').locator('dd').nth(1).textContent().then(t=>t==='—'));stale=false;}
   await manual.getByRole('button',{name:'Пауза ручных входов',exact:true}).click();await until(()=>manual.getByRole('button',{name:'Разрешить ручные входы',exact:true}).isEnabled());
   await page.evaluate(()=>LabNavigation.activate('market'));const plan=page.locator('#screener-plan');await until(()=>plan.getAttribute('data-state').then(s=>s==='ready'));
   await plan.getByRole('button',{name:'Подготовить ручной PAPER-вход',exact:true}).click();await until(()=>manual.locator('.manual-review').isVisible());const open=manual.getByRole('button',{name:'Открыть виртуальную позицию',exact:true});assert.equal(await open.isDisabled(),true);
   await manual.getByRole('button',{name:'Разрешить ручные входы',exact:true}).click();await until(()=>open.isEnabled());
   await page.getByLabel('Причина ручного входа',{exact:true}).fill('Проверка виртуального входа со стопом');
   failOpenOnce=width===1280;await open.click();if(width===1280){const retry=manual.getByRole('button',{name:'Повторить тот же PAPER-запрос',exact:true});await until(()=>retry.isVisible());await retry.click();await until(()=>retry.isHidden());const opens=posts.filter(p=>p.path==='/api/manual-paper'&&p.body.action==='open');assert.equal(opens.length,2);assert.deepEqual(opens[0].body,opens[1].body);}
   await until(()=>manual.locator('.position-symbol').textContent().then(t=>t.includes('BTCUSDT')));assert.match(await manual.locator('.position-reason').textContent(),/Проверка/);assert.equal(await manual.locator('.manual-review').isHidden(),true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);assert.equal(await manual.getByRole('button',{name:'Закрыть ручную PAPER-позицию',exact:true}).evaluate(n=>n.getBoundingClientRect().height>=44),true);
   await positions.screenshot({path:path.join(root,'artifacts',`positions-${width}.png`)});
   await page.reload();await until(()=>manual.getByRole('button',{name:'Закрыть ручную PAPER-позицию',exact:true}).isEnabled());assert.match(await manual.locator('.position-reason').textContent(),/Проверка/);
   manualOffline=true;await until(()=>manual.getByRole('button',{name:'Закрыть ручную PAPER-позицию',exact:true}).isDisabled());assert.match(await manual.locator('dd').nth(1).textContent(),/—/);manualOffline=false;await until(()=>manual.getByRole('button',{name:'Закрыть ручную PAPER-позицию',exact:true}).isEnabled());
   await manual.getByRole('button',{name:'Пауза ручных входов',exact:true}).click();await until(()=>manual.getByRole('button',{name:'Разрешить ручные входы',exact:true}).isEnabled());await manual.getByRole('button',{name:'Закрыть ручную PAPER-позицию',exact:true}).click();await until(()=>manual.locator('.position-symbol').count().then(n=>n===0));await until(()=>positions.locator('.manual-trade').count().then(n=>n>=1));
   await manual.getByRole('button',{name:'Разрешить ручные входы',exact:true}).click();await until(()=>manual.getByRole('button',{name:'Пауза ручных входов',exact:true}).isEnabled());
   assert.deepEqual(errors,[]);assert.equal(posts.some(p=>p.path!=='/api/manual-paper'&&p.path!=='/api/models-control'),false);await page.close();
  }
  console.log('Positions UI passed: desktop/mobile, saved B, model pause, real manual entry/close/reload, idempotent response retry, pause and offline state.');
 }catch(e){console.error(serverLog);throw e;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
