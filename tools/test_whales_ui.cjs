const {chromium}=require('playwright'),{spawn}=require('node:child_process'),assert=require('node:assert/strict');
const root=require('node:path').resolve(__dirname,'..');
(async()=>{const server=spawn(process.env.PYTHON||'python3',['tools/preview.py','--port','18806'],{cwd:root,stdio:'ignore'});let browser;
try{for(let i=0;i<100;i++){if(await fetch('http://127.0.0.1:18806/').then(r=>r.ok).catch(()=>false))break;await new Promise(r=>setTimeout(r,100));}
browser=await chromium.launch({headless:true});
for(const width of [1280,390,320]){const page=await browser.newPage({viewport:{width,height:950}}),errors=[];let requests=0;
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>assert.notEqual(r.method(),'POST'));
await page.addInitScript(()=>localStorage.setItem('lab-start-page','settings'));
await page.route('**/api/whales',route=>{requests++;const now=Date.now()/1000;return route.fulfill({json:{status:'ok',updated:now,epoch:'whale-test',cursor:3,targets:['BTCUSDT'],coverage:{BTCUSDT:{fresh:true,checked:now}},events:[['large_trade',150000],['large_wall',300000],['wall_missing',75000]].map(([kind,notional],i)=>({id:'whale-test:'+i,kind,notional,symbol:'BTCUSDT',exchange:'bybit',side:'Buy',price:100,time:now}))}});});
await page.goto('http://127.0.0.1:18806/');await page.waitForTimeout(2300);assert.ok(requests>=1,'monitor starts before alerts page opens');
await page.locator(width<=760?'.mobile-nav':'#dashboard-tabs').getByRole('button',{name:'Алерты',exact:true}).click();
const box=page.locator('.whale-monitor');await box.waitFor({state:'visible'});await page.waitForTimeout(1100);
assert.equal(await box.locator('[data-whale-id]').count(),2);
await box.getByLabel('Порог крупных событий, USDT').fill('250000');assert.equal(await box.locator('[data-whale-id]').count(),1);
await page.waitForTimeout(2500);assert.equal(await box.getByLabel('Порог крупных событий, USDT').inputValue(),'250000');
await box.getByLabel('Тип крупного события').selectOption('large_trade');assert.equal(await box.locator('[data-whale-id]').count(),0);
await box.getByLabel('Порог крупных событий, USDT').fill('100000');assert.equal(await box.locator('[data-whale-id]').count(),1);
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);await page.close();}
console.log('Whale UI passed: background polling, amount/type filters, preserved input, 1280/390/320, no order requests.');
}finally{if(browser)await browser.close();server.kill('SIGTERM');}})().catch(e=>{console.error(e);process.exitCode=1;});
