/* Actual server lifecycle; buttons never infer success from a click. */
(function(scope){
 'use strict';
 const names={running:'Работает',warming:'Прогрев',waiting:'Ожидает данные',paused:'Отключена',stopped:'Служба остановлена',draining:'Завершает позицию',pending:'Применяет команду',halted:'Остановлена по защите',stale:'Нет свежего отчёта',unknown:'Нет отчёта',not_installed:'Не подготовлен',idle:'Готов к тесту',starting:'Запускается',completed:'Тест завершён',cancelled:'Тест отменён',failed:'Ошибка теста',interrupted:'Тест прерван'};
 const engineNames={freqtrade:'Freqtrade',hummingbot:'Hummingbot',jesse:'Jesse'};
 const setupCommands={freqtrade:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine freqtrade --install',jesse:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine jesse --install',hummingbot:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine hummingbot --python /opt/hummingbot-env/bin/python'};
 function testSlot(item,engines=[]){
  if(item?.kind!=='engine')return {item,occupiedBy:null};
  const occupied=engines.find(e=>e.id!==item.id&&(e.busy||['running','starting'].includes(e.phase)));
  return {item:occupied?{...item,actions:{...item.actions,start:false,restart:false}}:item,occupiedBy:occupied?.id||null};
 }
 function buttons(item,current=true){
  const a=item?.actions||{},off=['paused','stopped'].includes(item?.phase),busy=item?.busy||!current;
  if(item?.kind==='engine')return {start:!busy&&a.start===true,stop:!busy&&a.stop===true,restart:!busy&&a.restart===true&&item.phase!=='idle'};
  return {start:!busy&&a.start===true&&(off||['draining','pending','stale','unknown'].includes(item.phase)),stop:!busy&&a.stop===true&&!off&&!(item.pending&&item.requested==='stop'),restart:!busy&&a.restart===true&&!item.pending};
 }
 const api={buttons,names,testSlot};if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-research');if(!page)return;
  const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(v,n=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const date=v=>typeof v==='number'&&Number.isFinite(v)?new Date(v*1000).toLocaleString('ru-RU'):'—';
  const advanced=make('details','box models-analysis');advanced.append(make('summary','','Диагностика C/D и условия стратегий'));
  for(const node of [...page.children])if(node.id!=='research-journals')advanced.append(node);page.append(advanced);
  const heading=make('div','page-heading models-heading');heading.append(make('div','', ''));
  heading.firstChild.append(make('small','eyebrow','УПРАВЛЕНИЕ / PAPER'),make('h2','','Модели и тестовые боты'));
  const connection=make('p','muted','Подключаем управление…');connection.setAttribute('role','status');heading.append(connection);
  const modelsBox=make('section','box models-section');modelsBox.id='model-controls';modelsBox.append(make('h3','','Текущие модели A / B / C / D'));
  modelsBox.append(make('p','muted','Отключение запрещает новые входы. Открытая PAPER-позиция завершается по прежним правилам. Перезапуск сохраняет капитал и журнал, затем заново накапливает условия входа.'));
  const modelGrid=make('div','managed-grid');modelsBox.append(modelGrid);
  const engineBox=make('section','box models-section');engineBox.id='engine-controls';engineBox.append(make('h3','','Тесты Freqtrade / Hummingbot / Jesse'));
  const resources=make('p','muted','Один внешний тест за раз.');engineBox.append(resources);
  const setup=make('details','models-setup');setup.append(make('summary','','Подготовка и проверка установки'));
  setup.append(make('p','muted','Тестовый движок сначала готовят на сервере. На этой странице запускается уже подготовленный тест. Требования к памяти включают резерв для панели.'));
  const diagnostic=make('pre','setup-command');diagnostic.append(make('code','','python3 /opt/trading-lab-repo/tools/diagnose_models.py'));setup.append(make('p','muted','Проверить службы, версии и доступность тестов без перезапуска:'),diagnostic);
  engineBox.append(setup);
  const engineGrid=make('div','engine-grid');engineBox.append(engineGrid);
  const logBox=make('details','box models-audit');logBox.id='model-control-journal';logBox.append(make('summary','','Журнал управления'));
  const log=make('div','control-log');logBox.append(log);
  page.prepend(heading,modelsBox,engineBox,logBox);
  const info={A:'Лента + дисбаланс + импульс',B:'EMA / VWAP + стакан + OFI',C:'Импульс в тренде',D:'Возврат к VWAP',freqtrade:'Исторический тест · 7 закрытых дней · Bybit BTC · 5 мин',hummingbot:'PAPER · Pure Market Making · Binance BTC spot · 20 мин',jesse:'Бесплатный исторический тест · 7 закрытых дней · Bybit BTC · 5 мин'};
  const inflight=new Set(),cards=new Map();let state=null,apiError='';
  function card(id,kind){
   const box=make('article','managed-card');box.dataset.model=id;
   const header=make('div','managed-title'),title=make('h4','',kind==='engine'?id==='freqtrade'?'Freqtrade':id==='hummingbot'?'Hummingbot':'Jesse':'Модель '+id),badge=make('span','managed-badge','Ожидание');header.append(title,badge);box.append(header);
   box.append(make('p','managed-description',info[id]));
   const metrics=make('div','managed-metrics'),position=make('p','managed-position'),reason=make('p','managed-reason');box.append(metrics,position,reason);
   const actions=make('div','managed-actions'),buttons={};
   for(const [action,label]of Object.entries(kind==='engine'?{start:'Запустить тест',stop:'Остановить',restart:'Повторить'}:{start:'Включить',stop:'Отключить',restart:'Перезапустить'})){
    const b=make('button',action==='start'?'control-primary':'control-secondary',label);b.type='button';b.disabled=true;b.setAttribute('aria-label',label+' '+title.textContent);b.dataset.action=action;b.addEventListener('click',()=>command(id,action));actions.append(b);buttons[action]=b;
   }box.append(actions);
   const response=make('p','control-response');response.setAttribute('role','status');box.append(response);
   let runs, runBody, readiness;
   if(kind==='engine'){
    readiness=make('ul','engine-readiness');readiness.setAttribute('aria-label','Готовность '+title.textContent);box.insertBefore(readiness,actions);
    const prepare=make('details','engine-prepare');prepare.append(make('summary','','Как подготовить '+title.textContent));
    prepare.append(make('p','muted',id==='hummingbot'?'Нужно официальное скомпилированное окружение Hummingbot. В шаблоне замени путь к Python на настоящий. Если исходники находятся отдельно, добавь --source-dir с их путём.':'Эта команда создаёт отдельное Python-окружение с проверенной версией. Выполняй её от root на сервере с достаточной памятью.'));
    const code=make('pre','setup-command');code.append(make('code','',setupCommands[id]));prepare.append(code);
    const copy=make('button','managed-copy',id==='hummingbot'?'Скопировать шаблон':'Скопировать команду');copy.type='button';copy.setAttribute('aria-label',copy.textContent+' '+title.textContent);
    const copyStatus=make('p','muted');copyStatus.setAttribute('role','status');
    copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(setupCommands[id]);copyStatus.textContent='Скопировано. Выполни команду в терминале сервера.';}catch{copyStatus.textContent='Буфер обмена недоступен. Выдели и скопируй команду выше.';}});prepare.append(copy,copyStatus);box.append(prepare);
    runs=make('details','engine-runs');runs.append(make('summary','','Последние тестовые запуски'));runBody=make('div','engine-run-list');runs.append(runBody);box.append(runs);
    const csv=make('a','research-link','Журнал тестов CSV');csv.href='/api/engine-journal?engine='+id;csv.download=id+'-tests.csv';box.append(csv);
   }else{
    const a=make('button','managed-journal','Открыть журнал сделок →');a.type='button';a.addEventListener('click',()=>{document.dispatchEvent(new CustomEvent('lab-navigate',{detail:'journals'}));document.getElementById(id==='C'||id==='D'?'research-journals':'model-journals')?.scrollIntoView({block:'start',behavior:'smooth'});});box.append(a);
   }
   const value={box,badge,metrics,position,reason,buttons,response,runBody,readiness,item:{id,kind,actions:{}}};cards.set(id,value);(kind==='engine'?engineGrid:modelGrid).append(box);
  }
  for(const id of ['A','B','C','D'])card(id,'model');for(const id of ['freqtrade','hummingbot','jesse'])card(id,'engine');
  const metric=(parent,label,value,cls='')=>{const n=make('div','managed-metric');n.append(make('span','muted',label),make('strong',cls,value));parent.append(n);};
  function enginesNow(){return (state?.engines||[]).map(e=>({...e,busy:e.busy||inflight.has(e.id)}));}
  function render(){
   const now=Date.now()/1000,current=!!state&&now-state.updated>=-1&&now-state.updated<=8;
   connection.textContent=apiError||(!current?'Управление недоступно: ждём свежий ответ сервера':'Управление подключено · '+date(state.updated));connection.className=current?'models-connection positive':'models-connection muted';
   resources.textContent='Один внешний тест за раз.'+(state?.memory?' RAM сервера '+fmt(state.memory.total_gb)+' ГБ · доступно '+fmt(state.memory.available_gb)+' ГБ.':'')+' Freqtrade/Jesse: отдельные исторические тесты; Hummingbot: PAPER по публичному стакану.';
   const list=[...(state?.models||[]),...(state?.engines||[])];
   for(const [id,c]of cards){
    const item=list.find(i=>i.id===id),slot=testSlot(item,enginesNow());c.item=slot.item||{id,kind:c.item.kind,actions:{}};
    if(current&&item&&c.pendingCommand){
     const q=c.pendingCommand,failed=state.audit.find(e=>e.id===q.id&&e.outcome==='error');
     const delivered=state.audit.some(e=>e.id===q.id&&['delivered','applied'].includes(e.outcome));
     const confirmed=item.kind==='model'?item.generation===q.generation&&!item.pending&&item.fresh:
       delivered&&(q.action==='stop'?['completed','cancelled','failed','interrupted'].includes(item.phase):['running','completed','failed'].includes(item.phase));
     if(failed){c.response.textContent=failed.message||'Команда не выполнена';c.response.className='control-response negative';c.pendingCommand=null;}
     else if(confirmed){c.response.textContent=['failed','halted'].includes(item.phase)?item.reason||'Движок остановлен по ошибке':item.kind==='model'?({start:'Включение подтверждено.',stop:'Отключение подтверждено.',restart:'Перезапуск подтверждён.'}[q.action]):({start:'Запуск теста подтверждён.',stop:'Остановка теста подтверждена.',restart:'Повтор теста подтверждён.'}[q.action]);c.response.className='control-response '+(['failed','halted'].includes(item.phase)?'negative':'positive');c.pendingCommand=null;}
    }
    const phase=current&&item?item.phase:'unknown',active=current&&['running','completed'].includes(phase);
    c.badge.textContent=current&&item?(names[phase]||phase):'Нет управления';c.badge.className='managed-badge '+(active?'is-on':['failed','halted','interrupted'].includes(phase)?'is-error':['draining','pending','warming'].includes(phase)?'is-pending':'');
    c.box.classList.toggle('is-working',phase==='running'&&current);c.metrics.replaceChildren();
    if(c.item.kind==='model'){
     metric(c.metrics,'Капитал, USDT',fmt(item?.equity));metric(c.metrics,'Закрыто сделок',fmt(item?.closed,0));
     c.position.textContent=item?.position?'Позиция '+item.position.symbol+' · '+(item.position.side===1?'LONG':'SHORT')+(item.fresh?'':' · оценка устарела'):item?.fresh?'Открытой позиции нет':'Состояние позиции не подтверждено';
    }else{
     const m=item?.metrics;metric(c.metrics,id==='hummingbot'?'Изменение оценки, USDT':'Net теста, USDT',fmt(m?.net,4),m?.net>0?'positive':m?.net<0?'negative':'');metric(c.metrics,id==='hummingbot'?'PAPER-исполнений':'Сделок',fmt(id==='hummingbot'?m?.fills:m?.count,0));
     if(m){if(id==='hummingbot'){metric(c.metrics,'Оценка портфеля',fmt(m.equity));metric(c.metrics,'Оборот, USDT',fmt(m.turnover));}else{metric(c.metrics,'Profit factor',fmt(m.profit_factor));metric(c.metrics,'Просадка, %',fmt(m.drawdown_pct));}}
     c.position.textContent=item?.version?'Движок '+item.version+(item.settings?.start?' · '+date(item.settings.start)+' — '+date(item.settings.end):''):item?.installed?'Движок подготовлен':'Ожидает подготовки движка';
     c.readiness.replaceChildren();
     const required=item?.required_gb,prepared=current&&item?item.installed:null,ramReady=current&&item?item.memory_ok:null;
     const checks=[
      [prepared,prepared===true?'Окружение зарегистрировано':prepared===false?'Окружение не подготовлено':'Окружение'],
      [ramReady,(ramReady===false?'Памяти недостаточно':'Память')+(Number.isFinite(required)?' · нужно '+fmt(required)+' ГБ всего, '+fmt(required-1)+' ГБ доступно':'')],
      [current&&item?!slot.occupiedBy:null,slot.occupiedBy?'Слот занят: '+(engineNames[slot.occupiedBy]||slot.occupiedBy):'Других тестов нет']
     ];
     for(const [pass,label]of checks){const li=make('li',pass===true?'is-ready':pass===false?'is-blocked':'is-unknown');li.append(make('span','readiness-dot',pass===true?'✓':pass===false?'!':'—'),make('span','',label+(pass==null?' · нет свежих данных':'')));c.readiness.append(li);}
     c.runBody.replaceChildren();
     if(!item?.runs?.length)c.runBody.append(make('p','muted','Завершённых запусков пока нет.'));
     for(const run of item?.runs||[]){const row=make('div','engine-run');row.append(make('p','',date(run.started)+' · '+(names[run.phase]||run.phase)),make('p','muted',run.reason||''));if(run.metrics){row.append(make('p',run.metrics.net>0?'positive':run.metrics.net<0?'negative':'muted',(run.metrics.valuation?'Изменение оценки ':'Net ')+fmt(run.metrics.net,4)+' USDT · '+fmt(run.metrics.count??run.metrics.fills,0)+(run.metrics.valuation?' исполнений':' сделок')));}c.runBody.append(row);}
    }
    c.reason.textContent=slot.occupiedBy&&current?'Заверши тест '+(engineNames[slot.occupiedBy]||slot.occupiedBy)+' перед запуском другого движка.':item?.reason||(!current?'Для кнопок нужна доступная служба управления.':'');
    if(item?.kind==='engine'&&item?.installed&&!item.memory_ok)c.reason.className='managed-reason negative';else c.reason.className='managed-reason muted';
    const enabled=buttons(c.item,current&&!inflight.has(id));for(const [action,b]of Object.entries(c.buttons))b.disabled=!enabled[action];
   }
   log.replaceChildren();for(const e of state?.audit||[]){const r=make('div','control-event');r.append(make('time','muted',date(e.time)),make('span','',e.target+' · '+({start:'Включение',stop:'Отключение',restart:'Перезапуск'}[e.action]||e.action)+' · '+({accepted:'принято',delivered:'передано движку',applied:'подтверждено движком',error:'ошибка'}[e.outcome]||e.outcome)),make('small','muted',e.message||''));log.append(r);}if(!log.childElementCount)log.append(make('p','muted','Команд пока нет.'));
  }
  async function command(id,action){
   const c=cards.get(id),slot=testSlot(c.item,enginesNow());if(inflight.has(id)||!buttons(slot.item,!!state&&Date.now()/1000-state.updated<=8)[action])return;
   inflight.add(id);c.pendingCommand=null;const expected=c.item.generation+1;c.response.textContent='Отправляем команду…';c.response.className='control-response muted';render();
   try{
    const r=await fetch('/api/models-control',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':state.token},credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000),body:JSON.stringify({target:id,action,generation:c.item.generation})});
    const result=await r.json();if(!r.ok||result.status!=='accepted')throw Error(result.error||'HTTP '+r.status);
    c.pendingCommand={id:result.id,action,generation:expected};c.response.textContent='Команда принята. Ждём фактического состояния движка.';c.response.className='control-response muted';await poll(false);
   }catch(e){c.response.textContent=e.message;c.response.className='control-response negative';}finally{inflight.delete(id);render();}
  }
  async function poll(repeat=true){
   try{if(!document.hidden){const r=await fetch('/api/models-control',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(8000)});if(!r.ok)throw Error('Недоступно');const s=await r.json();if(s.status!=='ok'||!Array.isArray(s.models)||!Array.isArray(s.engines))throw Error('Неверный ответ');state=s;apiError='';render();}}
   catch{apiError='Управление ещё не подключено. После установки здесь появятся фактические статусы и кнопки.';state=null;render();}
   finally{if(repeat)setTimeout(poll,3000);}
  }
  poll();setInterval(()=>{if(!document.hidden)render();},1000);
 });
})(globalThis);
