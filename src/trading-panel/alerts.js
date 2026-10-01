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
  if(typeof module!=='undefined')module.exports={classifyB,classifyWatch,fresh};
  if(typeof document==='undefined')return;
  document.addEventListener('DOMContentLoaded',()=>{
    const page=document.getElementById('page-alerts');if(!page)return;
    const make=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls||'';if(text!=null)e.textContent=text;return e;};
    const fmt=(v,d=3)=>Number.isFinite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:d}):'—';
    const stamp=t=>Number.isFinite(t)?new Date(t*1000).toLocaleTimeString('ru-RU'):'—';
    const head=make('section','box alerts-head');
    head.append(make('small','','МОНИТОР ВХОДОВ · PAPER'),make('h2','','Алерты и условия входа'),make('p','muted','Зелёный LONG и красный SHORT — условия модели B. Жёлтый — наблюдение, вход ещё не подтверждён. Это экспериментальные условия, а не обещание прибыли.'));
    const health=make('p','muted');health.setAttribute('role','status');head.append(health);
    const stats=make('div','alerts-stats');head.append(stats);
    const filter=make('select','alerts-filter');filter.setAttribute('aria-label','Фильтр алертов');
    for(const [value,text] of [['all','Все монеты'],['entry','Условия входа B'],['watch','Наблюдение']]){const option=make('option','',text);option.value=value;filter.append(option);}
    head.append(filter);page.append(head);
    const position=make('section','box');page.append(position);
    const list=make('div','alerts-list');page.append(list);
    const history=make('section','box');const log=make('div','alerts-log');
    const clear=make('button','alerts-clear','Очистить историю');clear.type='button';
    history.append(make('h2','','История алертов'),make('p','muted','До 50 событий с открытия панели. Обновление страницы очищает историю. Старое событие не является действующим сигналом.'),clear,log);page.append(history);
    let b=null,w=null,errors={b:'Подключение',w:'Подключение'},busy=false,events=[],states=new Map(),lastPosition=null;
    const addEvent=(key,state,text,now,tone)=>{
      const previous=states.get(key);states.set(key,state);
      if(previous===state||!['entry','watch','open'].includes(state))return;
      events.unshift({time:now,text,tone});events=events.slice(0,50);
    };
    const line=(parent,text,cls='')=>parent.append(make('p',cls,text));
    function render(){
      if(document.hidden)return;
      const now=Date.now()/1000;
      health.textContent='Модель B: '+(errors.b||(!b||!fresh(b.updated,now,8)?'устарела':b.phase))+' · Стакан: '+(errors.w||(!w||!fresh(w.updated,now,8)?'устарел':w.status));
      let rows=[];
      if(b)rows.push(...(b.observations||[]).map(r=>({source:'B',r,view:classifyB(b,r,now)})));
      if(w)rows.push(...(w.rows||[]).map(r=>({source:'Стакан',r,view:classifyWatch(w,r,now)})));
      const priority={entry:5,watch:4,blocked:3,wait:2,stale:1};rows.sort((a,c)=>priority[c.view.kind]-priority[a.view.kind]||a.r.symbol.localeCompare(c.r.symbol));
      stats.replaceChildren();
      for(const [kind,label] of [['entry','Вход B'],['watch','Наблюдение'],['stale','Нет данных']]){
        const item=make('div','');item.append(make('strong','',String(rows.filter(x=>x.view.kind===kind).length)),make('span','',label));stats.append(item);
      }
      const keys=new Set();
      for(const {source,r,view} of rows){const key=source+':'+r.symbol;keys.add(key);addEvent(key,view.kind,source+' · '+r.symbol+' '+view.direction+' · '+view.label,now,view.tone);}
      for(const key of states.keys())if(!keys.has(key))states.delete(key);
      position.replaceChildren(make('h3','','Позиция модели B'));
      if(b&&fresh(b.updated,now,8)&&b.position){const p=b.position;const direction=p.side===1?'LONG':'SHORT';line(position,p.symbol+' · '+direction+' · PAPER вход '+fmt(p.entry,8),'position-name');line(position,'Открыта '+stamp(p.opened)+'. Это уже открытая виртуальная позиция, не новый сигнал.');if(lastPosition!==p.opened){events.unshift({time:now,text:p.symbol+' '+direction+' · PAPER вход выполнен',tone:p.side===1?'long':'short'});events=events.slice(0,50);lastPosition=p.opened;}}
      else line(position,b&&fresh(b.updated,now,8)?'Открытой позиции нет.':'Состояние позиции неизвестно: нет свежего снимка.');
      const opened=new Set([...list.querySelectorAll('details[open]')].map(e=>e.dataset.key));list.replaceChildren();
      const visible=rows.filter(x=>filter.value==='all'||x.view.kind===filter.value);
      if(!visible.length)line(list,filter.value==='entry'?'Сейчас нет подтверждённых условий входа B.':'Нет алертов выбранного типа.','notice');
      for(const {source,r,view:v} of visible){
        const card=make('article','alert-card alert-'+v.tone);card.append(make('small','',source==='B'?'МОДЕЛЬ B':'АНАЛИЗ СТАКАНА'),make('h3','',r.symbol+' · '+v.direction),make('p','alert-label',v.label));
        const metrics=make('div','alert-metrics');
        const depth=source==='B'?r.bands?.['0.001']: {bid:r.bid_depth,ask:r.ask_depth};
        for(const [label,value] of [['Цена снимка',fmt(r.price,8)],['Спред',fmt(r.spread,4)+'%'],['Bid / Ask ±0,1%',fmt(depth?.bid,0)+' / '+fmt(depth?.ask,0)+' USDT'],['Возраст стакана',fmt(now-(r.time??r.book_time),1)+' сек.']]){const cell=make('div','');cell.append(make('span','',label),make('b','',value));metrics.append(cell);}card.append(metrics);
        if(depth?.covered===false||r.covered===false)line(card,'Полученная глубина — нижняя оценка зоны.','muted');
        if(source==='B')line(card,'ATR '+fmt(r.chart?.atr_pct)+'% · расходы оборота '+fmt(r.roundtrip_pct)+'%.','muted');
        const d=make('details','');d.dataset.key=source+':'+r.symbol;d.open=opened.has(d.dataset.key);d.append(make('summary','','Условия и ограничения'));
        for(const reason of v.reasons)line(d,reason);
        if(!v.reasons.length)line(d,source==='B'?'Условия выполнены на этом снимке. Фактический PAPER-вход подтверждается позицией и журналом.':'Условия наблюдения за стаканом выполнены. Это не сигнал входа модели B.');
        if(source==='B')line(d,'Лента 5 / 15 сек.: '+fmt(r.flow5?.ratio*100,1)+'% / '+fmt(r.flow15?.ratio*100,1)+'% · OFI 5 сек. '+fmt(r.ofi5,0));
        card.append(d);list.append(card);
      }
      log.replaceChildren();if(!events.length)line(log,'Новых событий пока нет.','muted');
      for(const e of events){const p=make('p','alert-event event-'+e.tone,stamp(e.time)+' · '+e.text);log.append(p);}
    }
    async function poll(){
      if(busy)return;busy=true;
      const results=await Promise.allSettled(['/api/model-b','/api/signals'].map(async path=>{const res=await labFetch(path);if(!res.ok)throw new Error('HTTP '+res.status);return res.json();}));
      for(let i=0;i<2;i++){const result=results[i],key=i?'w':'b';if(result.status==='fulfilled'){errors[key]='';if(i)w=result.value;else b=result.value;}else{errors[key]='недоступен';if(i)w=null;else b=null;}}
      busy=false;render();setTimeout(poll,2000);
    }
    clear.addEventListener('click',()=>{events=[];render();});filter.addEventListener('change',render);
    document.addEventListener('visibilitychange',render);
    setInterval(render,1000);poll();
  });
})(typeof window==='undefined'?globalThis:window);
