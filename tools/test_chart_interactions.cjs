/* Deterministic browser check for the user-supplied chart and screener controls. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');

const port=18789;
const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{stdio:'ignore'});
(async()=>{
 let browser;
 try{
  for(let i=0;i<50;i++){try{if((await fetch(`http://127.0.0.1:${port}/`)).ok)break;}catch{}if(i===49)throw Error('Preview not ready');await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/`);
  await page.waitForSelector('#screener-table .coin-button');
  await page.waitForSelector('#screener-candles svg');
  const chart=page.locator('#screener-candles'),scale=page.getByRole('button',{name:'Сбросить масштаб графика'});
  await chart.scrollIntoViewIfNeeded();
  const box=await chart.boundingBox();
  await page.mouse.move(box.x+box.width*.4,box.y+box.height*.35);
  await page.mouse.wheel(0,-250);
  assert.notEqual(await scale.textContent(),'100%','wheel over chart zooms time');
  const timeView=await page.evaluate(()=>JSON.parse(localStorage.getItem('lab-screener-chart-view-v2'))['BTCUSDT:5']);
  assert.ok(timeView.scale>1);
  await page.mouse.move(box.x+box.width-18,box.y+box.height*.35);
  await page.mouse.wheel(0,-250);
  const priceView=await page.evaluate(()=>JSON.parse(localStorage.getItem('lab-screener-chart-view-v2'))['BTCUSDT:5']);
  assert.ok(priceView.pScale>1,'wheel on right axis zooms price independently');
  await page.mouse.move(box.x+box.width*.5,box.y+box.height*.35);
  await page.mouse.down();await page.mouse.move(box.x+box.width*.68,box.y+box.height*.35,{steps:4});await page.mouse.up();
  const dragged=await page.evaluate(()=>JSON.parse(localStorage.getItem('lab-screener-chart-view-v2'))['BTCUSDT:5']);
  assert.ok(dragged.offset>0,'drag pans backward in time');
  await page.reload();await page.waitForSelector('#screener-candles svg');
  assert.equal(await scale.textContent(),Math.round(dragged.scale*100)+'%','zoom persists across page reload');
  await chart.dblclick({position:{x:box.width*.5,y:box.height*.35}});
  assert.equal(await scale.textContent(),'100%','double click restores default view');
  const sort=page.getByRole('button',{name:'Сортировать: Оборот'});
  await sort.click();assert.match(await sort.textContent(),/▼/);
  await sort.click();assert.match(await sort.textContent(),/▲/);
  await page.getByRole('button',{name:'Алерты',exact:true}).click();
  assert.ok(await page.locator('.alerts-head button').filter({hasText:/Уведомления/}).isVisible());
  assert.deepEqual(errors,[]);
  console.log('Chart interactions OK: wheel time/price, pan, persistence, reset, sorting and notification control');
 }finally{if(browser)await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
