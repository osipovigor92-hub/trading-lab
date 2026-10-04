/* Actual server lifecycle; buttons never infer success from a click. */
(function(scope){
 'use strict';
 const names={running:'Работает',warming:'Прогрев',waiting:'Ожидает данные',paused:'Отключена',stopped:'Служба остановлена',draining:'Завершает позицию',pending:'Применяет команду',halted:'Остановлена по защите',stale:'Нет свежего отчёта',unknown:'Нет отчёта',not_installed:'Не подготовлен',idle:'Готов к тесту',starting:'Запускается',completed:'Тест завершён',cancelled:'Тест отменён',failed:'Ошибка теста',interrupted:'Тест прерван',cancelling:'Останавливается на ПК',lost:'ПК потерял связь'};
 const engineNames={freqtrade:'Freqtrade',hummingbot:'Hummingbot',jesse:'Jesse'};
 const activePhases=['running','starting','cancelling','lost'];
 const terminalPhases=['completed','cancelled','failed','interrupted'];
 function controllerCurrent(state,now=Date.now()/1000){
  return typeof state?.updated==='number'&&Number.isFinite(state.updated)&&now-state.updated>=-1&&now-state.updated<=8;
 }
 function activeTest(state){
  const engines=Array.isArray(state?.engines)?state.engines:[];
  for(const raw of engines){
   const selected=Object.entries(raw.executors||{}).find(([,e])=>e?.test_active||activePhases.includes(e?.phase));
   if(selected)return {id:raw.id,execution:selected[0],item:executor(raw,selected[0])};
   if(raw.localPending)return {id:raw.id,execution:raw.localPending.execution,item:{phase:'pending',reason:'Ждём подтверждения запуска от исполнителя.',actions:{}}};
   if(raw.test_active||raw.busy||activePhases.includes(raw.phase))return {id:raw.id,execution:raw.execution||'vds',item:raw.busy&&!raw.test_active?{...raw,phase:'pending'}:raw};
  }
  const job=state?.worker?.job;
  return job&&engineNames[job.engine]&&['queued','dispatched',...activePhases].includes(job.phase)?{id:job.engine,execution:'pc',item:{phase:job.phase,test_active:true,actions:{}}}:null;
 }
 function lastTest(item){
  return (Array.isArray(item?.runs)?item.runs:[]).find(run=>terminalPhases.includes(run?.phase)&&
   (run.execution||'vds')===(item.execution||'vds'))||null;
 }
 function workerHealth(state,current=true){
  const pc=state?.worker||{},online=current&&pc.online===true;
  return {phase:!current?'unknown':online?'online':pc.configured?'offline':'unconfigured',
   online,configured:pc.configured===true,lastSeen:pc.last_seen||null,memory:online?pc.memory:null};
 }
 function centerState(state,id,execution,current=true){
  const raw=(Array.isArray(state?.engines)?state.engines:[]).find(e=>e.id===id),item=executor(raw,execution);
  const slot=testSlot(item,state?.engines||[]),enabled=buttons(slot.item,current),active=activeTest(state);
  const retry=terminalPhases.includes(item?.phase)&&enabled.restart;
  return {item,active,phase:current&&item?raw.localPending?'pending':item.phase:'unknown',result:lastTest(item),
   launchAction:retry?'restart':'start',canLaunch:!active&&(retry||enabled.start),
   canStop:current&&!!active&&buttons(active.item,true).stop,
   blockedBy:active&&(active.id!==id||active.execution!==execution)?active:null};
 }
 const setupCommands={freqtrade:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine freqtrade --install',jesse:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine jesse --install',hummingbot:'python3 /opt/trading-lab-repo/tools/prepare_engine.py --engine hummingbot --python /opt/hummingbot-env/bin/python'};
 async function controlJson(response){
  if(typeof scope.labParseJson==='function')return scope.labParseJson(response,'Управление моделями');
  const text=await response.text();let value;
  try{value=JSON.parse(text);}catch(_){throw Error('Управление моделями: сервер вернул некорректный ответ.');}
  if(!response.ok)throw Error(value?.error||'Управление моделями: HTTP '+response.status);
  return value;
 }
 function testSlot(item,engines=[]){
  if(item?.kind!=='engine')return {item,occupiedBy:null};
  const occupied=engines.find(e=>e.id!==item.id&&(e.busy||e.localPending||e.test_active||activePhases.includes(e.phase)||
   Object.values(e.executors||{}).some(x=>x?.test_active||activePhases.includes(x?.phase))));
  return {item:occupied?{...item,actions:{...item.actions,start:false,restart:false}}:item,occupiedBy:occupied?.id||null};
 }
 function executor(item,node='vds'){
  if(item?.kind!=='engine')return item;
  const selected=item.executors?.[node];
  if(!selected)return node==='vds'?{...item,execution:'vds'}:{...item,execution:'pc',installed:false,memory_ok:false,phase:'not_installed',reason:'Поддержка ПК ещё не установлена',metrics:null,runs:[],actions:{}};
  const result={...item,...selected,id:item.id,kind:'engine',execution:node};
  result.busy=!!(item.busy||selected.busy);
  if(item.test_active&&!selected.test_active){result.actions={...result.actions,start:false,restart:false};result.reason='Этот движок выполняется на другом исполнителе.';}
  return result;
 }
 function buttons(item,current=true){
  const a=item?.actions||{},off=['paused','stopped'].includes(item?.phase),busy=item?.busy||!current;
  if(item?.kind==='engine')return {start:!busy&&a.start===true,stop:!busy&&a.stop===true,restart:!busy&&a.restart===true&&item.phase!=='idle'};
  return {start:!busy&&a.start===true&&(off||['draining','pending','stale','unknown'].includes(item.phase)),stop:!busy&&a.stop===true&&!off&&!(item.pending&&item.requested==='stop'),restart:!busy&&a.restart===true&&!item.pending,new_run:!busy&&a.new_run===true&&!item.pending};
 }
 function operationsSummary(state,current=true){
  const models=Array.isArray(state?.models)?state.models:[],engines=Array.isArray(state?.engines)?state.engines:[];
  const worker=state?.worker||{};
  const activeModels=models.filter(x=>['running','warming','waiting','draining'].includes(x?.phase)).length;
  const protectedModels=models.filter(x=>['halted','stale','unknown','stopped'].includes(x?.phase)).length;
  const activeEngine=activeTest(state);
  const readyVds=current?engines.filter(x=>x?.executors?.vds?.installed&&x?.executors?.vds?.memory_ok).length:0;
  const readyPc=current&&worker.online===true?engines.filter(x=>x?.executors?.pc?.installed&&x?.executors?.pc?.memory_ok).length:0;
  return {current,activeModels,protectedModels,activeEngine:activeEngine?.id||null,
   workerOnline:current&&worker.online===true,workerConfigured:worker.configured===true,readyVds,readyPc};
 }
 const api={buttons,names,testSlot,executor,controlJson,operationsSummary,controllerCurrent,activeTest,lastTest,workerHealth,centerState};if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-research');if(!page)return;
  const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(v,n=2)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const date=v=>typeof v==='number'&&Number.isFinite(v)?new Date(v*1000).toLocaleString('ru-RU'):'—';
  const advanced=make('details','box models-analysis');advanced.append(make('summary','','Диагностика C/D и условия стратегий'));
  for(const node of [...page.children])if(node.id!=='research-journals')advanced.append(node);page.append(advanced);
  const heading=make('div','page-heading models-heading');heading.append(make('div','', ''));
  heading.firstChild.append(make('h2','','Модели и тестовые боты'));
  const connection=make('p','muted','Подключаем управление…');connection.setAttribute('role','status');heading.append(connection);
  const overview=make('section','models-ops-overview');overview.id='models-ops-overview';overview.setAttribute('aria-label','Состояние торговой лаборатории');
  const overviewGrid=make('div','models-ops-grid');overview.append(overviewGrid);
  const modelsBox=make('section','box models-section');modelsBox.id='model-controls';modelsBox.append(make('h3','','Текущие модели A / B / C / D'));
  modelsBox.append(make('p','muted','Отключение запрещает новые входы. Открытая PAPER-позиция завершается по прежним правилам. Перезапуск сохраняет капитал и журнал. Для другого бюджета создай новый PAPER-тест: прежний баланс, позиции и журнал останутся в архиве.'));
  const modelGrid=make('div','managed-grid');modelsBox.append(modelGrid);
  const engineBox=make('section','box models-section');engineBox.id='engine-controls';engineBox.append(make('h3','','Тесты Freqtrade / Hummingbot / Jesse'));
  const resources=make('p','muted','Один внешний тест за раз.');engineBox.append(resources);
  const worker=make('section','worker-status');worker.id='pc-worker-status';worker.setAttribute('aria-label','Исполнитель на ПК');
  const workerTitle=make('strong','','Проверяем связь с ПК'),workerNote=make('p','muted'),workerFacts=make('dl','worker-facts');workerTitle.setAttribute('role','status');
  const workerValues={};for(const [key,label]of [['seen','Последний ответ'],['total','Всего RAM'],['available','Доступно RAM']]){const pair=make('div');workerValues[key]=make('dd','','—');pair.append(make('dt','muted',label),workerValues[key]);workerFacts.append(pair);}
  const workerHelp=make('details','worker-help');workerHelp.append(make('summary','','Если ПК потерял связь'));
  workerHelp.append(make('p','muted','Оставь SSH-туннель 18787 открытым в отдельной вкладке Ubuntu. В другой вкладке проверь, что агент работает. После остановки агента его можно запустить этой командой:'));
  const agentCode=make('pre','setup-command');agentCode.append(make('code','','python3 ~/trading-lab-pc/integrations/worker/agent.py'));workerHelp.append(agentCode);
  const refresh=make('button','managed-copy','Проверить связь');refresh.type='button';refresh.addEventListener('click',async()=>{refresh.disabled=true;try{await poll(false);}finally{refresh.disabled=false;}});
  const workerTools=make('div','worker-tools');workerTools.append(workerHelp,refresh);worker.append(workerTitle,workerNote,workerFacts,workerTools);
  const center=make('section','engine-center');center.id='engine-test-center';center.setAttribute('aria-label','Центр управления внешним тестом');
  const launch=make('div','engine-launch');launch.append(make('h4','','Запуск внешнего теста'));
  const centerFields=make('div','engine-center-fields'),engineChoice=make('select'),targetChoice=make('select');engineChoice.setAttribute('aria-label','Движок внешнего теста');targetChoice.setAttribute('aria-label','Исполнитель внешнего теста');
  for(const [value,label]of Object.entries(engineNames)){const o=make('option','',label);o.value=value;engineChoice.append(o);}
  for(const [value,label]of [['pc','Мой ПК · Ubuntu / WSL2'],['vds','VDS · сервер']]){const o=make('option','',label);o.value=value;targetChoice.append(o);}
  for(const [label,input]of [['Движок',engineChoice],['Где выполнять расчёт',targetChoice]]){const n=make('label');n.append(make('span','muted',label),input);centerFields.append(n);}launch.append(centerFields);
  let centerInitialized=false;try{const saved=localStorage.getItem('lab-center-engine');if(engineNames[saved])engineChoice.value=saved;}catch{}
  const launchStatus=make('p','engine-launch-status'),launchNote=make('p','muted engine-launch-note'),launchButton=make('button','control-primary','Запустить выбранный тест'),launchResponse=make('p','control-response');launchResponse.setAttribute('role','status');launchButton.type='button';launchButton.disabled=true;
  launch.append(launchStatus,launchNote,launchButton,launchResponse);
  const session=make('div','engine-session');session.append(make('h4','','Единый тестовый слот'));
  const sessionTitle=make('strong','engine-session-title','Проверяем состояние'),sessionNote=make('p','muted'),stopButton=make('button','control-secondary','Остановить текущий тест');sessionTitle.setAttribute('role','status');stopButton.type='button';stopButton.disabled=true;
  const stages=make('ol','engine-test-stages');stages.setAttribute('aria-label','Этапы текущего теста');for(const label of ['Запуск','Расчёт','Итог'])stages.append(make('li','',label));
  const resultHeading=make('h5','','Последний завершённый запуск'),resultStamp=make('p','muted engine-result-stamp'),resultMetrics=make('dl','engine-result-metrics'),resultNote=make('p','muted engine-result-note'),resultLink=make('a','research-link','Журнал выбранного движка CSV');resultLink.download='tests.csv';
  const resultBox=make('div','engine-center-result');resultBox.append(resultHeading,resultStamp,resultMetrics,resultNote,resultLink);session.append(sessionTitle,sessionNote,stages,stopButton,resultBox);center.append(launch,session);
  const workbench=make('div','engine-workbench');workbench.append(center,worker);engineBox.append(workbench);
  const setup=make('details','models-setup');setup.append(make('summary','','Подготовка и проверка установки'));
  setup.append(make('p','muted','Выбери место расчёта: VDS или Мой ПК. Движок готовят на выбранной машине. На Windows исполнитель работает в Ubuntu / WSL2 и связывается с панелью через SSH-туннель. ПК должен быть включён; браузер можно закрыть.'));
  const diagnostic=make('pre','setup-command');diagnostic.append(make('code','','python3 /opt/trading-lab-repo/tools/diagnose_models.py'));setup.append(make('p','muted','Проверить службы, версии и доступность тестов без перезапуска:'),diagnostic);
  engineBox.append(setup);
  const engineGrid=make('div','engine-grid');engineBox.append(engineGrid);
  const logBox=make('details','box models-audit');logBox.id='model-control-journal';logBox.append(make('summary','','Журнал управления'));
  const log=make('div','control-log');logBox.append(log);
  page.prepend(heading,overview,engineBox,modelsBox,logBox);
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
   let paperSettings,paperFields,paperNote,newRunButton,paperDirty=false;
   if(kind==='model'){
    paperSettings=make('section','paper-settings');paperSettings.append(make('h5','','Новый PAPER-тест'));
    paperSettings.append(make('p','muted','Параметры применяются только к новому прогону. Текущий баланс и журнал не переписываются.'));
    const fieldGrid=make('div','paper-settings-grid');paperFields={};
    for(const [key,label,min,step] of [['capital','Бюджет, USDT','10','1'],['notional','Вход, USDT','1','1'],['max_loss','Лимит потерь, USDT','0.01','0.01']]){
     const labelNode=make('label','paper-setting');labelNode.append(make('span','',label));const input=make('input');input.type='number';input.inputMode='decimal';input.min=min;input.step=step;input.required=true;input.setAttribute('aria-label',label+' для модели '+id);input.addEventListener('input',()=>{paperDirty=true;paperNote.textContent='Параметры изменены. Они не затронут текущий прогон.';});labelNode.append(input);fieldGrid.append(labelNode);paperFields[key]=input;
    }
    paperSettings.append(fieldGrid);
    const presets=make('div','paper-presets');presets.append(make('span','muted','Бюджет:'));
    for(const value of [100,300,600,1000]){const preset=make('button','paper-preset',value+' USDT');preset.type='button';preset.addEventListener('click',()=>{paperFields.capital.value=String(value);if(Number(paperFields.notional.value)>value||!paperFields.notional.value)paperFields.notional.value=String(Math.min(100,value));if(Number(paperFields.max_loss.value)>=value||!paperFields.max_loss.value)paperFields.max_loss.value=String(Math.max(.5,Math.min(18,value*.03)));paperDirty=true;paperNote.textContent='Выбран бюджет '+value+' USDT. Проверь размер входа и лимит потерь.';});presets.append(preset);}
    paperSettings.append(presets);
    paperNote=make('p','paper-settings-note');paperNote.setAttribute('role','status');paperSettings.append(paperNote);
    newRunButton=make('button','new-run-button','Сохранить и начать новый тест');newRunButton.type='button';newRunButton.disabled=true;newRunButton.addEventListener('click',()=>command(id,'new_run'));paperSettings.append(newRunButton);box.append(paperSettings);
   }
   const response=make('p','control-response');response.setAttribute('role','status');box.append(response);
   let runs, runBody, readiness, selector, prepareCode, prepareNote;
   if(kind==='engine'){
    const target=make('label','engine-execution');target.append(make('span','muted','Где выполнять расчёт'));
    selector=make('select');selector.setAttribute('aria-label','Исполнитель '+title.textContent);
    for(const [value,label]of [['vds','VDS · сервер'],['pc','Мой ПК · Ubuntu / WSL2']]){const option=make('option','',label);option.value=value;selector.append(option);}
    try{selector.value=localStorage.getItem('lab-executor-'+id)||'vds';}catch{}
    selector.addEventListener('change',()=>{try{localStorage.setItem('lab-executor-'+id,selector.value);}catch{}cards.get(id).pendingCommand=null;cards.get(id).response.textContent='';render();});target.append(selector);box.insertBefore(target,metrics);
    readiness=make('ul','engine-readiness');readiness.setAttribute('aria-label','Готовность '+title.textContent);box.insertBefore(readiness,actions);
    const prepare=make('details','engine-prepare');prepare.append(make('summary','','Как подготовить '+title.textContent));
    prepareNote=make('p','muted');prepare.append(prepareNote);
    const code=make('pre','setup-command');prepareCode=make('code','',setupCommands[id]);code.append(prepareCode);prepare.append(code);
    const copy=make('button','managed-copy',id==='hummingbot'?'Скопировать шаблон':'Скопировать команду');copy.type='button';copy.setAttribute('aria-label',copy.textContent+' '+title.textContent);
    const copyStatus=make('p','muted');copyStatus.setAttribute('role','status');
    copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(prepareCode.textContent);copyStatus.textContent='Скопировано. Выполни команду на выбранном исполнителе.';}catch{copyStatus.textContent='Буфер обмена недоступен. Выдели и скопируй команду выше.';}});prepare.append(copy,copyStatus);box.append(prepare);
    runs=make('details','engine-runs');runs.append(make('summary','','Последние тестовые запуски'));runBody=make('div','engine-run-list');runs.append(runBody);box.append(runs);
    const csv=make('a','research-link','Журнал тестов CSV');csv.href='/api/engine-journal?engine='+id;csv.download=id+'-tests.csv';box.append(csv);
   }else{
    const a=make('button','managed-journal','Открыть журнал сделок →');a.type='button';a.addEventListener('click',()=>{document.dispatchEvent(new CustomEvent('lab-navigate',{detail:'journals'}));document.getElementById(id==='C'||id==='D'?'research-journals':'model-journals')?.scrollIntoView({block:'start',behavior:'smooth'});});box.append(a);
   }
   const value={box,badge,metrics,position,reason,buttons,response,runBody,readiness,selector,prepareCode,prepareNote,paperSettings,paperFields,paperNote,newRunButton,paperDirty,item:{id,kind,actions:{}}};cards.set(id,value);(kind==='engine'?engineGrid:modelGrid).append(box);
  }
  for(const id of ['A','B','C','D'])card(id,'model');for(const id of ['freqtrade','hummingbot','jesse'])card(id,'engine');
  const metric=(parent,label,value,cls='')=>{const n=make('div','managed-metric');n.append(make('span','muted',label),make('strong',cls,value));parent.append(n);};
  const put=(node,text)=>{if(node.textContent!==text)node.textContent=text;};
  function chooseTest(id,execution){
   const c=cards.get(id);if(!c?.selector||!['pc','vds'].includes(execution))return;
   engineChoice.value=id;c.selector.value=execution;
   try{localStorage.setItem('lab-center-engine',id);localStorage.setItem('lab-executor-'+id,execution);}catch{}
  }
  engineChoice.addEventListener('change',()=>{chooseTest(engineChoice.value,targetChoice.value);render();});
  targetChoice.addEventListener('change',()=>{chooseTest(engineChoice.value,targetChoice.value);render();});
  launchButton.addEventListener('click',()=>{
   const view=centerState(state,engineChoice.value,targetChoice.value,!apiError&&controllerCurrent(state));
   if(view.canLaunch)command(engineChoice.value,view.launchAction);
  });
  stopButton.addEventListener('click',()=>{
   const view=centerState(state,engineChoice.value,targetChoice.value,!apiError&&controllerCurrent(state));
   if(view.canStop&&view.active){chooseTest(view.active.id,view.active.execution);render();command(view.active.id,'stop');}
  });
  function enginesNow(){return (state?.engines||[]).map(e=>{
   const c=cards.get(e.id),q=c?.pendingCommand;
   const waiting=!e.test_active&&(inflight.has(e.id)||q&&q.action!=='stop');
   return {...e,busy:e.busy||inflight.has(e.id),localPending:waiting?{execution:q?.execution||c?.selector?.value||'vds'}:null};
  });}
  function renderCenter(current){
   const id=engineChoice.value,c=cards.get(id),raw=state?.engines?.find(e=>e.id===id);
   targetChoice.value=c.selector.value;targetChoice.disabled=!current||inflight.has(id)||!!raw?.test_active;
   engineChoice.disabled=inflight.size>0;
   const view=centerState({...state,engines:enginesNow()},id,targetChoice.value,current&&!inflight.has(id)),item=view.item;
   launchButton.disabled=!view.canLaunch;put(launchButton,view.launchAction==='restart'?'Повторить выбранный тест':'Запустить выбранный тест');
   put(launchStatus,!current?'Нет свежего состояния':view.canLaunch?'Готов к запуску':names[view.phase]||'Запуск недоступен');
   launchStatus.className='engine-launch-status '+(!current?'muted':view.canLaunch?'positive':'');
   const pc=workerHealth(state,current);
   put(launchNote,!current?'Проверяем связь с контроллером. Действия станут доступны после свежего ответа.':
    view.blockedBy?'Слот занят: '+engineNames[view.blockedBy.id]+' · '+(view.blockedBy.execution==='pc'?'Мой ПК':'VDS')+'. Дождись результата или останови текущий тест.':
    targetChoice.value==='pc'&&!pc.online?pc.configured?'ПК не отвечает. Проверь открытый туннель 18787 и работающий агент.':'Сначала подключи исполнитель на ПК.':
    item?.reason||'Выбери подготовленный движок и исполнитель.');
   put(launchResponse,c.response.textContent);launchResponse.className=c.response.className;
   const active=view.active,phase=active?.item?.phase;
   put(sessionTitle,!current?'Состояние слота не подтверждено':active?engineNames[active.id]+' · '+(active.execution==='pc'?'Мой ПК':'VDS')+' · '+(names[phase]||'Команда обрабатывается'):'Свободно');
   sessionTitle.className='engine-session-title '+(current&&active&&['lost','failed'].includes(phase)?'negative':'');
   put(sessionNote,!current?active?'Последний ответ содержал незавершённый тест '+engineNames[active.id]+'. Ждём подтверждения контроллера.':'Ждём подтверждения контроллера. Свободный слот пока не подтверждён.':
    active?phase==='lost'?'ПК потерял связь. Задание удерживает слот до подтверждения остановки.':phase==='cancelling'?'Отмена запрошена. Слот освободится после подтверждения исполнителя.':active.item.reason||'Ждём подтверждения исполнителя.':'Один внешний тест за раз на ПК или VDS.');
   const step=['starting','queued','dispatched'].includes(phase)?0:phase==='running'?1:-1;stages.hidden=!current||step<0;
   [...stages.children].forEach((node,index)=>{node.className=index<step?'is-done':index===step?'is-current':'';if(index===step)node.setAttribute('aria-current','step');else node.removeAttribute('aria-current');});
   stopButton.disabled=!view.canStop||!!active&&inflight.has(active.id);
   put(resultHeading,active?'Предыдущий завершённый запуск':'Последний завершённый запуск');
   const run=view.result,m=run?.metrics;resultMetrics.replaceChildren();
   put(resultStamp,run?engineNames[id]+' · '+(targetChoice.value==='pc'?'Мой ПК':'VDS')+' · '+(names[run.phase]||run.phase)+' · '+date(run.finished??run.started??run.created):'Завершённых запусков на этом исполнителе пока нет.');
   const resultMetric=(label,value,cls='')=>{const pair=make('div');pair.append(make('dt','muted',label),make('dd',cls,value));resultMetrics.append(pair);};
   if(m){
    resultMetric(id==='hummingbot'?'Изменение оценки, USDT':'Net P&L, USDT',fmt(m.net,4),m.net>0?'positive':m.net<0?'negative':'');
    resultMetric(id==='hummingbot'?'PAPER-исполнений':'Закрытых сделок',fmt(id==='hummingbot'?m.fills:m.count,0));
    if(id==='hummingbot'){resultMetric('Оценка портфеля, USDT',fmt(m.equity));resultMetric('Оборот, USDT',fmt(m.turnover));}
    else{resultMetric('Profit factor',fmt(m.profit_factor));resultMetric('Просадка, %',fmt(m.drawdown_pct));}
   }
   put(resultNote,run?(current?'':'Архивные данные; текущее исполнение не подтверждено. ')+(run.reason||'')+(!m?' Итоговые метрики для этого запуска не получены.':''):'После завершения исполнитель передаст результат в панель.');
   resultLink.href='/api/engine-journal?engine='+id;resultLink.download=id+'-tests.csv';
   worker.className='worker-status '+(pc.phase==='online'?'is-online':pc.phase==='unknown'?'is-unknown':'is-offline');
   put(workerTitle,pc.phase==='unknown'?'Связь с ПК не подтверждена':pc.online?'Мой ПК подключён':pc.configured?'Мой ПК не подключён':'Исполнитель ПК ещё не подключён');
   put(workerNote,pc.phase==='unknown'?'Нет свежего ответа контроллера. Проверяем доступность ПК.':pc.online?'Расчёты выполняются в Ubuntu / WSL2. ПК, туннель и агент должны оставаться включёнными.':pc.configured?'ПК уже привязан. Проверь туннель и агент, затем нажми «Проверить связь».':'В инструкции ниже описано первичное подключение Ubuntu / WSL2.');
   put(workerValues.seen,date(pc.lastSeen));put(workerValues.total,pc.memory?fmt(pc.memory.total_gb)+' ГБ':'—');put(workerValues.available,pc.memory?fmt(pc.memory.available_gb)+' ГБ':'—');
   workerHelp.hidden=!pc.configured;
  }
  function render(){
   const current=!apiError&&controllerCurrent(state);
   connection.textContent=apiError||(!current?'Управление недоступно: ждём свежий ответ сервера':'Управление подключено · '+date(state.updated));connection.className=apiError?'models-connection negative':current?'models-connection positive':'models-connection muted';
   const summary=operationsSummary({...state,engines:enginesNow()},current);overviewGrid.replaceChildren();
   const opCard=(label,value,note,cls='')=>{const n=make('div','models-ops-card '+cls);n.append(make('span','muted',label),make('strong','',value),make('small','muted',note));overviewGrid.append(n);};
   opCard('Модели A–D',current?summary.activeModels+' активны':'Нет связи',current?(summary.protectedModels?summary.protectedModels+' требуют внимания':'Защитных остановок нет'):'Ждём свежий ответ',current&&summary.protectedModels?'is-warning':'');
   opCard('Внешний тест',!current?'Нет свежих данных':summary.activeEngine?(engineNames[summary.activeEngine]||summary.activeEngine):'Свободно',!current?'Состояние слота не подтверждено':summary.activeEngine?'Занят единый тестовый слот':'Можно запускать подготовленный движок',current&&summary.activeEngine?'is-working':'');
   opCard('Мой ПК',!current?'Нет свежих данных':summary.workerOnline?'Подключён':summary.workerConfigured?'Не в сети':'Не настроен',!current?'Связь с ПК не подтверждена':summary.workerOnline?summary.readyPc+' движка готовы':summary.workerConfigured?'Проверь туннель и агент':'Требуется первичное подключение',summary.workerOnline?'is-online':current?'is-warning':'');
   opCard('VDS',current?summary.readyVds+' движка готовы':'Нет связи',current&&state?.memory?'RAM '+fmt(state.memory.available_gb)+' ГБ доступно':'Память не подтверждена');
   resources.textContent='Один внешний тест за раз.'+(current&&state?.memory?' RAM сервера '+fmt(state.memory.total_gb)+' ГБ · доступно '+fmt(state.memory.available_gb)+' ГБ.':'')+' Freqtrade/Jesse: отдельные исторические тесты; Hummingbot: PAPER по публичному стакану.';
   if(!centerInitialized&&state){
    const id=engineChoice.value,raw=state.engines.find(e=>e.id===id);let saved;
    try{saved=localStorage.getItem('lab-executor-'+id);}catch{}
    if(!saved&&state.worker?.configured&&!raw?.test_active)cards.get(id).selector.value='pc';
    centerInitialized=true;
   }
   const list=[...(state?.models||[]),...(state?.engines||[])];
   for(const [id,c]of cards){
    const raw=list.find(i=>i.id===id);
    if(c.selector&&raw?.test_active){const running=Object.entries(raw.executors||{}).find(([,e])=>e.test_active);if(running)c.selector.value=running[0];}
    const item=executor(raw,c.selector?.value||'vds'),slot=testSlot(item,enginesNow());c.item=slot.item||{id,kind:c.item.kind,actions:{}};
    if(c.selector)c.selector.disabled=inflight.has(id)||!!raw?.test_active;
    if(current&&item&&c.pendingCommand){
     const q=c.pendingCommand,failed=state.audit.find(e=>e.id===q.id&&e.outcome==='error');
     const delivered=state.audit.some(e=>e.id===q.id&&['delivered','applied'].includes(e.outcome));
     const confirmed=q.action==='new_run'?
       delivered&&item.generation===q.generation&&item.experiment?.id&&item.experiment.id!==q.previousExperiment:
       item.kind==='model'?item.generation===q.generation&&!item.pending&&item.fresh:
       delivered&&(q.action==='stop'?['completed','cancelled','failed','interrupted'].includes(item.phase):['running','completed','failed'].includes(item.phase));
     if(failed){c.response.textContent=failed.message||'Команда не выполнена';c.response.className='control-response negative';c.pendingCommand=null;}
     else if(confirmed){c.response.textContent=q.action==='new_run'?'Новый PAPER-тест запущен. Предыдущий журнал сохранён в архиве.':['failed','halted'].includes(item.phase)?item.reason||'Движок остановлен по ошибке':item.kind==='model'?({start:'Включение подтверждено.',stop:'Отключение подтверждено.',restart:'Перезапуск подтверждён.'}[q.action]):({start:'Запуск теста подтверждён.',stop:'Остановка теста подтверждена.',restart:'Повтор теста подтверждён.'}[q.action]);c.response.className='control-response '+(['failed','halted'].includes(item.phase)?'negative':'positive');if(q.action==='new_run')c.paperDirty=false;c.pendingCommand=null;}
    }
    const phase=current&&item?item.phase:'unknown',active=current&&['running','completed'].includes(phase);
    c.badge.textContent=current&&item?(names[phase]||phase):'Нет управления';c.badge.className='managed-badge '+(active?'is-on':['failed','halted','interrupted','lost'].includes(phase)?'is-error':['draining','pending','warming','cancelling'].includes(phase)?'is-pending':'');
    c.box.classList.toggle('is-working',phase==='running'&&current);c.metrics.replaceChildren();
    if(c.item.kind==='model'){
     const settings=item?.experiment?.settings||{};
     metric(c.metrics,'Бюджет, USDT',fmt(settings.capital));metric(c.metrics,'Оценка, USDT',fmt(current&&item?.fresh?item.equity:null));metric(c.metrics,'Закрыто сделок',fmt(item?.closed,0));
     c.position.textContent=!current?'Состояние позиции не подтверждено':item?.position?'Позиция '+item.position.symbol+' · '+(item.position.side===1?'LONG':'SHORT')+(item.fresh?'':' · оценка устарела'):item?.fresh?'Открытой позиции нет':'Состояние позиции не подтверждено';
     if(c.paperFields){
      const defaults={capital:settings.capital??item?.equity??600,notional:settings.notional??100,max_loss:settings.max_loss??18};
      if(!c.paperDirty)for(const [key,value]of Object.entries(defaults))c.paperFields[key].value=Number.isFinite(value)?String(value):'';
      c.paperNote.textContent=c.paperDirty?c.paperNote.textContent||'Параметры изменены. Они не затронут текущий прогон.':item?.new_run_note||'Сначала отключи модель, затем создай новый тест.';
      c.paperSettings.classList.toggle('is-ready',!!item?.actions?.new_run);
     }
    }else{
     const onPC=item?.execution==='pc';
     c.prepareCode.textContent=onPC?'python3 ~/trading-lab-pc/tools/worker_setup.py prepare --engine '+id+(id==='hummingbot'?' --python /home/USER/hummingbot-env/bin/python':' --install'):setupCommands[id];
     c.prepareNote.textContent=id==='hummingbot'?'Нужно официальное скомпилированное окружение Hummingbot на выбранной машине. В шаблоне замени путь к Python на настоящий. Если исходники отдельно, добавь --source-dir.':onPC?'Выполняй в терминале Ubuntu на ПК, без sudo. Перед подготовкой останови агент Ctrl+C; после проверки снова запусти его.':'Выполняй от root на VDS с достаточной памятью. Команда создаёт отдельное окружение с проверенной версией.';
     const m=item?.metrics;metric(c.metrics,id==='hummingbot'?'Изменение оценки, USDT':'Net теста, USDT',fmt(m?.net,4),m?.net>0?'positive':m?.net<0?'negative':'');metric(c.metrics,id==='hummingbot'?'PAPER-исполнений':'Сделок',fmt(id==='hummingbot'?m?.fills:m?.count,0));
     if(m){if(id==='hummingbot'){metric(c.metrics,'Оценка портфеля',fmt(m.equity));metric(c.metrics,'Оборот, USDT',fmt(m.turnover));}else{metric(c.metrics,'Profit factor',fmt(m.profit_factor));metric(c.metrics,'Просадка, %',fmt(m.drawdown_pct));}}
     c.position.textContent=(onPC?'Исполнение на ПК · ':'Исполнение на VDS · ')+(item?.version?'Движок '+item.version+(item.settings?.start?' · '+date(item.settings.start)+' — '+date(item.settings.end):''):item?.installed?'Движок подготовлен':'Ожидает подготовки движка');
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
     for(const run of item?.runs||[]){const row=make('div','engine-run');row.append(make('p','',date(run.started??run.created)+' · '+(run.execution==='pc'?'ПК':'VDS')+' · '+(names[run.phase]||run.phase)),make('p','muted',run.reason||''));if(run.metrics){row.append(make('p',run.metrics.net>0?'positive':run.metrics.net<0?'negative':'muted',(run.metrics.valuation?'Изменение оценки ':'Net ')+fmt(run.metrics.net,4)+' USDT · '+fmt(run.metrics.count??run.metrics.fills,0)+(run.metrics.valuation?' исполнений':' сделок')));}c.runBody.append(row);}
    }
    c.reason.textContent=slot.occupiedBy&&current?'Заверши тест '+(engineNames[slot.occupiedBy]||slot.occupiedBy)+' перед запуском другого движка.':item?.reason||(!current?'Для кнопок нужна доступная служба управления.':'');
    if(item?.kind==='engine'&&item?.installed&&!item.memory_ok)c.reason.className='managed-reason negative';else c.reason.className='managed-reason muted';
    const enabled=buttons(c.item,current&&!inflight.has(id)&&!(c.item.kind==='engine'&&c.pendingCommand&&!raw?.test_active));for(const [action,b]of Object.entries(c.buttons))b.disabled=!enabled[action];
    if(c.newRunButton){c.newRunButton.disabled=!enabled.new_run;for(const input of Object.values(c.paperFields))input.disabled=!current||inflight.has(id);}
   }
   renderCenter(current);
   log.replaceChildren();for(const e of state?.audit||[]){const r=make('div','control-event');r.append(make('time','muted',date(e.time)),make('span','',e.target+' · '+({start:'Включение',stop:'Отключение',restart:'Перезапуск',new_run:'Новый прогон'}[e.action]||e.action)+' · '+({accepted:'принято',delivered:'передано движку',applied:'подтверждено движком',error:'ошибка'}[e.outcome]||e.outcome)),make('small','muted',e.message||''));log.append(r);}if(!log.childElementCount)log.append(make('p','muted','Команд пока нет.'));
  }
  function paperExperiment(c){
   const values={};for(const key of ['capital','notional','max_loss'])values[key]=Number(c.paperFields?.[key]?.value);
   if(!Number.isFinite(values.capital)||values.capital<10||values.capital>1000000)throw Error('Бюджет: от 10 до 1 000 000 USDT.');
   if(!Number.isFinite(values.notional)||values.notional<1||values.notional>values.capital)throw Error('Размер входа: от 1 USDT до бюджета.');
   if(!Number.isFinite(values.max_loss)||values.max_loss<=0||values.max_loss>=values.capital)throw Error('Лимит потерь должен быть больше нуля и меньше бюджета.');
   return values;
  }
  async function command(id,action){
   const c=cards.get(id),slot=testSlot(c.item,enginesNow()),available=buttons(slot.item,!apiError&&controllerCurrent(state)&&!(c.item.kind==='engine'&&c.pendingCommand&&!c.item.test_active));if(inflight.has(id)||!available[action])return;
   let experiment;
   if(action==='new_run'){
    try{experiment=paperExperiment(c);}catch(e){c.response.textContent=e.message;c.response.className='control-response negative';return;}
    const shared=id==='C'||id==='D'?' Модели C и D начнут новый общий прогон.':'';
    if(!window.confirm('Начать новый PAPER-тест для модели '+id+'? Предыдущий баланс, позиции и журнал будут сохранены в архиве и не изменятся.'+shared))return;
   }
   inflight.add(id);c.pendingCommand=null;const expected=c.item.generation+1;c.response.textContent='Отправляем команду…';c.response.className='control-response muted';render();
   try{
    const payload={target:id,action,generation:c.item.generation};if(action==='new_run')payload.experiment=experiment;else if(c.item.kind==='engine'&&c.item.execution==='pc')payload.execution='pc';
    const r=await fetch('/api/models-control',{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':state.token},credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000),body:JSON.stringify(payload)});
    const result=await controlJson(r);if(result.status!=='accepted')throw Error(result.error||'Управление не приняло команду.');
    c.pendingCommand={id:result.id,action,execution:payload.execution||'vds',generation:expected,previousExperiment:c.item.experiment?.id||''};c.response.textContent=action==='new_run'?'Новый прогон принят. Сохраняем журнал и ждём запуска модели.':'Команда принята. Ждём фактического состояния движка.';c.response.className='control-response muted';await poll(false);
   }catch(e){c.response.textContent=e.message;c.response.className='control-response negative';}finally{inflight.delete(id);render();}
  }
  async function poll(repeat=true){
   try{if(!document.hidden){const r=await fetch('/api/models-control',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(8000)});const s=await controlJson(r);if(s.status!=='ok'||!Array.isArray(s.models)||!Array.isArray(s.engines)||typeof s.updated!=='number'||!Number.isFinite(s.updated))throw Error('Управление моделями: сервер вернул неполные данные.');state=s;apiError='';render();}}
   catch(e){apiError=e?.message||'Управление ещё не подключено. После установки здесь появятся фактические статусы и кнопки.';render();}
   finally{if(repeat)setTimeout(poll,3000);}
  }
  poll();setInterval(()=>{if(!document.hidden)render();},1000);
 });
})(globalThis);
