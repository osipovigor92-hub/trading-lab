/* Changing forming candles, a stalled book, halted model B and tab resume. No exchange calls. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const port=18802,root=path.resolve(__dirname,'..');
const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:['ignore','ignore','pipe']});
server.stderr.on('data',data=>process.stderr.write(data));
async function until(fn,label,timeout=12000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error(label);}
(async()=>{let browser;const evidence=[];
 try{
  await until(async()=>{try{return(await fetch('http://127.0.0.1:'+port+'/')).ok;}catch{return false;}},'preview startup',30000);
  browser=await chromium.launch({headless:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:850}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
   let updates=0,chartReads=0,bookReads=0,viewReads=0,bookActive=0,bookPeak=0,stale=false;
   await page.route('https://**/*',r=>r.abort());
   await page.route('**/api/model-b',async r=>{const response=await r.fetch(),data=await response.json();data.phase='halted';data.updated=0;data.observations=[];await r.fulfill({response,json:data});});
   await page.route('**/api/market-chart?**',async r=>{chartReads++;const response=await r.fetch(),data=await response.json();const price=data.price*(1+.0001*(++updates));data.current_candle={time:data.candle_end,open:data.price,high:Math.max(data.price,price)*1.0001,low:Math.min(data.price,price)*.9999,close:price,volume:10,turnover:price*10,confirmed:false};await r.fulfill({response,json:data});});
   await page.route('**/api/market-book?**',async r=>{bookReads++;bookActive++;bookPeak=Math.max(bookPeak,bookActive);await new Promise(resolve=>setTimeout(resolve,3500));try{await r.continue();}catch{}finally{bookActive--;}});
   await page.route('**/api/market-view?**',async r=>{viewReads++;const response=await r.fetch(),data=await response.json();if(stale)data.book.updated-=20;await r.fulfill({response,json:data});});
   const started=Date.now();await page.goto('http://127.0.0.1:'+port+'/');
   await page.locator('#screener-candles svg').waitFor({state:'attached'});const firstChartMs=Date.now()-started;
   const marker=page.locator('#screener-candles .chart-close-text'),first=await marker.textContent();
   await until(async()=>await marker.textContent()!==first,'chart must update while a book request is stalled');
   assert.ok(chartReads>=2);assert.equal(bookPeak,1,'the book requests do not pile up');
   await page.evaluate(()=>LabNavigation.activate('chart'));
   const native=page.frameLocator('.chart-host iframe');await native.locator('svg').waitFor();
   assert.equal(await native.locator('iframe').count(),0,'local chart is automatic and has no external provider');
   await until(async()=>await page.locator('.terminal-quote strong').textContent()!=='—','market price survives halted model B');
   const frame=await page.locator('.chart-host iframe').elementHandle();await page.evaluate(el=>window.savedMarketFrame=el,frame);
   const nativeFirst=await native.locator('.price').textContent();await until(async()=>await native.locator('.price').textContent()!==nativeFirst,'local chart must animate the open candle');
   assert.equal(await page.locator('.chart-host iframe').evaluate(el=>el===savedMarketFrame),true,'polling must retain the frame');
   await page.getByLabel('Контракт для анализа').selectOption('ETHUSDT');await until(async()=>/ETHUSDT/.test(await native.locator('#chart-status').textContent()),'coin switch must select ETH');
   await page.getByLabel('Таймфрейм графика').selectOption('15');await until(async()=>/15м/.test(await native.locator('#chart-status').textContent()),'timeframe switch');
   stale=true;await until(async()=>await page.locator('.terminal-quote strong').textContent()==='—','stale book must hide current price');
   assert.ok(await native.locator('svg').count(),'stale book must not remove independent candles');stale=false;
   await until(async()=>await page.locator('.terminal-quote strong').textContent()!=='—','recovery restores market price');
   await page.evaluate(()=>LabNavigation.activate('live'));await until(async()=>await page.locator('.liquidity-workspace .liquidity-row').count()===3,'LIVE depth works without the model');
   const before=viewReads;await page.evaluate(()=>LabNavigation.activate('research'));await page.waitForTimeout(2500);assert.ok(viewReads<=before+1,'hidden market panels stop polling');
   await page.evaluate(()=>LabNavigation.activate('chart'));await until(async()=>viewReads>before+1,'market resumes immediately');
   if(width!==320){fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});await page.locator('#page-chart').screenshot({path:path.join(root,'artifacts','live-chart-'+width+'.png')});}
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'no page overflow');assert.deepEqual(errors,[]);
   evidence.push({width,firstChartMs,chartReads,bookReads,bookPeak,viewReads});await page.unrouteAll({behavior:'ignoreErrors'});await page.close();
  }
  fs.writeFileSync(path.join(root,'artifacts','live-chart-check.json'),JSON.stringify(evidence,null,2));console.log('LIVE CHART UI OK: auto local chart, open-candle updates despite a slow book, retained frame, halted B, coin/timeframe switch, stale data, recovery and paused/resumed polling.');
 }finally{if(browser){for(const context of browser.contexts())for(const page of context.pages())await page.unrouteAll({behavior:'ignoreErrors'});await browser.close();}server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
