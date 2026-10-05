/* Isolated synthetic coin-card checks, including independent source failures. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18793;
async function until(predicate){const end=Date.now()+15000;while(Date.now()<end){if(await predicate())return;await new Promise(r=>setTimeout(r,100));}throw Error('Coin card condition was not met within 15 seconds');}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:900}}),errors=[];let mode='normal';page.on('pageerror',e=>errors.push(e.message));
   await page.route(/\/api\/(screener|market-chart|market-book)(?:\?|$)/,async route=>{
    try{
     const url=new URL(route.request().url()),kind=url.pathname.split('/').at(-1),active=mode;
     if(active==='html')return route.fulfill({contentType:'text/html',body:'<html>temporarily unavailable</html>'});
     if(active==='race'&&kind==='market-chart'&&url.searchParams.get('symbol')==='BTCUSDT')await new Promise(r=>setTimeout(r,800));
     const response=await route.fetch(),data=await response.json(),now=Date.now()/1000;
     if(active==='stale_'+kind)data.updated=now-100;
     if(kind==='screener')for(const row of data.rows){
      if(active==='missing'){row.open_interest=null;row.funding=null;row.funding_interval_hours=null;}
      if(active==='negative'){row.funding=-.0002;row.funding_interval_hours=4;}
     }
     if(active==='partial'&&kind==='market-book')data.bands['0.001'].covered=false;
     if(active==='wrong'&&kind!=='screener')data.symbol='SOLUSDT';
     if(active==='flat'&&kind==='market-chart'){
      data.atr=0;data.atr_pct=0;data.volume_window=0;data.turnover_window=0;data.vwap=null;data.rvol=null;data.levels=[];
      for(const bar of data.candles){bar.open=bar.high=bar.low=bar.close=data.price;bar.volume=bar.turnover=0;}
     }
     await route.fulfill({response,json:data});
    }catch{try{await route.abort();}catch{}}
   });
   const card=page.locator('#screener-detail'),metric=key=>card.locator(`[data-metric=${key}] dd`),source=key=>card.locator(`[data-source=${key}]`);
   const allFresh=async()=>await card.locator('[data-source][data-state=fresh]').count()===3;
   await page.goto(`http://127.0.0.1:${port}/`);await until(allFresh);
   assert.equal(await card.locator('[data-metric]').count(),6);
   assert.match(await metric('oi').textContent(),/20.*000.*000/);assert.equal(await metric('funding').textContent(),'+0,01%');
   assert.match(await card.locator('[data-metric=funding] small').textContent(),/8 ч/);
   assert.match(await metric('volume').textContent(),/60.*000 BTC/);assert.match(await metric('atr').textContent(),/USDT/);
   await card.locator('[data-metric=price]').evaluate(el=>el.dataset.kept='yes');
   for(const [value,name,label]of [['1','1 минута','1м'],['5','5 минут','5м'],['15','15 минут','15м'],['60','1 час','1ч']]){
    await page.getByRole('button',{name,exact:true}).click();await until(allFresh);
    assert.equal(await card.getAttribute('data-interval'),value);assert.match(await card.locator('[data-metric=atr] dt').textContent(),new RegExp(label));
    assert.equal(await page.getByRole('button',{name,exact:true}).getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#screener-candles .volume-bar').count(),width===1280?90:45);
   }
   await page.getByRole('button',{name:'5 минут',exact:true}).click();await until(allFresh);
   await card.locator('.chart-analysis>summary').click();await until(async()=>await page.locator('#screener-levels .level-item').count()>0);
   await page.waitForTimeout(2100);assert.equal(await card.locator('.chart-analysis').getAttribute('open'),'');assert.equal(await card.locator('[data-metric=price]').getAttribute('data-kept'),'yes');
   await card.locator('.chart-analysis>summary').click();await card.scrollIntoViewIfNeeded();
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'card overflow at '+width);
   if(width!==1280)assert.equal(await page.getByRole('button',{name:'1 час',exact:true}).evaluate(el=>el.getBoundingClientRect().height>=44),true,'timeframe touch target');
   await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(root,'artifacts',`coin-card-${width}.png`),fullPage:true});
   mode='missing';await until(async()=>await metric('oi').textContent()==='—');assert.equal(await metric('funding').textContent(),'—');assert.notEqual(await metric('price').textContent(),'—');assert.equal(await source('ticker').getAttribute('data-state'),'fresh');
   mode='negative';await until(async()=>await metric('funding').textContent()==='-0,02%');assert.match(await card.locator('[data-metric=funding] small').textContent(),/4 ч/);
   mode='stale_screener';await until(async()=>await source('ticker').getAttribute('data-state')==='stale');
   for(const key of ['price','oi','funding'])assert.equal(await metric(key).textContent(),'—');assert.notEqual(await metric('atr').textContent(),'—');assert.equal(await page.locator('#screener-candles svg').count(),1);
   mode='normal';await until(allFresh);
   mode='stale_market-chart';await until(async()=>await source('chart').getAttribute('data-state')==='stale');
   for(const key of ['atr','volume','vwap'])assert.equal(await metric(key).textContent(),'—');assert.notEqual(await metric('oi').textContent(),'—');assert.equal(await page.locator('#screener-candles svg').count(),0);assert.equal(await page.locator('#screener-levels .level-item').count(),0);
   mode='normal';await until(allFresh);
   mode='stale_market-book';await until(async()=>await source('book').getAttribute('data-state')==='stale');assert.equal(await page.locator('.book-total').count(),0);assert.equal(await page.locator('#screener-candles svg').count(),1);
   mode='partial';await until(async()=>await source('book').getAttribute('data-state')==='fresh');assert.match(await source('book').textContent(),/частично/);assert.match(await page.locator('.book-total b').first().textContent(),/^≥/);
   mode='flat';await until(async()=>await metric('vwap').textContent()==='—');assert.equal(await metric('atr').textContent(),'0 USDT');assert.equal(await metric('volume').textContent(),'0 BTC');assert.equal(await page.locator('#screener-candles svg').count(),1);assert.equal(await page.locator('#screener-levels .level-item').count(),0);
   mode='wrong';await until(async()=>await source('chart').getAttribute('data-state')==='error'&&await source('book').getAttribute('data-state')==='error');assert.equal(await page.locator('#screener-candles svg').count(),0);assert.equal(await page.locator('.book-total').count(),0);
   mode='normal';await until(allFresh);
   mode='race';await page.getByRole('button',{name:'BTCUSDT',exact:true}).click();await page.getByRole('button',{name:'ETHUSDT',exact:true}).click();await until(allFresh);await page.waitForTimeout(1200);
   assert.equal(await card.getAttribute('data-symbol'),'ETHUSDT');assert.match(await page.locator('#screener-candles svg').getAttribute('aria-label'),/ETHUSDT/);assert.match(await metric('volume').textContent(),/ETH$/);
   mode='html';await until(async()=>await card.locator('[data-source][data-state=cached]').count()===3);assert.notEqual(await metric('price').textContent(),'—');
   await page.evaluate(()=>{const realNow=Date.now;Date.now=()=>realNow()+90000;});await until(async()=>await card.locator('[data-source][data-state=stale]').count()===3);
   for(const key of ['price','oi','funding','vwap','atr','volume'])assert.equal(await metric(key).textContent(),'—');assert.equal(await page.locator('#screener-candles svg').count(),0);assert.equal(await page.locator('.book-total').count(),0);
   mode='normal';await page.reload();await until(allFresh);assert.equal(await card.getAttribute('data-symbol'),'ETHUSDT');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[],'browser errors at '+width);await page.unrouteAll({behavior:'wait'});await page.close();
  }
  console.log('Coin card UI passed: 1280/390/320, four timeframes, units, missing/zero/partial/stale/wrong/error data, switch race and refresh persistence');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
