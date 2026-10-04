/* Smart selection in an isolated preview; no production feeds or positions. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18792;
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];let mode='normal';page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/market-selection?*',async route=>{
    try{
    if(mode==='html')return route.fulfill({contentType:'text/html',body:'<html>temporarily unavailable</html>'});
    const response=await route.fetch(),data=await response.json();
    if(mode==='stale')for(const row of data.rows)row.selection.book_time=Date.now()/1000-60;
    if(mode==='pending')for(const row of data.rows)if(row.symbol==='BTCUSDT'){row.selection.status='pending';row.selection.samples=3;for(const c of row.selection.checks)if(['depth','book_spread','impact','coverage'].includes(c.key)){c.state='pending';c.value=null;}}
    await route.fulfill({response,json:data});
    }catch{try{await route.abort();}catch{}}
   });
   await page.goto(`http://127.0.0.1:${port}/`);
   await page.waitForFunction(()=>document.querySelectorAll('.selection-row[data-state=passed]').length===4);
   assert.equal(await page.locator('.selection-row[data-state=rejected]').count(),2);
   const btc=page.locator('#screener-table tbody tr',{has:page.getByRole('button',{name:'BTCUSDT',exact:true})});
   await btc.evaluate(el=>el.dataset.kept='yes');await btc.locator('.selection-row>summary').click();
   assert.match(await btc.locator('.selection-reasons').textContent(),/Открытый интерес.*20.*000.*000/);
   assert.match(await btc.locator('.selection-reasons').textContent(),/Снимки стакана: 5 \/ 5/);
   assert.equal(await btc.locator('.coin-price').evaluate(el=>{const r=el.getBoundingClientRect(),s=el.closest('.screener-scroll').getBoundingClientRect();return r.top>=s.top&&r.bottom<=s.bottom;}),true,'price remains visible when reasons open at '+width);
   await page.locator('.selection-panel>summary').click();
   assert.equal(await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).inputValue(),'20');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'open filters and reasons overflow at '+width);
   await page.screenshot({path:path.join(root,'artifacts',`selection-${width}.png`),fullPage:true});
   await page.waitForTimeout(2300);assert.equal(await btc.getAttribute('data-kept'),'yes');assert.equal(await btc.locator('.selection-row').getAttribute('open'),'');
   await page.getByLabel('Состояние отбора',{exact:true}).selectOption('passed');
   await page.waitForFunction(()=>document.querySelectorAll('#screener-table .coin-button').length===4);
   assert.equal(await page.locator('.selection-row[data-state=rejected]').count(),0);
   await page.getByLabel('Состояние отбора',{exact:true}).selectOption('all');
   await page.getByLabel('Спред до, %',{exact:true}).fill('-1');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   assert.equal(await page.getByLabel('Спред до, %',{exact:true}).getAttribute('aria-invalid'),'true');
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await page.getByLabel('Диапазон 24ч от, %',{exact:true}).fill('31');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   assert.match(await page.locator('.selection-message').textContent(),/Минимум/);
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).fill('500');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   await page.waitForFunction(()=>document.querySelectorAll('.selection-row[data-state=rejected]').length===6);
   await page.reload();await page.locator('.selection-panel>summary').click();
   assert.equal(await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).inputValue(),'500');
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await page.waitForFunction(()=>document.querySelectorAll('.selection-row[data-state=passed]').length===4);
   mode='pending';await page.waitForFunction(()=>[...document.querySelectorAll('.selection-reasons')].some(e=>e.textContent.includes('Снимки стакана: 3 / 5')));
   assert.match(await btc.locator('.selection-reasons').textContent(),/Снимки стакана: 3 \/ 5/);
   mode='stale';await page.waitForFunction(()=>[...document.querySelectorAll('.selection-reasons')].some(e=>e.textContent.includes('Данные проверки устарели')));
   assert.equal(await page.locator('.selection-row[data-state=passed]').count(),0);
   mode='html';await page.waitForFunction(()=>document.querySelector('.selection-summary')?.textContent.includes('Не удалось обновить'));
   assert.equal(await page.locator('.selection-row[data-state=passed]').count(),0);
   mode='normal';await page.waitForFunction(()=>document.querySelectorAll('.selection-row[data-state=passed]').length===4);
   await page.getByLabel('Поиск монеты',{exact:true}).fill('link');await page.waitForFunction(()=>document.querySelectorAll('#screener-table .coin-button').length===1);
   assert.equal(await page.locator('#screener-table .coin-button').textContent(),'LINKUSDT');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(errors,[],'browser errors at '+width);await page.unrouteAll({behavior:'wait'});await page.close();
  }
  console.log('Smart selection UI: thresholds, reasons, persistence, pending/stale/errors and widths 1280/390/320 passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
