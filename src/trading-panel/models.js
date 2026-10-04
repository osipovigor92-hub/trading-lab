/* Actual server lifecycle; buttons never infer success from a click. */
(function(scope){
 'use strict';
 const names={running:'Работает',warming:'Прогрев',waiting:'Ожидает данные',paused:'Отключена',stopped:'Служба остановлена',draining:'Завершает позицию',pending:'Применяет команду',halted:'Остановлена по защите',stale:'Нет свежего отчёта',unknown:'Нет отчёта',not_installed:'Не подготовлен',idle:'Готов к тесту',starting:'Запускается',completed:'Тест завершён',cancelled:'Тест отменён',failed:'Ошибка теста',interrupted:'Тест прерван',cancelling:'Останавливается на ПК',lost:'ПК потерял связь'};
 const engineNames={freqtrade:'Freqtrade',hummingbot:'Hummingbot',jesse:'Jesse'};
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
  const occupied=engines.find(e=>e.id!==item.id&&(e.busy||e.test_active||['running','starting','cancelling','lost'].includes(e.phase)));
  return {item:occupied?{...item,actions:{...item.actions,start:false,restart:false}}:item,occupiedBy:occupied?.id||null};
 }
 function executor(item,node='vds'){
  if(item?.kind!=='engine')return item;
  const selected=item.executors?.[node];
  if(!selected)return node==='vds'?{...item,execution:'vds'}:{...item,execution:'pc',installed:false,memory_ok:false,phase:'not_installed',reason:'Поддержка ПК ещё не установлена',metrics:null,runs:[],actions:{}};
  const result={...item,...selected,id:item.id,kind:'engine',execution:node};
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
  const activeEngine=engines.find(x=>x?.test_active||['running','starting','cancelling','lost'].includes(x?.phase));
  const readyVds=engines.filter(x=>x?.executors?.vds?.installed&&x?.executors?.vds?.memory_ok).length;
  const readyPc=engines.filter(x=>x?.executors?.pc?.installed&&x?.executors?.pc?.memory_ok).length;
  return {current,activeModels,protectedModels,activeEngine:activeEngine?.id||null,
   workerOnline:current&&worker.online===true,workerConfigured:worker.configured===true,readyVds,readyPc};
 }
 const api={buttons,names,testSlot,executor,controlJson,operationsSummary};if(typeof module!=='undefined')module.exports=api;
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
  const overview=make('section','models-ops-overview');overview.id='models-ops-overview';overview.setAttribute('aria-label','Состояние торговой лаборатории');
  const overviewGrid=make('div','models-ops-grid');overview.append(overviewGrid);
  const modelsBox=make('section','box models-section');modelsBox.id='model-controls';modelsBox.append(make('h3','','Текущие модели A / B / C / D'));
  modelsBox.append(make('p','muted','Отключение запрещает новые входы. Открытая PAPER-позиция завершается по прежним правилам. Перезапуск сохраняет капитал и журнал. Для другого бюджета создай новый PAPER-тест: прежний баланс, позиции и журнал останутся в архиве.'));
  const modelGrid=make('div','managed-grid');modelsBox.append(modelGrid);
  const engineBox=make('section','box models-section');engineBox.id='engine-controls';engineBox.append(make('h3','','Тесты Freqtrade / Hummingbot / Jesse'));
  const resources=make('p','muted','Один внешний тест за раз.');engineBox.append(resources);
  const worker=make('div','worker-status');worker.id='pc-worker-status';worker.setAttribute('role','status');engineBox.append(worker);
  const setup=make('details','models-setup');setup.append(make('summary','','Подготовка и проверка установки'));
  setup.append(make('p','muted','Выбери место расчёта: VDS или Мой ПК. Движок готовят на выбранной машине. На Windows исполнитель работает в Ubuntu / WSL2 и связывается с панелью через SSH-туннель. ПК должен быть включён; браузер можно закрыть.'));
  const diagnostic=make('pre','setup-command');diagnostic.append(make('code','','python3 /opt/trading-lab-repo/tools/diagnose_models.py'));setup.append(make('p','muted','Проверить службы, версии и доступность тестов без перезапуска:'),diagnostic);
  engineBox.append(setup);
  const engineGrid=make('div','engine-grid');engineBox.append(engineGrid);
  const logBox=make('details','box models-audit');logBox.id='model-control-journal';logBox.append(make('summary','','Журнал управления'));
  const log=make('div','control-log');logBox.append(log);
  page.prepend(heading,overview,modelsBox,engineBox,logBox);
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
  function enginesNow(){return (state?.engines||[]).map(e=>({...e,busy:e.busy||inflight.has(e.id)}));}
  function render(){
   const now=Date.now()/1000,current=!!state&&now-state.updated>=-1&&now-state.updated<=8;
   connection.textContent=apiError||(!current?'Управление недоступно: ждём свежий ответ сервера':'Управление подключено · '+date(state.updated));connection.className=apiError?'models-connection negative':current?'models-connection positive':'models-connection muted';
   const summary=operationsSummary(state,current);overviewGrid.replaceChildren();
   const opCard=(label,value,note,cls='')=>{const n=make('div','models-ops-card '+cls);n.append(make('span','muted',label),make('strong','',value),make('small','muted',note));overviewGrid.append(n);};
   opCard('Модели A–D',current?summary.activeModels+' активны':'Нет связи',current?(summary.protectedModels?summary.protectedModels+' требуют внимания':'Защитных остановок нет'):'Ждём свежий ответ',current&&summary.protectedModels?'is-warning':'');
   opCard('Внешний тест',summary.activeEngine?(engineNames[summary.activeEngine]||summary.activeEngine):'Свободно',summary.activeEngine?'Занят единый тестовый слот':'Можно запускать подготовленный движок',summary.activeEngine?'is-working':'');
   opCard('Мой ПК',summary.workerOnline?'Подключён':summary.workerConfigured?'Не в сети':'Не настроен',summary.workerOnline?summary.readyPc+' движка готовы':summary.workerConfigured?'Запусти туннель и агент':'Требуется первичное подключение',summary.workerOnline?'is-online':'is-warning');
   opCard('VDS',current?summary.readyVds+' движка готовы':'Нет связи',state?.memory?'RAM '+fmt(state.memory.available_gb)+' ГБ доступно':'Память не подтверждена');
   resources.textContent='Один внешний тест за раз.'+(state?.memory?' RAM сервера '+fmt(state.memory.total_gb)+' ГБ · доступно '+fmt(state.memory.available_gb)+' ГБ.':'')+' Freqtrade/Jesse: отдельные исторические тесты; Hummingbot: PAPER по публичному стакану.';
   const pc=state?.worker;worker.className='worker-status '+(current&&pc?.online?'is-online':'is-offline');worker.replaceChildren();
   worker.append(make('strong','',current&&pc?.online?'Мой ПК подключён':pc?.configured?'Мой ПК не подключён':'Исполнитель ПК ещё не подключён'));
   worker.append(make('p','muted',current&&pc?.online?'RAM исполнителя '+fmt(pc.memory?.total_gb)+' ГБ · доступно '+fmt(pc.memory?.available_gb)+' ГБ. Расчёты используют процессор и память ПК.':'Для подключения подготовь Ubuntu / WSL2, SSH-туннель и запусти агент. При выключении ПК новые тесты недоступны.'));
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
     metric(c.metrics,'Бюджет, USDT',fmt(settings.capital));metric(c.metrics,'Оценка, USDT',fmt(item?.equity));metric(c.metrics,'Закрыто сделок',fmt(item?.closed,0));
     c.position.textContent=item?.position?'Позиция '+item.position.symbol+' · '+(item.position.side===1?'LONG':'SHORT')+(item.fresh?'':' · оценка устарела'):item?.fresh?'Открытой позиции нет':'Состояние позиции не подтверждено';
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
    const enabled=buttons(c.item,current&&!inflight.has(id));for(const [action,b]of Object.entries(c.buttons))b.disabled=!enabled[action];
    if(c.newRunButton){c.newRunButton.disabled=!enabled.new_run;for(const input of Object.values(c.paperFields))input.disabled=!current||inflight.has(id);}
   }
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
   const c=cards.get(id),slot=testSlot(c.item,enginesNow()),available=buttons(slot.item,!!state&&Date.now()/1000-state.updated<=8);if(inflight.has(id)||!available[action])return;
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
    c.pendingCommand={id:result.id,action,generation:expected,previousExperiment:c.item.experiment?.id||''};c.response.textContent=action==='new_run'?'Новый прогон принят. Сохраняем журнал и ждём запуска модели.':'Команда принята. Ждём фактического состояния движка.';c.response.className='control-response muted';await poll(false);
   }catch(e){c.response.textContent=e.message;c.response.className='control-response negative';}finally{inflight.delete(id);render();}
  }
  async function poll(repeat=true){
   try{if(!document.hidden){const r=await fetch('/api/models-control',{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(8000)});const s=await controlJson(r);if(s.status!=='ok'||!Array.isArray(s.models)||!Array.isArray(s.engines))throw Error('Управление моделями: сервер вернул неполные данные.');state=s;apiError='';render();}}
   catch(e){apiError=e?.message||'Управление ещё не подключено. После установки здесь появятся фактические статусы и кнопки.';state=null;render();}
   finally{if(repeat)setTimeout(poll,3000);}
  }
  poll();setInterval(()=>{if(!document.hidden)render();},1000);
 });
})(globalThis);
