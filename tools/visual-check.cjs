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
   await page.route('https://www.tradingview-widget.com/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><title>Chart fixture</title><p>Provider fixture</p>'}));
   await page.goto(`http://127.0.0.1:${port}/`);
   await page.waitForSelector('.terminal-quote strong');
   await page.waitForTimeout(1000);
   await page.screenshot({path:path.join(root,'artifacts',`terminal-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'Загрузить TradingView',exact:true}).click();
   await page.waitForSelector('.chart-host iframe');
   assert.equal(await page.locator('.chart-host iframe').getAttribute('sandbox'),'allow-scripts allow-same-origin allow-popups');
   await page.frameLocator('.chart-host iframe').locator('#chart-status').filter({hasText:'Внешние данные'}).waitFor();
   await page.getByLabel('Таймфрейм графика').selectOption('15');
   assert.match(await page.locator('.chart-host iframe').getAttribute('src'),/interval=15/);

   for(const name of ['Обзор','Скринер','LIVE','Grid','Тесты','Алерты','Модели']){
    await page.getByRole('button',{name,exact:true}).click();await page.waitForTimeout(200);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal overflow '+name);
   }
   await page.getByRole('button',{name:'Скринер',exact:true}).click();
   await page.waitForSelector('#screener-table tbody .coin-button');
   assert.equal(await page.locator('#screener-table tbody tr').count(),4);
   await page.getByLabel('Поиск монеты').fill('ondo');
   assert.equal(await page.locator('#screener-table tbody tr').count(),1);
   await page.getByRole('button',{name:'ONDOUSDT',exact:true}).click();
   await page.waitForSelector('#screener-candles svg');
   await page.waitForSelector('#screener-levels .level-item');
   assert.match(await page.locator('#screener-candles svg').getAttribute('aria-label'),/ONDOUSDT/);
   assert.equal(await page.locator('#screener-candles .volume-bar').count(),90);
   await page.waitForSelector('#screener-orderbook .book-band');
   assert.equal(await page.locator('#screener-orderbook .book-band').count(),3);
   assert.equal(await page.locator('#screener-bots article').count(),4);
   await page.getByLabel('Поиск монеты').fill('');
   await page.getByLabel('Подборка').selectOption('liquid');
   assert.equal(await page.locator('#screener-table tbody .coin-button').count(),2);
   await page.getByLabel('Подборка').selectOption('all');
   await page.getByLabel('Таймфрейм уровней').selectOption('15');
   await page.waitForSelector('#screener-candles svg');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'screener overflow');
   await page.screenshot({path:path.join(root,'artifacts',`screener-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'В обзор',exact:true}).click();
   assert.equal(await page.getByLabel('Контракт для анализа').inputValue(),'ONDOUSDT');
   await page.getByRole('button',{name:'Модели',exact:true}).click();
   await page.waitForSelector('#research-observations .research-card');
   assert.equal(await page.locator('#research-observations .research-card').count(),6);
   assert.equal(await page.locator('.research-catalog article').count(),3);
   assert.equal(await page.locator('#all-model-status article').count(),4);
   assert.equal(await page.locator('#research-paper-summary .research-card').count(),2);
   assert.equal(await page.locator('#research-journals a').count(),2);
   assert.match(await page.locator('#research-paper-summary').textContent(),/PAPER работает/);
   assert.equal(await page.locator('#page-research .alert-long,#page-research .alert-short').count(),0);
   await page.locator('#research-observations .research-card details').first().evaluate(e=>e.open=true);
   await page.waitForTimeout(1200);
   assert.equal(await page.locator('#research-observations .research-card details').first().getAttribute('open'),'');
   await page.screenshot({path:path.join(root,'artifacts',`research-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'LIVE',exact:true}).click();
   await page.screenshot({path:path.join(root,'artifacts',`liquidity-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'Алерты',exact:true}).click();
   await page.waitForSelector('#page-alerts .alert-long');
   assert.equal(await page.locator('.alert-card').count(),3);
   assert.equal(await page.locator('.alert-watch').count(),1);
   await page.locator('#page-alerts details').first().evaluate(e=>e.open=true);
   await page.waitForTimeout(2300);
   assert.equal(await page.locator('#page-alerts details').first().getAttribute('open'),'');
   assert.equal(await page.locator('#page-alerts .alert-event').count(),3,'duplicate events');
   await page.screenshot({path:path.join(root,'artifacts',`alerts-${width}.png`),fullPage:true});
   await page.getByLabel('Фильтр алертов').selectOption('entry');
   assert.equal(await page.locator('.alert-card').count(),2);
   await page.reload();await page.waitForSelector('#page-alerts:not([hidden])');await page.waitForSelector('#page-alerts .alert-long');
   assert.equal(await page.locator('#page-alerts .alert-event').count(),3,'history must survive reload without duplicates');
   const frozen=await page.evaluate(()=>Date.now());
   await page.evaluate(t=>{Date.now=()=>t+20000},frozen);
   await page.waitForTimeout(1300);
   assert.equal(await page.locator('.alert-long,.alert-short').count(),0,'expired entry remains colored');
   assert.ok(await page.locator('.event-neutral').count()>=2,'entry cancellations visible');
   await page.getByRole('button',{name:'Обзор',exact:true}).click();
   await page.waitForTimeout(1100);
   assert.equal(await page.locator('.terminal-quote strong').textContent(),'—');
   await page.getByRole('button',{name:'Модели',exact:true}).click();
   assert.equal(await page.locator('.research-match').count(),0);
   assert.match(await page.locator('#page-research').textContent(),/ОТЧЁТ УСТАРЕЛ/);
   await page.getByRole('button',{name:'Скринер',exact:true}).click();
   await page.evaluate(t=>{Date.now=()=>t+90000},frozen);
   await page.waitForTimeout(4500);
   assert.equal(await page.locator('#screener-table tbody .coin-button').count(),0,'expired tickers stay visible');
   assert.equal(await page.locator('#screener-orderbook .book-band').count(),0,'expired depth stays visible');
   assert.equal(await page.locator('#screener-candles svg').count(),0,'expired candles stay visible');
   assert.deepEqual(errors,[]);
   await page.close();
  }
  // Separate best-effort provider smoke test; never substitutes for the deterministic checks.
  const remote=await browser.newPage({viewport:{width:1280,height:900}}),providerErrors=[];
  remote.on('pageerror',e=>providerErrors.push(e.message));
  await remote.goto(`http://127.0.0.1:${port}/`);
  await remote.getByRole('button',{name:'Загрузить TradingView',exact:true}).click();
  await remote.waitForTimeout(15000);
  const provider={frames:remote.frames().map(f=>f.url()),errors:providerErrors,canvases:0};
  for(const frame of remote.frames())if(/tradingview/.test(frame.url()))provider.canvases+=await frame.locator('canvas').count().catch(()=>0);
  fs.writeFileSync(path.join(root,'artifacts','tradingview-smoke.json'),JSON.stringify(provider,null,2));
  await remote.locator('.chart-box').screenshot({path:path.join(root,'artifacts','tradingview-provider.png')});
  console.log('TradingView provider smoke:',JSON.stringify(provider));await remote.close();
  console.log('VISUAL OK: 390/1280 px, six tabs, cards, filters, preserved details, deduplication, stale signals');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
