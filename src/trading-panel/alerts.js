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
    if(kind==='stale')return {signature:previous||signature,event:null};
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
    const diagnostics=make('details','box model-alert-diagnostics');diagnostics.append(make('summary','','Условия моделей B/C/D и наблюдение стакана'));
    diagnostics.append(make('p','muted','Текущие снимки моделей показаны отдельно от событий умного отбора. Открытая PAPER-позиция подтверждается во вкладке «Позиции».'));
    const health=make('p','muted');health.setAttribute('role','status');diagnostics.append(health);
    const filter=make('select','alerts-filter');filter.setAttribute('aria-label','Фильтр условий моделей');
    for(const [value,text]of [['all','Все состояния моделей'],['entry','Условия входа B/C/D'],['watch','Наблюдение']]){const option=make('option','',text);option.value=value;filter.append(option);}diagnostics.append(filter);
    const list=make('div','alerts-list');diagnostics.append(list);page.append(diagnostics);
    try{const saved=JSON.parse(localStorage.getItem('lab-alert-history-v2')||'null'),now=Date.now()/1000;
      const old=(Array.isArray(saved?.events)?saved.events:[]).filter(e=>e&&fresh(e.time,now,86400)&&typeof e.text==='string').slice(0,50);
      if(old.length){const archive=make('details','');archive.append(make('summary','','Прежняя история моделей'),make('p','muted','Сохранённые наблюдения предыдущей версии. Они не подтверждают текущие условия.'));for(const e of old)archive.append(make('p','muted',new Date(e.time*1000).toLocaleString('ru-RU')+' · '+e.text));diagnostics.append(archive);}
    }catch{}
    let b=null,w=null,research=null,errors={b:'Подключение',w:'Подключение',r:'Подключение'},busy=false,listSignature='';
    const alertCards=new Map(),line=(parent,text,cls='muted')=>parent.append(make('p',cls,text));
    function createAlertCard(source,r,v,opened){
      const researchModel=['C','D'].includes(source),labels=researchModel?['Проверок','Подтв.','Сторона','Возраст снимка']:['Цена снимка','Спред','Bid / Ask ±0,1%','Возраст стакана'];
      const card=make('article','alert-card'),sourceLabel=make('small',''),title=make('h3',''),label=make('p','alert-label'),metrics=make('div','alert-metrics'),values={};for(const [name,text] of ['price','spread','depth','age'].map((name,index)=>[name,labels[index]])){const cell=make('div',''),value=make('b','');cell.append(make('span','',text),value);metrics.append(cell);values[name]=value;}const coverage=make('p','muted'),atr=make('p','muted'),d=make('details',''),flow=make('p','');d.dataset.key=source+':'+r.symbol;d.open=opened.has(d.dataset.key);d.append(make('summary','','Условия и ограничения'));for(const reason of v.reasons)line(d,reason);if(!v.reasons.length)line(d,researchModel?'Условия этой модели выполнены на свежем снимке. Фактический PAPER-вход подтверждается позицией и журналом.':source==='B'?'Условия выполнены на этом снимке. Фактический PAPER-вход подтверждается позицией и журналом.':'Условия наблюдения за стаканом выполнены. Это не сигнал входа модели B.');d.append(flow);const chartButton=make('button','text-button','График и стакан ↗');chartButton.type='button';chartButton.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('lab-symbol',{detail:r.symbol})));card.append(sourceLabel,title,label,metrics,coverage,atr,d,chartButton);return {card,sourceLabel,title,label,values,coverage,atr,flow};
    }
    function updateAlertCard(item,source,r,v,now){
      const researchModel=['C','D'].includes(source),stampValue=r.time??r.book_time;item.card.className='alert-card alert-'+v.tone;item.sourceLabel.textContent=source==='B'?'МОДЕЛЬ B':source==='C'?'МОДЕЛЬ C · ТРЕНД':source==='D'?'МОДЕЛЬ D · VWAP':'АНАЛИЗ СТАКАНА';item.title.textContent=r.symbol+' · '+v.direction;item.label.textContent=v.label;
      if(researchModel){const checks=Array.isArray(r.checks)?r.checks:[],passed=checks.filter(x=>x?.pass_).length;item.values.price.textContent=passed+' / '+checks.length;item.values.spread.textContent=String(r.confirmations??0)+' / 3';item.values.depth.textContent=v.direction;item.values.age.textContent=fmt(now-stampValue,1)+' сек.';item.coverage.hidden=true;item.atr.hidden=true;item.flow.hidden=true;return;}
      const depth=source==='B'?r.bands?.['0.001']:{bid:r.bid_depth,ask:r.ask_depth};item.values.price.textContent=fmt(r.price,8);item.values.spread.textContent=fmt(r.spread,4)+'%';item.values.depth.textContent=fmt(depth?.bid,0)+' / '+fmt(depth?.ask,0)+' USDT';item.values.age.textContent=fmt(now-stampValue,1)+' сек.';item.coverage.hidden=!(depth?.covered===false||r.covered===false);item.coverage.textContent='Полученная глубина — нижняя оценка зоны.';item.atr.hidden=source!=='B';item.atr.textContent='ATR '+fmt(r.chart?.atr_pct)+'% · расходы оборота '+fmt(r.roundtrip_pct)+'%.';item.flow.hidden=source!=='B';item.flow.textContent='Лента 5 / 15 сек.: '+fmt(r.flow5?.ratio*100,1)+'% / '+fmt(r.flow15?.ratio*100,1)+'% · OFI 5 сек. '+fmt(r.ofi5,0);
    }
    function renderAlertList(rows,now){
      const visible=rows.filter(x=>filter.value==='all'||x.view.kind===filter.value),signature=JSON.stringify([filter.value,visible.map(({source,r,view})=>[source,r.symbol,view.kind,view.tone,view.direction,view.label,view.reasons,source==='B'?r.bands?.['0.001']?.covered:r.covered])]);if(signature!==listSignature){const opened=new Set([...list.querySelectorAll('details[open]')].map(e=>e.dataset.key));list.replaceChildren();alertCards.clear();if(!visible.length)line(list,filter.value==='entry'?'Сейчас нет подтверждённых условий входа B/C/D.':'Нет алертов выбранного типа.','notice');for(const item of visible){const key=item.source+':'+item.r.symbol,card=createAlertCard(item.source,item.r,item.view,opened);alertCards.set(key,card);list.append(card.card);}listSignature=signature;}for(const item of visible){const card=alertCards.get(item.source+':'+item.r.symbol);if(card)updateAlertCard(card,item.source,item.r,item.view,now);}
    }
    function render(){
      if(document.hidden)return;const now=Date.now()/1000,rows=collectAlerts(b,w,now,research);
      health.textContent='B: '+(errors.b||(!b||!fresh(b.updated,now,8)?'нет свежего снимка':b.phase))+' · C/D: '+(errors.r||(!research||!fresh(research.updated,now,8)?'нет свежего снимка':'актуальны'))+' · Стакан: '+(errors.w||(!w||!fresh(w.updated,now,8)?'нет свежего снимка':w.status));
      renderAlertList(rows,now);
    }
    async function poll(){
      if(busy)return;busy=true;const results=await Promise.allSettled(['/api/model-b','/api/signals','/api/research'].map(async path=>{const res=await labFetch(path);if(!res.ok)throw Error('HTTP');return res.json();}));
      for(let i=0;i<3;i++){const result=results[i],key=['b','w','r'][i],value=result.status==='fulfilled'?result.value:null;errors[key]=value?'':'недоступен';if(i===0)b=value;else if(i===1)w=value;else research=value;}
      busy=false;render();setTimeout(poll,2000);
    }
    filter.addEventListener('change',()=>{listSignature='';render();});document.addEventListener('lab-tab',render);document.addEventListener('visibilitychange',render);setInterval(render,1000);render();poll();
  });
})(typeof window!=='undefined'?window:globalThis);
