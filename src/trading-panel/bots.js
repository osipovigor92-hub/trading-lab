/* The builder owns its inputs. Market polling never replaces this form. */
document.addEventListener('DOMContentLoaded', () => {
 'use strict';
 const root=document.getElementById('page-bots');if(!root)return;
 const el=(tag,cls='',text='')=>{const e=document.createElement(tag);e.className=cls;e.textContent=text;return e;};
 const heading=el('div','bot-heading');heading.append(el('h2','','Настройки сигналов'),el('p','','Выбери стратегию. Задай рынок и границы риска.'));
 const status=el('p','bot-status','Загружаем сохранённые настройки…');status.setAttribute('role','status');
 const workspace=el('div','bot-workspace'),form=el('form','bot-form'),aside=el('aside','bot-summary');form.noValidate=false;
 const title=el('h3','','План сигнала'),summary=el('dl'),note=el('p','bot-muted','Сохранение задаёт параметры сценария. Подключение к алертам ещё не завершено.'),save=el('button','bot-primary','Сохранить настройки'),reload=el('button','bot-secondary','Загрузить сохранённые');save.type='submit';save.setAttribute('form','bot-form');form.id='bot-form';reload.type='button';
 aside.append(title,summary,note,save,reload);workspace.append(form,aside);root.append(heading,status,workspace);
 const library=el('section','bot-library'),libraryTitle=el('h3','','Торговые стратегии'),libraryNote=el('p','bot-muted','10 шаблонов · история сигналов ещё не собрана'),cards=el('div','bot-cards');library.append(libraryTitle,libraryNote,cards);root.insertBefore(library,workspace);
 const switcher=el('nav','bot-switcher');switcher.setAttribute('aria-label','Разделы стратегий');
 let view='catalog';const viewButtons=new Map();
 function showView(next){view=next;library.hidden=next==='builder';workspace.hidden=next!=='builder';
  heading.querySelector('h2').textContent=next==='builder'?'Настройки стратегии':next==='saved'?'Мои стратегии':'Стратегии и сигналы';
  heading.querySelector('p').textContent=next==='builder'?'Стратегия, рынок, размер, стоп и тейк.':next==='saved'?'Сохранённые правила для ручной торговли':'Сценарии Bybit · сигналы и алерты для ручного решения';
  for(const [key,button]of viewButtons)button.setAttribute('aria-pressed',String(key===next));
  filterCards();
 }
 for(const [key,label]of [['catalog','Каталог'],['saved','Мои стратегии'],['builder','Настроить сигнал']]){const b=el('button','bot-secondary',label);b.type='button';b.addEventListener('click',()=>showView(key));switcher.append(b);viewButtons.set(key,b);}root.insertBefore(switcher,status);workspace.hidden=true;
 const search=el('input','bot-search');search.type='search';search.placeholder='Найти стратегию';search.setAttribute('aria-label','Поиск стратегий');
 const group=el('select');group.setAttribute('aria-label','Тип стратегии');for(const name of ['Все стратегии','Стакан','Уровни','Наклонки','Импульс','Усреднение']){const option=el('option','',name);option.value=name;group.append(option);}
 const filters=el('div','bot-filters');filters.append(search,group);library.insertBefore(filters,cards);
 const emptyList=el('p','bot-muted');emptyList.hidden=true;library.append(emptyList);
 function filterCards(){let count=0;for(const card of cards.children){const matches=card.dataset.name.toLocaleLowerCase('ru').includes(search.value.trim().toLocaleLowerCase('ru'))&&(group.value==='Все стратегии'||group.value===card.dataset.group)&&(view!=='saved'||data?.drafts[card.dataset.id]);card.hidden=!matches;if(matches)count++;}
  libraryNote.textContent=count+' стратегий · '+(view==='saved'?'сохранённые настройки':'история сигналов ещё не собрана');emptyList.hidden=count!==0;emptyList.textContent=view==='saved'?'Сохранённых настроек по этому фильтру пока нет. Выбери стратегию в каталоге.':'Ничего не найдено. Измени запрос или тип стратегии.';
 }
 search.addEventListener('input',filterCards);group.addEventListener('change',filterCards);
 let data=null,config=null,busy=false,dirty=false,loaded=false;
 const inputs={},strategyButtons=new Map(),localDrafts=new Map();
 const description=el('p','bot-description'),catalog=el('div','bot-catalog');
 function section(number,label){const field=el('fieldset'),legend=el('legend');legend.append(el('span','bot-step',number),document.createTextNode(label));field.append(legend);form.append(field);return field;}
 const s1=section('01','Стратегия');s1.append(catalog,description);
 function field(parent,key,label,type,values){
  const wrap=el('label','bot-field',label),input=el(type==='select'?'select':'input');input.name=key;input.id='bot-'+key;
  if(type==='select')for(const [value,text]of values){const option=el('option','',text);option.value=value;if(key==='scope'&&value==='market'){option.disabled=true;option.textContent='Весь рынок · пока недоступно';}input.append(option);}
  else{input.type=type;input.required=true;if(type==='number'){input.min=values[0];input.max=values[1];input.step=values[2];input.inputMode='decimal';}}
  wrap.append(input);parent.append(wrap);inputs[key]=input;
  input.addEventListener('input',()=>{if(!config)return;config[key]=type==='number'?input.valueAsNumber:input.value;dirty=true;refresh();});return wrap;
 }
 const s2=section('02','Рынок'),market=el('p','bot-muted','Bybit · USDT perpetual');s2.append(market);
 field(s2,'scope','Где искать','select',[['favorites','Избранные монеты'],['pair','Одна пара'],['market','Весь рынок']]);
 const symbolField=field(s2,'symbol','Торговая пара','text');inputs.symbol.pattern='[A-Z0-9]{1,24}USDT';
 inputs.symbol.addEventListener('input',()=>{const start=inputs.symbol.selectionStart;inputs.symbol.value=inputs.symbol.value.toUpperCase();inputs.symbol.setSelectionRange(start,start);config.symbol=inputs.symbol.value;refresh();});
 field(s2,'side','Направление','select',[['both','LONG и SHORT'],['long','Только LONG'],['short','Только SHORT']]);
 const s3=section('03','Размер позиции');field(s3,'notional','Объём позиции, USDT','number',[5,100000,1]);
 const presets=el('div','bot-presets');for(const amount of [50,200,1000]){const b=el('button','bot-secondary',String(amount)+' USDT');b.type='button';b.addEventListener('click',()=>{config.notional=amount;inputs.notional.value=amount;dirty=true;refresh();});presets.append(b);}s3.append(presets,el('p','bot-muted','Это полный объём позиции, а не маржа. Плечо здесь не задаётся.'));
 const s4=section('04','Стоп и тейк');field(s4,'stop_pct','Стоп от цены входа, %','number',[.01,20,.01]);field(s4,'take_pct','Тейк от цены входа, %','number',[.01,100,.01]);
 const s5=section('05','Ограничения');field(s5,'daily_loss','Максимальный убыток за день, USDT','number',[1,10000,1]);field(s5,'max_positions','Одновременно открытых позиций','number',[1,10,1]);
 const densityField=field(s5,'density_multiple','Плотность: минимум × среднего','number',[10,1000,1]);
 const dcaField=field(s5,'dca_steps','Всего частей DCA, включая первый вход','number',[1,5,1]);
 s5.append(el('p','bot-muted','Для DCA заданный объём делится между частями. Увеличения общего бюджета и мартингейла нет.'));
 function refresh(){
  if(!config)return;
  const selected=data.catalog.find(v=>v.id===config.strategy);description.textContent=selected.description;
  for(const [key,b]of strategyButtons){b.setAttribute('aria-pressed',String(key===config.strategy));b.classList.toggle('selected',key===config.strategy);}
  symbolField.hidden=config.scope!=='pair';inputs.symbol.disabled=config.scope!=='pair';densityField.hidden=!config.strategy.startsWith('density_');dcaField.hidden=config.strategy!=='dca';
  const fmt=v=>Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:2}):'—';
  const rows=[['Стратегия',selected.name],['Рынок',config.scope==='pair'?config.symbol:config.scope==='market'?'Весь рынок Bybit':'Избранное Bybit'],['Объём',fmt(config.notional)+' USDT'],['Стоп / тейк',fmt(config.stop_pct)+'% / '+fmt(config.take_pct)+'%'],['Потеря при стопе*',fmt(config.notional*config.stop_pct/100)+' USDT'],['Лимит объёма',fmt(config.notional*config.max_positions)+' USDT'],['Состояние',config.strategy==='level_break'?'Пробой диапазона 20 минут · 1м':'Стратегия ещё не подключена']];
  summary.replaceChildren(...rows.flatMap(([k,v])=>[el('dt','',k),el('dd','',v)]));
  note.textContent='* Оценка без комиссий и проскальзывания. '+(config.strategy==='dca'?'Для DCA итог зависит от цен добавлений. ':'')+(config.strategy==='level_break'?'После сохранения сервер наблюдает выбранную пару или до 8 избранных Bybit-монет. Сигналы — в Алертах. Автоторговли нет.':'Эта стратегия пока не подключена к алертам.');
  save.disabled=busy||data.status!=='ok'||config.strategy!=='level_break'||config.scope==='market';reload.disabled=busy;form.setAttribute('aria-busy',String(busy));
  if(!busy)status.textContent=dirty?'Есть несохранённые изменения.':data.drafts[config.strategy]?'Настройки сохранены на сервере.':'Начальные настройки. Сохрани их для доступа с другого устройства.';
 }
 function fill(){for(const [key,input]of Object.entries(inputs))input.value=config[key];refresh();}
 function select(id){if(busy||!data)return;if(config)localDrafts.set(config.strategy,{config:{...config},dirty});const local=localDrafts.get(id);config={...(local?.config||data.drafts[id]||data.defaults),strategy:id};dirty=local?.dirty||false;fill();}
 async function request(options){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);try{const r=await fetch('/api/bots',{cache:'no-store',...options,signal:controller.signal});let value;try{value=await r.json();}catch{throw Error('Сервер не поддерживает конструктор. Проверь обновление панели.');}if(!r.ok||!['ok','accepted'].includes(value.status))throw Error(value.error||'Сервер недоступен');return value;}finally{clearTimeout(timer);}}
 async function load(){if(busy)return;busy=true;for(const input of form.querySelectorAll('input,select,button'))input.disabled=true;save.disabled=true;reload.disabled=true;status.textContent='Загружаем настройки…';try{const value=await request();data=value;if(!loaded){for(const item of data.catalog){
 const card=el('article','bot-template');card.dataset.id=item.id;card.dataset.name=item.name;card.dataset.group=item.group;const cardTitle=el('h4','',item.name),meta=el('p','bot-muted','Trading Lab · шаблон'),tag=el('span','bot-tag',item.group),empty=el('div','bot-empty','Нет истории сигналов'),explain=el('p','bot-muted','Статистика появится после записи и проверки сигналов.'),metrics=el('dl','bot-template-metrics');
 for(const label of ['Винрейт','Макс. просадка','Худший день','Сигналов']){const metric=el('div');metric.append(el('dt','',label),el('dd','','—'));metrics.append(metric);};
 const use=el('button','bot-primary','Настроить сигнал');use.type='button';use.addEventListener('click',()=>{select(item.id);showView('builder');heading.scrollIntoView({block:'start'});});card.append(cardTitle,meta,tag,empty,explain,metrics,use);cards.append(card);
 const b=el('button','bot-strategy'),name=el('strong','',item.name),group=el('span','',item.group);b.type='button';b.append(name,group);b.addEventListener('click',()=>select(item.id));strategyButtons.set(item.id,b);catalog.append(b);}loaded=true;}localDrafts.clear();const id=config?.strategy||data.defaults.strategy;config={...(data.drafts[id]||data.defaults),strategy:id};showView(view);dirty=false;busy=false;for(const input of form.querySelectorAll('input,select,button'))input.disabled=false;fill();}catch(e){busy=false;status.textContent=e.name==='AbortError'?'Сервер не ответил. Повтори загрузку.':e.message;reload.disabled=false;if(config){for(const input of form.querySelectorAll('input,select,button'))input.disabled=false;inputs.symbol.disabled=config.scope!=='pair';save.disabled=false;}}}
 reload.addEventListener('click',()=>{if((dirty||[...localDrafts.values()].some(v=>v.dirty))&&!window.confirm('Загрузить настройки с сервера и отменить несохранённые изменения?'))return;void load();});
 form.addEventListener('submit',async event=>{event.preventDefault();if(busy||!config||config.strategy!=='level_break'||config.scope==='market'||!form.reportValidity())return;busy=true;refresh();status.textContent='Сохраняем…';const payload={revision:data.revision,config:{...config}},token=data.token;for(const input of form.querySelectorAll('input,select,button'))input.disabled=true;
  try{const value=await request({method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':token},body:JSON.stringify(payload)});data={...value,token};filterCards();dirty=false;localDrafts.delete(config.strategy);busy=false;refresh();status.textContent='Сохранено на сервере. На другом устройстве нажми «Загрузить сохранённые».';}catch(e){busy=false;refresh();status.textContent=e.name==='AbortError'?'Ответ не получен. Повтори сохранение: дубликат не создастся.':e.message;}finally{for(const input of form.querySelectorAll('input,select,button'))input.disabled=false;inputs.symbol.disabled=config.scope!=='pair';}
 });
 // No polling or rerenders of controls: typing and selection survive feed ticks.
 document.addEventListener('lab-tab',e=>{if(e.detail==='bots'&&!loaded)void load();});
 window.addEventListener('beforeunload',e=>{if(dirty||[...localDrafts.values()].some(v=>v.dirty)){e.preventDefault();e.returnValue='';}});
 showView('catalog');
 if(window.LabNavigation?.current()==='bots')void load();else{save.disabled=true;status.textContent='Открой конструктор, чтобы загрузить настройки.';}
});
