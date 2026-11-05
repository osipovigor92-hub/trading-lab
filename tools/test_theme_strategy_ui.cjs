/* Browser coverage over synthetic quotes and source-bound strategy observations. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18827,base='http://127.0.0.1:'+port,widths=process.env.THEME_WIDTHS?process.env.THEME_WIDTHS.split(',').map(Number):[1280,390,320];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,why,timeout=14000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await sleep(45);}throw Error(why);}
function observation(symbol,setup,now,expired=false){
 const candle=Math.floor((now-2)/60)*60,id=symbol+':'+setup+':1:'+candle,direction=setup.endsWith('_up')?'LONG':'SHORT';
 return {symbol,assistant:{status:'ok',exchange:'bybit',timeframe:'1',eligible:true,setup,score:73,signal_id:id,candle_end:candle,
  sources:{quote:now-1,chart:candle+1,candle},reasons:['Подтверждены закрытие и объём.'],
  recommendation:{signal_id:id,direction,setup,exchange:'bybit',timeframe:'1',candle_end:candle,
   reason:'Закрытие и относительный объём подтверждены.',invalidation:'Цена вернулась за уровень.',expires:now+(expired?-1:30)}}};
}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:['ignore','ignore','pipe']});
 let browser,log='';server.stderr.on('data',data=>log+=data);
 try{
  await until(()=>fetch(base+'/').then(r=>r.ok).catch(()=>false),'preview starts');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  if(process.env.THEME_CAPTURE==='1')fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of widths){
   const page=await browser.newPage({viewport:{width,height:960}}),errors=[],posts=[],external=[];
   let firstPending=0,quoteReads=0,alertReads=0,updatedPrice=false,expired=false,offline=false;
   page.on('pageerror',error=>errors.push(error.message));
   page.on('request',request=>{if(request.method()==='POST')posts.push(request.url());if(!request.url().startsWith(base+'/'))external.push(request.url());});
   await page.addInitScript(()=>{if(!sessionStorage.getItem('theme-test-init')){sessionStorage.setItem('theme-test-init','1');localStorage.setItem('lab-screener-view-v1',JSON.stringify('table'));localStorage.setItem('lab-ui-theme','invalid');}});
   await page.route('**/api/screener',async route=>{
    quoteReads++;
    if(!firstPending){firstPending=Date.now();return route.fulfill({json:{status:'pending',rows:[],refreshing:true}});}
    const response=await route.fetch(),packet=await response.json();
    if(updatedPrice)packet.rows=packet.rows.map(row=>row.symbol==='BTCUSDT'?{...row,price:60015.42}:row);
    await route.fulfill({response,json:packet});
   });
   await page.route('**/api/market-alerts?*',async route=>{
    alertReads++;if(offline)return route.fulfill({status:502,json:{error:'fixture unavailable'}});
    const now=Date.now()/1000;await route.fulfill({json:{status:'ok',updated:now,epoch:'synthetic',scope:'synthetic',cursor:0,events:[],analyzing:['BTCUSDT','ETHUSDT'],rows:[
     observation('BTCUSDT','breakout_up',now,expired),observation('ETHUSDT','momentum_down',now,expired),
     observation('SOLUSDT','breakout_up',now,expired)
    ]}});
   });
   await page.goto(base+'/');const rootTheme=()=>page.locator('html').getAttribute('data-theme'),btc=page.locator('#screener-table tbody [data-symbol=BTCUSDT]');
   assert.equal(await rootTheme(),'dark','invalid saved palette defaults to graphite');
   await btc.waitFor({timeout:4000});const firstVisibleMs=Date.now()-firstPending;assert.ok(firstVisibleMs<3500,'queued quote is read before previous 5s cadence');
   await page.getByLabel('Минимум оборота',{exact:true}).selectOption('0');
   const symbols=()=>page.locator('#screener-table tbody tr[data-symbol]').evaluateAll(rows=>rows.map(row=>row.dataset.symbol)),pinned=await symbols();
   const changeAt=Date.now();updatedPrice=true;
   await until(()=>btc.locator('td').nth(1).textContent().then(s=>s.replace(/\s/g,'')==='60015,42'),'updated quote reaches table',3600);
   const quoteVisibleMs=Date.now()-changeAt;assert.deepEqual(await symbols(),pinned);
   const theme=page.locator('#theme-toggle'),light=async()=>{if(await rootTheme()!=='light')await theme.click();assert.equal(await rootTheme(),'light');};
   const dark=async()=>{if(await rootTheme()!=='dark')await theme.click();assert.equal(await rootTheme(),'dark');};
   const nav=page.locator(width<=760?'.mobile-nav':'#dashboard-tabs');
   const go=async(name,id)=>{await nav.getByRole('button',{name,exact:true}).click();await page.locator('#page-'+id).waitFor({state:'visible'});};
   const capture=async(state)=>{assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'page fits '+state+' at '+width);if(process.env.THEME_CAPTURE==='1'){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:path.join(root,'artifacts','themes-'+state+'-'+width+'.png')});}};
   await light();assert.equal(await page.evaluate(()=>getComputedStyle(document.body).color),'rgb(24, 39, 52)');
   await until(()=>page.locator('.screener-chart-box canvas').evaluate(canvas=>Array.from(canvas.getContext('2d').getImageData(1,1,1,1).data).join(',')==='251,253,255,255'),'table canvas uses light palette');
   await capture('table-light');
   await go('Стратегии','strategies');const strategy=page.locator('#page-strategies'),active=()=>strategy.locator('.strategy-row[data-direction=LONG],.strategy-row[data-direction=SHORT]').count();
   await until(()=>active().then(n=>n===2),'exactly two scoped recommendations');
   assert.equal(await strategy.locator('[data-symbol=SOLUSDT]').count(),0,'out of scope observations are hidden');
   await capture('strategies-light');await dark();await capture('strategies-dark');await light();
   await strategy.getByLabel('Направление стратегии').selectOption('SHORT');
   assert.equal(await strategy.locator('.strategy-row[data-symbol=ETHUSDT]').count(),1);assert.equal(await strategy.locator('.strategy-row[data-symbol=BTCUSDT]').count(),0);
   await strategy.getByText('Основание',{exact:true}).click();
   assert.match(await strategy.locator('.strategy-proof[open]').textContent(),/Отмена: Цена вернулась за уровень/);
   await strategy.getByRole('button',{name:'Открыть ETHUSDT в скринере'}).click();await page.locator('.screener-detail[data-symbol=ETHUSDT]').waitFor();
   await go('Стратегии','strategies');await strategy.getByLabel('Направление стратегии').selectOption('all');
   const beforeExpiry=alertReads;expired=true;
   await until(async()=>alertReads>beforeExpiry&&(await active())===0,'expired directions are withdrawn');
   offline=true;await until(()=>strategy.locator('.strategy-status').textContent().then(t=>t.includes('недоступен')),'strategy outage is explicit');
   assert.equal(await active(),0);
   await go('Скринер','market');await page.getByRole('button',{name:'Графики',exact:true}).click();
   const native=page.locator('.chart-tile .exchange-chart-host[data-chart-confirmed=true]').first();await native.waitFor();
   const initial=await native.evaluate(host=>host.labExchangeChart.getViewport());
   await native.evaluate(host=>host.labExchangeChart.pan(-8));
   await until(()=>native.evaluate((host,from)=>host.labExchangeChart.getViewport().from!==from,initial.from),'native pan finishes');
   const viewport=await native.evaluate(host=>host.labExchangeChart.getViewport());
   await dark();await light();
   assert.deepEqual(await native.evaluate(host=>host.labExchangeChart.getViewport()),viewport,'palette preserves chart viewport and closed evidence');
   await capture('charts-light');
   await go('Настройки','settings');assert.equal(await page.getByLabel('Тема оформления').inputValue(),'light');
   await page.reload();await page.getByLabel('Тема оформления').waitFor();assert.equal(await rootTheme(),'light','theme persists on reload');
   await page.getByLabel('Тема оформления').selectOption('dark');assert.equal(await rootTheme(),'dark');
   await capture('settings-dark');
   assert.deepEqual(errors,[]);assert.deepEqual(posts,[]);assert.deepEqual(external,[]);
   console.log(JSON.stringify({width,firstVisibleMs,quoteVisibleMs,quoteReads,alertReads}));await page.close();
  }
 }catch(error){console.error(log);throw error;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
