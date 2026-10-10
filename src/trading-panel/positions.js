/* Manual PAPER fills and storage stay on the server; the assistant has no model controls. */
(function(scope){
 'use strict';
 const numeric=x=>typeof x==='number'&&Number.isFinite(x),fresh=(t,now,age=8)=>numeric(t)&&now-t>=-1&&now-t<=age;
 const symbol=x=>typeof x==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(x);
 function modelPosition(id,s,now,control=null){
  const p=s?.position,c=s?.config||{},valid=p&&symbol(p.symbol)&&[1,-1].includes(p.side)&&numeric(p.quantity)&&p.quantity>0&&numeric(p.entry)&&p.entry>0;
  if(!valid)return {id,position:null,invalid:!!p,fresh:fresh(s?.updated,now)};
  const current=fresh(s.updated,now)&&['running','draining'].includes(s.phase)&&(!control||control.fresh===true&&control.unit_active==='active'&&['running','draining'].includes(control.phase));
  const quote=p.quote_time??s.market_time;
  const valuation=current&&fresh(quote,now)&&numeric(s.equity)&&numeric(s.balance)&&numeric(p.entry_fee)&&numeric(p.funding??0);
  const net=valuation?s.equity-s.balance-p.entry_fee+(p.funding??0):null;
  const stop=id==='B'?p.stop_usdt:id==='A'?c.stop_loss:c.stop;
  const target=id==='B'?p.target_usdt:id==='A'?c.take_profit:c.target;
  return {id,position:{symbol:p.symbol,side:p.side,entry:p.entry,quantity:p.quantity,opened:p.opened,stop:numeric(stop)?stop:null,target:numeric(target)?target:null,net,current,quote,reason:typeof p.entry_reason==='string'?p.entry_reason:typeof p.reason==='string'?p.reason:'Вход алгоритма '+id+'; точная причина в состоянии не записана'},fresh:fresh(s.updated,now)};
 }
 function manualPosition(s,now){
  const p=s?.position,m=p?.mark;
  return p?{...p,current:s.status==='ok'&&fresh(s.updated,now)&&fresh(m?.quote_time,now,5)&&m?.complete===true,net:s.status==='ok'&&fresh(s.updated,now)&&fresh(m?.quote_time,now,5)&&m?.complete===true?m.net:null}:null;
 }
 const api={modelPosition,manualPosition};if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;scope.LabPositions={manualPosition};
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-positions');if(!page)return;
  const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(v,n=4)=>numeric(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const price=v=>numeric(v)&&v!==0&&Math.abs(v)<1e-8?v.toExponential(3):fmt(v,8);
  const date=v=>numeric(v)?new Date(v*1000).toLocaleString('ru-RU'):'—';
  const line=(p,text,cls='muted')=>p.append(make('p',cls,text));
  const heading=make('div','page-heading');heading.append(make('h2','','Моя PAPER-позиция'),make('p','muted','Ручная проверка плана · реальных ордеров нет'));page.append(heading);
  const manual=make('section','box positions-manual');manual.id='manual-paper';const manualHead=make('div','position-heading'),manualState=make('span','muted'),pauseManual=make('button','secondary-button','Пауза ручных входов');pauseManual.type='button';pauseManual.disabled=true;manualHead.append(make('h3','','Ручной PAPER'),manualState,pauseManual);manual.append(manualHead);
  const account=make('p','muted');manual.append(account);line(manual,'Отдельный счёт 600 USDT, без плеча. Одна ручная позиция одновременно; выход по стопу, цели 1 или через 180 секунд. Вход рядом с funding запрещён.');
  const manualBody=make('div'),close=make('button','secondary-button','Закрыть ручную PAPER-позицию');close.type='button';close.disabled=true;const message=make('p','position-response');message.setAttribute('role','status');const repeat=make('button','secondary-button','Повторить тот же PAPER-запрос');repeat.type='button';repeat.hidden=true;manual.append(manualBody,close,message,repeat);
  const review=make('section','manual-review');review.hidden=true;review.append(make('h3','','Проверить ручной вход'));const draftText=make('p'),reasonLabel=make('label','','Причина ручного входа'),reasonInput=make('input');reasonInput.type='text';reasonInput.maxLength=240;reasonInput.id='manual-entry-reason';reasonLabel.htmlFor=reasonInput.id;reasonLabel.append(reasonInput);
  const open=make('button','primary-button','Открыть виртуальную позицию'),cancel=make('button','secondary-button','Убрать план'),reviewActions=make('div','paper-plan-actions');open.type=cancel.type='button';reviewActions.append(open,cancel);review.append(draftText,reasonLabel,reviewActions);line(review,'Сервер заново проверит цену, стакан и риск по текущему балансу. Используется цель 1; цель 2 остаётся сценарием плана.');manual.append(review);page.append(manual);
  let manualData=null,draft=null,inflight=false,retry=null,errors={},polling=null;
  const currentManual=()=>!errors.manual&&manualData?.status==='ok'&&fresh(manualData.updated,Date.now()/1000)&&typeof manualData.token==='string';
  function render(){
   if(page.hidden||document.hidden)return;const now=Date.now()/1000;
   const ok=currentManual(),p=manualPosition(manualData,now);manualState.textContent=!ok?'Недоступен':manualData.incomplete?'Учёт funding неполон':manualData.paused?'Новые входы на паузе':'Входы разрешены';
   account.textContent=ok?'Баланс '+fmt(manualData.balance)+' USDT · начальный капитал '+fmt(manualData.capital,0)+' USDT'+(manualData.incomplete?' · итог неполон; новые входы заблокированы':''):errors.manual||'Ручной PAPER пока не установлен или недоступен.';
   const body=document.createDocumentFragment();if(p){line(body,p.symbol+' · '+(p.side===1?'LONG':'SHORT'),'position-symbol');const facts=make('dl','position-facts');for(const [label,value]of [['Вход, USDT',price(p.entry)],['PnL позиции, net USDT',ok&&p.current?fmt(p.net):'—'],['Стоп, цена USDT',price(p.stop)],['Цель 1, цена USDT',price(p.target)],['Количество монет',price(p.quantity)],['Открыта',date(p.opened)]]){const cell=make('div');cell.append(make('dt','muted',label),make('dd','',value));facts.append(cell);}body.append(facts);line(body,p.reason,'position-reason');line(body,p.blocked||p.valuation_error||'Оценка закрытия с комиссией, VWAP доступных уровней и проскальзыванием.');if(p.blocked)line(body,'Автоматический выход остановлен. Ручное закрытие возможно только по свежему стакану. Пропуск наблюдений сохраняется в записи.','negative');}else line(body,ok?'Ручной позиции нет. Откройте готовый план в скринере и нажмите «Подготовить ручной PAPER-вход».':'Состояние ручной позиции не подтверждено.');LabUI.syncChildren(manualBody,body);
   pauseManual.textContent=manualData?.paused?'Разрешить ручные входы':'Пауза ручных входов';pauseManual.disabled=!ok||inflight||!!retry;
   close.disabled=!ok||!p||!fresh(p.mark?.quote_time,now,5)||inflight||!!retry;
   repeat.hidden=!retry;repeat.disabled=!ok||inflight;open.textContent=inflight?'Отправляем…':'Открыть виртуальную позицию';open.disabled=!ok||inflight||!!retry||!draft||!reasonInput.value.trim()||!!p||manualData.paused||manualData.incomplete;
   reasonInput.disabled=inflight||!!retry;cancel.disabled=inflight||!!retry;

  }
  async function json(path,options={}){const r=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(8000),...options});let value;try{value=await r.json();}catch{const e=Error('Сервер вернул неполные данные. Повторите после обновления.');e.uncertain=true;throw e;}if(!r.ok){const e=Error(value.error||'Запрос отклонён · HTTP '+r.status);e.uncertain=r.status>=500;throw e;}return value;}
  async function poll(afterCommand=false){
   if(polling){await polling;if(!afterCommand)return;}
   if(document.hidden||page.hidden)return;
   polling=(async()=>{try{const next=await json('/api/manual-paper');if(next.status!=='ok')throw Error('Ручной PAPER пока не установлен или недоступен.');if(!manualData||!numeric(next.generation)||!numeric(manualData.generation)||next.generation>=manualData.generation)manualData=next;delete errors.manual;}catch(error){errors.manual=error.message;}render();})();
   try{await polling;}finally{polling=null;}
  }
  async function command(action){if(!currentManual()||inflight)return;const payload=retry||{id:crypto.randomUUID(),action,generation:manualData.generation,...(action==='open'?{plan:{...draft,reason:reasonInput.value.trim()}}:{})};inflight=true;message.textContent='Отправляем PAPER-команду…';render();try{const result=await json('/api/manual-paper',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':manualData.token},body:JSON.stringify(payload)});if(result.status!=='accepted'){const e=Error(result.error||'Команда отклонена');e.uncertain=true;throw e;}retry=null;message.textContent='PAPER-команда выполнена. Реальных ордеров нет.';if(payload.action==='open'){draft=null;review.hidden=true;}}catch(e){if(e.name==='TimeoutError'||e.name==='AbortError'||e instanceof TypeError||e.uncertain){retry=payload;message.textContent='Ответ не получен. Повторите тот же запрос: второй вход не будет создан.';}else{retry=null;message.textContent=e.message;}}finally{await poll(true);inflight=false;render();}}
  pauseManual.addEventListener('click',()=>command(manualData.paused?'resume':'pause'));close.addEventListener('click',()=>command('close'));open.addEventListener('click',()=>command('open'));repeat.addEventListener('click',()=>command(retry.action));reasonInput.addEventListener('input',render);cancel.addEventListener('click',()=>{draft=null;review.hidden=true;render();});
  document.addEventListener('lab-paper-draft',e=>{if(inflight||retry)return;draft=e.detail;review.hidden=false;reasonInput.value=draft.reason;draftText.textContent=draft.symbol+' · '+(draft.side===1?'LONG':'SHORT')+' · зона '+price(draft.low)+'–'+price(draft.high)+' · стоп '+price(draft.stop)+' · цель 1 '+price(draft.target);message.textContent='План подготовлен; открытие требует нажатия кнопки ниже.';render();});
  document.addEventListener('lab-tab',e=>{if(e.detail==='positions'){render();poll();}});setInterval(poll,2000);setInterval(render,1000);render();poll();
 });
})(globalThis);
