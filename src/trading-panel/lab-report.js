document.addEventListener('DOMContentLoaded',()=>{
 const page=document.getElementById('page-tests');if(!page)return;
 const box=document.createElement('section');box.className='box';box.id='lab-report';
 const title=document.createElement('h2');title.textContent='A / B · общий период и постоянный журнал';
 const status=document.createElement('p'),body=document.createElement('div');box.append(title,status,body);page.prepend(box);
 const fmt=(x,n=3)=>x==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:n});
 const dt=x=>new Date(x*1000).toLocaleString('ru-RU');
 const line=(parent,text)=>{const p=document.createElement('p');p.textContent=text;parent.append(p);};
 async function refresh(){
  try{
   const res=await fetch('/api/lab-report',{cache:'no-store',signal:AbortSignal.timeout(8000)});
   if(!res.ok)throw new Error('HTTP '+res.status);const s=await res.json();
   const age=Date.now()/1000-s.updated,fresh=age>=-3&&age<=150;
   status.textContent=(!fresh?'ОТЧЁТ УСТАРЕЛ':s.status==='ok'?'Отчёт обновляется':s.status==='partial'?'Неполные или устаревшие исходные данные':'Ожидание / ошибка')+' · '+dt(s.updated);
   status.className=fresh&&s.status==='ok'?'positive':'negative';
   const open=new Set([...body.querySelectorAll('details[open]')].map(d=>d.dataset.key));body.replaceChildren();
   for(const error of s.errors||[])line(body,error);
   if(!s.models)return;
   line(body,'Общий период: '+dt(s.start)+' — '+dt(s.end)+'. Максимум 24 часа.');
   line(body,'Включены только точно записанные сделки, открытые и закрытые внутри периода. Начало ограничено запуском B и первым точным закрытием A.');
   const scroll=document.createElement('div');scroll.className='scroll';const table=document.createElement('table');
   function row(values,head=false){const tr=document.createElement('tr');for(const value of values){const td=document.createElement(head?'th':'td');td.textContent=value;tr.append(td);}table.append(tr);}
   row(['Показатель','Модель A','Модель B'],true);
   for(const [label,key,digits] of [['Закрыто','count',0],['Net, USDT','net',4],['Gross, USDT','gross',4],['Комиссии, USDT','fees',4],['Funding, USDT','funding',4],['Средний net','average',4],['Прибыльных, %','win_rate',1],['Profit factor','profit_factor',2]]){
    row([label,...['A','B'].map(k=>s.models[k].count?fmt(s.models[k][key],digits):(key==='count'?'0':'—'))]);
   }
   scroll.append(table);body.append(scroll);
   line(body,'Net уже включает комиссии и funding. Проскальзывание учтено в ценах исполнения. Profit factor — отношение суммы положительных net к модулю отрицательных; без убытков показан прочерк.');
   line(body,'Различаются правила входа, выхода и исполнения: это наблюдательное сравнение, не доказательство преимущества индикаторов. Отсутствие сделок не означает более прибыльную стратегию.');
   line(body,'Закрытий A до точного журнала: '+s.legacy_a+'. Пересекают начало периода и исключены: A '+s.models.A.crossing_excluded+', B '+s.models.B.crossing_excluded+'.');
   for(const k of ['A','B']){
    const p=s.positions[k];line(body,k+': '+(p?'открыта '+p.symbol+' '+(p.side===1?'LONG':'SHORT')+' с '+dt(p.opened):'открытой позиции нет')+'. Открытый P&L не включён в таблицу.');
    const d=document.createElement('details');d.dataset.key='model-'+k;d.open=open.has(d.dataset.key);const h=document.createElement('summary');h.textContent='Модель '+k+' · результат по монетам';d.append(h);
    for(const r of s.models[k].symbols){const p=document.createElement('p');p.textContent=r.symbol+' · '+r.count+' закрытий · '+fmt(r.net,4)+' USDT';p.className=r.net>0?'positive':r.net<0?'negative':'muted';d.append(p);}body.append(d);
   }
   const diag=s.diagnostics;
   line(body,'Постоянная диагностика B: полные минуты '+dt(diag.start)+' — '+dt(diag.end)+'. Источник — архивные снимки примерно раз в 5 секунд; пропуски не восстанавливаются.');
   line(body,'Проценты относятся к сохранённым свежим наблюдениям, не ко времени и не к числу сделок. Причины могут сочетаться. Сбор работает при закрытом Safari.');
   for(const r of diag.rows){
    const d=document.createElement('details');d.dataset.key=r.symbol;d.open=open.has(r.symbol);const h=document.createElement('summary');h.textContent=r.symbol+' · '+r.samples+' наблюдений';d.append(h);
    line(d,'Поток готов: '+r.ready+'/'+r.samples+' · условия входа выполнены в '+r.signals+' снимках (это не количество независимых сигналов).');
    for(const v of r.reasons)line(d,fmt(v.percent,1)+'% · '+v.reason+' ('+v.n+'/'+r.samples+')');body.append(d);
   }
   if(!diag.rows.length)line(body,'В этом периоде пока нет сохранённых свежих наблюдений B.');
  }catch(e){status.textContent='Отчёт недоступен: '+e.message;status.className='negative';body.replaceChildren();}
  finally{setTimeout(refresh,15000);}
 }
 refresh();
});
