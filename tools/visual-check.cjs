/* One bounded screenshot batch of the assistant, using isolated synthetic data. */
const {chromium}=require('playwright');
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),port=18788;
const sections={market:'Скринер',alerts:'Алерты',positions:'Позиции',settings:'Настройки'};
const until=async(check,label)=>{const end=Date.now()+15000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error(label);};
async function navigate(page,key,width){
 const nav=page.locator(width<=760?'.mobile-nav':'#dashboard-tabs');
 await nav.getByRole('button',{name:sections[key],exact:true}).click();
 await page.locator('#page-'+key).waitFor({state:'visible'});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal overflow '+key+' at '+width);
}
(async()=>{
 const server=spawn(process.env.PYTHON||'python3',[path.join(__dirname,'preview.py'),'--port',String(port)],{cwd:root,stdio:['ignore','ignore','pipe']});let browser,log='';server.stderr.on('data',data=>log+=data);
 try{
  await until(()=>fetch(`http://127.0.0.1:${port}/`).then(response=>response.ok).catch(()=>false),'Preview not ready');
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{})});fs.mkdirSync(path.join(root,'artifacts'),{recursive:true});
  const evidence=[];
  for(const width of [1280,390,320]){
   const page=await browser.newPage({viewport:{width,height:950}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
   await page.goto(`http://127.0.0.1:${port}/`);await page.locator('#screener-table .coin-button').first().waitFor();
   assert.equal(await page.evaluate(()=>LabNavigation.current()),'market');
   assert.deepEqual(await page.evaluate(()=>Object.keys(LabNavigation.names)),Object.keys(sections));
   for(const key of Object.keys(sections)){
    await navigate(page,key,width);
    if(key==='market')await page.locator('.screener-chart-note[data-status="ok"]').waitFor();
    if(key==='alerts')await page.locator('.fresh-alert-health[data-status="ok"]').waitFor({state:'attached'});
    if(key==='positions')await until(()=>page.locator('#manual-paper').textContent().then(text=>text.includes('Баланс')),'Manual PAPER not ready');
    await page.screenshot({path:path.join(root,'artifacts',`assistant-${key}-${width}.png`),fullPage:true});
    evidence.push({width,page:key,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});
   }
   assert.equal(await page.locator('[data-model],#screener-bots,#screener-orderbook').count(),0);
   assert.deepEqual(errors,[]);await page.close();
  }
  fs.writeFileSync(path.join(root,'artifacts','assistant-visual.json'),JSON.stringify(evidence,null,2));
  console.log('Visual assistant check passed: four pages at 1280/390/320 px, no overflow or browser errors.');
 }catch(error){console.error(log);throw error;}finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
