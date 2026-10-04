/* Derived display only. Does not create orders or change model conditions. */
(function (scope) {
  const fresh=(stamp,now,limit)=>Number.isFinite(stamp)&&now-stamp>=-1&&now-stamp<=limit;
  function classifyB(s,r,now) {
    const reasons=Array.isArray(r.reasons)?[...r.reasons]:['Некорректные условия модели'];
    const direction=['LONG','SHORT'].includes(r.signal)?r.signal:r.chart?.side===1?'LONG':r.chart?.side===-1?'SHORT':'—';
    const valid=Number.isFinite(r.price)&&r.price>0&&Number.isFinite(r.spread)&&r.spread>=0&&s.phase==='running'&&fresh(s.updated,now,8)&&fresh(r.time,now,3)&&
      fresh(r.chart?.end,now,120)&&r.ready===true&&Number.isFinite(r.trade_age)&&r.trade_age>=0&&r.trade_age+(now-s.updated)<=10;
    if(!valid)return {kind:'stale',tone:'neutral',label:'Нет готовых свежих данных',direction,reasons:[s.reason||'Ожидание свежего стакана, ленты и свечей',...reasons]};
    if(r.chart_error)return {kind:'wait',tone:'neutral',label:'Ошибка свечей',direction,reasons:[r.chart_error,...reasons]};
    if(['LONG','SHORT'].includes(r.signal)&&r.chart?.side===(r.signal==='LONG'?1:-1)&&!reasons.length){
      if(s.position)return {kind:'blocked',tone:'neutral',label:'Условия B · уже есть позиция',direction,reasons:['Новый вход заблокирован открытой PAPER-позицией']};
      if(!Number.isFinite(s.cooldown_until)||s.cooldown_until>now)return {kind:'blocked',tone:'neutral',label:'Условия B · пауза входов',direction,reasons:['Модель ждёт окончания паузы между сделками']};
      return {kind:'entry',tone:direction==='LONG'?'long':'short',label:'Условия входа B выполнены',direction,reasons:[]};
    }
    const wait=['Откат к EMA20 ещё не подтверждён','Нет возобновления движения после отката','Нет пробоя локального экстремума последних секунд'];
    if(direction!=='—'&&reasons.length&&reasons.every(x=>wait.includes(x)))return {kind:'watch',tone:'watch',label:'Подготовка B · ждать подтверждения',direction,reasons};
    return {kind:'wait',tone:'neutral',label:'Условия входа не выполнены',direction,reasons:reasons.length?reasons:['Нет подтверждённого направления']};
  }
  function classifyWatch(s,r,now) {
    const direction=r.status==='WATCH_LONG'?'LONG':r.status==='WATCH_SHORT'?'SHORT':'—';
    if(s.status!=='ok'||!fresh(s.updated,now,8)||!fresh(r.book_time,now,5))return {kind:'stale',tone:'neutral',label:'Наблюдение устарело',direction,reasons:['Нет свежих данных']};
    if(direction!=='—'&&Array.isArray(r.reasons)&&!r.reasons.length)return {kind:'watch',tone:'watch',label:'Стакан · только наблюдение',direction,reasons:[]};
    return {kind:'wait',tone:'neutral',label:'Стакан · ожидание',direction,reasons:r.reasons||[]};
  }
  function classifyResearch(model,s,r,now){
    const direction=r.side===1?'LONG':r.side===-1?'SHORT':'—';
    const checks=Array.isArray(r.checks)?r.checks:[];
    const reasons=checks.filter(x=>!x?.pass_).map(x=>x.label).filter(x=>typeof x==='string');
    const valid=s?.phase==='running'&&fresh(s.updated,now,8)&&fresh(r?.time,now,5)&&direction!=='—';
    if(!valid)return {kind:'stale',tone:'neutral',label:'Модель '+model+' · нет свежего подтверждения',direction,reasons:reasons.length?reasons:['Ожидание свежего снимка модели']};
    if(r.confirmed){
      if(s.position)return {kind:'blocked',tone:'neutral',label:'Модель '+model+' · уже есть позиция',direction,reasons:['Новый PAPER-вход заблокирован открытой позицией']};
      if(Number.isFinite(s.cooldown_until)&&s.cooldown_until>now)return {kind:'blocked',tone:'neutral',label:'Модель '+model+' · пауза входов',direction,reasons:['Модель ждёт окончания паузы между сделками']};
      return {kind:'entry',tone:direction==='LONG'?'long':'short',label:'Условия входа '+model+' выполнены',direction,reasons:[]};
    }
    const passed=checks.filter(x=>x?.pass_).length;
    if(checks.length&&passed>=Math.ceil(checks.length*.7))return {kind:'watch',tone:'watch',label:'Модель '+model+' · почти готово '+passed+'/'+checks.length,direction,reasons};
    return {kind:'wait',tone:'neutral',label:'Модель '+model+' · ожидание',direction,reasons:reasons.length?reasons:['Нет подтверждённого направления']};
  }
  function transition(previous,kind,direction){
    const signature=kind+':'+direction;
    if(previous===signature)return {signature,event:null};
    const event=['entry','watch'].includes(kind)?kind:previous?.startsWith('entry:')?'cancel':null;
    return {signature,event};
  }
  function collectAlerts(b,w,now,research){
    const rows=[];
    const usable=rs=>Array.isArray(rs)?rs.filter(r=>r&&typeof r.symbol==='string'):[];
    if(b)rows.push(...usable(b.observations).map(r=>({source:'B',r,view:classifyB(b,r,now)})));
    if(w)rows.push(...usable(w.rows).map(r=>({source:'Стакан',r,view:classifyWatch(w,r,now)})));
    for(const model of ['C','D']){const state=research?.models?.[model];if(state)rows.push(...usable(state.observations).map(r=>({source:model,r,view:classifyResearch(model,state,r,now)})));}
    const priority={entry:5,watch:4,blocked:3,wait:2,stale:1};
    return rows.sort((a,c)=>priority[c.view.kind]-priority[a.view.kind]||a.r.symbol.localeCompare(c.r.symbol));
  }
  scope.LabAlerts={classifyB,classifyWatch,classifyResearch,fresh,transition,collectAlerts};
  if(typeof module!=='undefined')module.exports=scope.LabAlerts;
  if(typeof document==='undefined')return;
  document.addEventListener('DOMContentLoaded',()=>{
    const page=document.getElementById('page-alerts');if(!page)return;
    const make=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!=null)e.textContent=text;return e;};
    const fmt=(v,d=3)=>Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:d}):'—';
    const stamp=t=>Number.isFinite(t)?new Date(t*1000).toLocaleTimeString('ru-RU'):'—';
    const head=make('section','box alerts-head');
    head.append(make('small','','МОНИТОР ВХОДОВ · PAPER'),make('h2','','Алерты и условия входа'),make('p','muted','Зелёный LONG и красный SHORT — подтверждённые условия B, C или D. Жёлтый — наблюдение, вход ещё не подтверждён. Это экспериментальные условия, а не обещание прибыли.'));
    const health=make('p','muted');health.setAttribute('role','status');head.append(health);
    const stats=make('div','alerts-stats'),statValues={};for(const [kind,label] of [['entry','Вход B/C/D'],['watch','Наблюдение'],['stale','Нет данных']]){const item=make('div',''),value=make('strong','','0');item.append(value,make('span','',label));stats.append(item);statValues[kind]=value;}head.append(stats);
    const filter=make('select','alerts-filter');filter.setAttribute('aria-label','Фильтр алертов');
    for(const [value,text] of [['all','Все монеты'],['entry','Условия входа B/C/D'],['watch','Наблюдение']]){const option=make('option','',text);option.value=value;filter.append(option);}
    head.append(filter);page.append(head);
    const position=make('section','box');page.append(position);
    const list=make('div','alerts-list');page.append(list);
    const history=make('section','box');const log=make('div','alerts-log');
    const clear=make('button','alerts-clear','Очистить историю');clear.type='button';
    history.append(make('h2','','История алертов'),make('p','muted','До 50 событий за 24 часа в этом браузере. История сохраняется после обновления страницы. Серверные состояния обновляются независимо от открытого раздела и показываются сразу при возвращении в панель. Старый алерт не является действующим сигналом.'),clear,log);page.append(history);
    let b=null,w=null,research=null,errors={b:'Подключение',w:'Подключение',r:'Подключение'},busy=false,events=[],states=new Map(),lastPosition=null,listSignature='',positionSignature='',historySignature='';
    const alertCards=new Map();
    const storeKey='lab-alert-history-v2';
    let sound=false,audio=null;
    const soundButton=make('button','alerts-clear','Звук: выключен');soundButton.type='button';soundButton.setAttribute('aria-pressed','false');head.append(soundButton);
    let notify=false;const notifyButton=make('button','alerts-clear','Уведомления: выкл');notifyButton.type='button';notifyButton.setAttribute('aria-pressed','false');head.append(notifyButton);
    function notifyNow(title,body,tag){if(!notify||!document.hidden||!('Notification' in window)||Notification.permission!=='granted')return;try{const n=new Notification(title,{body:String(body).slice(0,180),tag:'lab-'+tag});setTimeout(()=>n.close(),9000);}catch(_){}}
    notifyButton.addEventListener('click',async()=>{if(!('Notification' in window)){notifyButton.textContent='Уведомления не поддерживаются';return;}if(notify)notify=false;else{let permission=Notification.permission;if(permission==='default')try{permission=await Notification.requestPermission();}catch(_){}if(permission!=='granted'){notifyButton.textContent='Уведомления запрещены в браузере';return;}notify=true;}notifyButton.textContent='Уведомления: '+(notify?'вкл':'выкл');notifyButton.setAttribute('aria-pressed',String(notify));});
    if('Notification' in window&&Notification.permission==='denied')notifyButton.textContent='Уведомления запрещены в браузере';
    const storageNote=make('p','muted','Звук работает при открытой активной странице. Браузерные уведомления возможны в фоне при работающем браузере; на iPhone доставка не гарантируется.');head.append(storageNote);
    try {const data=JSON.parse(localStorage.getItem(storeKey)||'null');if(data){
      events=(Array.isArray(data.events)?data.events:[]).filter(e=>Number.isFinite(e.time)&&e.time<=Date.now()/1000+1&&Date.now()/1000-e.time<86400&&typeof e.text==='string'&&['long','short','watch','neutral'].includes(e.tone)).slice(0,50);
      if(Array.isArray(data.states))states=new Map(data.states.filter(x=>Array.isArray(x)&&x.length===2&&x.every(v=>typeof v==='string')));
      lastPosition=Number.isFinite(data.lastPosition)?data.lastPosition:null;
    }}catch(_) {storageNote.textContent+=' Сохранение истории недоступно.';}
    function persist(){try{localStorage.setItem(storeKey,JSON.stringify({events,states:[...states],lastPosition}));}catch(_){storageNote.textContent='История только в памяти: браузер запретил сохранение. Звук — при открытой странице.';}}
    function beep(freq=740){if(!sound||!audio||document.hidden)return;try{const o=audio.createOscillator(),g=audio.createGain();o.connect(g);g.connect(audio.destination);o.frequency.value=freq;g.gain.setValueAtTime(.035,audio.currentTime);g.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.2);o.start();o.stop(audio.currentTime+.2);}catch(_) {}}
    soundButton.addEventListener('click',async()=>{try{if(!audio)audio=new (window.AudioContext||window.webkitAudioContext)();await audio.resume();sound=!sound;soundButton.textContent='Звук: '+(sound?'включён':'выключен');soundButton.setAttribute('aria-pressed',String(sound));if(sound)beep();}catch(_){soundButton.textContent='Звук недоступен';}});
    const addEvent=(key,kind,direction,text,now,tone)=>{
      const previous=states.get(key),next=transition(previous,kind,direction);states.set(key,next.signature);
      if(!next.event)return;
      const cancel=next.event==='cancel';events.unshift({time:now,text:cancel?key+' · условия входа сняты / заблокированы':text,tone:cancel?'neutral':tone});events=events.slice(0,50);persist();
      if(!cancel&&kind==='entry'&&previous!==undefined){beep(tone==='short'?520:740);notifyNow('Условия входа '+direction+' · '+key,text,key);}
    };
    const line=(parent,text,cls='')=>parent.append(make('p',cls,text));
    function createAlertCard(source,r,v,opened){
      const researchModel=['C','D'].includes(source),labels=researchModel?['Проверок','Подтв.','Сторона','Возраст снимка']:['Цена снимка','Спред','Bid / Ask ±0,1%','Возраст стакана'];
      const card=make('article','alert-card'),sourceLabel=make('small',''),title=make('h3',''),label=make('p','alert-label'),metrics=make('div','alert-metrics'),values={};for(const [name,text] of ['price','spread','depth','age'].map((name,index)=>[name,labels[index]])){const cell=make('div',''),value=make('b','');cell.append(make('span','',text),value);metrics.append(cell);values[name]=value;}const coverage=make('p','muted'),atr=make('p','muted'),d=make('details',''),flow=make('p','');d.dataset.key=source+':'+r.symbol;d.open=opened.has(d.dataset.key);d.append(make('summary','','Условия и ограничения'));for(const reason of v.reasons)line(d,reason);if(!v.reasons.length)line(d,researchModel?'Условия этой модели выполнены на свежем снимке. Фактический PAPER-вход подтверждается позицией и журналом.':source==='B'?'Условия выполнены на этом снимке. Фактический PAPER-вход подтверждается позицией и журналом.':'Условия наблюдения за стаканом выполнены. Это не сигнал входа модели B.');d.append(flow);const chartButton=make('button','text-button','График и стакан ↗');chartButton.type='button';chartButton.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('lab-symbol',{detail:r.symbol})));card.append(sourceLabel,title,label,metrics,coverage,atr,d,chartButton);return {card,sourceLabel,title,label,values,coverage,atr,flow};
    }
    function updateAlertCard(item,source,r,v,now){
      const researchModel=['C','D'].includes(source),stampValue=r.time??r.book_time;item.card.className='alert-card alert-'+v.tone;item.sourceLabel.textContent=source==='B'?'МОДЕЛЬ B':source==='C'?'МОДЕЛЬ C · ТРЕНД':source==='D'?'МОДЕЛЬ D · VWAP':'АНАЛИЗ СТАКАНА';item.title.textContent=r.symbol+' · '+v.direction;item.label.textContent=v.label;
      if(researchModel){const checks=Array.isArray(r.checks)?r.checks:[],passed=checks.filter(x=>x?.pass_).length;item.values.price.textContent=passed+' / '+checks.length;item.values.spread.textContent=String(r.confirmations??0)+' / 3';item.values.depth.textContent=v.direction;item.values.age.textContent=fmt(now-stampValue,1)+' сек.';item.coverage.hidden=true;item.atr.hidden=true;item.flow.hidden=true;return;}
      const depth=source==='B'?r.bands?.['0.001']:{bid:r.bid_depth,ask:r.ask_depth};item.values.price.textContent=fmt(r.price,8);item.values.spread.textContent=fmt(r.spread,4)+'%';item.values.depth.textContent=fmt(depth?.bid,0)+' / '+fmt(depth?.ask,0)+' USDT';item.values.age.textContent=fmt(now-stampValue,1)+' сек.';item.coverage.hidden=!(depth?.covered===false||r.covered===false);item.coverage.textContent='Полученная глубина — нижняя оценка зоны.';item.atr.hidden=source!=='B';item.atr.textContent='ATR '+fmt(r.chart?.atr_pct)+'% · расходы оборота '+fmt(r.roundtrip_pct)+'%.';item.flow.hidden=source!=='B';item.flow.textContent='Лента 5 / 15 сек.: '+fmt(r.flow5?.ratio*100,1)+'% / '+fmt(r.flow15?.ratio*100,1)+'% · OFI 5 сек. '+fmt(r.ofi5,0);
    }
    function positionEvent(now){
      const p=b&&fresh(b.updated,now,8)?b.position:null;if(!p||lastPosition===p.opened)return;
      const previous=lastPosition,direction=p.side===1?'LONG':'SHORT';events.unshift({time:now,text:p.symbol+' '+direction+' · PAPER вход выполнен',tone:p.side===1?'long':'short'});events=events.slice(0,50);lastPosition=p.opened;persist();if(previous!==null){beep(p.side===1?740:520);notifyNow('PAPER вход выполнен',p.symbol+' '+direction+' · вход '+fmt(p.entry,8),'position-B');}
    }
    function renderPosition(now){
      const active=b&&fresh(b.updated,now,8),p=active?b.position:null,signature=JSON.stringify(p?[p.symbol,p.side,p.entry,p.quantity,p.opened]:[active,'none']);if(signature===positionSignature)return;positionSignature=signature;position.replaceChildren(make('h3','','Позиция модели B'));if(p){const direction=p.side===1?'LONG':'SHORT';line(position,p.symbol+' · '+direction+' · PAPER вход '+fmt(p.entry,8),'position-name');line(position,'Открыта '+stamp(p.opened)+'. Это уже открытая виртуальная позиция, не новый сигнал.');}else line(position,active?'Открытой позиции нет.':'Состояние позиции неизвестно: нет свежего снимка.');
    }
    function renderAlertList(rows,now){
      const visible=rows.filter(x=>filter.value==='all'||x.view.kind===filter.value),signature=JSON.stringify([filter.value,visible.map(({source,r,view})=>[source,r.symbol,view.kind,view.tone,view.direction,view.label,view.reasons,source==='B'?r.bands?.['0.001']?.covered:r.covered])]);if(signature!==listSignature){const opened=new Set([...list.querySelectorAll('details[open]')].map(e=>e.dataset.key));list.replaceChildren();alertCards.clear();if(!visible.length)line(list,filter.value==='entry'?'Сейчас нет подтверждённых условий входа B/C/D.':'Нет алертов выбранного типа.','notice');for(const item of visible){const key=item.source+':'+item.r.symbol,card=createAlertCard(item.source,item.r,item.view,opened);alertCards.set(key,card);list.append(card.card);}listSignature=signature;}for(const item of visible){const card=alertCards.get(item.source+':'+item.r.symbol);if(card)updateAlertCard(card,item.source,item.r,item.view,now);}
    }
    function renderHistory(now){events=events.filter(e=>now-e.time<86400);const signature=JSON.stringify(events);if(signature===historySignature)return;historySignature=signature;log.replaceChildren();if(!events.length)line(log,'Новых событий пока нет.','muted');for(const e of events){const p=make('p','alert-event event-'+e.tone,stamp(e.time)+' · '+e.text);log.append(p);}}
    function render(){
      const now=Date.now()/1000;
      const rows=collectAlerts(b,w,now,research);
      const keys=new Set();for(const {source,r,view} of rows){const key=source+':'+r.symbol;keys.add(key);addEvent(key,view.kind,view.direction,source+' · '+r.symbol+' '+view.direction+' · '+view.label,now,view.tone);}for(const key of states.keys())if(!keys.has(key)&&!states.get(key).startsWith('stale:'))addEvent(key,'stale','—',key+' · поток недоступен',now,'neutral');
      positionEvent(now);if(document.hidden)return;
      health.textContent='B: '+(errors.b||(!b||!fresh(b.updated,now,8)?'устарела':b.phase))+' · C/D: '+(errors.r||(!research||!fresh(research.updated,now,8)?'устарели':'актуальны'))+' · Стакан: '+(errors.w||(!w||!fresh(w.updated,now,8)?'устарел':w.status));
      document.dispatchEvent(new CustomEvent('lab-alerts',{detail:rows.filter(x=>['entry','watch'].includes(x.view.kind)).length}));for(const kind of ['entry','watch','stale'])statValues[kind].textContent=String(rows.filter(x=>x.view.kind===kind).length);
      renderPosition(now);renderAlertList(rows,now);renderHistory(now);
    }
    async function poll(){
      if(busy)return;busy=true;
      const results=await Promise.allSettled(['/api/model-b','/api/signals','/api/research'].map(async path=>{const res=await labFetch(path);if(!res.ok)throw new Error('HTTP '+res.status);return res.json();}));
      for(let i=0;i<3;i++){const result=results[i],key=i===0?'b':i===1?'w':'r';if(result.status==='fulfilled'){errors[key]='';if(i===0)b=result.value;else if(i===1)w=result.value;else research=result.value;}else errors[key]='недоступен';}
      busy=false;render();setTimeout(poll,2000);
    }
    clear.addEventListener('click',()=>{events=[];persist();render();});filter.addEventListener('change',render);
    document.addEventListener('visibilitychange',render);document.addEventListener('lab-tab',e=>{if(e.detail==='alerts')render();});
    setInterval(render,1000);poll();
  });
})(typeof window==='undefined'?globalThis:window);
