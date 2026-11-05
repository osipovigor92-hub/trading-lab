/* Alert annotations on the native chart, with synthetic market events. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18829,url='http://127.0.0.1:'+port,widths=process.env.ALERT_CHART_WIDTHS?process.env.ALERT_CHART_WIDTHS.split(',').map(Number):[1280,390,320];
async function until(check,label){const limit=Date.now()+15000;while(Date.now()<limit){if(await check())return;await new Promise(r=>setTimeout(r,60));}throw Error(label);}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:['ignore','ignore','pipe']});let browser,log='';server.stderr.on('data',data=>log+=data);
 try{
  await until(()=>fetch(url+'/').then(r=>r.ok).catch(()=>false),'preview starts');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  for(const width of widths){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[],commands=[];let offline=false;
   const at=Date.now()/1000,sources={quote:at,chart:at,candle:Math.floor(at/60)*60,book:at,fetched:at};
   const event=(id,symbol,kind,label,extras)=>({id:'alert-chart:'+id,sequence:id,symbol,kind,label,detail:'Синтетическое наблюдение',time:at,expires:at+30,sources,...extras});
   const events=[
    event(1,'LINKUSDT','near_level','Цена у уровня',{level:{side:'support',low:13.95,high:14.05},price:14.12}),
    event(2,'BTCUSDT','breakout_up','Пробой вверх',{exchange:'bybit',breakout_level:59920,price:60020}),
    event(3,'SOLUSDT','momentum_up','Импульс вверх',{exchange:'bybit',breakout_level:144,price:145.2}),
    event(4,'ETHUSDT','near_level','Старый алерт без уровня',{})
   ];
   const manual=JSON.stringify({'bybit:LINKUSDT':[{id:'existing',type:'support',price:13.75}]});
   await page.addInitScript(({manual,light})=>{if(!sessionStorage.getItem('alert-chart-fixture')){sessionStorage.setItem('alert-chart-fixture','1');localStorage.setItem('lab-chart-levels-v1',manual);localStorage.setItem('lab-ui-theme',light?'light':'dark');}}, {manual,light:width===390});
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET')commands.push(r.url());});
   await page.route('**/api/market-alerts?*',r=>r.fulfill(offline?{status:503,json:{error:'fixture unavailable'}}:{json:{status:'ok',updated:Date.now()/1000,epoch:'alert-chart',scope:'fixture',cursor:4,events,rows:[],analyzing:[]}}));
   await page.goto(url+'/');await page.getByRole('button',{name:'Алерты',exact:true}).click();
   const feed=page.locator('#fresh-alert-events'),history=page.locator('#fresh-alert-history'),dialog=page.locator('.exchange-chart-dialog'),host=dialog.locator('.exchange-chart-host');
   const lines=()=>host.evaluate(n=>n.labExchangeChart.getLevels().filter(l=>l.id.startsWith('alert:')).map(l=>l.price));
   const open=async(container,symbol)=>{await container.getByRole('button',{name:'График алерта '+symbol,exact:true}).click();await dialog.waitFor();assert.equal(await dialog.getAttribute('data-symbol'),symbol);await until(()=>host.getAttribute('data-chart-source').then(s=>s==='bybit:'+symbol+':1'),'alert opens correct 1m source');};
   const close=async()=>{await dialog.getByRole('button',{name:'Закрыть',exact:true}).click();await dialog.waitFor({state:'hidden'});await until(()=>lines().then(x=>x.length===0),'closed modal clears alert lines');};
   await open(feed,'LINKUSDT');assert.deepEqual(await lines(),[13.95,14.05]);assert.equal(await host.getAttribute('data-chart-manual-levels'),'1');
   assert.match(await dialog.locator('.exchange-chart-alert').textContent(),/Поддержка: 13,95–14,05 USDT/);
   await until(()=>host.getAttribute('data-chart-confirmed').then(x=>x==='true'),'real native chart loads fixture candles');
   await until(()=>host.evaluate(n=>[13.95,14.05].every(p=>{const y=n.labExchangeChart.priceToCoordinate(p);return Number.isFinite(y)&&y>=0&&y<=n.querySelector('.exchange-chart-plot').clientHeight;})),'saved zone is in view');
   assert.equal(await dialog.evaluate(n=>n.scrollWidth>n.clientWidth),false,'dialog fits '+width);
   if(process.env.ALERT_CHART_CAPTURE==='1'){fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});await page.screenshot({path:path.join(root,'artifacts','alert-chart-'+width+'.png')});}
   await dialog.getByRole('button',{name:'5м',exact:true}).click();assert.deepEqual(await lines(),[13.95,14.05],'period switch preserves saved zone');
   await close();
   await open(feed,'BTCUSDT');assert.deepEqual(await lines(),[59920],'use original breakout boundary, not signal close');assert.match(await dialog.locator('.exchange-chart-alert').textContent(),/Граница пробоя вверх/);await close();
   await open(feed,'SOLUSDT');assert.deepEqual(await lines(),[145.2],'momentum uses observed price, not an older breakout');assert.match(await dialog.locator('.exchange-chart-alert').textContent(),/Цена при алерте/);await close();
   await open(feed,'ETHUSDT');assert.deepEqual(await lines(),[]);assert.match(await dialog.locator('.exchange-chart-alert').textContent(),/Уровень не сохранён/);await close();
   offline=true;await page.reload();await page.locator('.fresh-alert-history>summary').click();
   await open(history,'LINKUSDT');assert.deepEqual(await lines(),[13.95,14.05],'stored historical event works during alert API outage');await close();
   await page.evaluate(()=>document.dispatchEvent(new CustomEvent('lab-exchange-chart',{detail:{exchange:'bybit',symbol:'LINKUSDT',interval:'1'}})));
   await dialog.waitFor();assert.deepEqual(await lines(),[],'normal chart does not inherit alert overlay');assert.equal(await host.getAttribute('data-chart-manual-levels'),'1');assert.equal(await dialog.locator('.exchange-chart-alert').isVisible(),false);await close();
   assert.equal(await page.evaluate(()=>localStorage.getItem('lab-chart-levels-v1')),manual,'opening an alert does not persist a manual level');
   assert.deepEqual(commands,[]);assert.deepEqual(errors,[]);await page.close();
  }
  console.log('Alert chart UI passed: '+widths.join('/')+'px; exact zone and breakout, price-only fallback, saved history, fit, timeframe, isolation, no commands.');
 }catch(error){console.error(log);throw error;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
