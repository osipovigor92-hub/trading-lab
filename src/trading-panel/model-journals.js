document.addEventListener('DOMContentLoaded',()=>{
 const page=document.getElementById('page-tests');if(!page)return;
 const box=document.createElement('section');box.className='box';box.id='model-journals';
 const title=document.createElement('h2');title.textContent='Журналы сделок · A и B';box.append(title);page.prepend(box);
 const fmt=(x,n=4)=>x==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:n});
 const dt=x=>x?new Date(x*1000).toLocaleString('ru-RU'):'—';
 const line=(p,text)=>{const el=document.createElement('p');el.textContent=text;p.append(el);return el;};
 const issueRows=s=>Array.isArray(s.issues)&&s.issues.length?s.issues:(s.errors||[]).map(detail=>({title:'Данные требуют внимания',detail:String(detail)}));
 function showIssues(parent,s){const rows=issueRows(s).filter(row=>row&&typeof row.title==='string');if(!rows.length)return;const box=document.createElement('details');box.className='data-notice report-issues';const summary=document.createElement('summary');summary.textContent='Данные требуют внимания · '+rows.length;box.append(summary);for(const row of rows){const item=document.createElement('div');item.className='report-issue';const h=document.createElement('strong');h.textContent=row.title;const p=document.createElement('p');p.textContent=row.detail||'';item.append(h,p);box.append(item);}parent.append(box);}
 const metric=(parent,label,value,cls='')=>{const cell=document.createElement('div');cell.className='journal-metric';const h=document.createElement('span');h.textContent=label;const v=document.createElement('strong');v.className=cls;v.textContent=value;cell.append(h,v);parent.append(cell);};
 for(const model of ['A','B']){
  const root=document.createElement('section'),h=document.createElement('h3'),status=document.createElement('p'),body=document.createElement('div');
  h.textContent='Модель '+model;root.append(h,status,body);box.append(root);
  async function refresh(){
   try{
    const url='/api/journal-'+model.toLowerCase();const s=typeof window.labJson==='function'?await window.labJson(url,{cache:'no-store',signal:AbortSignal.timeout(8000)},'Журнал модели '+model):await (async()=>{const response=await labFetch(url,{cache:'no-store',signal:AbortSignal.timeout(8000)});if(!response.ok)throw new Error('HTTP '+response.status);return response.json();})();const now=Date.now()/1000;
    const reportFresh=now-s.updated>=-3&&now-s.updated<=150;
    const sourceAtBuild=s.updated-s.source_updated,sourceFresh=sourceAtBuild>=-3&&sourceAtBuild<=15;
    status.textContent=(!reportFresh?'ОТЧЁТ УСТАРЕЛ':!sourceFresh?'ИСХОДНОЕ СОСТОЯНИЕ УСТАРЕЛО':s.phase==='halted'?'МОДЕЛЬ ОСТАНОВЛЕНА':s.status==='ok'?'Журнал обновляется':'НЕПОЛНЫЙ ОТЧЁТ')+' · '+dt(s.updated);
    status.className=reportFresh&&sourceFresh&&s.status==='ok'&&s.phase!=='halted'?'positive':'negative';
    const opened=new Set([...body.querySelectorAll('details[open]')].map(d=>d.dataset.key));body.replaceChildren();
    showIssues(body,s);if(s.reason)line(body,s.reason,s.phase==='halted'?'negative':'muted');
    const t=s.summary;
    const summary=document.createElement('div');summary.className='journal-summary';metric(summary,'Точные закрытия',String(t.count));metric(summary,'Чистый результат',fmt(t.net)+' USDT',t.net>0?'positive':t.net<0?'negative':'');metric(summary,'Средняя сделка',fmt(t.average)+' USDT',t.average>0?'positive':t.average<0?'negative':'');metric(summary,'Profit factor',fmt(t.profit_factor,2));body.append(summary);
    line(body,'Прибыльных '+t.wins+' · убыточных '+t.losses+' · нулевых '+(t.count-t.wins-t.losses)+'.');
    line(body,'Gross '+fmt(t.gross)+' · комиссии '+fmt(t.fees)+' · funding '+fmt(t.funding)+' USDT. Комиссии и funding уже включены в net.');
    line(body,'Прибыльных '+fmt(t.win_rate,1)+'% · profit factor '+fmt(t.profit_factor,2)+'. Прочерк — показатель не определён.');
    line(body,'Покрытие: '+dt(s.first_opened)+' — '+dt(s.last_closed)+'. Старых закрытий без точного журнала: '+s.legacy_closed+'.');
    line(body,'Этот журнал охватывает всю записанную историю модели; периоды A и B могут различаться. Сравнение общего периода — в отдельном блоке.');
    const csv=document.createElement('a');csv.href='/journal-'+model.toLowerCase()+'.csv';csv.download='model-'+model+'-trades.csv';csv.textContent='Скачать все точные сделки '+model+' · CSV';body.append(csv);
    line(body,'В CSV время — Unix, секунды UTC; числа с десятичной точкой.');
    if(s.position){const p=s.position;line(body,'Открыта '+p.symbol+' '+p.side+' · вход '+fmt(p.entry,8)+' · количество '+fmt(p.quantity,8)+' · с '+dt(p.opened)+'.');}
    else line(body,'На исходном снимке '+dt(s.source_updated)+' открытой позиции нет.');
    line(body,'Открытый P&L не включён в результаты закрытых сделок.');
    const by=document.createElement('details');by.dataset.key='symbols';by.open=opened.has('symbols');const bh=document.createElement('summary');bh.textContent='Результат по монетам';by.append(bh);
    for(const r of t.symbols){const p=line(by,r.symbol+' · '+r.count+' сделок · '+fmt(r.net)+' USDT');p.className=r.net>0?'positive':r.net<0?'negative':'muted';}body.append(by);
    line(body,'Показаны последние '+s.shown+' закрытий. В CSV — все '+t.count+'.');
    for(const r of s.rows){
     const d=document.createElement('details');d.dataset.key=r.symbol+':'+r.opened;d.open=opened.has(d.dataset.key);d.className='box';
     const summary=document.createElement('summary');summary.textContent=dt(r.closed)+' · '+r.symbol+' '+r.side+' · '+fmt(r.net)+' USDT';summary.className=r.net>0?'positive':r.net<0?'negative':'muted';d.append(summary);
     line(d,'Причина: '+r.reason+' · удержание '+fmt(r.seconds,1)+' сек.');
     line(d,'Вход '+dt(r.opened)+' · '+fmt(r.entry,8)+' USDT; выход '+dt(r.closed)+' · '+fmt(r.exit,8)+' USDT.');
     line(d,'Количество '+fmt(r.quantity,8)+' · gross '+fmt(r.gross)+' · комиссия входа '+fmt(r.entry_fee)+' / выхода '+fmt(r.exit_fee)+' · funding '+fmt(r.funding)+' USDT.');
     line(d,r.mfe_net==null?'Экстремумы net для этой сделки не записывались.':'Лучший / худший наблюдённый net: '+fmt(r.mfe_net)+' / '+fmt(r.mae_net)+' USDT; между снимками могли быть другие значения.');
     if(r.features){const f=r.features;line(d,'На входе: спред '+fmt(f.spread)+'% · расходы полного оборота '+fmt(f.roundtrip_pct)+'% · OFI 5 сек. '+fmt(f.ofi5)+'.');if(f.chart)line(d,'ATR '+fmt(f.chart.atr_pct)+'% · относительный оборот '+fmt(f.chart.rvol5,2)+'×.');}
     body.append(d);
    }
   }catch(e){status.textContent='Журнал '+model+' недоступен: '+e.message;status.className='negative';body.replaceChildren();}
   finally{setTimeout(refresh,15000);}
  }
  refresh();
 }
});
