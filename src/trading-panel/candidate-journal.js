/* Historical evidence only. No account commands or notification replay. */
((root)=>{
 'use strict';
 const labels={passed:'Отбор пройден',rejected:'Отсев',pending:'Ожидание данных',gap:'Пропуск сбора'};
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 function closingSummary(rows){
  const exact=rows.filter(r=>r.complete===true&&finite(r.net)),gaps=rows.filter(r=>r.observation_gap);
  return {exact:exact.length,incomplete:rows.length-exact.length,gaps:gaps.length,net:exact.length?exact.reduce((n,r)=>n+r.net,0):null};
 }
 const api={closingSummary,labels};if(typeof module!=='undefined')module.exports=api;
 if(!root.document)return;root.LabJournal=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-journals');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(n,d=4)=>finite(n)?(n!==0&&Math.abs(n)<10**-d?n.toExponential(2).replace('.',','):n.toLocaleString('ru-RU',{maximumFractionDigits:d})):n===true?'Да':n===false?'Нет':'—';
  const date=n=>finite(n)&&n>0?new Date(n*1000).toLocaleString('ru-RU'):'—';
  const line=(parent,text,cls='muted')=>{const n=el('p',cls,text);parent.append(n);return n;};
  const btn=text=>{const n=el('button','secondary-button',text);n.type='button';return n;};
  const rowTitle=text=>{const n=el('strong','',text);n.prepend(root.LabUI.icon('arrow','journal-disclosure'));return n;};
  const get=async url=>root.labJson(url,{cache:'no-store',signal:AbortSignal.timeout(8000)},'Постоянный журнал');
  const box=el('section','box candidate-journal');box.id='candidate-journal';
  box.append(el('h2','','Кандидаты и события'));
  line(box,'Сохранённые решения отбора и причины. Запись работает на сервере при закрытом сайте.');
  const health=el('p','journal-health','Загрузка истории…');health.setAttribute('role','status');box.append(health);
  const controls=el('form','journal-controls');controls.setAttribute('aria-label','Фильтры журнала кандидатов');
  function select(label,choices){const l=el('label','',label),s=el('select');s.setAttribute('aria-label',label);for(const [v,t]of choices){const o=el('option','',t);o.value=v;s.append(o);}l.append(s);controls.append(l);return s;}
  const status=select('Решение',[['all','Все записи'],['rejected','Отсев'],['passed','Отбор пройден'],['pending','Ожидание данных'],['signal','События']]);
  const period=select('Период',[['day','24 часа'],['week','7 дней'],['all','Вся история']]);
  const scope=select('Набор фильтров',[['all','Все наборы'],['default','Базовый отбор']]);
  const searchLabel=el('label','','Монета'),search=el('input');search.type='search';search.maxLength=24;search.placeholder='BTC';search.setAttribute('aria-label','Монета в журнале');searchLabel.append(search);controls.append(searchLabel);
  const apply=btn('Показать');apply.type='submit';controls.append(apply);box.append(controls);
  const count=el('p','journal-count'),learning=el('details','journal-learning'),lh=el('summary','','Причины отсева'),learnBody=el('div');learning.append(lh,learnBody);box.append(count,learning);
  const list=el('div','journal-entries'),nav=el('div','journal-pager'),back=btn('Назад'),next=btn('Раньше'),fresh=btn('Обновить'),csv=el('a','secondary-button','CSV этой страницы');csv.download='candidate-journal.csv';nav.append(back,next,fresh,csv);box.append(list,nav);
  line(box,'Эпизод объединяет повторные наблюдения с одинаковыми проверками и состоянием. В подробностях — первый снимок. События и эпизоды не являются числом сделок.');
  line(box,'CSV содержит показанную страницу. Время: Unix, секунды UTC; числа с десятичной точкой.');
  page.prepend(box);
  let params={},before=0,stack=[],nextBefore=0,generation=0,anchor=0;
  function readParams(){return {status:status.value,period:period.value,scope:scope.value,search:search.value.toUpperCase().replace(/[^A-Z0-9]/g,'')};}
  function query(){const q=new URLSearchParams({...params,limit:20});if(before)q.set('before',before);if(anchor)q.set('anchor',anchor);return q;}
  function coinButton(parent,symbol){if(!/^[A-Z0-9]{2,24}USDT$/.test(symbol))return;const b=btn('Карточка '+symbol);b.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('lab-coin',{detail:{symbol,interval:'1'}})));parent.append(b);}
  function checkRows(parent,checks){
   const checksBox=el('div','journal-checks');
   for(const c of (checks||[]).slice(0,12)){
    const row=el('div','journal-check');row.append(el('strong','',c.label||c.key));
    const bounds=[c.min!=null?'от '+fmt(c.min):'',c.max!=null?'до '+fmt(c.max):''].filter(Boolean).join(' · ');
    row.append(el('span','','Значение: '+fmt(c.value)+' '+(c.unit||'')),el('span','muted',bounds?'Порог: '+bounds+' '+(c.unit||''):'Полное покрытие'),el('span',c.state==='fail'?'negative':c.state==='pass'?'positive':'muted',({fail:'Не пройдено',pass:'Пройдено',pending:'Нет данных'})[c.state]||'Нет данных'));checksBox.append(row);
   }parent.append(checksBox);
  }
  function entry(row){
   const d=el('details','journal-entry');d.dataset.id=String(row.id);const head=el('summary'),e=row.evidence||{};
   const title=row.kind==='signal'?'Событие · '+(e.event?.label||'Алерт'):labels[row.status]||'Сохранённая запись';
   head.append(rowTitle(row.kind==='gap'?'Сбор данных':row.symbol),el('span','journal-decision status-'+row.status,title),el('time','muted',date(row.first_seen)));d.append(head);
   if(row.kind==='gap'){line(d,e.detail||'Решения за этот период не восстанавливались');line(d,date(row.first_seen)+' — '+date(row.last_seen));return d;}
   line(d,'Первое наблюдение: '+date(row.first_seen)+' · последнее: '+date(row.last_seen)+' · сохранённых снимков: '+row.samples);
   if(row.kind==='signal'){line(d,e.event?.detail||'');line(d,'Это архив события. Его текущая готовность здесь не подтверждается.');}
   else line(d,'Историческая цена: '+fmt(e.price,8)+' USDT · рейтинг: '+fmt(e.rating?.score,0)+' / 100');
   if(e.note)line(d,e.note);
   const rating=e.rating;if(rating?.status==='ok'&&Array.isArray(rating.components))for(const p of rating.components)line(d,p.name+': '+fmt(p.points,0)+' / 25 · '+p.label);
   checkRows(d,e.checks);
   const context=el('details','journal-context'),ch=el('summary','','Фильтры и источники на момент записи');context.append(ch);
   line(context,'Набор '+row.scope+' · поиск: '+(e.search||'все монеты')+' · версия правил журнала '+e.version+'.');
   const filters=el('dl','journal-filter-values');for(const [k,v]of Object.entries(e.filters||{})){const dt=el('dt','',({turnover_min:'Минимальный оборот, USDT',spread_max:'Максимальный спред, %',range_min:'Минимальный диапазон 24ч, %',range_max:'Максимальный диапазон 24ч, %',atr_min:'Минимальный ATR, %',atr_max:'Максимальный ATR, %',rvol_min:'Минимальный RVOL, ×',oi_min:'Минимальный OI, USDT',funding_max:'Максимальный |funding|, %',depth_min:'Минимальная глубина, USDT',impact_max:'Максимальный impact, %'})[k]||k);filters.append(dt,el('dd','',fmt(v)));}context.append(filters);
   for(const [key,label]of [['quote','Котировка'],['chart','Получение свечей'],['candle','Закрытая свеча'],['book','Время стакана'],['fetched','Получение стакана']])line(context,label+': '+date(e.sources?.[key]));
   if(e.source_status)line(context,'Доступность при записи: котировка '+e.source_status.quote+', свечи '+e.source_status.chart+', стакан '+e.source_status.book+'.');
   for(const [key,text]of Object.entries(e.source_errors||{}))if(text)line(context,'Ошибка '+key+': '+text);
   line(context,'Число снимков стакана: '+(e.book_samples??'—')+' · интервал funding: '+fmt(e.funding_interval_hours)+' ч.');d.append(context);coinButton(d,row.symbol);return d;
  }
  function render(packet){
   if(!packet||!['ok','partial'].includes(packet.status)||!Array.isArray(packet.rows))throw Error(packet?.collector?.error||'Нет ответа хранилища');
   const c=packet.collector||{};health.dataset.status=c.collecting?'ok':'partial';
   health.textContent=(c.collecting?'Сервер сохраняет журнал':c.error||'Ожидание первого сбора')+' · последнее сохранение '+date(c.last_cycle);
   const opened=new Set([...list.querySelectorAll('details[open]')].filter(d=>d.dataset.id).map(d=>d.dataset.id)),contexts=new Set([...list.querySelectorAll('.journal-context[open]')].map(d=>d.closest('.journal-entry').dataset.id));list.replaceChildren();
   if(!packet.rows.length)line(list,'В этом периоде записей нет. Измените фильтры или дождитесь серверной проверки.', 'journal-empty');
   for(const row of packet.rows){const d=entry(row);d.open=opened.has(d.dataset.id);const context=d.querySelector('.journal-context');if(context)context.open=contexts.has(d.dataset.id);list.append(d);}
   const counts=packet.summary?.counts||{};count.textContent='Найдено '+packet.total+' · отсев '+(counts.rejected||0)+' · прошли '+(counts.passed||0)+' · ждут данных '+(counts.pending||0)+' · событий '+(counts.signal||0)+' · пропусков '+(counts.gap||0);
   learnBody.replaceChildren();line(learnBody,'Причины среди '+(counts.rejected||0)+' эпизодов отсева, пересекающих выбранный период. У эпизода может быть несколько причин; это не вероятность прибыли.');
   for(const reason of packet.summary?.reasons||[])line(learnBody,reason.label+' — '+reason.count+' из '+(counts.rejected||0)+' ('+fmt(counts.rejected?reason.count/counts.rejected*100:0,1)+'%).');
   if(!packet.summary?.reasons?.length)line(learnBody,'Подтверждённых причин отсева в выбранных записях нет.');
   if(packet.coverage?.first)line(learnBody,'Всего сохранено за период '+date(packet.coverage.first)+' — '+date(packet.coverage.last)+'. Пропуски не заполняются задним числом.');
   nextBefore=packet.next_before||0;next.disabled=!nextBefore;back.disabled=!stack.length;csv.href='/candidate-journal.csv?'+query();csv.removeAttribute('aria-disabled');
  }
  async function refresh(){
   const id=++generation,requested=query().toString();apply.disabled=fresh.disabled=next.disabled=back.disabled=true;list.setAttribute('aria-busy','true');
   try{const packet=await get('/api/candidate-journal?'+requested);if(id!==generation)return;if(!anchor)anchor=packet.query?.anchor||Math.floor(Date.now()/1000);render(packet);}
   catch(error){if(id!==generation)return;health.dataset.status='unavailable';health.textContent='Журнал недоступен: '+error.message+'. Нажмите «Обновить». Сохранённая история не удаляется.';list.replaceChildren();count.textContent='';learnBody.replaceChildren();nextBefore=0;csv.removeAttribute('href');csv.setAttribute('aria-disabled','true');}
   finally{if(id===generation){apply.disabled=fresh.disabled=false;next.disabled=!nextBefore;back.disabled=!stack.length;list.setAttribute('aria-busy','false');}}
  }
  controls.addEventListener('submit',event=>{event.preventDefault();params=readParams();search.value=params.search;before=anchor=0;stack=[];refresh();});
  next.addEventListener('click',()=>{stack.push(before);before=nextBefore;refresh();});back.addEventListener('click',()=>{before=stack.pop()||0;refresh();});fresh.addEventListener('click',()=>{before=anchor=0;stack=[];refresh();});
  params=readParams();refresh();
  document.addEventListener('lab-tab',()=>{if(root.LabNavigation.current()==='journals'&&!before){anchor=0;refresh();}});

  const manual=el('details','box manual-journal');manual.id='manual-journal';manual.append(el('summary','','Ручной PAPER · история закрытий'));
  const manualHealth=el('p','journal-health'),manualList=el('div','journal-entries'),manualCount=el('p'),manualNav=el('div','journal-pager'),mb=btn('Назад'),mn=btn('Раньше'),mr=btn('Обновить'),mc=el('a','secondary-button','CSV этой страницы');mc.download='manual-journal.csv';manualNav.append(mb,mn,mr,mc);manual.append(manualHealth,manualCount,manualList,manualNav);page.append(manual);
  line(manual,'CSV содержит показанную страницу закрытий. Время: Unix, секунды UTC; числа с десятичной точкой.');
  let mbefore=0,mstack=[],mnext=0,mgeneration=0;
  async function manualRefresh(){
   const id=++mgeneration;mr.disabled=mb.disabled=mn.disabled=true;manualList.setAttribute('aria-busy','true');
   try{const q=new URLSearchParams({limit:20});if(mbefore)q.set('before',mbefore);const packet=await get('/api/manual-journal?'+q);if(id!==mgeneration)return;
    if(packet.status!=='ok'||!Array.isArray(packet.rows))throw Error(packet.error||'История не ответила');
    manualHealth.dataset.status='ok';manualHealth.textContent='Всего закрытий в хранилище: '+packet.total;
    const s=closingSummary(packet.rows);manualCount.textContent='На странице: '+s.exact+' закрытий с точным net · '+s.incomplete+' с неполным учётом · '+s.gaps+' с пропусками наблюдений. Net точных закрытий: '+fmt(s.net)+' USDT.';
    const opened=new Set([...manualList.querySelectorAll('details[open]')].map(d=>d.dataset.id));manualList.replaceChildren();
    if(!packet.rows.length)line(manualList,'Ручных закрытий пока нет. После закрытия PAPER-позиции здесь появятся вход, выход и причины.', 'journal-empty');
    for(const row of packet.rows){const d=el('details','journal-entry');d.dataset.id=row.id;d.open=opened.has(row.id);const h=el('summary');h.append(rowTitle(row.symbol+' '+(row.side===1?'LONG':'SHORT')),el('span',row.complete&&finite(row.net)?row.net>0?'positive':row.net<0?'negative':'muted':'muted',row.complete&&finite(row.net)?fmt(row.net)+' USDT':'Net не подтверждён'),el('time','muted',date(row.closed)));d.append(h);
     line(d,'Вход: '+date(row.opened)+' · '+fmt(row.entry,8)+' USDT; выход: '+date(row.closed)+' · '+fmt(row.exit,8)+' USDT.');
     line(d,'Причина входа: '+(row.reason||'—'));line(d,'Причина выхода: '+(row.exit_reason||'—'));line(d,'Количество: '+fmt(row.quantity,8)+' · gross '+fmt(row.gross)+' · комиссии '+fmt(row.entry_fee)+' / '+fmt(row.exit_fee)+' USDT.');
     if(row.observation_gap)line(d,'Пропуск наблюдений: '+row.observation_gap, 'negative');if(row.complete!==true)line(d,'Funding или другой расход не подтверждён; это закрытие исключено из точного net.', 'negative');
     line(d,'Стоп '+fmt(row.stop,8)+' · цель '+fmt(row.target,8)+' · риск '+fmt(row.risk)+' USDT · котировка на входе '+date(row.quote_time));coinButton(d,row.symbol);manualList.append(d);
    }mnext=packet.next_before||0;mc.href='/manual-journal.csv?'+q;mc.removeAttribute('aria-disabled');
   }catch(error){if(id!==mgeneration)return;manualHealth.dataset.status='unavailable';manualHealth.textContent='История ручного PAPER недоступна: '+error.message;manualList.replaceChildren();manualCount.textContent='';mnext=0;mc.removeAttribute('href');mc.setAttribute('aria-disabled','true');}
   finally{if(id===mgeneration){mr.disabled=false;mb.disabled=!mstack.length;mn.disabled=!mnext;manualList.setAttribute('aria-busy','false');}}
  }
  manual.addEventListener('toggle',()=>{if(manual.open)manualRefresh();});mn.addEventListener('click',()=>{mstack.push(mbefore);mbefore=mnext;manualRefresh();});mb.addEventListener('click',()=>{mbefore=mstack.pop()||0;manualRefresh();});mr.addEventListener('click',()=>{mbefore=0;mstack=[];manualRefresh();});
 });
})(typeof window!=='undefined'?window:globalThis);
