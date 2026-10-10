/* Smart selection and ranking in an isolated preview; no production feeds or positions. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18792;
async function until(predicate){const end=Date.now()+15000;while(Date.now()<end){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw Error('Selection condition was not met within 15 seconds');}
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
    if(mode==='mismatch')data.source_time-=5;
    if(mode==='invalid_rating')for(const row of data.rows)row.selection.rating.score=101;
    if(mode==='stale')for(const row of data.rows)row.selection.book_time=Date.now()/1000-60;
    if(mode==='pending')for(const row of data.rows)if(row.symbol==='BTCUSDT'){row.selection.status='pending';row.selection.samples=3;for(const c of row.selection.checks)if(['depth','book_spread','impact','coverage'].includes(c.key)){c.state='pending';c.value=null;}}
    await route.fulfill({response,json:data});
    }catch{try{await route.abort();}catch{}}
   });
   await page.goto(`http://127.0.0.1:${port}/`);
   await until(async()=>await page.locator('.selection-row[data-state=passed]').count()===4);
   assert.equal(await page.locator('.selection-row[data-state=rejected]').count(),2);
   assert.equal(await page.locator('.selection-row[data-rating=pending]').count(),0);
   await page.getByRole('button',{name:'Пересортировать',exact:true}).click();
   assert.deepEqual(await page.locator('#screener-table .coin-button').allTextContents(),['BTCUSDT','ETHUSDT','SOLUSDT','LINKUSDT','ONDOUSDT','AVAXUSDT'],'rating sort keeps passed candidates first');
   const btc=page.locator('#screener-table tbody tr',{has:page.getByRole('button',{name:'BTCUSDT',exact:true})});
   assert.equal(await btc.locator('.selection-row').getAttribute('data-rating'),'83');
   assert.equal(await btc.locator('.rating-compact').textContent(),'Рейтинг: 83 / 100');
   await btc.evaluate(el=>el.dataset.kept='yes');
   if(width===1280){await btc.locator('.rating-button').click();assert.equal(await btc.locator('.rating-button').getAttribute('aria-expanded'),'true');}
   else await btc.locator('.selection-row>summary').click();
   assert.equal(await btc.locator('.rating-breakdown h3').textContent(),'Рейтинг: 83 / 100');
   assert.deepEqual(await btc.locator('.rating-part b').allTextContents(),['25 / 25','20 / 25','13 / 25','25 / 25']);
   assert.match(await btc.locator('.rating-breakdown').textContent(),/Ликвидность высокая.*320.*USDT.*Спред узкий.*0,01%.*Объём около среднего.*1×.*Стакан подтверждает.*5 снимков/);
   assert.equal(await btc.locator('.rating-part').last().evaluate(el=>{const r=el.getBoundingClientRect(),s=el.closest('.screener-scroll').getBoundingClientRect();return r.top>=s.top&&r.bottom<=s.bottom;}),true,'all four rating parts are visible when expanded at '+width);
   assert.match(await btc.locator('.selection-reasons').textContent(),/Открытый интерес.*20.*000.*000/);
   assert.match(await btc.locator('.selection-reasons').textContent(),/Снимки стакана: 5 \/ 5/);
   assert.equal(await btc.locator('.coin-price').evaluate(el=>{const r=el.getBoundingClientRect(),s=el.closest('.screener-scroll').getBoundingClientRect();return r.top>=s.top&&r.bottom<=s.bottom;}),true,'price remains visible when reasons open at '+width);
   await page.screenshot({path:path.join(root,'artifacts',`ranking-${width}.png`),fullPage:true});
   if(width===1280){
    await page.getByRole('button',{name:'Сортировать: Рейтинг',exact:true}).click();
    assert.deepEqual(await page.locator('#screener-table .coin-button').allTextContents(),['LINKUSDT','SOLUSDT','ETHUSDT','BTCUSDT','AVAXUSDT','ONDOUSDT'],'ascending rating keeps rejected candidates last');
    await page.getByRole('button',{name:'Сортировать: Рейтинг',exact:true}).click();
   }
   await page.locator('.ranking-method>summary').click();assert.match(await page.locator('.ranking-method').textContent(),/Четыре части по 25.*Шкала фиксирована/);await page.locator('.ranking-method>summary').click();
   await page.locator('.selection-panel>summary').click();
   assert.equal(await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).inputValue(),'20');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'open filters and reasons overflow at '+width);
   await page.screenshot({path:path.join(root,'artifacts',`selection-${width}.png`),fullPage:true});
   await page.waitForTimeout(2300);assert.equal(await btc.getAttribute('data-kept'),'yes');assert.equal(await btc.locator('.selection-row').getAttribute('open'),'');
   await page.getByLabel('Состояние отбора',{exact:true}).selectOption('passed');
   await until(async()=>await page.locator('#screener-table .coin-button').count()===4);
   assert.equal(await page.locator('.selection-row[data-state=rejected]').count(),0);
   await page.getByLabel('Состояние отбора',{exact:true}).selectOption('all');
   await page.getByLabel('Спред до, %',{exact:true}).fill('-1');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   assert.equal(await page.getByLabel('Спред до, %',{exact:true}).getAttribute('aria-invalid'),'true');
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await page.getByLabel('Диапазон 24ч от, %',{exact:true}).fill('31');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   assert.match(await page.locator('.selection-message').textContent(),/Минимум/);
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).fill('500');await page.getByRole('button',{name:'Применить отбор',exact:true}).click();
   await until(async()=>await page.locator('.selection-row[data-state=rejected]').count()===6);
   await page.reload();await page.locator('.selection-panel>summary').click();
   assert.equal(await page.getByLabel('Оборот 24ч от, млн USDT',{exact:true}).inputValue(),'500');
   await page.getByRole('button',{name:'Сбросить пороги',exact:true}).click();
   await until(async()=>await page.locator('.selection-row[data-state=passed]').count()===4);
   mode='pending';await until(async()=>await page.locator('.selection-reasons').filter({hasText:'Снимки стакана: 3 / 5'}).count()>0);
   assert.match(await btc.locator('.selection-reasons').textContent(),/Снимки стакана: 3 \/ 5/);
   assert.equal(await btc.locator('.selection-row').getAttribute('data-rating'),'pending');
   assert.equal(await btc.locator('.rating-button').textContent(),'Было 83');
   assert.match(await btc.locator('.rating-button').getAttribute('title'),/Последний подтверждённый рейтинг.*сейчас проверяется/);
   assert.match(await btc.locator('.rating-compact').textContent(),/Было 83 · проверяется/);
   assert.deepEqual(await btc.locator('.rating-part b').allTextContents(),['25 / 25','— / 25','13 / 25','— / 25'],'known parts remain visible without inventing or rescaling the total');
   mode='stale';await until(async()=>await page.locator('.selection-reasons').filter({hasText:'Данные проверки устарели'}).count()>0);
   assert.equal(await page.locator('.selection-row[data-state=passed]').count(),0);
   assert.equal(await page.locator('.selection-row[data-rating=pending]').count(),6);
   mode='html';await until(async()=> (await page.locator('.selection-summary').textContent()).includes('Не удалось обновить'));
   assert.equal(await page.locator('.selection-row[data-state=passed]').count(),0);
   assert.equal(await page.locator('.selection-row[data-rating=pending]').count(),6);
   mode='mismatch';await until(async()=>await page.locator('.selection-reasons').filter({hasText:'Ожидание проверки свежих котировок'}).count()===6);
   assert.equal(await page.locator('.selection-row[data-rating=pending]').count(),6);
   mode='invalid_rating';await until(async()=>await page.locator('.selection-row[data-state=passed]').count()===4);
   assert.equal(await page.locator('.selection-row[data-rating=pending]').count(),6,'malformed totals cannot be displayed or used for sorting');
   mode='normal';await until(async()=>await page.locator('.selection-row[data-state=passed]').count()===4&&await page.locator('.selection-row[data-rating=pending]').count()===0);
   if(width===1280){
    mode='html';await until(async()=> (await page.locator('.selection-summary').textContent()).includes('Не удалось обновить'));
    assert.equal(await btc.locator('.rating-breakdown h3').textContent(),'Рейтинг: Было 83 · проверяется');
    await btc.evaluate(el=>el.dataset.ratingExpiry='retained');
    const reasonsBefore=await btc.locator('.selection-reasons p').allTextContents();let clockOffset=0;
    await page.evaluate(()=>{
     const originalNow=Date.now,originalJson=Response.prototype.json;window.ratingExpiryClockOffset=0;
     Date.now=()=>originalNow()+window.ratingExpiryClockOffset;
     Response.prototype.json=async function(){const data=await originalJson.call(this);if(new URL(this.url).pathname==='/api/screener')window.ratingExpiryClockOffset=data.testClockOffset||0;return data;};
     window.restoreRatingExpiryClock=()=>{Date.now=originalNow;Response.prototype.json=originalJson;};
    });
    await page.route('**/api/screener',async route=>{const response=await route.fetch(),data=await response.json();data.updated+=clockOffset/1000;data.testClockOffset=clockOffset;await route.fulfill({response,json:data});});
    // Move browser time together with the fresh quote response; the pending verdict stays unchanged.
    clockOffset=301000;await until(async()=> (await btc.locator('.rating-button').textContent())==='—');
    assert.equal(await btc.getAttribute('data-rating-expiry'),'retained','expiry updates the existing row');
    assert.equal(await btc.locator('.rating-compact').textContent(),'Рейтинг: проверяется');
    assert.equal(await btc.locator('.rating-breakdown h3').textContent(),'Рейтинг: проверяется','expanded historical score expires with the button');
    assert.deepEqual(await btc.locator('.selection-reasons p').allTextContents(),reasonsBefore,'pending evidence stays unchanged during expiry');
    clockOffset=0;await page.evaluate(()=>window.restoreRatingExpiryClock());await page.unroute('**/api/screener');mode='normal';
    await until(async()=>await page.locator('.selection-row[data-state=passed]').count()===4&&await page.locator('.selection-row[data-rating=pending]').count()===0);
   }
   await page.getByLabel('Поиск монеты',{exact:true}).fill('link');await until(async()=>await page.locator('#screener-table .coin-button').count()===1);
   assert.equal(await page.locator('#screener-table .coin-button').textContent(),'LINKUSDT');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
   assert.deepEqual(errors,[],'browser errors at '+width);await page.unrouteAll({behavior:'wait'});await page.close();
  }
  console.log('Smart selection and ranking UI: score parts, ordering, thresholds, persistence, partial/stale/malformed/error data and widths 1280/390/320 passed');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
