/* Presentation layer only: model decisions remain authoritative. */
(function(scope){
 'use strict';
 const numeric=x=>typeof x==='number'&&Number.isFinite(x);
 const fresh=(t,now,age)=>numeric(t)&&now-t>=-1&&now-t<=age;
 function bookRows(r){return ['0.0002','0.0005','0.001'].map(key=>{
  const b=r?.bands?.[key];const valid=numeric(b?.bid)&&numeric(b?.ask)&&b.bid>=0&&b.ask>=0&&b.bid+b.ask>0;
  return {key,label:'±'+(Number(key)*100).toFixed(2)+'%',valid,bid:valid?b.bid:null,ask:valid?b.ask:null,share:valid?b.bid/(b.bid+b.ask):null,covered:b?.covered===true};
 });}
 function flowRows(r){return [5,15,60].map(seconds=>{const f=r?.['flow'+seconds];const valid=numeric(f?.buy)&&numeric(f?.sell)&&f.buy>=0&&f.sell>=0;
  return {seconds,valid,buy:valid?f.buy:null,sell:valid?f.sell:null,delta:valid?f.buy-f.sell:null,share:valid&&f.buy+f.sell>0?f.buy/(f.buy+f.sell):null,count:f?.count};
 });}
 function seriesPoints(values,width=600,height=100){
  if(!values.length||values.some(x=>!numeric(x)))return '';
  const lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
  return values.map((v,i)=>`${8+i*(width-16)/Math.max(1,values.length-1)},${height-8-(hi===lo?.5:(v-lo)/span)*(height-16)}`).join(' ');
 }
 const api={numeric,fresh,bookRows,flowRows,seriesPoints};if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;scope.LabMetrics=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const overview=document.getElementById('page-overview'),live=document.getElementById('page-live'),tests=document.getElementById('page-tests');if(!overview)return;
  const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const fmt=(x,n=2)=>numeric(x)?x.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
  const line=(p,t,c='muted')=>p.append(make('p',c,t));
  const heading=(p,k,t)=>{p.append(make('small','eyebrow',k),make('h2','',t));};
  const wrap=(page,title)=>{const old=[...page.children],d=make('details','box archive-details');d.append(make('summary','',title));for(const n of old)d.append(n);page.append(d);return d;};
  const oldOverview=wrap(overview,'Подробности контрольной модели A');
  const oldLive=wrap(live,'Сырые метрики LIVE, уровни и независимый наблюдатель');
  document.querySelector('header h1').textContent='Trading Lab';
  document.querySelector('header small').textContent='NODE 02 / MARKET INTELLIGENCE';
  const hero=make('section','terminal-hero');heading(hero,'ОБЗОР РЫНКА','Цена. Поток. Подтверждение.');
  line(hero,'Один экран для графика, ликвидности и условий модели. Реальных ордеров нет.');
  overview.prepend(hero);
  const modelSummary=make('div','model-summary');hero.after(modelSummary);
  const toolbar=make('section','box terminal-toolbar');
  const label=make('label','','Контракт');const select=make('select');select.setAttribute('aria-label','Контракт для анализа');label.append(select);
  const interval=make('select');interval.setAttribute('aria-label','Таймфрейм графика');for(const [v,t] of [['1','1 мин'],['5','5 мин'],['15','15 мин'],['60','1 час']]){const o=make('option','',t);o.value=v;interval.append(o);}interval.value='5';
  const external=make('a','text-link','Открыть TradingView ↗');external.target='_blank';external.rel='noopener noreferrer';
  const quote=make('div','terminal-quote');toolbar.append(label,interval,quote,external);modelSummary.after(toolbar);
  const layout=make('div','terminal-layout'),chartBox=make('section','box chart-box'),decision=make('section','box decision-box');layout.append(chartBox,decision);toolbar.after(layout);
  heading(chartBox,'TRADINGVIEW / BYBIT PERPETUAL','График цены и объёма');
  const chartHost=make('div','chart-host');const load=make('button','primary-button','Загрузить TradingView');load.type='button';
  const hint=make('p','muted','Внешний график загружается по нажатию. TradingView получит IP браузера и выбранный символ; данные панели ему не передаются.');chartHost.append(hint,load);chartBox.append(chartHost);
  line(chartBox,'График TradingView и анализ Bybit — разные источники. Индикаторы на графике не меняют правила PAPER-входа.');
  const pulse=make('section','box');layout.after(pulse);const modelCharts=make('section','box');pulse.after(modelCharts);
  const liquidity=make('section','box liquidity-workspace');live.insertBefore(liquidity,oldLive);
  const guide=make('details','box strategy-guide');guide.append(make('summary','','Как читать аналитику · стратегии и ограничения'));
  const guideItems=[
   ['01 / Режим рынка','EMA20/50 и VWAP описывают направление; ATR — масштаб колебаний. Это фильтры контекста, а не самостоятельный прогноз.'],
   ['02 / Исполнение','Сначала проверяем свежесть, спред, глубину и расходы. ATR / расходы — описательное сравнение; ATR не равен ожидаемой прибыли сделки.'],
   ['03 / Подтверждение','OFI отражает изменение спроса и предложения в стакане. Лента показывает уже исполненные сделки. Совпадение направления не гарантирует продолжения цены.'],
   ['04 / Тестируемая гипотеза B','Тренд → откат → возобновление движения с подтверждением стакана и ленты. Вход определяется кодом B; жёлтое наблюдение входом не является.'],
   ['05 / Следующие гипотезы','Пробой с относительным объёмом и возврат к VWAP в боковике требуют отдельных PAPER-версий. Они описаны для исследования и не включены в текущую модель.'],
   ['06 / Проверка результата','Сравниваем A/B за общий период после комиссий, проскальзывания и funding. Правила фиксируем до теста на новых данных. Частые изменения по прошлым убыткам ведут к подгонке.']
  ];for(const [title,text] of guideItems){const a=make('article');a.append(make('h3','',title),make('p','',text));guide.append(a);}
  for(const [title,url] of [['OFI · Cont, Kukanov, Stoikov','https://arxiv.org/abs/1011.6402'],['Дисбаланс очередей · Gould, Bonart','https://arxiv.org/abs/1512.03492'],['Риск подгонки бэктеста · Bailey и др.','https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf'],['Bybit · порядок snapshot / delta','https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook']]){const a=make('a','research-link',title);a.href=url;a.target='_blank';a.rel='noopener noreferrer';guide.append(a);}
  line(guide,'Исследования OFI и дисбаланса выполнены преимущественно на акциях. Эффективность на этих криптоконтрактах ещё предстоит проверить.');tests.prepend(guide);
  let b=null,a=null,report=null,journals={},selected='LINKUSDT',chartEnabled=false,sequence='',samples=new Map(),error='Подключение',lastSample=new Map();
  const chooseChart=()=>{const safe=/^[A-Z0-9]{2,24}USDT$/.test(selected)?selected:'LINKUSDT';external.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BYBIT:'+safe+'.P');
   if(!chartEnabled)return;chartHost.replaceChildren();const frame=make('iframe');frame.title='TradingView '+safe;frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-popups');frame.referrerPolicy='no-referrer';frame.src='/chart.html?symbol='+encodeURIComponent(safe)+'&interval='+interval.value;chartHost.append(frame);
  };
  load.addEventListener('click',()=>{chartEnabled=true;chooseChart();});select.addEventListener('change',()=>{selected=select.value;chooseChart();render();});interval.addEventListener('change',chooseChart);
  function graph(parent,values,label){const box=make('div','spark-chart');box.append(make('span','muted',label));if(values.length<2){line(box,'Накопление наблюдений…');parent.append(box);return;}
   const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 600 100');svg.setAttribute('role','img');svg.setAttribute('aria-label',label);const p=document.createElementNS(svg.namespaceURI,'polyline');p.setAttribute('points',seriesPoints(values));p.setAttribute('class','spark-line');svg.append(p);box.append(svg);parent.append(box);
  }
  function meter(parent,label,bid,ask,share){const row=make('div','liquidity-row');const title=make('div','liquidity-caption');title.append(make('b','',label),make('span','',fmt(bid,0)+' / '+fmt(ask,0)+' USDT'));row.append(title);
   const bar=make('div','liquidity-meter');if(share!==null){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 100 8');svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('role','img');svg.setAttribute('aria-label','Доля покупок '+fmt(share*100,1)+'%');
    for(const [x,w,cls] of [[0,share*100,'meter-buy'],[share*100,(1-share)*100,'meter-sell']]){const rect=document.createElementNS(svg.namespaceURI,'rect');rect.setAttribute('x',x);rect.setAttribute('width',w);rect.setAttribute('height',8);rect.setAttribute('class',cls);svg.append(rect);}bar.append(svg);
   }else bar.append(make('span','muted','Нет объёма'));row.append(bar);parent.append(row);
  }
  function render(){if(document.hidden)return;const now=Date.now()/1000;const rows=b?.observations||[];const signature=rows.map(r=>r.symbol).join('|');
   if(signature!==sequence){sequence=signature;select.replaceChildren();for(const symbol of rows.map(r=>r.symbol)){const o=make('option','',symbol);o.value=symbol;select.append(o);}if(!rows.some(r=>r.symbol===selected))selected=rows[0]?.symbol||'LINKUSDT';select.value=selected;chooseChart();}
   const r=rows.find(r=>r.symbol===selected);const current=b?.phase==='running'&&fresh(b.updated,now,8)&&fresh(r?.time,now,3);const view=r&&scope.LabAlerts?scope.LabAlerts.classifyB(b,r,now):null;
   modelSummary.replaceChildren();for(const [name,s] of [['A',a],['B',b]]){const card=make('article','model-tile');const active=s&&fresh(s.updated,now,10);card.append(make('small','eyebrow','МОДЕЛЬ '+name),make('h3','',active?(s.phase==='running'?'PAPER работает':s.phase==='halted'?'Остановлена':'Ожидание'):'Нет свежих данных'));
    const pnl=s&&numeric(s.equity)&&numeric(s.config?.capital)?s.equity-s.config.capital:null;card.append(make('strong',pnl<0?'negative':'positive',fmt(pnl,4)+' USDT'));line(card,'Полный P&L модели · '+(s?.position?s.position.symbol+' в позиции':'нет открытой позиции'));modelSummary.append(card);}
   quote.replaceChildren(make('strong','',current?fmt(r.price,6):'—'),make('small',current?'positive':'negative',current?'Свежий стакан · '+fmt(now-r.time,1)+' с':error||'Данные устарели'));
   decision.replaceChildren();heading(decision,'РЕШЕНИЕ МОДЕЛИ B',view?view.label:'Ожидание данных');decision.className='box decision-box alert-'+(view?.tone||'neutral');
   line(decision,selected+(view?' · '+view.direction:''),'decision-symbol');
   const chartFresh=current&&fresh(r.chart?.end,now,120)&&!r.chart_error;const metrics=make('div','terminal-metrics');for(const [k,v] of [['Спред',current?fmt(r.spread,4)+'%':'—'],['Расходы оборота',current?fmt(r.roundtrip_pct,3)+'%':'—'],['ATR минутный',chartFresh?fmt(r.chart?.atr_pct,3)+'%':'—'],['RVOL 5 мин',chartFresh?fmt(r.chart?.rvol5,2)+'×':'—']]){const cell=make('div');cell.append(make('span','muted',k),make('b','',v));metrics.append(cell);}decision.append(metrics);
   const reasons=view?.reasons||['Нет данных модели'];for(const text of reasons.slice(0,4))line(decision,text,'condition-reason');if(reasons.length>4)line(decision,'Ещё '+(reasons.length-4)+' ограничений во вкладке «Алерты».');
   if(!reasons.length)line(decision,'Проверяйте фактическое открытие в PAPER-журнале.');
   pulse.replaceChildren();heading(pulse,'МИКРОСТРУКТУРА','Ликвидность и исполненные сделки');
   liquidity.replaceChildren();heading(liquidity,'BYBIT / ПОТОК МОДЕЛИ B','Активность стакана · '+selected);line(liquidity,'Монета выбирается в «Обзоре». Зелёный — покупатели; красный — продавцы.');
   for(const target of [pulse,liquidity]){if(!current){line(target,'Нет свежего стакана. Объёмы и активность скрыты.','negative');continue;}
    const grid=make('div','micro-grid'),book=make('div'),flow=make('div');book.append(make('h3','','Видимые заявки в зонах'));for(const band of bookRows(r)){meter(book,band.label,band.bid,band.ask,band.share);if(!band.covered)line(book,band.label+' — зона покрыта не полностью либо нет данных.');}
    flow.append(make('h3','','Лента исполнений'));if(!r.ready)line(flow,'Поток ещё не готов: прогрев или нет свежих сделок.','negative');line(flow,'Возраст последней сделки: '+fmt(r.trade_age+now-b.updated,1)+' с.');for(const f of flowRows(r)){meter(flow,f.seconds+' сек. · '+fmt(f.count,0)+' сделок',f.buy,f.sell,f.share);line(flow,'Дельта '+fmt(f.delta,0)+' USDT',f.delta<0?'negative':'positive');}grid.append(book,flow);target.append(grid);
    line(target,'Зоны стакана вложены друг в друга: их объёмы не складываются. Окна ленты скользящие: их дельты не являются накопленной CVD.');
   }
   if(current){line(liquidity,'OFI за 5 / 15 / 60 сек.: '+[r.ofi5,r.ofi15,r.ofi60].map(v=>fmt(v,0)).join(' / ')+' · в единицах контракта.');line(liquidity,'Заявки могут быть отменены. Уменьшение глубины не доказывает исполнение или спуфинг.');}
   const sampled=samples.get(selected)||[];graph(liquidity,sampled.map(x=>x.price),'Mid-price · до 120 снимков этой сессии, не свечи');graph(liquidity,sampled.map(x=>x.spread),'Спред, % · до 120 снимков этой сессии');
   if(!current&&sampled.length)line(liquidity,'Графики показывают прошлые наблюдения, текущий поток недоступен.','negative');
   modelCharts.replaceChildren();heading(modelCharts,'РЕЗУЛЬТАТ ПОСЛЕ ИЗДЕРЖЕК','Модели и журнал');
   if(report&&fresh(report.updated,now,180)){const table=make('table'),thead=make('thead'),tr=make('tr');for(const t of ['Модель','Сделки','Net, USDT','Средняя','PF'])tr.append(make('th','',t));thead.append(tr);table.append(thead);const body=make('tbody');for(const name of ['A','B']){const s=report.models?.[name];if(!s)continue;const tr=make('tr');for(const v of [name,fmt(s.count,0),fmt(s.net,4),fmt(s.average,4),fmt(s.profit_factor,2)])tr.append(make('td','',v));body.append(tr);}table.append(body);const scroll=make('div','scroll');scroll.append(table);modelCharts.append(scroll);line(modelCharts,'Общий период: '+new Date(report.start*1000).toLocaleString('ru-RU')+' — '+new Date(report.end*1000).toLocaleString('ru-RU')+'.');if(report.status!=='ok')line(modelCharts,'Отчёт неполный: '+(report.errors||[]).join('; '),'negative');
   }else line(modelCharts,'Сравнительный отчёт недоступен или устарел.','negative');
   const curves=make('div','micro-grid');for(const name of ['A','B']){const j=journals[name];const box=make('div');if(j){const trades=[...(j.rows||[])].filter(t=>numeric(t.net)&&numeric(t.closed)).sort((x,y)=>x.closed-y.closed);let sum=0;const vals=[0,...trades.map(t=>sum+=t.net)];graph(box,vals,'Модель '+name+' · сумма net по '+trades.length+' последним записям');if(!fresh(j.updated,now,180))line(box,'Снимок журнала устарел.','negative');}else line(box,'Журнал '+name+' недоступен.');curves.append(box);}modelCharts.append(curves);line(modelCharts,'Кривые начинаются с нуля для показанных записей, не отражают полный капитал и открытые позиции. Это PAPER-результаты; малое число сделок не подтверждает преимущество.');
  }
  async function poll(){try{const res=await labFetch('/api/model-b');if(!res.ok)throw Error('HTTP '+res.status);b=await res.json();error='';const now=Date.now()/1000;for(const r of b.observations||[]){if(b.phase!=='running'||!fresh(b.updated,now,8)||!fresh(r.time,now,3)||!numeric(r.price)||!numeric(r.spread)||lastSample.get(r.symbol)===r.time)continue;const previous=lastSample.get(r.symbol);const arr=previous&&r.time-previous>6?[]:samples.get(r.symbol)||[];arr.push({time:r.time,price:r.price,spread:r.spread});samples.set(r.symbol,arr.slice(-120));lastSample.set(r.symbol,r.time);}}catch(e){b=null;error='Поток недоступен';}render();setTimeout(poll,2000);}
  async function slow(){const paths=['/api/paper','/api/lab-report','/api/journal-a','/api/journal-b'];const results=await Promise.allSettled(paths.map(async p=>{const r=await labFetch(p);if(!r.ok)throw Error();return r.json();}));a=results[0].status==='fulfilled'?results[0].value:null;report=results[1].status==='fulfilled'?results[1].value:null;for(let i=2;i<4;i++)journals[i===2?'A':'B']=results[i].status==='fulfilled'?results[i].value:null;render();setTimeout(slow,10000);}
  document.addEventListener('lab-symbol',e=>{if((b?.observations||[]).some(r=>r.symbol===e.detail)){selected=e.detail;select.value=selected;chooseChart();render();document.querySelector('[aria-controls="page-overview"]').click();}});
  setInterval(render,1000);poll();slow();chooseChart();
 });
})(typeof window==='undefined'?globalThis:window);
