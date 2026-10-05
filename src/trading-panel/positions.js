/* Native model marks stay authoritative; manual fills and storage live on the server. */
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
 if(typeof document==='undefined')return;scope.LabPositions=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-positions');if(!page)return;
  const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(v,n=4)=>numeric(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const price=v=>numeric(v)&&v!==0&&Math.abs(v)<1e-8?v.toExponential(3):fmt(v,8);
  const date=v=>numeric(v)?new Date(v*1000).toLocaleString('ru-RU'):'—';
  const line=(p,text,cls='muted')=>p.append(make('p',cls,text));
  const heading=make('div','page-heading');heading.append(make('h2','','Активные позиции'),make('p','muted','A/B/C/D и ручной PAPER · значения в USDT'));page.append(heading);
  const note=make('p','positions-notice','Пауза запрещает новые входы. Открытые позиции продолжают штатные выходы.');page.append(note);
  const models=make('section','box positions-models');models.append(make('h3','','Позиции моделей'));const rows={};
  for(const id of 'ABCD'){
   const row=make('section','position-row');row.dataset.model=id;const head=make('div','position-heading'),title=make('h3','','Модель '+id),status=make('span','muted'),pause=make('button','secondary-button','Пауза '+id);pause.type='button';pause.disabled=true;head.append(title,status,pause);const summary=make('p','position-symbol'),facts=make('dl','position-facts'),fields={};
   for(const [key,label]of [['entry','Вход, USDT'],['net','PnL позиции, net USDT'],['stop','Стоп, net USDT'],['target','Цель, net USDT'],['quantity','Количество монет'],['opened','Открыта']]){const cell=make('div');cell.append(make('dt','muted',label));const value=make('dd','','—');cell.append(value);facts.append(cell);fields[key]=value;}
   const reason=make('p','position-reason'),age=make('p','muted'),response=make('p','position-response');response.setAttribute('role','status');row.append(head,summary,facts,reason,age,response);models.append(row);rows[id]={row,status,pause,summary,fields,reason,age,response};pause.addEventListener('click',()=>pauseModel(id));
  }page.append(models);
  const manual=make('section','box positions-manual');manual.id='manual-paper';const manualHead=make('div','position-heading'),manualState=make('span','muted'),pauseManual=make('button','secondary-button','Пауза ручных входов');pauseManual.type='button';pauseManual.disabled=true;manualHead.append(make('h3','','Ручной PAPER'),manualState,pauseManual);manual.append(manualHead);
  const account=make('p','muted');manual.append(account);line(manual,'Отдельный счёт 600 USDT, без плеча. Одна ручная позиция одновременно; выход по стопу, цели 1 или через 180 секунд. Вход рядом с funding запрещён.');
  const manualBody=make('div'),close=make('button','secondary-button','Закрыть ручную PAPER-позицию');close.type='button';close.disabled=true;const message=make('p','position-response');message.setAttribute('role','status');const repeat=make('button','secondary-button','Повторить тот же PAPER-запрос');repeat.type='button';repeat.hidden=true;manual.append(manualBody,close,message,repeat);
  const review=make('section','manual-review');review.hidden=true;review.append(make('h3','','Проверить ручной вход'));const draftText=make('p'),reasonLabel=make('label','','Причина ручного входа'),reasonInput=make('input');reasonInput.type='text';reasonInput.maxLength=240;reasonInput.id='manual-entry-reason';reasonLabel.htmlFor=reasonInput.id;reasonLabel.append(reasonInput);
  const open=make('button','primary-button','Открыть виртуальную позицию'),cancel=make('button','secondary-button','Убрать план'),reviewActions=make('div','paper-plan-actions');open.type=cancel.type='button';reviewActions.append(open,cancel);review.append(draftText,reasonLabel,reviewActions);line(review,'Сервер заново проверит цену, стакан и риск по текущему балансу. Используется цель 1; цель 2 остаётся сценарием плана.');manual.append(review);page.append(manual);
  const history=make('details','box manual-history');history.append(make('summary','','Последние закрытые ручные PAPER-сделки'));const historyBody=make('div');history.append(historyBody);page.append(history);
  let data={},control=null,manualData=null,draft=null,inflight=false,retry=null,errors={},modelCommands={};
  const currentControl=()=>!errors.control&&control?.status==='ok'&&fresh(control.updated,Date.now()/1000)&&typeof control.token==='string';
  const currentManual=()=>!errors.manual&&manualData?.status==='ok'&&fresh(manualData.updated,Date.now()/1000)&&typeof manualData.token==='string';
  function render(){
   if(page.hidden||document.hidden)return;const now=Date.now()/1000;
   for(const id of 'ABCD'){
    const r=rows[id],s=data[id],ctl=control?.models?.find(m=>m.id===id),v=modelPosition(id,s,now,ctl),p=v.position,valid=!errors[id]&&v.fresh;
    const phase=currentControl()?ctl?.phase:s?.phase;
    r.status.textContent=errors[id]?'Источник недоступен':!valid?'Нет свежего состояния':phase==='halted'?'Остановлена по защите':phase==='draining'?'Завершает позицию':phase==='paused'?'Входы на паузе':p?'PAPER':'Без позиции';
    r.summary.textContent=p?p.symbol+' · '+(p.side===1?'LONG':'SHORT')+(valid&&p.current?'':' · сохранённая позиция'):v.invalid?'Некорректные данные позиции':valid?'Открытой позиции нет':'Состояние позиции не подтверждено';
    const values={entry:p?price(p.entry):'—',net:p&&valid&&p.current?fmt(p.net):'—',stop:p&&p.stop!==null?'−'+fmt(p.stop):'—',target:p&&p.target!==null?'+'+fmt(p.target):'—',quantity:p?price(p.quantity):'—',opened:p?date(p.opened):'—'};
    for(const [key,value]of Object.entries(values))r.fields[key].textContent=value;
    r.fields.net.className=p&&valid&&numeric(p.net)?p.net>0?'positive':p.net<0?'negative':'':'';r.row.dataset.current=String(!!p&&valid&&p.current);r.row.dataset.hasPosition=String(!!p);
    r.reason.textContent=p?p.reason:'';r.age.textContent=p?'Оценка модели: '+date(s.updated)+(values.net==='—'?' · текущий PnL не подтверждён':' · комиссии входят в net'):'Снимок: '+date(s?.updated);
    const pending=modelCommands[id];if(pending&&ctl?.generation>=pending.generation&&!ctl.pending){r.response.textContent=['paused','draining'].includes(ctl.phase)?'Пауза подтверждена; новые входы запрещены.':ctl.reason||'Команда обработана.';delete modelCommands[id];}
    r.pause.disabled=!currentControl()||!ctl?.actions?.stop||ctl.busy||ctl.unit_active!=='active'||['paused','stopped','halted'].includes(ctl.phase)||!!modelCommands[id]||ctl.pending&&ctl.requested==='stop';
   }
   const ok=currentManual(),p=manualPosition(manualData,now);manualState.textContent=!ok?'Недоступен':manualData.incomplete?'Учёт funding неполон':manualData.paused?'Новые входы на паузе':'Входы разрешены';
   account.textContent=ok?'Баланс '+fmt(manualData.balance)+' USDT · начальный капитал '+fmt(manualData.capital,0)+' USDT'+(manualData.incomplete?' · итог неполон; новые входы заблокированы':''):errors.manual||'Ручной PAPER пока не установлен или недоступен.';
   manualBody.replaceChildren();if(p){line(manualBody,p.symbol+' · '+(p.side===1?'LONG':'SHORT'),'position-symbol');const facts=make('dl','position-facts');for(const [label,value]of [['Вход, USDT',price(p.entry)],['PnL позиции, net USDT',ok&&p.current?fmt(p.net):'—'],['Стоп, цена USDT',price(p.stop)],['Цель 1, цена USDT',price(p.target)],['Количество монет',price(p.quantity)],['Открыта',date(p.opened)]]){const cell=make('div');cell.append(make('dt','muted',label),make('dd','',value));facts.append(cell);}manualBody.append(facts);line(manualBody,p.reason,'position-reason');line(manualBody,p.blocked||p.valuation_error||'Оценка закрытия с комиссией, VWAP доступных уровней и проскальзыванием.');if(p.blocked)line(manualBody,'Автоматический выход остановлен. Ручное закрытие возможно только по свежему стакану. Пропуск наблюдений сохраняется в записи.','negative');}else line(manualBody,ok?'Ручной позиции нет. Откройте готовый план в скринере и нажмите «Подготовить ручной PAPER-вход».':'Состояние ручной позиции не подтверждено.');
   pauseManual.textContent=manualData?.paused?'Разрешить ручные входы':'Пауза ручных входов';pauseManual.disabled=!ok||inflight||!!retry;
   close.disabled=!ok||!p||!fresh(p.mark?.quote_time,now,5)||inflight||!!retry;
   repeat.hidden=!retry;repeat.disabled=!ok||inflight;open.textContent=inflight?'Отправляем…':'Открыть виртуальную позицию';open.disabled=!ok||inflight||!!retry||!draft||!reasonInput.value.trim()||!!p||manualData.paused||manualData.incomplete;
   reasonInput.disabled=inflight||!!retry;cancel.disabled=inflight||!!retry;
   historyBody.replaceChildren();for(const t of ok?manualData.trades||[]:[]){const row=make('div','manual-trade');line(row,date(t.closed)+' · '+t.symbol+' '+(t.side===1?'LONG':'SHORT')+' · '+t.exit_reason,'');line(row,'Net '+fmt(t.net)+' USDT · вход '+price(t.entry)+' → выход '+price(t.exit));if(t.observation_gap)line(row,'Пропуск наблюдений: '+t.observation_gap);if(t.net===null)line(row,'Funding не учтён: итоговый net не подтверждён.','negative');historyBody.append(row);}if(!historyBody.childElementCount)line(historyBody,ok?'Закрытых ручных сделок пока нет.':'Журнал временно недоступен.');
  }
  async function json(path,options={}){const r=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(8000),...options});let value;try{value=await r.json();}catch{const e=Error('Сервер вернул неполные данные. Повторите после обновления.');e.uncertain=true;throw e;}if(!r.ok){const e=Error(value.error||'Запрос отклонён · HTTP '+r.status);e.uncertain=r.status>=500;throw e;}return value;}
  async function poll(){if(!document.hidden&&!page.hidden){await Promise.allSettled([['A','/api/paper'],['B','/api/model-b'],['CD','/api/research'],['control','/api/models-control'],['manual','/api/manual-paper']].map(async([key,path])=>{try{const s=await json(path);if(key==='control'){if(s.status!=='ok'||!Array.isArray(s.models))throw Error('Контроллер недоступен');control=s;}else if(key==='manual'){if(s.status!=='ok')throw Error('Ручной PAPER пока не установлен или недоступен.');manualData=s;}else if(key==='CD'){for(const id of 'CD'){data[id]={...s.models?.[id],config:s.config,updated:s.updated};delete errors[id];}}else data[key]=s;delete errors[key];}catch(e){errors[key]=e.message;if(key==='CD')errors.C=errors.D=e.message;}}));render();}}
  async function pauseModel(id){const ctl=control?.models?.find(m=>m.id===id),r=rows[id];if(r.pause.disabled||!currentControl())return;r.pause.disabled=true;modelCommands[id]={generation:ctl.generation+1};r.response.textContent='Отправляем паузу…';try{const result=await json('/api/models-control',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':control.token},body:JSON.stringify({target:id,action:'stop',generation:ctl.generation})});if(result.status!=='accepted')throw Error(result.error||'Пауза отклонена');r.response.textContent='Команда принята; ждём подтверждения модели.';}catch(e){r.response.textContent=e.message;delete modelCommands[id];}await poll();}
  async function command(action){if(!currentManual()||inflight)return;const payload=retry||{id:crypto.randomUUID(),action,generation:manualData.generation,...(action==='open'?{plan:{...draft,reason:reasonInput.value.trim()}}:{})};inflight=true;message.textContent='Отправляем PAPER-команду…';render();try{const result=await json('/api/manual-paper',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':manualData.token},body:JSON.stringify(payload)});if(result.status!=='accepted'){const e=Error(result.error||'Команда отклонена');e.uncertain=true;throw e;}retry=null;message.textContent='PAPER-команда выполнена. Реальных ордеров нет.';if(payload.action==='open'){draft=null;review.hidden=true;}}catch(e){if(e.name==='TimeoutError'||e.name==='AbortError'||e instanceof TypeError||e.uncertain){retry=payload;message.textContent='Ответ не получен. Повторите тот же запрос: второй вход не будет создан.';}else{retry=null;message.textContent=e.message;}}finally{inflight=false;await poll();render();}}
  pauseManual.addEventListener('click',()=>command(manualData.paused?'resume':'pause'));close.addEventListener('click',()=>command('close'));open.addEventListener('click',()=>command('open'));repeat.addEventListener('click',()=>command(retry.action));reasonInput.addEventListener('input',render);cancel.addEventListener('click',()=>{draft=null;review.hidden=true;render();});
  document.addEventListener('lab-paper-draft',e=>{if(inflight||retry)return;draft=e.detail;review.hidden=false;reasonInput.value=draft.reason;draftText.textContent=draft.symbol+' · '+(draft.side===1?'LONG':'SHORT')+' · зона '+price(draft.low)+'–'+price(draft.high)+' · стоп '+price(draft.stop)+' · цель 1 '+price(draft.target);message.textContent='План подготовлен; открытие требует нажатия кнопки ниже.';render();});
  document.addEventListener('lab-tab',e=>{if(e.detail==='positions'){render();poll();}});setInterval(poll,2000);setInterval(render,1000);render();poll();
 });
})(globalThis);
