const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const assert=require('node:assert/strict');
const base='http://127.0.0.1:18807', keys=['lab-favorites-v1','lab-exchange-favorites-v1','lab-density-watch-v1'];
async function until(page,fn,arg){const end=Date.now()+20000;while(Date.now()<end){if(await page.evaluate(fn,arg))return;await new Promise(r=>setTimeout(r,100));}throw Error('Favorites condition timed out');}
const server=spawn('python3',['tools/preview.py','--port','18807'],{stdio:['ignore','pipe','inherit']});
const ready=new Promise(resolve=>server.stdout.once('data',resolve));
(async()=>{
 let browser;
 try{
  await ready;browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});
  const pc=await browser.newContext({viewport:{width:1280,height:900}}),phone=await browser.newContext({viewport:{width:390,height:844}});
  const p=await pc.newPage(),m=await phone.newPage(),errors=[],writes=[];
  for(const page of [p,m]){page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')writes.push(new URL(r.url()).pathname);});}
  await pc.addInitScript(({keys})=>{if(!localStorage.getItem('test-seeded')){keys.forEach((key,i)=>localStorage.setItem(key,JSON.stringify([['BTCUSDT','binance:ETHUSDT','bybit:SOLUSDT'][i]])));localStorage.setItem('test-seeded','true');}},{keys});
  await m.goto(base);await until(m,()=>document.querySelector('#favorites-sync-status')?.textContent.includes('синхронизировано'));
  await p.goto(base);await until(p,()=>document.querySelector('#favorites-sync-status')?.textContent.includes('синхронизировано'));
  async function has(page,key,value,present=true){await until(page,({key,value,present})=>JSON.parse(localStorage.getItem(key)||'[]').includes(value)===present,{key,value,present} );}
  for(const [i,value]of ['BTCUSDT','binance:ETHUSDT','bybit:SOLUSDT'].entries())await has(m,keys[i],value);
  async function change(page,value,present){await page.evaluate(({value,present,key})=>{const items=new Set(JSON.parse(localStorage.getItem(key)||'[]'));if(present)items.add(value);else items.delete(value);localStorage.setItem(key,JSON.stringify([...items]));window.LabFavorites.changed(key);},{value,present,key:keys[0]});}
  await change(m,'ETHUSDT',true);await has(p,keys[0],'ETHUSDT');
  await change(p,'BTCUSDT',false);await has(m,keys[0],'BTCUSDT',false);
  await p.reload();await until(p,()=>document.querySelector('#favorites-sync-status')?.textContent.includes('синхронизировано'));await has(p,keys[0],'BTCUSDT',false);
  await p.route('**/api/favorites',r=>r.abort());await change(p,'SOLUSDT',true);
  await until(p,()=>document.querySelector('#favorites-sync-status')?.textContent.includes('недоступна'));
  assert.ok(await p.evaluate(()=>JSON.parse(localStorage.getItem('lab-favorites-outbox')).length));
  await p.unroute('**/api/favorites');await has(m,keys[0],'SOLUSDT');
  assert.deepEqual(errors,[]);assert.ok(writes.length>0);assert.ok(writes.every(path=>path==='/api/favorites'));
  console.log('PASS: empty phone first, migration of three lists, PC/phone add and remove, reload, offline retry; only preference POSTs.');
 }finally{await browser?.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
