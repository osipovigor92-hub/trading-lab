/* Opt-in live integration check. Requires serve_public.py + actual Kronos worker. */
const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
async function until(check,label,timeout=90000){const end=Date.now()+timeout;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,250));}throw Error(label);}
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})}),page=await browser.newPage({viewport:{width:1280,height:950}}),errors=[],commands=[];
 page.on('pageerror',error=>errors.push(error.message));page.on('request',request=>{if(request.method()!=='GET')commands.push(new URL(request.url()).pathname);});
 try{
  await page.goto(process.env.PUBLIC_ASSISTANT_URL||'http://127.0.0.1:8789/');assert.equal(await page.locator('body').getAttribute('data-demo'),null,'public panel cannot use demo data');
  await page.getByLabel('Количество графиков',{exact:true}).selectOption('4');await page.getByLabel('Метрика графиков',{exact:true}).selectOption('turnover');
  await until(()=>page.locator('.chart-tile .exchange-chart-host[data-chart-confirmed=true]').count().then(n=>n===4),'four genuine closed charts');
  const panel=page.locator('#kronos-screener');await panel.locator('summary').click();const button=panel.getByRole('button',{name:'Оценить монеты',exact:true});await until(()=>button.isEnabled(),'real model readiness');await button.click();
  await until(async()=>await panel.locator('.kronos-table tbody tr').count()===4&&(await panel.locator('[role=status]').textContent()).includes('4 / 4'),'four genuine model results');
  const rows=await panel.locator('.kronos-table tbody tr').allTextContents();assert.equal(rows.length,4);assert.deepEqual(errors,[]);assert.equal(commands.every(command=>command==='/api/kronos/forecast'),true,'only model inference is requested');assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.resolve(__dirname,'../artifacts/kronos-live-1280.png')});console.log(JSON.stringify({real_model:true,real_public_data:true,results:rows.length,model_commands:commands.length,rows,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
