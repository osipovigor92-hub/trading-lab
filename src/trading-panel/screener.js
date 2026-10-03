(function(scope){
 'use strict';
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const fresh=(t,now,limit)=>finite(t)&&now-t>=-2&&now-t<=limit;
 const safeSymbol=s=>typeof s==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(s);
 const fmt=(v,n=2)=>finite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
 function filterRows(rows,{search='',preset='all',sort='turnover',minimum=0,bots=new Set()}={}){
  const allowed=rows.filter(r=>safeSymbol(r.symbol)&&finite(r.turnover)&&r.turnover>=minimum&&r.symbol.includes(search.toUpperCase())&&(
   preset==='all'||preset==='active'&&r.range24>=3&&r.turnover>=2e7&&r.spread<=.03||
   preset==='liquid'&&r.turnover>=5e7&&r.spread<=.02||preset==='up'&&r.change>=3||
   preset==='down'&&r.change<=-3||preset==='bots'&&bots.has(r.symbol)));
  const key=['turnover','range24','spread','change'].includes(sort)?sort:'turnover';
  return allowed.sort((a,b)=>(key==='spread'?1:-1)*(a[key]-b[key])||a.symbol.localeCompare(b.symbol));
 }
 function botModels(a,b,cd){
  return {A:a,B:b,C:cd?.models?.C?{...cd.models.C,updated:cd.updated}:null,D:cd?.models?.D?{...cd.models.D,updated:cd.updated}:null};
 }
 function positionView(s,now){
  const p=s?.position;
  if(!p||!safeSymbol(p.symbol)||![1,-1].includes(p.side)||!finite(p.quantity)||!finite(p.entry)||p.quantity<=0||p.entry<=0)return null;
  return {symbol:p.symbol,side:p.side===1?'LONG':p.side===-1?'SHORT':p.side,entry:p.entry,
   notional:p.quantity*p.entry,opened:p.opened,current:s.phase==='running'&&fresh(s.updated,now,8)};
 }
 function domain(bars){
  const low=Math.min(...bars.map(b=>b.low)),high=Math.max(...bars.map(b=>b.high));
  const padding=Math.max((high-low)*.08,high*.0005);
  return {low:low-padding,high:high+padding};
 }
 const api={fresh,filterRows,botModels,positionView,domain};
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 scope.LabScreener=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-market');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const line=(p,t,c='muted')=>p.append(el('p',c,t));
  const old=el('details','box archive-details');old.append(el('summary','','Подробный Grid / скальпинг-отбор'));while(page.firstChild)old.append(page.firstChild);page.append(old);
  const root=el('section','screener-workspace');root.id='crypto-screener';page.prepend(root);
  const hero=el('section','box screener-head');hero.append(el('small','eyebrow','BYBIT / USDT PERPETUAL'),el('h2','','Скринер криптовалют'));
  line(hero,'Оборот, колебания и ликвидность. Выбери монету: уровни, стакан и позиции ботов появятся ниже.');root.append(hero);
  const status=el('p','muted','Загрузка публичных данных Bybit…');status.id='screener-status';hero.append(status);
  const controls=el('div','screener-controls');
  const field=(name,node)=>{const label=el('label','',name);label.append(node);controls.append(label);return node;};
  const search=field('Монета',el('input'));search.type='search';search.placeholder='BTC, SOL, ONDO…';search.setAttribute('aria-label','Поиск монеты');
  const select=(label,items)=>{const node=el('select');node.setAttribute('aria-label',label);for(const [value,text]of items){const o=el('option','',text);o.value=value;node.append(o);}return field(label,node);};
  const preset=select('Подборка',[['all','Все монеты'],['active','Активные и ликвидные'],['liquid','Узкий спред'],['up','Растут ≥ 3%'],['down','Падают ≥ 3%'],['bots','Монеты ботов']]);
  const sorting=select('Сортировка',[['turnover','Оборот ↓'],['range24','Диапазон ↓'],['spread','Спред ↑'],['change','Рост цены ↓']]);
  const minimum=select('Оборот от',[['0','Любой'],['10000000','10 млн USDT'],['50000000','50 млн USDT'],['100000000','100 млн USDT']]);hero.append(controls);
  const counter=el('p','muted'),scroll=el('div','scroll screener-scroll'),table=el('table','screener-table');table.id='screener-table';
  const head=el('thead'),tr=el('tr');for(const name of ['Монета / боты','Цена, USDT','24 ч','Оборот 24 ч','Диапазон 24 ч','Спред'])tr.append(el('th','',name));head.append(tr);
  const tbody=el('tbody');table.append(head,tbody);scroll.append(table);hero.append(counter,scroll);
  line(hero,'«Активные»: диапазон суток ≥ 3%, оборот ≥ 20 млн USDT, спред ≤ 0,03%. Диапазон суток — не минутный ATR. Подборки описывают рынок и не дают сигнал входа.');
  const panel=el('section','box screener-detail');panel.id='screener-detail';root.append(panel);
  const toolbar=el('div','screener-detail-toolbar'),title=el('h2','','BTCUSDT');
  const timeframe=el('select');timeframe.setAttribute('aria-label','Таймфрейм уровней');for(const [v,t]of [['1','1 мин'],['5','5 мин'],['15','15 мин'],['60','1 час']]){const o=el('option','',t);o.value=v;timeframe.append(o);}timeframe.value='5';
  const external=el('a','text-link','TradingView ↗');external.target='_blank';external.rel='noopener noreferrer';
  const overview=el('button','primary-button','В обзор');overview.type='button';toolbar.append(title,timeframe,external,overview);panel.append(toolbar);
  const chartStatus=el('p','muted'),metrics=el('div','terminal-metrics'),chartHost=el('div','screener-chart');chartHost.id='screener-candles';
  panel.append(chartStatus,metrics,chartHost);line(panel,'Закрытые свечи Bybit · объём исполнений в USDT. Зелёные зоны — поддержка, красные — сопротивление, голубая линия — VWAP последних 60 свечей.');
  const levelsBox=el('div','screener-levels');levelsBox.id='screener-levels';panel.append(levelsBox);
  const explanation=el('details','screener-method');explanation.append(el('summary','','Как рассчитываются уровни'));
  line(explanation,'Берём до 180 закрытых свечей выбранного таймфрейма. Экстремум подтверждается двумя свечами слева и двумя справа: последние два бара ещё не могут стать новым уровнем. Близкие экстремумы объединяются в зоны шириной до max(0,05% цены; 0,25 ATR).');
  line(explanation,'Показаны три ближайшие зоны ниже и выше последней цены закрытия. Число экстремумов — описание прошлого, не вероятность отскока. Роль зоны определяется относительно последнего закрытия; удержание или будущий пробой не подтверждены. На графике видны последние 90 свечей, на телефоне — 45, и уровни в их ценовом масштабе.');panel.append(explanation);
  const bookBox=el('section','box');bookBox.id='screener-orderbook';root.append(bookBox);
  const botsBox=el('section','box');botsBox.id='screener-bots';root.append(botsBox);
  let snapshot=null,chart=null,book=null,models={},bState=null,selected='BTCUSDT',generation=0,tickerError='',chartError='',bookError='';
  let previousBook=null,bookChange=null,tableSignature='',chartSignature='';
  const visible=()=>!document.hidden&&!page.hidden;
  const svgNode=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
  function addText(svg,x,y,text,cls){const n=svgNode('text',{x,y,class:cls||'chart-axis'});n.textContent=text;svg.append(n);}
  function drawChart(data){
   chartHost.replaceChildren();const widthPixels=Math.max(300,Math.round(chartHost.clientWidth-20)),right=widthPixels-86,mobile=widthPixels<560;
   const bars=data.candles.slice(mobile?-45:-90),d=domain(bars),svg=svgNode('svg',{viewBox:'0 0 '+widthPixels+' 390',role:'img','aria-label':selected+' · свечи, поддержка, сопротивление и оборот USDT'});
   const x=i=>18+i*(right-30)/Math.max(1,bars.length-1),y=p=>24+(d.high-p)/(d.high-d.low)*214;
   for(let i=0;i<=4;i++){const price=d.low+(d.high-d.low)*i/4,yp=y(price);svg.append(svgNode('line',{x1:12,x2:right,y1:yp,y2:yp,class:'chart-grid'}));addText(svg,right+6,yp+4,fmt(price,8));}
   const labels=[];
   for(const level of data.levels){if(level.price<d.low||level.price>d.high)continue;const yp=y(level.price),height=Math.max(2,Math.abs(y(level.low)-y(level.high)));svg.append(svgNode('rect',{x:12,y:yp-height/2,width:right-12,height,class:'zone-'+level.side}));svg.append(svgNode('line',{x1:12,x2:right,y1:yp,y2:yp,class:'line-'+level.side}));if(labels.every(p=>Math.abs(p-yp)>14)){addText(svg,24,yp-5,(level.side==='support'?'S':'R')+' · '+fmt(level.price,8),'label-'+level.side);labels.push(yp);}}
   if(finite(data.vwap)&&data.vwap>=d.low&&data.vwap<=d.high){const yp=y(data.vwap);svg.append(svgNode('line',{x1:12,x2:right,y1:yp,y2:yp,class:'line-vwap'}));addText(svg,16,252,'VWAP '+fmt(data.vwap,8),'label-vwap');}
   for(const [id,s]of Object.entries(models)){const p=positionView(s,Date.now()/1000);if(!p?.current||p.symbol!==selected||p.entry<d.low||p.entry>d.high)continue;const yp=y(p.entry);svg.append(svgNode('line',{x1:12,x2:right,y1:yp,y2:yp,class:'line-entry'}));if(labels.every(l=>Math.abs(l-yp)>14)){addText(svg,24,yp-5,'Вход '+id+' '+p.side+' '+fmt(p.entry,8),'label-entry');labels.push(yp);}}
   const width=Math.max(1,Math.min(9,(right-30)/Math.max(1,bars.length-1)*.72)),maxVolume=Math.max(1,...bars.map(b=>b.turnover));
   for(const [i,b]of bars.entries()){const cls=b.close>=b.open?'candle-up':'candle-down',xp=x(i);svg.append(svgNode('line',{x1:xp,x2:xp,y1:y(b.high),y2:y(b.low),class:cls}));svg.append(svgNode('rect',{x:xp-width/2,y:Math.min(y(b.open),y(b.close)),width,height:Math.max(1,Math.abs(y(b.open)-y(b.close))),class:cls}));svg.append(svgNode('rect',{x:xp-width/2,y:345-b.turnover/maxVolume*70,width,height:Math.max(0,b.turnover/maxVolume*70),class:cls+' volume-bar'}));}
   addText(svg,16,268,'Оборот свечи · USDT');addText(svg,right+6,292,fmt(maxVolume,0));
   for(const i of [0,Math.floor(bars.length/3),Math.floor(bars.length*2/3),bars.length-1])addText(svg,Math.max(12,x(i)-18),375,new Date(bars[i].time*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}));
   chartHost.append(svg);
  }
  function renderTable(now){
   const usable=snapshot?.status==='ok'&&fresh(snapshot.updated,now,45);
   status.textContent=tickerError||(!snapshot||snapshot.status==='pending'?'Получаем список контрактов…':snapshot.status!=='ok'?'Bybit недоступен: '+(snapshot.error||'ошибка данных'):!usable?'СКРИНЕР УСТАРЕЛ · текущие цены скрыты':'Снимок '+new Date(snapshot.updated*1000).toLocaleTimeString('ru-RU')+' · возраст '+fmt(now-snapshot.updated,0)+' с · до 100 пар по обороту');status.className=usable?'muted':'negative';
   if(!usable){tbody.replaceChildren();tableSignature='';counter.textContent='Публичные данные недоступны. Состояние PAPER-моделей показано отдельно.';return;}
   const coins=new Set();for(const s of Object.values(models)){const p=positionView(s,now);if(p?.current)coins.add(p.symbol);}if(bState?.phase==='running'&&fresh(bState.updated,now,8))for(const r of bState.observations||[])coins.add(r.symbol);
   const signature=[snapshot.updated,search.value,preset.value,sorting.value,minimum.value,selected,...Object.entries(models).map(([id,s])=>id+JSON.stringify(positionView(s,now))),...coins].join('|');
   if(signature===tableSignature)return;tableSignature=signature;tbody.replaceChildren();
   const rows=filterRows(snapshot.rows,{search:search.value,preset:preset.value,sort:sorting.value,minimum:Number(minimum.value),bots:coins});
   counter.textContent='Показано '+rows.length+' / '+snapshot.rows.length+' · валидных USDT-контрактов '+snapshot.eligible+(snapshot.rejected?' · исключено некорректных '+snapshot.rejected:'');
   if(!rows.length){const tr=el('tr'),td=el('td','','Монет с выбранными условиями нет.');td.colSpan=6;tr.append(td);tbody.append(tr);}
   for(const r of rows){const tr=el('tr',r.symbol===selected?'selected-coin':''),td=el('td'),button=el('button','coin-button',r.symbol);button.type='button';button.setAttribute('aria-pressed',String(selected===r.symbol));button.addEventListener('click',()=>choose(r.symbol));td.append(button);
    const badges=el('div','coin-tags');for(const [id,s]of Object.entries(models)){const p=positionView(s,now);if(p?.symbol===r.symbol&&p.current)badges.append(el('span','coin-tag '+(p.side==='LONG'?'tag-long':'tag-short'),id+' '+p.side));}if((bState?.observations||[]).some(o=>o.symbol===r.symbol)&&bState.phase==='running'&&fresh(bState.updated,now,8))badges.append(el('span','coin-tag','B/C/D наблюдают'));td.append(badges);
    const mobileFacts=el('div','coin-mobile-facts');mobileFacts.append(el('span','','Оборот '+fmt(r.turnover/1e6,1)+' млн USDT'),el('span','','Диапазон '+fmt(r.range24)+'%'),el('span','','Спред '+fmt(r.spread,4)+'%'));td.append(mobileFacts);tr.append(td);
    for(const [text,cls]of [[fmt(r.price,8),''],[(r.change>0?'+':'')+fmt(r.change)+'%',r.change>=0?'positive':'negative'],[fmt(r.turnover/1e6,1)+' млн',''],[fmt(r.range24)+'%',''],[fmt(r.spread,4)+'%',r.spread>.03?'negative':'']])tr.append(el('td',cls,text));tbody.append(tr);
   }
  }
  function renderLevels(now){
   title.textContent=selected;external.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BYBIT:'+selected+'.P');
   const step=Number(timeframe.value)*60,usable=chart?.symbol===selected&&chart.interval===timeframe.value&&chart.status==='ok'&&fresh(chart.updated,now,75)&&fresh(chart.candle_end,now,step+75);
   metrics.replaceChildren();levelsBox.replaceChildren();chartStatus.textContent=chartError||(!chart||chart.status==='pending'?'Загрузка закрытых свечей…':chart.status!=='ok'?'Свечи недоступны: '+(chart.error||'ошибка'):!usable?'СВЕЧИ УСТАРЕЛИ · уровни скрыты':'Закрытие '+new Date(chart.candle_end*1000).toLocaleString('ru-RU')+' · '+chart.candles.length+' закрытых свечей');chartStatus.className=usable?'muted':'negative';
   if(!usable){chartSignature='';chartHost.replaceChildren(el('p','muted','Ожидание свежего анализа.'));return;}
   for(const [key,value]of [['Последнее закрытие',fmt(chart.price,8)],['ATR(14)',fmt(chart.atr_pct,3)+'%'],['RVOL · 5 / 20 свечей',fmt(chart.rvol)+'×'],['Оборот 60 свечей',fmt(chart.turnover_window/1e6,2)+' млн USDT']]){const cell=el('div');cell.append(el('span','muted',key),el('b','',value));metrics.append(cell);}
   const signature=selected+'|'+timeframe.value+'|'+chart.updated+'|'+chartHost.clientWidth+'|'+Object.entries(models).map(([id,s])=>id+JSON.stringify(positionView(s,now))).join('|');if(signature!==chartSignature){drawChart(chart);chartSignature=signature;}
   for(const [side,label]of [['support','Поддержка'],['resistance','Сопротивление']]){const section=el('div','level-group '+side);section.append(el('h3','',label));const levels=chart.levels.filter(l=>l.side===side);if(!levels.length)line(section,'Подтверждённых зон в истории нет.');for(const l of levels){const row=el('div','level-item');row.append(el('b','',fmt(l.price,8)+' USDT'),el('span','muted',fmt(l.distance_pct,2)+'% от закрытия · экстремумов '+l.pivots));section.append(row);}levelsBox.append(section);}
  }
  function renderBook(now){
   bookBox.replaceChildren(el('small','eyebrow','REST / ВИДИМЫЕ ЗАЯВКИ'),el('h2','','Стакан · '+selected));
   const usable=book?.symbol===selected&&book.status==='ok'&&fresh(book.updated,now,8);
   if(!usable){line(bookBox,bookError||(!book||book.status==='pending'?'Ожидание снимка стакана…':book.status!=='ok'?'Стакан недоступен: '+book.error:'СТАКАН УСТАРЕЛ · объёмы скрыты'),'negative');return;}
   line(bookBox,'Mid '+fmt(book.mid,8)+' USDT · спред '+fmt(book.spread,4)+'% · возраст '+fmt(now-book.updated,1)+' с. Это периодический снимок, не полный поток изменений.');
   const bands=el('div','book-bands');for(const [key,b]of Object.entries(book.bands)){const cell=el('div','book-band');cell.append(el('b','','±'+fmt(Number(key)*100,2)+'%'),el('span','positive','Bid '+fmt(b.bid,0)+' USDT'),el('span','negative','Ask '+fmt(b.ask,0)+' USDT'));
    const meter=svgNode('svg',{viewBox:'0 0 100 8','aria-label':'Объёмы bid и ask',role:'img'}),share=b.bid+b.ask?b.bid/(b.bid+b.ask):.5;meter.append(svgNode('rect',{width:share*100,height:8,class:'meter-buy'}),svgNode('rect',{x:share*100,width:(1-share)*100,height:8,class:'meter-sell'}));cell.append(meter);if(!b.covered)cell.append(el('small','muted','Зона не покрыта: нижняя оценка'));bands.append(cell);}bookBox.append(bands);
   if(bookChange&&fresh(bookChange.time,now,8))line(bookBox,'Изменение видимой глубины ±0,1% за '+fmt(bookChange.seconds,1)+' с: bid '+fmt(bookChange.bid,0)+' / ask '+fmt(bookChange.ask,0)+' USDT. Включает выставление, отмены, исполнения и сдвиг зоны.');
   const walls=el('div','screener-levels');for(const [side,rows]of Object.entries(book.walls)){const group=el('div','level-group '+(side==='bid'?'support':'resistance'));group.append(el('h3','',(side==='bid'?'Покупки':'Продажи')+' · крупные уровни'));if(!rows.length)line(group,'В зоне ±0,1% нет уровней.');for(const w of rows){const row=el('div','level-item');row.append(el('b','',fmt(w.price,8)),el('span','muted',fmt(w.notional,0)+' USDT'));group.append(row);}walls.append(group);}bookBox.append(walls);
   line(bookBox,'Объём — сумма заявок по одной цене, не отдельный участник. Крупный уровень стакана не подтверждает поддержку на графике. Зоны вложены: их объёмы не складываются.');
   const r=bState?.observations?.find(r=>r.symbol===selected);if(bState?.phase==='running'&&fresh(bState.updated,now,8)&&fresh(r?.time,now,3)&&r.ready){const f=r.flow60;if(finite(f?.buy)&&finite(f?.sell))line(bookBox,'Исполнено за скользящие 60 с потока B: покупки '+fmt(f.buy,0)+' / продажи '+fmt(f.sell,0)+' USDT · сделок '+fmt(f.count,0)+'.');}
  }
  function renderBots(now){
   botsBox.replaceChildren(el('small','eyebrow','A / B / C / D · PAPER'),el('h2','','Активность торговых ботов'));
   const grid=el('div','screener-bot-grid');for(const id of ['A','B','C','D']){const s=models[id],p=positionView(s,now),active=s&&fresh(s.updated,now,8),card=el('article','screener-bot');
    card.append(el('h3','','Модель '+id),el('small',active&&s.phase==='running'?'positive':'muted',!s?'Нет отчёта / не установлена':!active?'Отчёт устарел':s.phase==='running'?'Работает':s.phase==='halted'?'Остановлена':'Ожидает данных'));
    if(p){line(card,p.symbol+' · '+p.side,p.current?(p.side==='LONG'?'positive':'negative'):'muted');line(card,'Номинал входа '+fmt(p.notional,2)+' USDT · цена '+fmt(p.entry,8));if(!p.current)line(card,'Последняя сохранённая позиция: текущая оценка недоступна.','negative');}
    else line(card,'Открытой позиции нет.');
    if(s?.reason)line(card,s.reason);
    const trades=id==='A'?s?.journal_trades:s?.trades;const last=Array.isArray(trades)?[...trades].sort((a,b)=>b.closed-a.closed)[0]:null;
    if(last)line(card,'Закрытие '+last.symbol+' · '+new Date(last.closed*1000).toLocaleTimeString('ru-RU')+' · net '+fmt(last.net,4)+' USDT');
    grid.append(card);
   }botsBox.append(grid);line(botsBox,'Номинал позиции бота, исполненный объём свечей и видимые заявки стакана — разные величины. Список скринера не переключает монеты и правила моделей. Grid-бот показан во вкладке Grid.');
  }
  function render(){if(!visible())return;const now=Date.now()/1000;renderTable(now);renderLevels(now);renderBook(now);renderBots(now);}
  function choose(symbol){if(!safeSymbol(symbol))return;selected=symbol;chart=null;book=null;previousBook=null;bookChange=null;generation++;chartError='';bookError='';render();detailPoll();}
  for(const control of [search,preset,sorting,minimum])control.addEventListener(control===search?'input':'change',()=>renderTable(Date.now()/1000));
  timeframe.addEventListener('change',()=>choose(selected));overview.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('lab-symbol',{detail:selected})));
  async function get(path){const r=await labFetch(path);if(!r.ok)throw Error('HTTP '+r.status);return r.json();}
  async function listPoll(){if(visible()){try{snapshot=await get('/api/screener');tickerError='';}catch{snapshot=null;tickerError='Нет связи со скринером Bybit';}render();}setTimeout(listPoll,5000);}
  let detailBusy=false;
  async function detailPoll(){if(!visible()||detailBusy)return;detailBusy=true;const current=generation,coin=selected,tf=timeframe.value;
   try{const result=await Promise.allSettled([get('/api/market-chart?symbol='+encodeURIComponent(coin)+'&interval='+tf),get('/api/market-book?symbol='+encodeURIComponent(coin))]);
    if(current!==generation)return;
    if(result[0].status==='fulfilled'){chart=result[0].value;chartError='';}else{chart=null;chartError='Свечи недоступны';}
    if(result[1].status==='fulfilled'){book=result[1].value;bookError='';if(book.status==='ok'&&book.symbol===coin&&previousBook&&book.updated>previousBook.updated&&book.updated-previousBook.updated<=12){const a=previousBook.bands['0.001'],b=book.bands['0.001'];bookChange={time:book.updated,seconds:book.updated-previousBook.updated,bid:b.bid-a.bid,ask:b.ask-a.ask};}if(book.status==='ok')previousBook=book;}else{book=null;bookError='Стакан недоступен';previousBook=null;bookChange=null;}render();
   }finally{detailBusy=false;if(current!==generation&&visible())detailPoll();}
  }
  async function botPoll(){if(visible()){const result=await Promise.allSettled(['/api/paper','/api/model-b','/api/research'].map(get));const states=result.map(r=>r.status==='fulfilled'?r.value:null);models=botModels(...states);bState=states[1];render();}setTimeout(botPoll,2000);}
  document.addEventListener('lab-tab',e=>{if(e.detail==='market')setTimeout(()=>{render();detailPoll();},0);});
  document.addEventListener('visibilitychange',()=>{if(visible()){render();detailPoll();}});
  setInterval(()=>{render();detailPoll();},4000);setInterval(()=>{if(visible()){renderTable(Date.now()/1000);renderBook(Date.now()/1000);}},1000);
  listPoll();botPoll();detailPoll();render();
 });
})(typeof window==='undefined'?globalThis:window);
