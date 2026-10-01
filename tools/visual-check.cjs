/* Run with Playwright installed. Starts and stops its own synthetic preview. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');const path=require('node:path');const fs=require('node:fs');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const port=18788;
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});
 let browser;
 try{
  for(let i=0;i<50;i++){try{const r=await fetch(`http://127.0.0.1:${port}/`);if(r.ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [390,1280]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
   // Verify the isolated widget contract without making CI depend on market data availability.
   await page.route('https://s3.tradingview.com/**',route=>route.fulfill({contentType:'text/javascript',body:"document.getElementById('chart-status').textContent='TEST: external widget transport';"}));
   await page.goto(`http://127.0.0.1:${port}/`);
   await page.waitForSelector('.terminal-quote strong');
   await page.waitForTimeout(1000);
   await page.screenshot({path:path.join(root,'artifacts',`terminal-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'Загрузить TradingView',exact:true}).click();
   await page.waitForSelector('.chart-host iframe');
   assert.equal(await page.locator('.chart-host iframe').getAttribute('sandbox'),'allow-scripts allow-popups');
   await page.frameLocator('.chart-host iframe').locator('#chart-status').filter({hasText:'Внешние данные'}).waitFor();
   await page.getByLabel('Таймфрейм графика').selectOption('15');
   assert.match(await page.locator('.chart-host iframe').getAttribute('src'),/interval=15/);

   for(const name of ['Обзор','Рынок','LIVE','Grid','Тесты','Алерты']){
    await page.getByRole('button',{name,exact:true}).click();await page.waitForTimeout(200);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal overflow '+name);
   }
   await page.getByRole('button',{name:'LIVE',exact:true}).click();
   await page.screenshot({path:path.join(root,'artifacts',`liquidity-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'Алерты',exact:true}).click();
   await page.waitForSelector('.alert-long');
   assert.equal(await page.locator('.alert-card').count(),3);
   assert.equal(await page.locator('.alert-watch').count(),1);
   await page.locator('#page-alerts details').first().evaluate(e=>e.open=true);
   await page.waitForTimeout(2300);
   assert.equal(await page.locator('#page-alerts details').first().getAttribute('open'),'');
   assert.equal(await page.locator('.alert-event').count(),3,'duplicate events');
   await page.screenshot({path:path.join(root,'artifacts',`alerts-${width}.png`),fullPage:true});
   await page.getByLabel('Фильтр алертов').selectOption('entry');
   assert.equal(await page.locator('.alert-card').count(),2);
   await page.reload();await page.waitForSelector('#page-alerts:not([hidden])');await page.waitForSelector('.alert-long');
   assert.equal(await page.locator('.alert-event').count(),3,'history must survive reload without duplicates');
   const frozen=await page.evaluate(()=>Date.now());
   await page.evaluate(t=>{Date.now=()=>t+20000},frozen);
   await page.waitForTimeout(1300);
   assert.equal(await page.locator('.alert-long,.alert-short').count(),0,'expired entry remains colored');
   assert.ok(await page.locator('.event-neutral').count()>=2,'entry cancellations visible');
   await page.getByRole('button',{name:'Обзор',exact:true}).click();
   await page.waitForTimeout(1100);
   assert.equal(await page.locator('.terminal-quote strong').textContent(),'—');
   assert.deepEqual(errors,[]);
   await page.close();
  }
  console.log('VISUAL OK: 390/1280 px, six tabs, cards, filters, preserved details, deduplication, stale signals');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
