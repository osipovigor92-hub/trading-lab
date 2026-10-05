/* Offline watchlist, stable ranking and explicit reordering under live updates. */
const {chromium}=require('playwright'),{spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18801;
async function until(fn,label){const end=Date.now()+15000;while(Date.now()<end){if(await fn())return;await new Promise(r=>setTimeout(r,100));}throw Error(label);}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port',String(port)],{cwd:root,stdio:'ignore'});let browser;
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}`).then(r=>r.ok).catch(()=>false),'preview');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[],queries=[];let changed=false;
   page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/market-selection?')||r.url().includes('/api/market-alerts?'))queries.push(new URL(r.url()));});
   const fixture=await (await fetch('http://127.0.0.1:'+port+'/api/screener')).json();await page.route('**/api/screener',async route=>{const data=structuredClone(fixture);data.updated=Date.now()/1000;if(changed){data.updated=Date.now()/1000;data.rows=data.rows.map(r=>({...r,price:r.symbol==='BTCUSDT'?61234:r.price,turnover:r.symbol==='LINKUSDT'?1e10:r.turnover}));}await route.fulfill({json:data});});
   await page.goto(`http://127.0.0.1:${port}`);await until(()=>page.locator('#screener-table tbody tr').count().then(n=>n===6),'rows');
   if(width<600){await page.getByLabel('Дополнительные фильтры').click();await page.getByLabel('Порядок монет',{exact:true}).selectOption('turnover');}else await page.getByLabel('Сортировка',{exact:true}).selectOption('turnover');
   const symbols=()=>page.locator('#screener-table tbody tr').evaluateAll(rows=>rows.map(r=>r.querySelector('.coin-button')?.textContent||r.querySelector('button')?.textContent));
   const before=await symbols();await page.locator('#screener-table tbody tr').first().evaluate(n=>n.dataset.kept='yes');
   changed=true;await until(()=>page.locator('#screener-table').textContent().then(t=>/61\s*234/.test(t)),'live price');
   assert.deepEqual(await symbols(),before,'default order is stable through changing turnover and pending ratings');assert.equal(await page.locator('[data-kept="yes"]').count(),1);
   await page.getByRole('button',{name:'Пересортировать',exact:true}).click();assert.notDeepEqual(await symbols(),before,'explicit sort applies current data');
   const stars=page.getByRole('button',{name:'Избранное LINKUSDT',exact:true});for(const b of await stars.all())if(await b.isVisible()){await b.click();break;}
   await until(()=>page.getByRole('button',{name:'Открыть наблюдение LINKUSDT'}).count().then(n=>n===1),'watch added');
   await page.getByLabel('Поиск монеты',{exact:true}).fill('BTC');await until(()=>queries.some(q=>q.searchParams.get('search')==='BTC'&&q.searchParams.get('watch')==='LINKUSDT'),'watch priority query');
   assert.equal(await page.getByRole('button',{name:'Открыть наблюдение LINKUSDT'}).count(),1,'watchlist survives table search');
   await page.getByRole('button',{name:'Открыть наблюдение LINKUSDT'}).click();assert.equal(await page.locator('#screener-detail').getAttribute('data-symbol'),'LINKUSDT');
   await page.getByLabel('Поиск монеты',{exact:true}).fill('');await page.getByLabel('Обновление порядка').selectOption('minute');await page.reload();
   await until(()=>page.getByRole('button',{name:'Открыть наблюдение LINKUSDT'}).count().then(n=>n===1),'watch survives reload');assert.equal(await page.getByLabel('Обновление порядка').inputValue(),'minute');
   await page.getByLabel('Обновление порядка').selectOption('manual');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow '+width);
   await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(root,'artifacts',`tracking-${width}.png`),fullPage:true});
   await page.getByRole('button',{name:'Убрать из наблюдения LINKUSDT'}).click();assert.equal(await page.getByRole('button',{name:'Открыть наблюдение LINKUSDT'}).count(),0);assert.deepEqual(JSON.parse(await page.evaluate(()=>localStorage.getItem('lab-favorites-v1'))),[]);
   assert.deepEqual(errors,[]);await page.close();changed=false;
  }
  console.log('Tracking UI passed: stable live prices, manual reorder, watch priority/search/reload/remove, 1280/390/320.');
 }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1;});
