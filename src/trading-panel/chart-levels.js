/* Local annotations and source-specific, read-only orderbook overlays. */
(function(scope){
 'use strict';
 const STORE='lab-chart-levels-v1',TYPES={resistance:'Сопротивление',support:'Поддержка'};
 const finite=n=>typeof n==='number'&&Number.isFinite(n),positive=n=>finite(n)&&n>0&&n<=1e15;
 const fresh=(t,now,ttl)=>finite(t)&&t<=now+2&&now-t<=ttl;
 const pair=s=>s.exchange+':'+s.symbol;
 function cleanManual(value){return Array.isArray(value)?value.filter(v=>v&&typeof v.id==='string'&&/^[\w-]{1,80}$/.test(v.id)&&Object.hasOwn(TYPES,v.type)&&positive(v.price)).slice(0,12).map(({id,type,price})=>({id,type,price})):[];}
 function densityLevels(packet,source,now=Date.now()/1000){
  if(!source||!Array.isArray(packet?.rows))return [];
  const confirmed=!packet.error&&!packet.refresh_error&&fresh(packet.updated,now,30)&&['ok','partial'].includes(packet.status);
  const rows=packet.rows.filter(r=>r&&r.exchange===source.exchange&&r.symbol===source.symbol&&typeof r.id==='string'&&['bid','ask'].includes(r.side)&&positive(r.price)&&finite(r.notional)&&r.notional>=100000&&finite(r.distance_pct)&&r.distance_pct>=0&&r.distance_pct<=5&&['active','unavailable','unobserved'].includes(r.status));
  const seen=new Set(),result=[];
  for(const side of ['bid','ask'])for(const r of rows.filter(r=>r.side===side).sort((a,b)=>b.notional-a.notional).slice(0,3)){
   if(seen.has(r.id))continue;seen.add(r.id);result.push({id:r.id,price:r.price,side:r.side,notional:r.notional,confirmed:confirmed&&r.status==='active'&&fresh(r.last_seen,now,25)});
  }
  return result;
 }
 function autoLevels(packet,now=Date.now()/1000){
  const bars=packet?.candles,step=Number(packet?.interval)*60;
  if(packet?.status!=='ok'||packet.error||packet.refresh_error||packet.stale||!fresh(packet.updated,now,75)||!Array.isArray(bars)||bars.length<30||!step||packet.candle_end!==Math.floor((now-2)/step)*step)return [];
  if(!bars.every((b,i)=>b&&[b.t,b.open,b.high,b.low,b.close].every(finite)&&b.low>0&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&b.t+step<=packet.candle_end&&(!i||b.t-bars[i-1].t===step)))return [];
  const last=bars.at(-1);if(last.t+step!==packet.candle_end)return [];
  const atr=bars.slice(-14).reduce((sum,b,i)=>{const index=bars.length-14+i,prev=bars[index-1].close;return sum+Math.max(b.high-b.low,Math.abs(b.high-prev),Math.abs(b.low-prev));},0)/14;
  const tolerance=Math.max(atr*.35,last.close*.0001),groups=[];
  for(let i=2;i<bars.length-2;i++){
   const b=bars[i],neighbors=[bars[i-2],bars[i-1],bars[i+1],bars[i+2]];
   for(const field of ['low','high']){
    if(!neighbors.every(n=>field==='low'?b.low<n.low:b.high>n.high))continue;
    const value=b[field];let group=groups.find(g=>g.field===field&&Math.abs(g.price-value)<=tolerance);
    if(!group){group={field,price:value,touches:0,last:-10};groups.push(group);}
    if(i-group.last<3)continue;
    group.price=(group.price*group.touches+value)/(group.touches+1);group.touches++;group.last=i;
   }
  }
  return groups.filter(g=>g.touches>=2&&(g.field==='low'?g.price<last.close:g.price>last.close)).map(g=>({id:packet.interval+':'+g.field+':'+g.price.toPrecision(10),type:g.field==='low'?'support':'resistance',price:g.price,touches:g.touches,interval:packet.interval,distance:Math.abs(g.price-last.close)/last.close}));
 }
 function levelId(cryptoApi=scope.crypto){
  if(typeof cryptoApi?.randomUUID==='function')return cryptoApi.randomUUID();
  return Array.from(cryptoApi.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
 }
 const api={cleanManual,densityLevels,levelId,autoLevels};if(typeof module!=='undefined')module.exports=api;if(typeof document==='undefined')return;
 function create({tools,after,widget,onChange}){
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const button=(text,action)=>{const b=el('button','screener-order',text);b.type='button';b.addEventListener('click',action);return b;};
  let saved;try{saved=JSON.parse(localStorage.getItem(STORE));}catch{}saved=saved&&typeof saved==='object'&&!Array.isArray(saved)?saved:{};
  const stored=new Map(Object.entries(saved).filter(([key])=>/^(bybit|binance|okx|gate|bitget):[A-Z0-9]{1,28}USDT$/.test(key)).slice(-48).map(([key,value])=>[key,cleanManual(value)]));
  let source=null,manual=[],densityPacket=null,densityError='',densityEnabled=false,drawing=false,editorOpen=false,revision=0,inFlight=null,lastRead=0;
  let autoEnabled=false,autoPackets=[],autoBusy=false,autoRead=0,autoError='';
  const auto=button('Автоуровни',()=>{autoEnabled=!autoEnabled;autoRead=0;render();onChange();poll(true);});auto.setAttribute('aria-pressed','false');tools.append(auto);
  const autoStatus=el('p','chart-density-status');autoStatus.hidden=true;after.after(autoStatus);
  const densities=button('Плотности',()=>{densityEnabled=!densityEnabled;lastRead=0;render();onChange();poll(true);});densities.setAttribute('aria-pressed','false');
  const levels=button('Уровни',()=>{editorOpen=!editorOpen;if(!editorOpen)drawing=false;render();});levels.setAttribute('aria-expanded','false');levels.setAttribute('aria-controls','chart-level-editor');tools.append(densities,levels);
  const panel=el('section','chart-level-editor');panel.id='chart-level-editor';panel.setAttribute('aria-label','Уровни поддержки и сопротивления');panel.hidden=true;
  const form=el('form','chart-level-form'),type=el('select'),input=el('input');type.setAttribute('aria-label','Тип уровня');
  for(const [value,label]of Object.entries(TYPES)){const option=el('option','',label);option.value=value;type.append(option);}
  input.type='text';input.inputMode='decimal';input.placeholder='Цена уровня';input.setAttribute('aria-label','Цена уровня');input.maxLength=32;
  const add=el('button','screener-order','Добавить');add.type='submit';const draw=button('Нанести кликом',()=>{drawing=!drawing;render();if(drawing)widget.focus();});draw.setAttribute('aria-pressed','false');form.append(type,input,add,draw);panel.append(form);
  const hint=el('p','chart-level-hint',''),list=el('div','chart-manual-levels');hint.setAttribute('role','status');panel.append(hint,list,el('p','muted','Ручные уровни сохраняются для этой монеты и биржи. Это ваши отметки.'));
  const densityStatus=el('p','chart-density-status');densityStatus.setAttribute('role','status');densityStatus.hidden=true;after.after(densityStatus,panel);
  function persist(){if(!source)return;stored.delete(pair(source));stored.set(pair(source),manual);while(stored.size>48)stored.delete(stored.keys().next().value);try{localStorage.setItem(STORE,JSON.stringify(Object.fromEntries(stored)));}catch{hint.textContent='Уровни действуют до закрытия страницы · хранилище недоступно';}}
  function addPrice(value){if(!source||!positive(value)){input.setAttribute('aria-invalid','true');hint.textContent='Введите цену больше нуля.';return;}if(manual.length>=12){hint.textContent='Уже 12 уровней. Удалите ненужный, чтобы добавить новый.';return;}input.removeAttribute('aria-invalid');manual.push({id:levelId(),type:type.value,price:Number(value.toPrecision(10))});drawing=false;input.value='';persist();render();onChange();}
  form.addEventListener('submit',event=>{event.preventDefault();const text=input.value.trim().replace(',','.');addPrice(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(text)?Number(text):NaN);});
  function render(){
   auto.setAttribute('aria-pressed',String(autoEnabled));auto.classList.toggle('selected',autoEnabled);autoStatus.hidden=!autoEnabled;autoStatus.textContent=autoError||('Автоуровни 15м / 1ч · '+automatic().length+' · минимум 2 касания · закрытые свечи');
   panel.hidden=!editorOpen;levels.setAttribute('aria-expanded',String(editorOpen));levels.textContent='Уровни'+(manual.length?' · '+manual.length:'');densities.setAttribute('aria-pressed',String(densityEnabled));densities.classList.toggle('selected',densityEnabled);draw.setAttribute('aria-pressed',String(drawing));draw.textContent=drawing?'Отменить нанесение':'Нанести кликом';widget.classList.toggle('is-drawing-level',drawing);
   hint.textContent=drawing?'Нажмите на нужную цену в области свечей. Для отмены — Escape.':'Введите цену или нанесите горизонтальный уровень кликом.';
   const price=n=>n.toLocaleString('ru-RU',{maximumSignificantDigits:10});list.replaceChildren();
   for(const item of manual){const row=el('div','chart-manual-level '+item.type),label=el('span','',TYPES[item.type]+' · '+price(item.price)),remove=button('Удалить',()=>{manual=manual.filter(r=>r.id!==item.id);persist();render();onChange();});remove.setAttribute('aria-label','Удалить '+TYPES[item.type].toLowerCase()+' '+price(item.price));row.append(label,remove);list.append(row);}
   densityStatus.hidden=!densityEnabled;const current=densityLevels(densityPacket,source),valid=current.filter(r=>r.confirmed).length;
   densityStatus.dataset.status=valid?'ok':densityPacket?'unavailable':'pending';
   densityStatus.textContent=densityError?'Плотности не подтверждены · '+densityError:!densityPacket?'Загружаем плотности этой монеты…':valid?'Плотности: '+valid+' подтверждены'+(valid<current.length?' · '+(current.length-valid)+' без подтверждения':'')+' · от 100 000 USDT, до 3 на сторону':current.length?'Последние плотности не подтверждены · проверяем стакан':'Подтверждённых плотностей от 100 000 USDT пока нет · проверяем стакан';
  }
  async function pollDensity(force=false){
   if(!densityEnabled||!source||!source.isOpen()||document.hidden)return;render();if(inFlight||!force&&Date.now()-lastRead<5000)return;
   lastRead=Date.now();const mine=revision,identity={exchange:source.exchange,symbol:source.symbol},controller=new AbortController();inFlight=controller;
   const timer=setTimeout(()=>controller.abort(),8000);
   try{const packet=await scope.labJson('/api/densities?'+new URLSearchParams({exchanges:identity.exchange,symbols:identity.symbol,watch:pair(identity),overlay:'1'}),{fresh:force,signal:controller.signal},'Плотности');if(mine!==revision||!source?.isOpen())return;if(!Array.isArray(packet.rows)||!finite(packet.updated)||!['ok','partial','pending','unavailable','error'].includes(packet.status))throw Error('Некорректный ответ стакана');if(!packet.rows.length&&['unavailable','error'].includes(packet.status)&&densityPacket?.rows?.length)densityPacket={...densityPacket,status:'unavailable'};else densityPacket=packet;densityError=packet.error?String(packet.error).slice(0,180):'';}catch(error){if(mine!==revision||!source?.isOpen())return;densityError=error.name==='AbortError'?'Истёк срок запроса · повторяем':String(error.message||'Нет ответа биржи').slice(0,180);if(densityPacket)densityPacket={...densityPacket,status:'unavailable'};}finally{clearTimeout(timer);if(inFlight===controller)inFlight=null;if(mine===revision){render();onChange();}}
  }
  function automatic(){
   const levels=autoPackets.flatMap(p=>autoLevels(p));
   return ['support','resistance'].flatMap(type=>levels.filter(l=>l.type===type).sort((a,b)=>a.distance-b.distance).slice(0,3));
  }
  async function poll(force=false){
   void pollDensity(force);
   if(!autoEnabled||!source?.isOpen()||document.hidden||autoBusy||!force&&Date.now()-autoRead<15000)return;
   autoBusy=true;autoRead=Date.now();const mine=revision,identity={exchange:source.exchange,symbol:source.symbol};
   try{
    const packets=[];
    for(const interval of ['15','60'])packets.push(await scope.labJson('/api/exchange-chart?'+new URLSearchParams({...identity,interval}),{background:true},'Автоуровни'));
    if(mine!==revision)return;
    autoPackets=packets;autoError=packets.some(p=>p.status!=='ok'||p.error||p.stale)?'Автоуровни: ожидаем свежие закрытые свечи 15м / 1ч':'';
   }catch{if(mine===revision){autoPackets=[];autoError='Автоуровни: источник недоступен · повторяем запрос';}}
   finally{autoBusy=false;if(mine===revision){render();onChange();}}
  }
  function open(next){revision++;autoPackets=[];autoRead=0;autoError="";inFlight?.abort();inFlight=null;source=next;manual=cleanManual(stored.get(pair(source)));drawing=false;input.value='';lastRead=0;densityError='';densityPacket=null;if(next.density){densityEnabled=true;densityPacket={updated:next.density.last_seen,status:'partial',rows:[{...next.density,exchange:next.exchange,symbol:next.symbol}]};}render();poll(true);}
  function close(){revision++;inFlight?.abort();inFlight=null;source=null;drawing=false;widget.classList.remove('is-drawing-level');}
  widget.addEventListener('keydown',event=>{if(event.key==='Escape'&&drawing){event.preventDefault();event.stopPropagation();drawing=false;render();}});
  return {open,close,poll,render,settings:()=>({autoLevels:autoEnabled?automatic():[],levels:manual,densities:densityEnabled?densityLevels(densityPacket,source):[]}),placePrice:value=>{if(drawing)addPrice(value);}};
 }
 scope.LabChartLevels={...api,create};
})(typeof window==='undefined'?globalThis:window);

