const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
 for(const width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:900}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(process.env.PREVIEW_URL||'http://127.0.0.1:8791');
  await page.evaluate(()=>window.LabNavigation.activate('bots'));
  await page.locator('.bot-template').nth(9).waitFor();
  assert.equal(await page.locator('.bot-template').count(),10);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:`/tmp/bots-${width}.png`,fullPage:true});
  await page.getByRole('button',{name:'Настроить бота'}).first().click();
  await page.locator('#bot-notional').fill('123');
  await page.evaluate(()=>{window.LabNavigation.activate('market');window.LabNavigation.activate('bots');});
  assert.equal(await page.locator('#bot-notional').inputValue(),'123');
  await page.getByRole('button',{name:'Сохранить настройки',exact:true}).click();
  await page.locator('.bot-status').filter({hasText:'Сохранено на сервере'}).waitFor();
  const second=await browser.newContext(),phone=await second.newPage();
  await phone.goto(process.env.PREVIEW_URL||'http://127.0.0.1:8791');
  await phone.evaluate(()=>window.LabNavigation.activate('bots'));
  await phone.getByRole('button',{name:'Настроить бота'}).first().click();
  assert.equal(await phone.locator('#bot-notional').inputValue(),'123');
  await second.close();
  await page.screenshot({path:`/tmp/builder-${width}.png`,fullPage:true});
  assert.deepEqual(errors,[]);await context.close();
 }
 await browser.close();console.log('PASS: desktop/mobile catalog, preserved input, server save, second device');
})().catch(e=>{console.error(e);process.exit(1)});
