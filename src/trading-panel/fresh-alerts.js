/* Current public-market events. History is separate; no order commands. */
(function(scope){
 const kinds=['ready','almost','cancelled','book_worse','near_level'];
 const finite=Number.isFinite,fresh=(t,now,limit)=>finite(t)&&now-t>=-2&&now-t<=limit;
 const sourceLimits={quote:45,chart:75,candle:120,book:8,fetched:8};
 function currentEvents(packet,now){
  if(packet?.status!=='ok'||!fresh(packet.updated,now,5)||!Array.isArray(packet.events))return [];
  return packet.events.filter(e=>e&&kinds.includes(e.kind)&&typeof e.id==='string'&&e.id.length<=100&&
   typeof e.symbol==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(e.symbol)&&typeof e.detail==='string'&&typeof e.label==='string'&&
   Number.isSafeInteger(e.sequence)&&e.sequence>0&&e.sequence<=packet.cursor&&fresh(e.time,now,30)&&finite(e.expires)&&e.expires>=now&&
   e.sources&&(['book_worse'].includes(e.kind)?['quote','book','fetched']:Object.keys(sourceLimits)).every(k=>fresh(e.sources[k],now,sourceLimits[k]))).slice(0,50);
 }
 function consume(packet,previous,now){
  if(packet?.status!=='ok'||!fresh(packet.updated,now,5)||typeof packet.epoch!=='string'||typeof packet.scope!=='string'||!Number.isSafeInteger(packet.cursor)||packet.cursor<0)return {cursor:previous,captured:[],notify:[]};
  const same=previous?.epoch===packet.epoch&&previous?.scope===packet.scope;
  if(same&&packet.cursor<previous.value)return {cursor:previous,captured:[],notify:[]};
  const captured=currentEvents(packet,now).filter(e=>!same||e.sequence>previous.value);
  return {cursor:{epoch:packet.epoch,scope:packet.scope,value:packet.cursor},captured,notify:same?captured:[]};
 }
 function archive(history,events,now){
  const seen=new Set(),out=[];
  for(const e of [...events,...history].filter(e=>e&&finite(e.time)).sort((a,b)=>b.time-a.time||(b.sequence||0)-(a.sequence||0))){
   if(!e||typeof e.id!=='string'||seen.has(e.id)||!fresh(e.time,now,86400)||!kinds.includes(e.kind)||typeof e.symbol!=='string'||typeof e.detail!=='string'||typeof e.label!=='string')continue;
   seen.add(e.id);out.push(e);if(out.length===50)break;
  }
  return out;
 }
 const api={currentEvents,consume,archive,kinds};scope.LabMarketAlerts=api;
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-alerts');if(!page)return;
  const el=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text!=null)n.textContent=text;return n;};
  const heading=el('section','box fresh-alerts-head');heading.append(el('h2','','Свежие алерты'),el('p','muted','События умного отбора и уровней 1м. «Кандидат готов» — все проверки отбора пройдены; направление и вход проверяются в PAPER-плане.'));
  const health=el('p','fresh-alert-health','Подключаем монитор…');health.setAttribute('role','status');heading.append(health);
  const toolbar=el('div','fresh-alert-toolbar'),filterLabel=el('label','','Тип события'),filter=el('select');filter.setAttribute('aria-label','Тип события');
  for(const [value,text]of [['all','Все события'],['ready','Кандидат готов'],['almost','Почти готов'],['cancelled','Условие отменено'],['book_worse','Стакан ухудшился'],['near_level','Цена у уровня']]){const option=el('option','',text);option.value=value;filter.append(option);}filterLabel.append(filter);toolbar.append(filterLabel);
  const soundButton=el('button','secondary-button','Звук: выключен'),notifyButton=el('button','secondary-button','Уведомления: выключены');for(const b of [soundButton,notifyButton]){b.type='button';b.setAttribute('aria-pressed','false');toolbar.append(b);}heading.append(toolbar);
  const note=el('p','muted','Звук — на активной странице. Уведомления — при открытом браузере и разрешении; после закрытия сайта доставка не работает.');heading.append(note);
  const rules=el('details','fresh-alert-rules');rules.append(el('summary','','Как появляются события'));
  for(const text of ['Кандидат готов: 12 известных проверок прошли, рейтинг полный, источники свежие. Это допуск к анализу входа.','Почти готов: одна известная проверка не прошла, отклонение от её порога не больше 20%. Ожидание данных сюда не относится.','Условие отменено: ранее готовый или почти готовый кандидат перестал выполнять условия на свежих данных.','Стакан ухудшился: после подтверждённых пяти снимков перестали выполняться глубина, спред, impact или полное покрытие зоны.','Цена у уровня: свежая цена в зоне подтверждённой поддержки или сопротивления 1м с допуском 0,25 ATR. Повтор — после отхода дальше 0,5 ATR.'])rules.append(el('p','muted',text));heading.append(rules);page.append(heading);
  const feedSection=el('section','box fresh-alert-feed');feedSection.append(el('h3','','События сейчас'));const feed=el('div','fresh-event-list');feed.id='fresh-alert-events';feedSection.append(feed);page.append(feedSection);
  const conditions=el('details','box fresh-alert-conditions');conditions.append(el('summary','','Текущие условия отбора'));const conditionList=el('div');conditions.append(conditionList);page.append(conditions);
  const historySection=el('details','box fresh-alert-history');historySection.append(el('summary','','История событий'));historySection.append(el('p','muted','До 50 событий за 24 часа в этом браузере. Это прошлые наблюдения; они не подтверждают текущие условия.'));
  const clear=el('button','secondary-button','Очистить историю');clear.type='button';const historyList=el('div','fresh-event-list');historyList.id='fresh-alert-history';historySection.append(clear,historyList);page.append(historySection);
  let packet=null,error='',busy=false,requestGeneration=0,cursor=null,history=[],lastSuccess=0,sound=false,notify=false,audio=null,feedSignature='',historySignature='',conditionsSignature='',lastQuery='';
  const key='lab-market-alerts-v1';try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved){history=archive(Array.isArray(saved.history)?saved.history:[],[],Date.now()/1000);if(typeof saved.cursor?.epoch==='string'&&typeof saved.cursor?.scope==='string'&&Number.isSafeInteger(saved.cursor.value)&&saved.cursor.value>=0)cursor=saved.cursor;}}catch{}
  const persist=()=>{try{localStorage.setItem(key,JSON.stringify({cursor,history}));}catch{note.textContent='Браузер запретил сохранение: история доступна до закрытия страницы. Уведомления требуют открытого браузера.';}};
  const query=()=>{let filters={};try{const values=JSON.parse(localStorage.getItem('lab-selection-v1')||'null');if(values&&typeof values==='object'&&!Array.isArray(values))for(const [k,v]of Object.entries(values))if(finite(v))filters[k]=v;}catch{}const search=(document.querySelector('[aria-label="Поиск монеты"]')?.value||'').toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,24);return new URLSearchParams({...filters,search}).toString();};
  const openCoin=symbol=>document.dispatchEvent(new CustomEvent('lab-coin',{detail:{symbol,interval:'1'}}));
  function eventRow(e,historical){const row=el('div','fresh-event');row.dataset.kind=e.kind;row.dataset.id=e.id;const body=el('div','fresh-event-body'),caption=el('div','fresh-event-caption');caption.append(el('strong','fresh-kind kind-'+e.kind,e.label),el('time','muted',new Date(e.time*1000).toLocaleTimeString('ru-RU')));body.append(caption,el('b','fresh-event-symbol',e.symbol+(finite(e.score)?' · '+e.score+' / 100':'')),el('p','muted',e.detail));
   const sources=el('small','muted','Наблюдение '+new Date(e.time*1000).toLocaleString('ru-RU')+(historical?' · история':' · свежесть проверена'));body.append(sources);row.append(body);
   if(!historical){const button=el('button','secondary-button','Карточка монеты');button.type='button';button.setAttribute('aria-label','Карточка '+e.symbol);button.addEventListener('click',()=>openCoin(e.symbol));row.append(button);}return row;}
  function render(){const now=Date.now()/1000,events=error?[]:currentEvents(packet,now),visible=events.filter(e=>filter.value==='all'||e.kind===filter.value),connected=!error&&packet?.status==='ok'&&fresh(packet.updated,now,5);
   health.textContent=error?'Монитор недоступен · повторяем запрос. Текущие события скрыты.':!connected?'Ожидаем свежий ответ монитора. Текущие события скрыты.':'Свежих событий: '+events.length+' · до 8 пар по обороту'+(packet.search?' · поиск '+packet.search:'')+' · пороги из скринера';health.dataset.status=connected?'ok':'unavailable';
   const signature=JSON.stringify([visible,connected,filter.value]);if(signature!==feedSignature){feedSignature=signature;feed.replaceChildren();for(const e of visible)feed.append(eventRow(e,false));if(!visible.length)feed.append(el('p','muted',!connected?'После получения свежих данных события появятся здесь.':events.length?'Событий этого типа сейчас нет.':'Новых свежих событий сейчас нет. Действующие условия можно раскрыть ниже.'));}
   const rows=connected&&Array.isArray(packet.rows)?packet.rows:[],rowSignature=JSON.stringify(rows.map(r=>[r.symbol,r.state,r.score,r.reasons,r.sources,Object.entries(sourceLimits).every(([k,limit])=>fresh(r.sources?.[k],now,limit))]));
   if(rowSignature!==conditionsSignature){conditionsSignature=rowSignature;conditionList.replaceChildren();for(const r of rows){const valid=Object.entries(sourceLimits).every(([k,limit])=>fresh(r.sources?.[k],now,limit)),state=valid?r.state:'unavailable',line=el('div','fresh-condition');line.append(el('b','',r.symbol),el('span','',({ready:'Отбор пройден',almost:'Одна проверка близка к порогу',waiting:'Условия не выполнены',unavailable:'Нет полного свежего подтверждения'}[state]||'Ожидание проверки')));if(valid&&r.reasons?.length)line.append(el('small','muted',r.reasons.join(', ')));conditionList.append(line);}if(!rows.length)conditionList.append(el('p','muted','Монитор ожидает котировки, закрытые минутные свечи и пять снимков стакана.'));}
   history=archive(history,[],now);const hSignature=JSON.stringify(history);if(hSignature!==historySignature){historySignature=hSignature;historyList.replaceChildren();for(const e of history)historyList.append(eventRow(e,true));if(!history.length)historyList.append(el('p','muted','История пуста. Новые события сохранятся здесь.'));}
   document.dispatchEvent(new CustomEvent('lab-alerts',{detail:events.length}));document.dispatchEvent(new CustomEvent('lab-market-alerts',{detail:events}));
  }
  function beep(){if(!sound||!audio||document.hidden)return;try{const o=audio.createOscillator(),g=audio.createGain();o.connect(g);g.connect(audio.destination);o.frequency.value=740;g.gain.setValueAtTime(.035,audio.currentTime);g.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.2);o.start();o.stop(audio.currentTime+.2);}catch{}}
  soundButton.addEventListener('click',async()=>{try{if(!audio)audio=new (window.AudioContext||window.webkitAudioContext)();await audio.resume();sound=!sound;soundButton.textContent='Звук: '+(sound?'включён':'выключен');soundButton.setAttribute('aria-pressed',String(sound));if(sound)beep();}catch{soundButton.textContent='Звук недоступен';soundButton.disabled=true;}});
  notifyButton.addEventListener('click',async()=>{if(!('Notification' in window)){notifyButton.textContent='Уведомления не поддерживаются';notifyButton.disabled=true;return;}if(notify)notify=false;else{let permission=Notification.permission;if(permission==='default')try{permission=await Notification.requestPermission();}catch{}if(permission!=='granted'){notifyButton.textContent='Уведомления запрещены';return;}notify=true;}notifyButton.textContent='Уведомления: '+(notify?'включены':'выключены');notifyButton.setAttribute('aria-pressed',String(notify));});
  filter.addEventListener('change',render);clear.addEventListener('click',()=>{history=[];persist();render();});
  async function poll(){if(busy)return;busy=true;const q=query(),generation=requestGeneration;lastQuery=q;try{const response=await labFetch('/api/market-alerts?'+q,{background:true});if(!response.ok)throw Error('HTTP');const next=await response.json();if(generation!==requestGeneration||q!==query())return;if(next?.status!=='ok'||!fresh(next.updated,Date.now()/1000,5))throw Error('Нет свежего ответа');
    if(cursor?.epoch===next.epoch&&cursor?.scope===next.scope&&next.cursor<cursor.value)return;
    const now=Date.now()/1000,result=consume(next,cursor,now),canNotify=lastSuccess>0&&fresh(lastSuccess,now,8);packet=next;error='';cursor=result.cursor;history=archive(history,result.captured,now);lastSuccess=now;persist();
    if(canNotify&&result.notify.length){beep();if(notify&&document.hidden&&'Notification' in window&&Notification.permission==='granted')for(const e of result.notify.slice(0,3))try{const n=new Notification(e.label,{body:e.symbol+' · '+e.detail,tag:'lab-market-'+e.id});setTimeout(()=>n.close(),9000);}catch{}}
   }catch{if(generation===requestGeneration){packet=null;error='unavailable';lastSuccess=0;}}finally{busy=false;render();}}
  const changed=()=>{requestGeneration++;packet=null;lastSuccess=0;error='';render();poll();};document.addEventListener('lab-selection-changed',changed);window.addEventListener('storage',e=>{if(e.key==='lab-selection-v1')changed();});
  document.addEventListener('lab-tab',()=>{if(query()!==lastQuery)changed();else{render();poll();}});document.addEventListener('visibilitychange',()=>{render();poll();});
  setInterval(()=>{if(query()!==lastQuery)changed();else poll();},2000);setInterval(render,1000);render();poll();
 });
})(typeof window!=='undefined'?window:globalThis);
