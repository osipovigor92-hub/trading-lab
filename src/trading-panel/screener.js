/* The approved screener layout; all numbers come from the existing public feeds. */
(function(scope){
 'use strict';
 const finite=x=>typeof x==='number'&&Number.isFinite(x);
 const fresh=(t,now,limit)=>finite(t)&&now-t>=-2&&now-t<=limit;
 const safeSymbol=s=>typeof s==='string'&&/^[A-Z0-9]{2,24}USDT$/.test(s);
 const fmt=(v,n=2)=>finite(v)?v.toLocaleString('ru-RU',{maximumFractionDigits:n}):'—';
 const clamp=(value,low=0,high=1)=>Math.min(high,Math.max(low,value));
 function ratingScore(row){const r=row?.rating;return r?.status==='ok'&&Number.isInteger(r.score)&&r.score>=0&&r.score<=100?r.score:null;}
 function filterRows(rows,{search='',preset='all',sort='turnover',minimum=0,bots=new Set(),favorites=new Set(),dir=''}={}){
  const allowed=rows.map(r=>({...r,quality:ratingScore(r)})).filter(r=>safeSymbol(r.symbol)&&finite(r.turnover)&&r.turnover>=minimum&&r.symbol.includes(search.toUpperCase())&&(
   preset==='all'||preset==='active'&&r.range24>=3&&r.turnover>=2e7&&r.spread<=.03||
   preset==='liquid'&&r.turnover>=5e7&&r.spread<=.02||preset==='up'&&r.change>=3||
   preset==='down'&&r.change<=-3||preset==='bots'&&bots.has(r.symbol)||preset==='favorites'&&favorites.has(r.symbol)));
  const key=['quality','turnover','range24','spread','change'].includes(sort)?sort:'turnover';
  const sign=(key==='spread'?1:-1)*(dir==='asc'?-1:1);
  const group=r=>({passed:0,pending:1,rejected:2}[r.selection?.status]??1);
  return allowed.sort((a,b)=>key==='quality'?(group(a)-group(b)||(finite(a.quality)!==finite(b.quality)?finite(a.quality)?-1:1:finite(a.quality)?sign*(a.quality-b.quality):0)||b.turnover-a.turnover||a.symbol.localeCompare(b.symbol)):sign*(a[key]-b[key])||a.symbol.localeCompare(b.symbol));
 }
 function stableRows(rows,order=[]){
  const ranks=new Map(order.map((s,i)=>[s,i]));
  return rows.map((row,i)=>({row,index:ranks.has(row.symbol)?ranks.get(row.symbol):order.length+i})).sort((a,b)=>a.index-b.index).map(x=>x.row);
 }
 function botModels(a,b,cd){return {A:a,B:b,C:cd?.models?.C?{...cd.models.C,updated:cd.updated}:null,D:cd?.models?.D?{...cd.models.D,updated:cd.updated}:null};}
 function positionView(s,now){
  const p=s?.position;
  if(!p||!safeSymbol(p.symbol)||![1,-1].includes(p.side)||!finite(p.quantity)||!finite(p.entry)||p.quantity<=0||p.entry<=0)return null;
  return {symbol:p.symbol,side:p.side===1?'LONG':'SHORT',entry:p.entry,notional:p.quantity*p.entry,opened:p.opened,current:['running','draining'].includes(s.phase)&&fresh(s.updated,now,8)};
 }
 function domain(bars){const low=Math.min(...bars.map(b=>b.low)),high=Math.max(...bars.map(b=>b.high)),padding=Math.max((high-low)*.08,high*.0005);return {low:low-padding,high:high+padding};}
 function barCount(width,scale,total){const base=width<560?45:90,safe=finite(scale)?Math.min(8,Math.max(.3,scale)):1;return Math.min(total,Math.max(20,Math.round(base/safe)));}
 function chartBars(bars,width,scale=1,offset=0){const count=barCount(width,scale,bars.length),back=Math.max(0,Math.min(bars.length-count,Math.round(finite(offset)?offset:0)));return bars.slice(bars.length-count-back,bars.length-back);}
 const selectionDefaults={turnover_min:2e7,spread_max:.03,range_min:1,range_max:30,atr_min:.08,atr_max:.8,rvol_min:1,oi_min:1e6,funding_max:.05,depth_min:5000,impact_max:.05};
 const selectionLimits={turnover_min:1e13,spread_max:10,range_min:1000,range_max:1000,atr_min:100,atr_max:100,rvol_min:1000,oi_min:1e13,funding_max:100,depth_min:1e12,impact_max:100};
 function validateSelection(values){
  if(!values||typeof values!=='object'||Array.isArray(values)||Object.keys(values).some(k=>!(k in selectionDefaults)))throw Error('Неизвестный фильтр');
  const out={...selectionDefaults};for(const [key,value]of Object.entries(values)){if(!finite(value)||value<0||value>selectionLimits[key])throw Error('Проверьте числовые пороги');out[key]=value;}
  if(out.range_min>out.range_max||out.atr_min>out.atr_max)throw Error('Минимум диапазона или ATR превышает максимум');return out;
 }
 function selectionView(verdict,sourceTime,tickerTime,now){
  const waiting=note=>({status:'pending',checks:[],samples:0,note});
  if(!verdict||sourceTime!==tickerTime||!fresh(sourceTime,now,45))return waiting('Ожидание проверки свежих котировок');
  if(!['passed','pending','rejected'].includes(verdict.status)||!Array.isArray(verdict.checks))return waiting('Ожидание корректных данных отбора');
  if(verdict.status==='passed'&&(verdict.samples!==5||verdict.checks.length!==12||verdict.checks.some(c=>c.state!=='pass')||!fresh(verdict.chart_time,now,75)||!fresh(verdict.candle_end,now,120)||!fresh(verdict.book_time,now,12)))return waiting('Данные проверки устарели · повторяем анализ');
  return verdict;
 }
 function ratingView(verdict,now){
  const waiting=note=>({status:'pending',score:null,components:[],note});
  const rating=verdict?.rating,keys=['liquidity','spread','volume','book'];
  if(!rating||rating.version!==1||!Array.isArray(rating.components)||rating.components.length!==4)return waiting(verdict?.note||'Ожидаем данные рейтинга');
  if(rating.components.some(c=>!c||!keys.includes(c.key)||c.maximum!==25||(c.points!==null&&(!Number.isInteger(c.points)||c.points<0||c.points>25)))||new Set(rating.components.map(c=>c.key)).size!==4)return waiting('Ожидаем корректный рейтинг');
  const ticker=fresh(verdict.ticker_time,now,45),chart=fresh(verdict.chart_time,now,75)&&fresh(verdict.candle_end,now,120),book=verdict.samples===5&&fresh(verdict.book_time,now,12)&&verdict.checks?.some(c=>c.key==='coverage'&&c.value===true);
  const parts=rating.components.map(c=>{const valid=c.key==='liquidity'?ticker:c.key==='volume'?chart:c.key==='spread'?ticker&&book:book;return valid?c:{...c,points:null,values:{},label:'Ожидаем свежие данные: '+c.name};});
  const checkKeys=['turnover','spread','range','oi','funding','volume24','atr','rvol','depth','book_spread','impact','coverage'];
  const known=verdict.checks?.length===12&&verdict.checks.every(c=>c&&checkKeys.includes(c.key)&&['pass','fail'].includes(c.state)&&(c.key==='coverage'?c.value===true:finite(c.value)&&c.value>=0))&&new Set(verdict.checks.map(c=>c.key)).size===12;
  const complete=ticker&&chart&&book&&known&&rating.status==='ok'&&Number.isInteger(rating.score)&&rating.score>=0&&rating.score<=100&&parts.every(c=>c.points!==null)&&parts.reduce((total,c)=>total+c.points,0)===rating.score;
  return {...rating,components:parts,status:complete?'ok':'pending',score:complete?rating.score:null,note:complete?rating.note:rating.status==='ok'?'Рейтинг не подтверждён · повторяем проверку':rating.note};
 }
 function coinCardView({snapshot,chart,book,symbol,interval,now,tickerError='',chartError='',bookError=''}){
  const state=(data,identity,timely,error)=>{
   const stamp=identity&&finite(data?.updated)?data.updated:null,age=stamp===null?null:Math.max(0,now-stamp);
   const status=!data||data.status==='pending'?(error?'error':'pending'):data.status!=='ok'||!identity?'error':!timely?'stale':error||data.refresh_error?'cached':'fresh';
   return {status,stamp,age,available:['fresh','cached'].includes(status),note:String(error||data?.refresh_error||data?.error||(!identity&&data?.status==='ok'?'Ответ источника не соответствует выбранной монете или неполный':'')).slice(0,120)};
  };
  const quote=Array.isArray(snapshot?.rows)?snapshot.rows.find(r=>r.symbol===symbol):null;
  const ticker=state(snapshot,true,fresh(snapshot?.updated,now,45),tickerError);
  if(ticker.available&&!quote)Object.assign(ticker,{status:'missing',available:false,note:'Монета отсутствует в текущей подборке котировок'});
  const candle=state(chart,chart?.symbol===symbol&&chart.interval===interval&&Array.isArray(chart.candles)&&chart.candles.length>=25,
   fresh(chart?.updated,now,75)&&['1','5','15','60'].includes(interval)&&fresh(chart?.candle_end,now,Number(interval)*60+75),chartError);
  const near=book?.bands?.['0.001'],depth=state(book,book?.symbol===symbol&&finite(book.mid)&&book.mid>0&&finite(book.spread)&&near&&finite(near.bid)&&finite(near.ask),fresh(book?.updated,now,8),bookError);
  if(depth.available&&!near.covered)depth.note='Зона ±0,1% покрыта частично · объёмы являются нижней оценкой';
  const nonnegative=v=>finite(v)&&v>=0?v:null;
  return {sources:{ticker,chart:candle,book:depth},
   quote:ticker.available?{price:finite(quote.price)&&quote.price>0?quote.price:null,change:finite(quote.change)?quote.change:null,turnover:nonnegative(quote.turnover),oi:nonnegative(quote.open_interest),funding_pct:finite(quote.funding)&&finite(quote.funding*100)?quote.funding*100:null,funding_hours:finite(quote.funding_interval_hours)&&quote.funding_interval_hours>0?quote.funding_interval_hours:null}:null,
   chart:candle.available?{price:chart.price,atr:nonnegative(chart.atr),atr_pct:nonnegative(chart.atr_pct),vwap:finite(chart.vwap)&&chart.vwap>0?chart.vwap:null,volume:nonnegative(chart.volume_window),turnover:nonnegative(chart.turnover_window),rvol:nonnegative(chart.rvol)}:null};
 }
 const planDefaults=Object.freeze({capital:600,risk_pct:.5,max_notional:100,fee_pct:.055,slippage_pct:.05,min_rr:1.5});
 const planLimits={capital:[10,1e6],risk_pct:[.01,5],max_notional:[1,1e6],fee_pct:[0,1],slippage_pct:[0,5],min_rr:[1,10]};
 function validatePlan(values){
  if(!values||typeof values!=='object'||Array.isArray(values)||Object.keys(values).some(k=>!Object.hasOwn(planDefaults,k)))throw Error('Некорректные настройки PAPER-плана');
  const result={...planDefaults};for(const [key,value]of Object.entries(values)){const [low,high]=planLimits[key];if(!finite(value)||value<low||value>high)throw Error('Настройка PAPER-плана вне допустимого диапазона');result[key]=value;}
  if(result.max_notional>result.capital)throw Error('Лимит входа не должен превышать виртуальный капитал');return result;
 }
 function paperPlan(input){
  const {snapshot,chart,book,selectionPacket,symbol,interval,now,models={}}=input;
  const outcome=(status,reason,data=null)=>({status,reasons:[reason],symbol,interval,data});let settings;
  try{settings=validatePlan(input.settings===undefined?planDefaults:input.settings);}catch(e){return outcome('settings_error',e.message);}
  const card=coinCardView(input),names={ticker:'Котировки',chart:'Свечи',book:'Стакан'};
  for(const [key,source]of Object.entries(card.sources))if(source.status!=='fresh')return outcome('pending',names[key]+': '+({cached:'ошибка обновления; ждём успешный ответ',stale:'данные устарели',pending:'ожидаем загрузку',error:'источник недоступен',missing:'монета отсутствует в подборке'}[source.status]||'ожидаем свежие данные'));
  const selectionRows=Array.isArray(selectionPacket?.rows)?selectionPacket.rows:[];
  const verdict=selectionView(selectionRows.find(r=>r?.symbol===symbol)?.selection,selectionPacket?.source_time,snapshot?.updated,now);
  if(verdict.status==='rejected')return outcome('rejected','Не пройден умный отбор: '+(verdict.checks.filter(c=>c.state==='fail').map(c=>c.label).join(', ')||'условия рынка не подходят'));
  if(selectionPacket?.status!=='ok'||verdict.ticker_time!==snapshot?.updated||verdict.status!=='passed'||ratingView(verdict,now).status!=='ok')return outcome('pending','Ожидаем полный умный отбор по свежим котировкам, минутным свечам и пяти снимкам стакана');
  const q=card.quote,c=card.chart,step=Number(interval)*60,bars=chart.candles;
  if(!q||!finite(q.price)||!finite(q.funding_pct)||!c||!finite(c.vwap)||!finite(c.atr)||c.atr<=0)return outcome('neutral','Для сценария нужны цена, VWAP, funding и положительный ATR');
  if(bars.length<60||bars.length>180||bars.some((b,i)=>!b||![b.time,b.open,b.high,b.low,b.close].every(finite)||b.low<=0||b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||b.time%step!==0||i&&b.time-bars[i-1].time!==step)||chart.candle_end!==bars.at(-1).time+step||chart.price!==bars.at(-1).close)return outcome('pending','Ожидаем непрерывные закрытые свечи выбранного таймфрейма');
  const ema=period=>{let value=bars.slice(0,period).reduce((sum,b)=>sum+b.close,0)/period;for(const b of bars.slice(period))value+=(b.close-value)*2/(period+1);return value;};
  const fast=ema(20),slow=ema(50),last=chart.price,move=last-bars.at(-6).close;
  const side=fast>slow&&last>c.vwap&&move>0?1:fast<slow&&last<c.vwap&&move<0?-1:0;
  if(!side)return outcome('neutral','Нет согласованного направления: EMA20/50, VWAP и движение за пять закрытых свечей расходятся');
  const levels=Array.isArray(chart.levels)?chart.levels:[];
  const valid=l=>l&&['support','resistance'].includes(l.side)&&[l.low,l.high,l.price].every(finite)&&l.low>0&&l.low<=l.price&&l.price<=l.high&&Number.isInteger(l.pivots)&&l.pivots>0&&(l.side==='support'?l.high<last:l.low>last);
  if(!levels.length||levels.some(l=>!valid(l)))return outcome('neutral','Нет корректных подтверждённых зон для входа и цели');
  const behind=levels.filter(l=>l.side===(side===1?'support':'resistance')).sort((a,b)=>Math.abs(a.price-last)-Math.abs(b.price-last));
  const ahead=levels.filter(l=>l.side===(side===1?'resistance':'support')).sort((a,b)=>Math.abs(a.price-last)-Math.abs(b.price-last));
  if(!behind.length||!ahead.length)return outcome('neutral','Нужны подтверждённая зона входа и противоположная целевая зона');
  const zone=behind[0],low=side===1?zone.low:zone.low-.25*c.atr,high=side===1?zone.high+.25*c.atr:zone.high;
  const entry=side===1?high:low,stop=side===1?zone.low-.5*c.atr:zone.high+.5*c.atr;
  const prices=ahead.slice(0,2).map(l=>side===1?l.low-.1*c.atr:l.high+.1*c.atr);
  if(![low,high,entry,stop,...prices].every(v=>finite(v)&&v>0)||side*(entry-stop)<=0||prices.some((p,i)=>side*(p-entry)<=0||i&&side*(p-prices[i-1])<=0))return outcome('rejected','Зоны слишком близки или пересекаются после буфера ATR');
  const near=book.bands['0.001'];if(near.covered!==true||near.bid<0||near.ask<0)return outcome('pending','Стакан должен полностью покрывать зону ±0,1% с обеих сторон');
  const row=snapshot.rows.find(r=>r.symbol===symbol),spread=Math.max(book.spread,row.spread);
  if(!finite(spread)||spread<0||spread>5||Math.abs(q.price/book.mid-1)>Math.max(.001,c.atr/last*.5))return outcome('pending','Котировка и свежий стакан не согласованы; повторяем проверку');
  const fee=settings.fee_pct/100,execution=settings.slippage_pct/100+spread/200;
  const filled=entry*(1+side*execution),stopFilled=stop*(1-side*execution),exits=prices.map(p=>p*(1-side*execution));
  // Reserve one adverse funding payment; receiving funding never inflates rewards.
  const fundingUnit=Math.max(filled,stopFilled,...exits)*Math.max(0,side*q.funding_pct/100);
  const lossUnit=side*(filled-stopFilled)+fee*(filled+stopFilled)+fundingUnit;
  const budget=settings.capital*settings.risk_pct/100;
  const quantity=Math.min(budget/lossUnit,settings.max_notional/filled,settings.capital/(filled*(1+fee)))*(1-Number.EPSILON);
  const notional=quantity*filled,risk=quantity*lossUnit;
  const targets=exits.map((exit,i)=>{const profitUnit=side*(exit-filled)-fee*(filled+exit)-fundingUnit;return {price:prices[i],profit:quantity*profitUnit,rr:profitUnit/lossUnit};});
  if(![filled,stopFilled,lossUnit,quantity,notional,risk,budget,fundingUnit,...exits,...targets.flatMap(t=>[t.profit,t.rr])].every(finite)||filled<=0||stopFilled<=0||lossUnit<=0||quantity<=0||risk>budget*(1+1e-12)||notional>settings.max_notional*(1+1e-12))return outcome('rejected','Расчёт риска выходит за допустимые числовые пределы');
  const data={side,direction:side===1?'LONG':'SHORT',low,high,entry,stop,targets,quantity,notional,risk,budget,risk_pct:risk/settings.capital*100,
   costs:quantity*(side*(filled-entry)+side*(stop-stopFilled)+fee*(filled+stopFilled)),funding_reserve:quantity*fundingUnit,capital:settings.capital,
   ema20:fast,ema50:slow,vwap:c.vwap,atr:c.atr,stamp:chart.candle_end,settings};
  const impact=name=>{
   const levels=book.top?.[name];if(!Array.isArray(levels)||!levels.length||levels.length>5||levels.some((l,i)=>!l||![l.price,l.quantity].every(finite)||l.price<=0||l.quantity<=0||i&&(name==='ask'?l.price<=levels[i-1].price:l.price>=levels[i-1].price)))return null;
   let left=quantity,value=0;for(const l of levels){const take=Math.min(left,l.quantity);value+=take*l.price;left-=take;if(left<=quantity*1e-10)break;}
   return left>quantity*1e-10?null:Math.max(0,(name==='ask'?value/quantity/levels[0].price-1:1-value/quantity/levels[0].price)*100);
  };
  const buy=impact('ask'),sell=impact('bid');
  if(buy===null||sell===null||!finite(buy)||!finite(sell)||book.top.bid[0].price>=book.top.ask[0].price)return outcome('rejected','Недостаточно проверенных уровней стакана для рассчитанного количества монет',data);
  const bestMid=(book.top.bid[0].price+book.top.ask[0].price)/2,bestSpread=(book.top.ask[0].price-book.top.bid[0].price)/bestMid*100;
  if(Math.abs(bestMid/book.mid-1)>1e-8||Math.abs(bestSpread-book.spread)>1e-7)return outcome('pending','Верхние уровни и сводка стакана не согласованы; повторяем проверку');
  if(Math.max(buy,sell)>settings.slippage_pct+1e-9)return outcome('rejected','Текущий impact рассчитанного объёма превышает допуск проскальзывания',data);
  if(side*(q.price-stop)<=0)return outcome('invalidated','Условие отменено: текущая цена уже за стопом',data);
  if(side*(prices[0]-q.price)<=0)return outcome('invalidated','Условие отменено: первая цель уже достигнута без входа',data);
  if(targets[0].rr<settings.min_rr)return outcome('rejected','Прибыль / риск первой цели после издержек ниже '+fmt(settings.min_rr,2),data);
  const occupied=Object.entries(models).filter(([,s])=>positionView(s,now)?.current&&s.position.symbol===symbol).map(([id])=>id);
  if(occupied.length)return outcome('watch','По монете уже есть PAPER-позиция: '+occupied.join(', '),data);
  if(q.price<low||q.price>high)return outcome('watch','Ожидаем возврата цены в зону входа; направление подтверждено закрытыми свечами',data);
  return outcome('ready','Цена в зоне входа; направление, отбор, стакан и расчёт риска подтверждены для PAPER-плана',data);
 }
 const api={stableRows,fresh,ratingScore,ratingView,coinCardView,paperPlan,planDefaults,validatePlan,filterRows,botModels,positionView,domain,chartBars,barCount,selectionDefaults,validateSelection,selectionView};
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 scope.LabScreener=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-market');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const line=(p,t,c='muted')=>p.append(el('p',c,t));
  const icon=(name)=>scope.LabUI.icon(name),coin=s=>scope.LabUI.coin(s),go=key=>scope.LabNavigation.activate(key);
  const action=(text,key)=>{const b=el('button','text-button',text);b.type='button';b.append(icon('arrow'));b.addEventListener('click',()=>go(key));return b;};
  const old=el('details','box archive-details');old.append(el('summary','','Подробный Grid / скальпинг-отбор'));while(page.firstChild)old.append(page.firstChild);page.append(old);
  const root=el('section','screener-workspace');root.id='crypto-screener';page.prepend(root);
  const hero=el('section','screener-head'),heroText=el('div'),heading=el('h2');heading.append(el('span','desktop-only','Скринер криптовалют'),el('span','mobile-only','Скринер'));
  heroText.append(heading,el('p','','Активность рынка, уровни и ликвидность'));hero.append(heroText,el('span','mode-pill','PAPER'));root.append(hero);
  const summary=el('section','screener-summary'),summaryValues={};
  for(const [key,label,glyph]of [['coins','Монет в подборке','market'],['alerts','Свежих событий','alerts'],['models','Отчётов моделей','research']]){const item=el('div'),mark=el('span','summary-icon'),text=el('div'),value=el('strong','','—');mark.append(icon(glyph));text.append(el('span','',label),value);item.append(mark,text);summary.append(item);summaryValues[key]=value;}root.append(summary);
  const marketBox=el('section','box screener-market');root.append(marketBox);
  const controls=el('div','screener-controls'),searchLabel=el('label'),search=el('input');search.type='search';search.placeholder='Поиск монеты';search.setAttribute('aria-label','Поиск монеты');searchLabel.append(search);controls.append(searchLabel);
  const chips=el('div','preset-chips'),presetButtons={};chips.setAttribute('aria-label','Подборки монет');
  const makeSelect=(name,items)=>{const n=el('select');n.setAttribute('aria-label',name);for(const [value,text]of items){const o=el('option','',text);o.value=value;n.append(o);}return n;};
  const presets=[['all','Все'],['active','Активные'],['liquid','Ликвидные'],['up','Рост'],['down','Падение'],['favorites','Наблюдение']];
  const preset=makeSelect('Подборка',[...presets,['bots','Монеты ботов']]);
  for(const [value,text]of presets){const b=el('button','preset-chip',text);b.type='button';b.setAttribute('aria-pressed',String(value==='all'));b.addEventListener('click',()=>{preset.value=value;render();});presetButtons[value]=b;chips.append(b);}controls.append(chips);
  const sorts=[['quality','Рейтинг ↓'],['turnover','Оборот ↓'],['range24','Диапазон ↓'],['spread','Спред ↑'],['change','Рост цены ↓']],sorting=makeSelect('Сортировка',sorts),sortLabel=el('label','sort-control');sortLabel.append(sorting);controls.append(sortLabel);
  const filtersButton=el('button','icon-button');filtersButton.type='button';filtersButton.setAttribute('aria-label','Дополнительные фильтры');filtersButton.setAttribute('aria-expanded','false');filtersButton.setAttribute('aria-controls','screener-extra-filters');filtersButton.append(icon('filter'));controls.append(filtersButton);marketBox.append(controls);
  const filters=el('div','screener-extra-filters');filters.id='screener-extra-filters';filters.hidden=true;
  const minimum=makeSelect('Оборот от',[['0','Любой'],['10000000','10 млн USDT'],['50000000','50 млн USDT'],['100000000','100 млн USDT']]),mobileSort=makeSelect('Порядок монет',sorts);
  for(const [name,node,cls]of [['Подборка',preset,''],['Оборот от',minimum,''],['Порядок монет',mobileSort,'mobile-sort']]){const l=el('label',cls,name);l.append(node);filters.append(l);}marketBox.append(filters);
  filtersButton.addEventListener('click',()=>{filters.hidden=!filters.hidden;filtersButton.setAttribute('aria-expanded',String(!filters.hidden));});
  const tracking=el('section','screener-tracking');tracking.setAttribute('aria-label','Мои монеты');
  tracking.append(el('h3','','Мои монеты'));const watchList=el('div','watch-list'),watchNote=el('p','muted');tracking.append(watchList,watchNote);marketBox.append(tracking);
  const orderControls=el('div','order-controls'),orderLabel=el('label','','Порядок строк'),orderMode=makeSelect('Обновление порядка',[['manual','Закреплён'],['minute','Раз в минуту'],['live','При каждом обновлении']]),resort=el('button','secondary-button','Пересортировать'),orderNote=el('p','muted');resort.type='button';orderLabel.append(orderMode);orderControls.append(orderLabel,resort,orderNote);marketBox.append(orderControls);
  let rowOrder=[],orderKey='',orderedAt=0;const watchedNodes=new Map(),lastRatings=new Map();
  try{const saved=JSON.parse(localStorage.getItem('lab-screener-order-v1')||'null');if(saved&&['manual','minute','live'].includes(saved.mode)){orderMode.value=saved.mode;sorting.value=mobileSort.value=sorts.some(x=>x[0]===saved.sort)?saved.sort:'quality';}}catch{}
  const saveOrder=()=>{try{localStorage.setItem('lab-screener-order-v1',JSON.stringify({mode:orderMode.value,sort:sorting.value}));}catch{}};
  resort.addEventListener('click',()=>{rowOrder=[];tableSignature='';render();});orderMode.addEventListener('change',()=>{rowOrder=[];tableSignature='';saveOrder();render();});
  const selectionPanel=el('details','selection-panel'),selectionHeading=el('summary','','Умный отбор · фильтры и проверка'),selectionForm=el('fieldset','selection-fields');selectionPanel.append(selectionHeading);selectionForm.append(el('legend','sr-only','Пороги умного отбора'));
  const selectionInputs={},selectionFields=[['turnover_min','Оборот 24ч от, млн USDT',1e6],['spread_max','Спред до, %',1],['range_min','Диапазон 24ч от, %',1],['range_max','Диапазон 24ч до, %',1],['atr_min','ATR 1м от, %',1],['atr_max','ATR 1м до, %',1],['rvol_min','Объём 5 / 20 минут от, ×',1],['oi_min','OI от, млн USDT',1e6],['funding_max','|Funding| до, % за интервал',1],['depth_min','Глубина Bid и Ask от, USDT',1],['impact_max','Impact до, % · около 100 USDT',1]];
  let selectionFilters={...selectionDefaults},selectionPacket=null,selectionError='',selectionBusy=false;
  try{selectionFilters=validateSelection(JSON.parse(localStorage.getItem('lab-selection-v1')||'null'));}catch{}
  for(const [key,label,scale]of selectionFields){const l=el('label','',label),input=el('input');input.type='number';input.min='0';input.max=String(selectionLimits[key]/scale);input.step='any';input.required=true;input.value=String(selectionFilters[key]/scale);input.id='selection-'+key;l.htmlFor=input.id;l.append(input);selectionForm.append(l);selectionInputs[key]={input,scale};}
  const selectionActions=el('div','selection-actions'),selectionApply=el('button','primary-button','Применить отбор'),selectionReset=el('button','secondary-button','Сбросить пороги'),selectionMode=makeSelect('Состояние отбора',[['all','Все состояния'],['passed','Прошли отбор'],['pending','Ожидают проверки'],['rejected','Не подходят']]),selectionModeLabel=el('label','','Показать');selectionApply.type=selectionReset.type='button';selectionModeLabel.append(selectionMode);selectionActions.append(selectionApply,selectionReset,selectionModeLabel);
  const selectionMessage=el('p','selection-message');selectionMessage.setAttribute('role','status');selectionPanel.append(selectionForm,selectionActions,selectionMessage);line(selectionPanel,'Проверка по закрытым минутным свечам и пяти снимкам стакана. Объём: количество монет за последние 5 минут относительно предыдущих 20. Funding: за интервал контракта.');marketBox.append(selectionPanel);
  const selectionSummary=el('p','selection-summary','Умный отбор: ожидаем данные');selectionSummary.setAttribute('role','status');marketBox.append(selectionSummary);
  const rankingMethod=el('details','ranking-method');rankingMethod.append(el('summary','','Как считается рейтинг 0–100'));
  line(rankingMethod,'Четыре части по 25 баллов. В строке монеты раскрой отбор или нажми на балл — появятся значения и вклад каждой части.');
  for(const text of ['Ликвидность: шкала оборота 24ч от 2 до 200 млн USDT, логарифмическая.','Спред: худший из котировки и пяти снимков стакана; 0% даёт 25 баллов, 0,05% и шире — 0.','Объём: средний минутный объём монет за 5 закрытых минут / предыдущие 20; 1× даёт 13 баллов, 2× — 25.','Стакан: до 15 баллов за глубину каждой стороны до 20 000 USDT и до 10 за impact от 0,05% до 0%. Зона ±0,1% должна быть полностью проверена по пяти снимкам.'])line(rankingMethod,text);
  line(rankingMethod,'Баллы частей округляются и складываются. Шкала фиксирована; пороги отбора определяют допуск. При сортировке сначала идут прошедшие отбор, затем ожидающие и отсеянные; неполный рейтинг показан как «—». Рейтинг описывает качество рыночных условий, а высокий балл сам по себе не является условием входа.');marketBox.append(rankingMethod);
  const scroll=el('div','scroll screener-scroll'),table=el('table','screener-table');table.id='screener-table';const head=el('thead'),headerRow=el('tr');
  const sortDirs={};
  const thSort=(label,key)=>{const th=el('th'),b=el('button','th-sort',label);b.type='button';b.dataset.sort=key;b.dataset.label=label;b.setAttribute('aria-label','Сортировать: '+label);b.addEventListener('click',()=>{if(sorting.value===key)sortDirs[key]=sortDirs[key]==='asc'?'desc':'asc';else{sorting.value=key;mobileSort.value=key;sortDirs[key]='desc';}rowOrder=[];tableSignature='';saveOrder();render();});th.append(b);return th;};
  headerRow.append(el('th','','Монета'),el('th','','Цена, USDT'),thSort('24 ч','change'),thSort('Оборот','turnover'),thSort('Спред','spread'),thSort('Рейтинг','quality'),el('th',''));headerRow.lastChild.append(el('span','sr-only','Избранное'));head.append(headerRow);
  const tbody=el('tbody');table.append(head,tbody);scroll.append(table);marketBox.append(scroll);
  const counter=el('p','screener-counter'),status=el('p','screener-status','Получаем публичные данные Bybit…');status.id='screener-status';status.setAttribute('role','status');marketBox.append(counter,status);
  const alertsBox=el('section','box screener-alerts');alertsBox.id='screener-alerts';const alertHead=el('div','panel-heading'),alertList=el('div');alertHead.append(el('h2','','Алерты'),action('Все алерты','alerts'));alertsBox.append(alertHead,alertList);root.append(alertsBox);
  const panel=el('section','box screener-detail');panel.id='screener-detail';root.append(panel);
  panel.setAttribute('aria-label','Карточка выбранной монеты');
  const toolbar=el('div','screener-detail-toolbar'),title=el('h2','','BTCUSDT · 5 мин'),timeChips=el('div','time-chips'),timeframe={value:'5'},timeButtons={};timeChips.setAttribute('role','group');timeChips.setAttribute('aria-label','Таймфрейм уровней');
  for(const [value,text,label]of [['1','1м','1 минута'],['5','5м','5 минут'],['15','15м','15 минут'],['60','1ч','1 час']]){const b=el('button','time-chip',text);b.type='button';b.setAttribute('aria-label',label);b.setAttribute('aria-pressed',String(value==='5'));b.addEventListener('click',()=>{timeframe.value=value;updateScaleControls();for(const [v,n]of Object.entries(timeButtons))n.setAttribute('aria-pressed',String(v===value));choose(selected);});timeButtons[value]=b;timeChips.append(b);}
  const scaleControls=el('div','chart-scale-controls');scaleControls.setAttribute('role','group');scaleControls.setAttribute('aria-label','Масштаб графика');
  const scaleOut=el('button','chart-scale-button','−');scaleOut.type='button';scaleOut.setAttribute('aria-label','Уменьшить масштаб графика');
  const scaleValue=el('button','chart-scale-value','100%');scaleValue.type='button';scaleValue.setAttribute('aria-label','Сбросить масштаб графика');
  const scaleIn=el('button','chart-scale-button','+');scaleIn.type='button';scaleIn.setAttribute('aria-label','Увеличить масштаб графика');
  scaleControls.append(scaleOut,scaleValue,scaleIn);
  const external=el('a','icon-button external-chart');external.target='_blank';external.rel='noopener noreferrer';external.setAttribute('aria-label','Открыть TradingView');external.append(icon('arrow'));
  const expand=el('button','icon-button');expand.type='button';expand.setAttribute('aria-label','Открыть график');expand.append(icon('expand'));toolbar.append(title,timeChips,scaleControls,external,expand);panel.append(toolbar);
  const cardFacts=el('dl','coin-card-facts'),cardFields={},cardSources=el('ul','coin-card-sources'),cardSourceNodes={};
  for(const [key,name]of [['price','Цена, USDT'],['oi','OI, USDT'],['funding','Funding'],['vwap','VWAP · 60 свечей'],['atr','ATR(14)'],['volume','Объём · 60 свечей']]){const item=el('div'),label=el('dt','',name),value=el('dd','','—'),hint=el('small','');item.dataset.metric=key;item.append(label,value,hint);cardFacts.append(item);cardFields[key]={item,label,value,hint};}
  for(const [key,name]of [['ticker','Котировки'],['chart','Свечи'],['book','Стакан']]){const item=el('li'),text=el('span'),stamp=el('time'),note=el('small');item.dataset.source=key;item.append(text,stamp,note);cardSources.append(item);cardSourceNodes[key]={item,text,stamp,note,name};}panel.append(cardFacts,cardSources);
  const chartHost=el('div','screener-chart');chartHost.id='screener-candles';const quickLevels=el('div','chart-quick-levels'),chartStatus=el('small','chart-stamp');panel.append(chartHost,quickLevels,chartStatus);
  const analysis=el('details','chart-analysis'),metrics=el('div','terminal-metrics'),levelsBox=el('div','screener-levels');levelsBox.id='screener-levels';analysis.append(el('summary','','Уровни и показатели'),metrics,levelsBox);panel.append(analysis);
  const explanation=el('details','screener-method');explanation.append(el('summary','','Как рассчитываются уровни'));
  line(explanation,'До 180 закрытых свечей. Экстремумы подтверждаются двумя барами слева и справа. Близкие экстремумы объединяются в зоны шириной до max(0,05% цены; 0,25 ATR).');
  line(explanation,'Три ближайшие зоны ниже и выше последнего закрытия. Число экстремумов не является вероятностью отскока. По умолчанию видно 90 свечей, на телефоне — 45. Колесо меняет масштаб времени, колесо над правой шкалой — масштаб цены; перетаскивание сдвигает вид, щипок меняет масштаб, двойной клик сбрасывает. Голубая линия — VWAP 60 свечей, столбцы — оборот в USDT.');analysis.append(explanation);
  const planBox=el('section','box paper-plan');planBox.id='screener-plan';planBox.setAttribute('aria-label','План PAPER-сделки');root.append(planBox);
  const planHeading=el('div','panel-heading'),planContext=el('p','paper-plan-context'),planStatus=el('p','paper-plan-status'),planFacts=el('dl','paper-plan-facts'),planFields={},planCosts=el('p','paper-plan-costs');
  planHeading.append(el('h2','','План сделки · PAPER'));planStatus.setAttribute('role','status');planBox.append(planHeading,planContext,planStatus,planFacts,planCosts);
  for(const [key,name]of [['direction','Направление'],['entry','Зона входа, USDT'],['stop','Стоп, USDT'],['target1','Цель 1, USDT'],['target2','Цель 2, USDT'],['size','Виртуальный вход'],['risk','Риск, USDT'],['rr','Прибыль / риск']]){const item=el('div'),label=el('dt','',name),value=el('dd','','—'),hint=el('small');item.dataset.planField=key;item.append(label,value,hint);planFacts.append(item);planFields[key]={item,value,hint};}
  let planSettings={...planDefaults},planDirty=false;try{planSettings=validatePlan(JSON.parse(localStorage.getItem('lab-paper-plan-v1')||'null'));}catch{}
  const planControls=el('details','paper-plan-controls'),planForm=el('form'),planInputs={},planSettingsSummary=el('summary','','Капитал и расчёт риска'),planFieldset=el('fieldset','paper-plan-inputs');planFieldset.append(el('legend','sr-only','Настройки PAPER-плана'));
  const planSettingsFields=[['capital','Виртуальный капитал, USDT'],['risk_pct','Риск на план, % капитала'],['max_notional','Лимит входа, USDT'],['fee_pct','Комиссия на сторону, %'],['slippage_pct','Допуск проскальзывания на сторону, %'],['min_rr','Минимум прибыль / риск']];
  const planMessage=el('p','paper-plan-message');planMessage.setAttribute('role','status');
  for(const [key,name]of planSettingsFields){const label=el('label','',name),input=el('input');input.type='number';input.inputMode='decimal';input.id='paper-plan-'+key;input.min=String(planLimits[key][0]);input.max=String(planLimits[key][1]);input.step='any';input.required=true;input.value=String(planSettings[key]);label.htmlFor=input.id;label.append(input);planInputs[key]=input;planFieldset.append(label);input.addEventListener('input',()=>{planDirty=true;input.setAttribute('aria-invalid','false');planMessage.textContent='Настройки изменены · примените расчёт';render();});input.addEventListener('invalid',()=>{input.setAttribute('aria-invalid','true');planMessage.textContent='Проверьте поле: '+name;});}
  const planActions=el('div','paper-plan-actions'),planApply=el('button','primary-button','Применить расчёт'),planReset=el('button','secondary-button','Сбросить расчёт');planApply.type='submit';planReset.type='button';planActions.append(planApply,planReset);planForm.append(planFieldset,planActions,planMessage);planControls.append(planSettingsSummary,planForm);planBox.append(planControls);
  function applyPlan(reset=false){let values={...planDefaults};if(!reset){values={};for(const [key,input]of Object.entries(planInputs))values[key]=input.valueAsNumber;}try{planSettings=validatePlan(values);}catch(e){planMessage.textContent=e.message;planDirty=true;render();return;}for(const [key,input]of Object.entries(planInputs)){input.value=String(planSettings[key]);input.setAttribute('aria-invalid','false');}planDirty=false;try{localStorage.setItem('lab-paper-plan-v1',JSON.stringify(planSettings));}catch{}planMessage.textContent=reset?'Параметры расчёта сброшены':'Параметры расчёта применены';render();}
  planForm.addEventListener('submit',e=>{e.preventDefault();applyPlan();});planReset.addEventListener('click',()=>applyPlan(true));
  const manualActions=el('div','paper-plan-actions'),manualDraft=el('button','primary-button','Подготовить ручной PAPER-вход');manualDraft.type='button';manualDraft.disabled=true;manualActions.append(manualDraft);planBox.append(manualActions);
  let currentManualPlan=null;
  manualDraft.addEventListener('click',()=>{if(!currentManualPlan||manualDraft.disabled)return;document.dispatchEvent(new CustomEvent('lab-paper-draft',{detail:structuredClone(currentManualPlan)}));go('positions');});
  const planMethod=el('details','paper-plan-method');planMethod.append(el('summary','','Почему такой план'));
  for(const text of ['Направление: EMA20 выше EMA50, закрытие выше VWAP и рост за пять свечей для LONG; обратные условия для SHORT. Вход — ближайшая подтверждённая зона позади цены закрытия с расширением 0,25 ATR в сторону входа. Стоп — на 0,5 ATR за зоной.',
   'Первая цель — перед ближайшей противоположной зоной, вторая — перед следующей, с буфером 0,1 ATR. Цель 2 предполагает пробой первой зоны. Если второй зоны нет, цель 2 остаётся неподтверждённой. Результат каждой цели рассчитан на полный объём отдельно и не складывается.',
   'Риск рассчитан от дальнего от стопа края входа: комиссия на вход и выход, половина текущего спреда и допуск проскальзывания на каждой стороне. Добавлен резерв одного funding-платежа по текущей ставке, если его платит выбранное направление; получение funding не увеличивает прибыль.',
   'Количество монет ограничено риском, лимитом входа и виртуальным капиталом без плеча. Размер дробный, для PAPER-расчёта. Impact проверяется для этого количества по доступным пяти верхним уровням каждой стороны; если их мало, план не подходит.',
   '«Готов для PAPER» требует свежих источников без ошибки обновления, полного отбора, согласованного стакана, цены в зоне входа и достаточного прибыль / риск первой цели после издержек. Параметры сценария — исследовательские правила, не проверенная прибыльная стратегия. Фактическое проскальзывание и будущий funding могут изменить результат.'])line(planMethod,text);planBox.append(planMethod);
  const bookBox=el('section','box screener-orderbook');bookBox.id='screener-orderbook';root.append(bookBox);
  const botsBox=el('section','box screener-bots');botsBox.id='screener-bots';root.append(botsBox);
  let snapshot=null,chart=null,book=null,models={},bState=null,wState=null,researchState=null,selected='BTCUSDT',generation=0,tickerError='',chartError='',bookError='';
  let previousBook=null,bookChange=null,tableSignature='',chartSignature='',chartInfoSignature='',bookSignature='',botSignature='',bookOpen=false,tickerStamp=0,focusSelected=false;
  const favorites=new Set(),priceHistory=new Map(),tableRows=new Map();
  const SCALE_MIN=.3,SCALE_MAX=8,PRICE_MIN=.2,PRICE_MAX=10,legacyScales={};let chartViews={};
  try{for(const s of JSON.parse(localStorage.getItem('lab-favorites-v1')||'[]').slice(0,100))if(safeSymbol(s))favorites.add(s);const s=localStorage.getItem('lab-selected-coin');if(safeSymbol(s))selected=s;
   const legacy=JSON.parse(localStorage.getItem('lab-screener-chart-scale-v1')||'{}');for(const k of ['1','5','15','60'])if(finite(legacy?.[k]))legacyScales[k]=Math.min(3,Math.max(.5,legacy[k]));
   const saved=JSON.parse(localStorage.getItem('lab-screener-chart-view-v2')||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))chartViews=saved;}catch{}
  function toggleWatch(symbol){
   if(favorites.has(symbol))favorites.delete(symbol);else if(favorites.size<8)favorites.add(symbol);else{watchNote.textContent='Лимит 8 монет. Снимите звезду с одной монеты, чтобы добавить другую.';return;}
   try{localStorage.setItem('lab-favorites-v1',JSON.stringify([...favorites]));}catch{}
   selectionPacket=null;tableSignature='';render();refreshSelection();document.dispatchEvent(new CustomEvent('lab-selection-changed'));
  }
  function renderWatch(now){
   const wanted=new Set(favorites);for(const [symbol,item]of watchedNodes)if(!wanted.has(symbol)){item.row.remove();watchedNodes.delete(symbol);}
   for(const symbol of favorites){let item=watchedNodes.get(symbol);if(!item){const row=el('div','watch-item'),open=el('button','text-button',symbol),value=el('span'),remove=el('button','text-button','Убрать');open.type=remove.type='button';open.setAttribute('aria-label','Открыть наблюдение '+symbol);remove.setAttribute('aria-label','Убрать из наблюдения '+symbol);open.addEventListener('click',()=>{choose(symbol);panel.scrollIntoView({block:'start'});});remove.addEventListener('click',()=>toggleWatch(symbol));row.append(open,value,remove);watchList.append(row);item={row,open,value};watchedNodes.set(symbol,item);}
    const quote=snapshot?.rows?.find(r=>r.symbol===symbol);item.open.setAttribute('aria-pressed',String(symbol===selected));item.value.textContent=quote&&fresh(snapshot.updated,now,45)?fmt(quote.price,8)+' USDT · '+fmt(quote.change)+'%':'Нет свежей котировки';
   }
   watchNote.textContent=favorites.size?'Наблюдение: '+favorites.size+' · первые 8 монет проверяются в приоритете, даже при смене поиска. Цены — из топ-100; отсутствующие пары отмечены явно.':'Нажмите звезду у монеты: она останется здесь и получит приоритет проверки. До 8 пар.';
  }
  document.addEventListener('lab-watch',e=>{if(safeSymbol(e.detail?.symbol)&&!favorites.has(e.detail.symbol))toggleWatch(e.detail.symbol);});
  window.addEventListener('storage',e=>{if(e.key==='lab-favorites-v1'){try{const values=JSON.parse(e.newValue||'[]');if(!Array.isArray(values))return;favorites.clear();for(const s of values.slice(0,100))if(safeSymbol(s))favorites.add(s);}catch{return;}selectionPacket=null;tableSignature='';render();refreshSelection();document.dispatchEvent(new CustomEvent('lab-selection-changed'));}});
  const viewKey=()=>selected+':'+timeframe.value;
  const defaultView=()=>({scale:legacyScales[timeframe.value]||1,offset:0,pScale:1,pCenter:null});
  function getView(){const v=chartViews[viewKey()];return clampView(v&&typeof v==='object'&&!Array.isArray(v)?{...defaultView(),...v}:defaultView());}
  function persistViews(){try{const keys=Object.keys(chartViews).slice(-40),out={};for(const k of keys)out[k]=chartViews[k];chartViews=out;localStorage.setItem('lab-screener-chart-view-v2',JSON.stringify(out));}catch{}}
  function clampView(v){v.scale=Math.min(SCALE_MAX,Math.max(SCALE_MIN,finite(v.scale)?v.scale:1));v.offset=Math.max(0,Math.round(finite(v.offset)?v.offset:0));v.pScale=Math.min(PRICE_MAX,Math.max(PRICE_MIN,finite(v.pScale)?v.pScale:1));if(!finite(v.pCenter))v.pCenter=null;const total=chart?.candles?.length||0;if(total)v.offset=Math.min(v.offset,Math.max(0,total-barCount(chartHost.clientWidth,v.scale,total)));return v;}
  function applyView(patch){chartViews[viewKey()]=clampView({...getView(),...patch});persistViews();chartSignature='';updateScaleControls();render();}
  function resetView(){delete chartViews[viewKey()];persistViews();chartSignature='';updateScaleControls();render();}
  function updateScaleControls(){const v=getView();scaleValue.textContent=Math.round(v.scale*100)+'%';scaleOut.disabled=v.scale<=SCALE_MIN;scaleIn.disabled=v.scale>=SCALE_MAX;}
  updateScaleControls();
  scaleOut.addEventListener('click',()=>applyView({scale:getView().scale/1.25}));scaleIn.addEventListener('click',()=>applyView({scale:getView().scale*1.25}));scaleValue.addEventListener('click',resetView);
  function viewDomain(pixels){if(!chart?.candles?.length)return null;const v=getView(),bars=chartBars(chart.candles,pixels,v.scale,v.offset);if(!bars.length)return null;const b=domain(bars),half=(b.high-b.low)/2/v.pScale,center=finite(v.pCenter)?v.pCenter:(b.high+b.low)/2;return {v,bars,count:bars.length,total:chart.candles.length,center,half};}
  function viewCoords(e){const rect=chartHost.getBoundingClientRect();if(!rect.width||!rect.height)return null;const w=Math.max(250,Math.round(rect.width));return {w,right:w-78,px:(e.clientX-rect.left)*w/rect.width,py:(e.clientY-rect.top)*254/rect.height};}
  chartHost.addEventListener('wheel',e=>{const c=viewCoords(e),d=c&&viewDomain(c.w);if(!d)return;e.preventDefault();const factor=e.deltaY<0?1.15:1/1.15;
   if(c.px>=c.right){const fy=Math.min(1,Math.max(0,(c.py-18)/138)),anchor=d.center+d.half*(1-2*fy),pScale=Math.min(PRICE_MAX,Math.max(PRICE_MIN,d.v.pScale*factor)),half=d.half*d.v.pScale/pScale;applyView({pScale,pCenter:anchor-half*(1-2*fy)});}
   else{const fx=Math.min(1,Math.max(0,(c.px-12)/Math.max(1,c.right-12))),index=d.total-d.v.offset-d.count+fx*(d.count-1),scale=Math.min(SCALE_MAX,Math.max(SCALE_MIN,d.v.scale*factor)),count=barCount(c.w,scale,d.total);applyView({scale,offset:Math.round(d.total-count-index+fx*(count-1))});}
  },{passive:false});
  let drag=null,pinch=null;const pointers=new Map();
  chartHost.addEventListener('pointerdown',e=>{const c=viewCoords(e),d=c&&viewDomain(c.w);if(!d)return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});try{chartHost.setPointerCapture(e.pointerId);}catch{}
   if(pointers.size===2){const p=[...pointers.values()];pinch={distance:Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)||1,scale:d.v.scale};drag=null;return;}
   drag={zone:c.px>=c.right?'price':c.py>=232?'time':'body',x:e.clientX,y:e.clientY,w:c.w,view:d.v,center:d.center,half:d.half,count:d.count};});
  chartHost.addEventListener('pointermove',e=>{if(pinch&&pointers.has(e.pointerId)){pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});const p=[...pointers.values()];if(p.length===2)applyView({scale:pinch.scale*Math.hypot(p[0].x-p[1].x,p[0].y-p[1].y)/pinch.distance});return;}
   if(!drag||!pointers.has(e.pointerId))return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)<2)return;
   if(drag.zone==='price')applyView({pScale:drag.view.pScale*Math.exp(-dy*.005)});
   else if(drag.zone==='time')applyView({scale:drag.view.scale*Math.exp(-dx*.005)});
   else applyView({offset:drag.view.offset+Math.round(dx/Math.max(4,(drag.w-98)/Math.max(1,drag.count))),pCenter:drag.center+dy/138*2*drag.half});});
  const endPointer=e=>{pointers.delete(e.pointerId);if(pointers.size<2)pinch=null;if(!pointers.size)drag=null;};chartHost.addEventListener('pointerup',endPointer);chartHost.addEventListener('pointercancel',endPointer);
  chartHost.addEventListener('dblclick',resetView);
  const visible=()=>!document.hidden&&!page.hidden;
  const cardView=now=>coinCardView({snapshot,chart,book,symbol:selected,interval:timeframe.value,now,tickerError,chartError,bookError});
  const chartFresh=now=>cardView(now).sources.chart.available;
  const turnover=v=>finite(v)?v>=1e9?fmt(v/1e9,2)+' млрд':fmt(v/1e6,1)+' млн':'—';
  const svgNode=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
  function addText(svg,x,y,text,cls='chart-axis'){const n=svgNode('text',{x,y,class:cls});n.textContent=text;svg.append(n);}
  function drawChart(data){
   chartHost.replaceChildren();const pixels=Math.max(250,Math.round(chartHost.clientWidth)),right=pixels-78,view=getView(),bars=chartBars(data.candles,pixels,view.scale,view.offset),base=domain(bars),half=(base.high-base.low)/2/view.pScale,center=finite(view.pCenter)?view.pCenter:(base.high+base.low)/2,d={low:center-half,high:center+half},svg=svgNode('svg',{viewBox:'0 0 '+pixels+' 254',role:'img','aria-label':selected+' · свечи, уровни и оборот USDT · масштаб времени '+Math.round(view.scale*100)+'% и цены '+Math.round(view.pScale*100)+'%'});
   const x=i=>12+i*(right-20)/Math.max(1,bars.length-1),y=p=>18+(d.high-p)/(d.high-d.low)*138;
   for(let i=0;i<=4;i++){const p=d.low+(d.high-d.low)*i/4,yp=y(p);svg.append(svgNode('line',{x1:8,x2:right,y1:yp,y2:yp,class:'chart-grid'}));addText(svg,right+7,yp+3,fmt(p,8));}
   const labels=[],sides=new Set();
   for(const l of data.levels){if(l.price<d.low||l.price>d.high)continue;const yp=y(l.price),height=Math.max(2,Math.abs(y(l.low)-y(l.high)));svg.append(svgNode('rect',{x:8,y:yp-height/2,width:right-8,height,class:'zone-'+l.side}),svgNode('line',{x1:8,x2:right,y1:yp,y2:yp,class:'line-'+l.side}));if(!sides.has(l.side)&&labels.every(p=>Math.abs(p-yp)>14)){addText(svg,Math.max(10,right-104),yp-5,l.side==='support'?'Поддержка':'Сопротивление','label-'+l.side);sides.add(l.side);labels.push(yp);}}
   if(finite(data.vwap)&&data.vwap>=d.low&&data.vwap<=d.high){const yp=y(data.vwap);svg.append(svgNode('line',{x1:8,x2:right,y1:yp,y2:yp,class:'line-vwap'}));addText(svg,8,172,'VWAP '+fmt(data.vwap,8),'label-vwap');}
   for(const [id,s]of Object.entries(models)){const p=positionView(s,Date.now()/1000);if(!p?.current||p.symbol!==selected||p.entry<d.low||p.entry>d.high)continue;const yp=y(p.entry);svg.append(svgNode('line',{x1:8,x2:right,y1:yp,y2:yp,class:'line-entry'}));if(labels.every(l=>Math.abs(l-yp)>14)){addText(svg,12,yp-5,'Вход '+id+' '+p.side,'label-entry');labels.push(yp);}}
   const width=Math.max(1,Math.min(8,(right-20)/Math.max(1,bars.length-1)*.7)),maxVolume=Math.max(1,...bars.map(b=>b.turnover));
   for(const [i,b]of bars.entries()){const cls=b.close>=b.open?'candle-up':'candle-down',xp=x(i);svg.append(svgNode('line',{x1:xp,x2:xp,y1:y(b.high),y2:y(b.low),class:cls}),svgNode('rect',{x:xp-width/2,y:Math.min(y(b.open),y(b.close)),width,height:Math.max(1,Math.abs(y(b.open)-y(b.close))),class:cls}),svgNode('rect',{x:xp-width/2,y:230-b.turnover/maxVolume*38,width,height:Math.max(0,b.turnover/maxVolume*38),class:cls+' volume-bar'}));}
   addText(svg,8,188,'Оборот · USDT');addText(svg,right+7,206,fmt(maxVolume,0));
   for(const i of [0,Math.floor(bars.length/3),Math.floor(bars.length*2/3),bars.length-1])addText(svg,Math.max(8,x(i)-18),247,new Date(bars[i].time*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}));if(data.price>=d.low&&data.price<=d.high){const closeY=y(data.price);svg.append(svgNode('rect',{x:right+3,y:closeY-8,width:74,height:16,rx:2,class:'chart-close-marker'}));addText(svg,right+6,closeY+3,fmt(data.price,8),'chart-close-text');}chartHost.append(svg);
  }
  function spark(symbol,now){
   const candles=symbol===selected&&chartFresh(now),values=candles?chart.candles.slice(-24).map(b=>b.close):(priceHistory.get(symbol)||[]).filter(v=>fresh(v[0],now,180)).map(v=>v[1]);if(values.length<2)return null;
   const high=Math.max(...values),low=Math.min(...values),svg=svgNode('svg',{viewBox:'0 0 50 22',class:'coin-trend '+(values.at(-1)>=values[0]?'trend-up':'trend-down'),role:'img','aria-label':symbol+' · '+(candles?'последние закрытия свечей':'накопленные снимки цены')});
   svg.append(svgNode('polyline',{points:values.map((p,i)=>(2+i*46/(values.length-1))+','+(high===low?11:3+(high-p)/(high-low)*16)).join(' ')}));return svg;
  }
  function displayedPositions(now){return Object.entries(models).map(([id,s])=>{const p=positionView(s,now);return p?[id,p.symbol,p.side,p.entry,p.current].join(':'):id+':—';}).join('|');}
  function updateCoinTags(host,symbol,now){const tags=[];for(const [id,s]of Object.entries(models)){const p=positionView(s,now);if(p?.symbol===symbol&&p.current)tags.push(el('span','coin-tag '+(p.side==='LONG'?'tag-long':'tag-short'),id+' '+p.side));}host.replaceChildren(...tags);}
  function createTableRow(r,now){
   const tr=el('tr'),td=el('td'),cell=el('div','coin-cell'),identity=el('div'),name=el('div','coin-name-row'),button=el('button','coin-button',r.symbol),trendHost=el('span','coin-trend-host'),tags=el('div','coin-tags'),mobileTurnover=el('div','coin-mobile-facts');button.type='button';button.addEventListener('click',()=>choose(r.symbol));name.append(button,trendHost);identity.append(name,tags,mobileTurnover);cell.append(coin(r.symbol),identity);td.append(cell);tr.append(td);
   const price=el('td'),priceValue=el('span','coin-price'),mobileFacts=el('div','mobile-quote-facts'),mobileChange=el('span'),mobileSpread=el('small');mobileFacts.append(mobileChange,mobileSpread);price.append(priceValue,mobileFacts);
   const changeCell=el('td'),turnoverCell=el('td'),spreadCell=el('td'),qualityCell=el('td','quality-score');tr.append(price,changeCell,turnoverCell,spreadCell,qualityCell);
   const favoriteCell=el('td'),favorite=el('button','favorite-button'),mobileFavorite=el('button','favorite-button favorite-mobile');for(const b of [favorite,mobileFavorite]){b.type='button';b.setAttribute('aria-label','Избранное '+r.symbol);b.append(icon('star'));}const toggleFavorite=()=>toggleWatch(r.symbol);favorite.addEventListener('click',toggleFavorite);mobileFavorite.addEventListener('click',toggleFavorite);name.append(mobileFavorite);favoriteCell.append(favorite);tr.append(favoriteCell);
   const selectionDetails=el('details','selection-row'),selectionLabel=el('summary'),selectionReasons=el('div','selection-reasons');selectionDetails.append(selectionLabel,selectionReasons);td.append(selectionDetails);
   const ratingButton=el('button','rating-button');ratingButton.type='button';ratingButton.setAttribute('aria-label','Показать рейтинг '+r.symbol);selectionReasons.id='selection-reasons-'+r.symbol;ratingButton.setAttribute('aria-controls',selectionReasons.id);ratingButton.addEventListener('click',()=>{selectionDetails.open=!selectionDetails.open;ratingButton.setAttribute('aria-expanded',String(selectionDetails.open));});selectionDetails.addEventListener('toggle',()=>ratingButton.setAttribute('aria-expanded',String(selectionDetails.open)));qualityCell.append(ratingButton);
   const item={tr,button,trendHost,tags,mobileTurnover,priceValue,mobileChange,mobileSpread,changeCell,turnoverCell,spreadCell,qualityCell,ratingButton,favorite,mobileFavorite,selectionDetails,selectionLabel,selectionReasons,selectionSignature:'',lastPrice:null};updateTableRow(item,r,now);return item;
  }
  function updateTableRow(item,r,now){
   const change=(r.change>0?'+':'')+fmt(r.change)+'%',positive=r.change>=0;item.tr.className=r.symbol===selected?'selected-coin':'';item.button.setAttribute('aria-pressed',String(selected===r.symbol));item.trendHost.replaceChildren();const trend=spark(r.symbol,now);if(trend)item.trendHost.append(trend);updateCoinTags(item.tags,r.symbol,now);item.mobileTurnover.textContent='Оборот '+turnover(r.turnover)+' USDT';
   if(finite(item.lastPrice)&&finite(r.price)&&r.price!==item.lastPrice){item.priceValue.classList.remove('flash-up','flash-down');void item.priceValue.offsetWidth;item.priceValue.classList.add(r.price>item.lastPrice?'flash-up':'flash-down');}if(finite(r.price))item.lastPrice=r.price;
   const v=r.selection,grade=r.rating,previous=lastRatings.get(r.symbol),historical=!finite(r.quality)&&previous&&fresh(previous.time,now,300),rankText=finite(r.quality)?fmt(r.quality,0)+' / 100':historical?'Было '+fmt(previous.score,0):'—';item.ratingButton.title=historical?'Последний подтверждённый рейтинг · '+new Date(previous.time*1000).toLocaleTimeString('ru-RU')+' · сейчас проверяется':'Текущий подтверждённый рейтинг';item.priceValue.textContent=fmt(r.price,8);item.mobileChange.className=positive?'positive':'negative';item.mobileChange.textContent=change;item.mobileSpread.textContent='Спред '+fmt(r.spread,3)+'%';item.changeCell.className=positive?'positive':'negative';item.changeCell.textContent=change;item.turnoverCell.textContent=turnover(r.turnover);item.spreadCell.className=r.spread>.03?'negative':'';item.spreadCell.textContent=fmt(r.spread,3)+'%';item.ratingButton.textContent=rankText;item.ratingButton.setAttribute('aria-expanded',String(item.selectionDetails.open));item.qualityCell.className='quality-score '+(finite(r.quality)&&v.status==='passed'&&r.quality>=70?'positive':finite(r.quality)&&r.quality<45?'negative':'muted');for(const b of [item.favorite,item.mobileFavorite])b.setAttribute('aria-pressed',String(favorites.has(r.symbol)));
   const key=JSON.stringify([v,grade,rankText]);item.selectionDetails.dataset.state=v.status;item.selectionDetails.dataset.rating=finite(r.quality)?String(r.quality):'pending';item.selectionLabel.replaceChildren(el('span','','Отбор: '+({passed:'прошёл',pending:'проверяется',rejected:'отсев'}[v.status])),el('span','rating-compact','Рейтинг: '+(finite(r.quality)?rankText:historical?rankText+' · проверяется':'проверяется')));
   if(item.selectionSignature!==key){item.selectionSignature=key;item.selectionReasons.replaceChildren();const breakdown=el('div','rating-breakdown');breakdown.append(el('h3','','Рейтинг: '+(finite(r.quality)?rankText:historical?rankText+' · проверяется':'проверяется')));for(const c of grade.components){const part=el('div','rating-part'),caption=el('div'),values=c.values||{};caption.append(el('span','',c.label),el('b','',fmt(c.points,0)+' / 25'));part.append(caption);let detail='Ожидаем свежие данные';if(c.points!==null)detail=c.key==='liquidity'?'Оборот '+turnover(values.turnover)+' USDT':c.key==='spread'?'Худший спред '+fmt(values.worst,3)+'%':c.key==='volume'?'RVOL · 5 / 20 минут: '+fmt(values.rvol,2)+'×':'Bid / Ask от '+fmt(values.depth,0)+' USDT · impact '+fmt(values.impact,3)+'% · 5 снимков';part.append(el('small','muted',detail));breakdown.append(part);}if(grade.status!=='ok')line(breakdown,grade.note||'Ожидаем полный рейтинг');item.selectionReasons.append(breakdown);if(v.note)line(item.selectionReasons,v.note);for(const c of v.checks){const target=finite(c.min)&&finite(c.max)?fmt(c.min,4)+'–'+fmt(c.max,4):finite(c.min)?'от '+fmt(c.min,4):finite(c.max)?'до '+fmt(c.max,4):'';const value=typeof c.value==='boolean'?(c.value?'да':'нет'):fmt(c.value,4)+(c.unit?' '+c.unit:'');line(item.selectionReasons,({pass:'✓ ',fail:'✕ ',pending:'… '}[c.state]||'… ')+c.label+': '+(c.state==='pending'?'ожидаем данные':value)+(target?' · '+target+(c.unit?' '+c.unit:''):''),c.state==='fail'?'negative':c.state==='pass'?'positive':'muted');}line(item.selectionReasons,'Снимки стакана: '+Math.min(5,v.samples||0)+' / 5'+(finite(v.funding_interval_hours)?' · funding каждые '+fmt(v.funding_interval_hours,1)+' ч':''));}
  }
  function clearTableRows(){for(const item of tableRows.values())item.tr.remove();tableRows.clear();const empty=tbody.querySelector('[data-empty]');if(empty)empty.remove();}
  function patchTableRows(rows,now){
   const wanted=new Set(rows.map(r=>r.symbol));for(const [symbol,item]of tableRows)if(!wanted.has(symbol)){item.tr.remove();tableRows.delete(symbol);}const existingEmpty=tbody.querySelector('[data-empty]');if(existingEmpty)existingEmpty.remove();
   if(!rows.length){const tr=el('tr');tr.dataset.empty='true';const td=el('td','','Монет с выбранными условиями нет.');td.colSpan=7;tr.append(td);tbody.append(tr);return;}
   for(const r of rows){let item=tableRows.get(r.symbol);if(!item){item=createTableRow(r,now);tableRows.set(r.symbol,item);}else updateTableRow(item,r,now);}
   for(const [index,r]of rows.entries()){const item=tableRows.get(r.symbol),current=tbody.children[index];if(current!==item.tr)tbody.insertBefore(item.tr,current||null);}
  }
  function renderTable(now){
   renderWatch(now);
   for(const [v,b]of Object.entries(presetButtons))b.setAttribute('aria-pressed',String(v===preset.value));
   const usable=Array.isArray(snapshot?.rows)&&fresh(snapshot.updated,now,45),refreshIssue=tickerError||snapshot?.refresh_error;
   status.textContent=!snapshot||snapshot.status==='pending'?'Получаем список контрактов…':!usable?'СКРИНЕР УСТАРЕЛ · текущие цены скрыты':refreshIssue?'Bybit · последнее подтверждённое обновление '+new Date(snapshot.updated*1000).toLocaleTimeString('ru-RU')+' · повторяем обновление':'Bybit · '+new Date(snapshot.updated*1000).toLocaleTimeString('ru-RU')+' · '+fmt(now-snapshot.updated,0)+' с';status.className='screener-status'+(usable?'':' negative');
   if(!usable){clearTableRows();tableSignature='';summaryValues.coins.textContent='—';counter.textContent='Ожидание свежих котировок';selectionSummary.textContent='Умный отбор: ожидаем свежие котировки';return;}
   const coins=new Set();for(const s of Object.values(models)){const p=positionView(s,now);if(p?.current)coins.add(p.symbol);}if((bState?.feed_phase||bState?.phase)==='running'&&fresh(bState.updated,now,8))for(const r of bState.observations||[])coins.add(r.symbol);
   const verdicts=new Map((Array.isArray(selectionPacket?.rows)?selectionPacket.rows:[]).map(r=>[r.symbol,r.selection])),enriched=snapshot.rows.map(r=>{const selection=selectionView(selectionPacket?.status==='ok'?verdicts.get(r.symbol):null,selectionPacket?.source_time,snapshot.updated,now);return {...r,selection,rating:ratingView(selection,now)};});
   const counts={passed:0,pending:0,rejected:0};for(const r of enriched)counts[r.selection.status]++;selectionSummary.textContent='Отбор: прошли '+counts.passed+' · ожидают '+counts.pending+' · отсев '+counts.rejected+'. Свечи и стакан: до 8 пар, сначала наблюдение, затем по обороту с учётом поиска; остальные ждут проверки.'+(selectionError?' '+selectionError:'');
   for(const r of enriched)if(r.rating.status==='ok')lastRatings.set(r.symbol,{score:r.rating.score,time:Math.min(r.selection.ticker_time,r.selection.chart_time,r.selection.book_time)});for(const [s,v]of lastRatings)if(!fresh(v.time,now,300))lastRatings.delete(s);
   let rows=filterRows(enriched,{search:search.value,preset:preset.value,sort:sorting.value,minimum:Number(minimum.value),bots:coins,favorites,dir:sortDirs[sorting.value]}).filter(r=>selectionMode.value==='all'||r.selection.status===selectionMode.value);summaryValues.coins.textContent=String(rows.length);
   const nextKey=JSON.stringify([search.value,preset.value,sorting.value,sortDirs[sorting.value],minimum.value,selectionMode.value]);
   const reorder=!rowOrder.length||nextKey!==orderKey||orderMode.value==='live'||orderMode.value==='minute'&&now-orderedAt>=60;
   if(reorder){rowOrder=rows.map(r=>r.symbol);orderKey=nextKey;orderedAt=now;tableSignature='';saveOrder();}else{rows=stableRows(rows,rowOrder);for(const r of rows)if(!rowOrder.includes(r.symbol))rowOrder.push(r.symbol);rowOrder=rowOrder.slice(-200);}
   orderNote.textContent=orderMode.value==='live'?'Строки следуют за текущими значениями.':'Цены и баллы обновляются. '+(orderMode.value==='minute'?'Пересортировка раз в минуту.':'Строки закреплены до пересортировки.')+' Порядок от '+new Date(orderedAt*1000).toLocaleTimeString('ru-RU');
   for(const b of headerRow.querySelectorAll('.th-sort')){const on=b.dataset.sort===sorting.value;b.classList.toggle('active',on);b.setAttribute('aria-sort',on?(sortDirs[b.dataset.sort]==='asc'?'ascending':'descending'):'none');b.textContent=b.dataset.label+(on?(sortDirs[b.dataset.sort]==='asc'?' ▲':' ▼'):'');}
   const signature=[snapshot.updated,chart?.candle_end,chartFresh(now),search.value,preset.value,sorting.value,sortDirs[sorting.value],minimum.value,selected,selectionMode.value,JSON.stringify(enriched.map(r=>[r.selection,r.rating])),JSON.stringify([...lastRatings]),...favorites,displayedPositions(now),...coins].join('|');if(signature===tableSignature)return;tableSignature=signature;const savedScroll=scroll.scrollTop;
   counter.textContent=rows.length+' из '+snapshot.rows.length+' · до 100 пар по обороту · рейтинг: ликвидность + спред + объём + стакан';patchTableRows(rows,now);scroll.scrollTop=savedScroll;
   if(focusSelected){const row=tbody.querySelector('.selected-coin');if(row){const bounds=scroll.getBoundingClientRect(),r=row.getBoundingClientRect();if(r.bottom>bounds.bottom)scroll.scrollTop+=r.bottom-bounds.bottom;else if(r.top<bounds.top)scroll.scrollTop+=r.top-bounds.top;}focusSelected=false;}
  }
  function renderCard(now){
   const view=cardView(now),q=view.quote,c=view.chart,base=selected.slice(0,-4),tf=timeframe.value==='60'?'1ч':timeframe.value+'м';
   const priceText=value=>!finite(value)?'—':value>0&&value<1e-8?value.toExponential(3).replace('.',','):fmt(value,value>=1000?2:value>=1?4:value>=.01?6:8);
   panel.dataset.symbol=selected;panel.dataset.interval=timeframe.value;
   const fields={
    price:['Цена, USDT',priceText(q?.price),q&&finite(q.change)?'24ч '+(q.change>=0?'+':'')+fmt(q.change,2)+'% · оборот '+turnover(q.turnover)+' USDT':'Ожидаем свежую котировку'],
    oi:['OI, USDT',fmt(q?.oi,0),q&&q.oi!==null?'Открытый интерес · по котировке':'OI недоступен'],
    funding:['Funding',finite(q?.funding_pct)?(q.funding_pct>0?'+':'')+fmt(q.funding_pct,4)+'%':'—',q&&q.funding_pct!==null?(q.funding_hours!==null?'За интервал '+fmt(q.funding_hours,1)+' ч':'Интервал не указан биржей'):'Funding недоступен'],
    vwap:['VWAP · 60 свечей',finite(c?.vwap)?priceText(c.vwap)+' USDT':'—',c&&c.vwap!==null?'Закрытые свечи · '+tf:'VWAP недоступен'],
    atr:['ATR(14) · '+tf,finite(c?.atr)?priceText(c.atr)+' USDT':'—',finite(c?.atr_pct)?fmt(c.atr_pct,3)+'% цены · 14 свечей':'Ожидаем свежие свечи'],
    volume:['Объём · 60 свечей',finite(c?.volume)?fmt(c.volume,2)+' '+base:'—',finite(c?.turnover)?'Оборот '+turnover(c.turnover)+' USDT · '+tf:'Объём недоступен']
   };
   for(const [key,[name,value,hint]]of Object.entries(fields)){const node=cardFields[key];node.label.textContent=name;node.value.textContent=value;node.hint.textContent=hint;node.item.dataset.available=String(value!=='—');}
   const names={fresh:'свежие',cached:'повторяем обновление',stale:'устарели',pending:'загрузка',error:'недоступны',missing:'нет котировки'};
   for(const [key,source]of Object.entries(view.sources)){const node=cardSourceNodes[key];node.item.dataset.state=source.status;node.text.textContent=node.name+': '+names[source.status]+(finite(source.age)?' · '+fmt(source.age,0)+' с':'');const date=new Date(source.stamp*1000),valid=source.stamp!==null&&Number.isFinite(date.getTime());node.stamp.textContent=valid?date.toLocaleTimeString('ru-RU'):'';if(valid)node.stamp.dateTime=date.toISOString();else node.stamp.removeAttribute('datetime');node.note.textContent=source.note;}
  }
  function renderLevels(now){
   title.textContent=selected+' · '+(timeframe.value==='60'?'1 час':timeframe.value+' мин');external.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BYBIT:'+selected+'.P');updateScaleControls();
   const source=cardView(now).sources.chart,usable=source.available;chartStatus.textContent=(!usable&&chartError?chartError:!chart||chart.status==='pending'?'Загрузка закрытых свечей…':source.status==='error'?'Свечи недоступны: '+(source.note||'неверный ответ'):!usable?'СВЕЧИ УСТАРЕЛИ · уровни скрыты':(source.status==='cached'?'Последний подтверждённый анализ · ':'')+chart.candles.length+' закрытых свечей · '+new Date(chart.candle_end*1000).toLocaleString('ru-RU'));chartStatus.className='chart-stamp'+(usable?'':' negative');
   if(!usable){const unavailable='unavailable|'+chartStatus.textContent;if(chartInfoSignature!==unavailable){chartInfoSignature=unavailable;metrics.replaceChildren();levelsBox.replaceChildren();quickLevels.replaceChildren();chartHost.replaceChildren(el('p','muted','Ожидание свежего анализа.'));}chartSignature='';return;}
   const last=chart.candles.at(-1)||{},infoSignature=[selected,timeframe.value,chart.candle_end,chart.candles.length,last.time,last.open,last.high,last.low,last.close,chart.price,chart.atr_pct,chart.rvol,chart.turnover_window,JSON.stringify(chart.levels)].join('|');
   if(infoSignature!==chartInfoSignature){metrics.replaceChildren();levelsBox.replaceChildren();quickLevels.replaceChildren();for(const [key,value]of [['Цена закрытия',fmt(chart.price,8)],['RVOL по обороту · 5 / 20 свечей',fmt(chart.rvol)+'×']]){const c=el('div');c.append(el('span','muted',key),el('b','',value));metrics.append(c);}for(const [side,label]of [['support','Поддержка'],['resistance','Сопротивление']]){const group=el('div','level-group '+side),levels=chart.levels.filter(l=>l.side===side);group.append(el('h3','',label));if(!levels.length)line(group,'Подтверждённых зон в истории нет.');for(const [i,l]of levels.entries()){const row=el('div','level-item');row.append(el('b','',fmt(l.price,8)+' USDT'),el('span','muted',fmt(l.distance_pct,2)+'% от закрытия · экстремумов '+l.pivots));group.append(row);if(i===0)quickLevels.append(el('span',side,label+' '+fmt(l.price,8)));}levelsBox.append(group);}chartInfoSignature=infoSignature;}
   const signature=infoSignature+'|'+chartHost.clientWidth+'|'+JSON.stringify(getView())+'|'+displayedPositions(now);if(signature!==chartSignature){drawChart(chart);chartSignature=signature;}
  }
  let marketEvents=[];
  function renderAlerts(now){
   const events=marketEvents.filter(e=>fresh(e.time,now,86400)),current=events.slice(0,3);
   summaryValues.alerts.textContent=String(events.filter(e=>e.live).length);
   const signature=JSON.stringify(current);if(alertList.dataset.signature===signature)return;alertList.dataset.signature=signature;const wanted=new Set(current.map(e=>e.id));for(const child of [...alertList.children])if(!wanted.has(child.dataset.id))child.remove();
   if(!current.length){alertList.append(el('p','muted','Новых свежих событий сейчас нет. Действующие условия — во вкладке «Алерты».'));return;}
   for(const [index,e]of current.entries()){const existing=[...alertList.children].find(n=>n.dataset.id===e.id);if(existing){existing.dataset.live=String(!!e.live);existing.querySelector('.compact-live').textContent=e.live?'Свежесть подтверждена':'История · проверьте текущие условия';if(alertList.children[index]!==existing)alertList.insertBefore(existing,alertList.children[index]||null);continue;}const card=el('button','compact-alert'),body=el('div','compact-alert-body');card.type='button';card.dataset.kind=e.kind;body.append(el('small','compact-alert-time',new Date(e.time*1000).toLocaleTimeString('ru-RU')),el('b','',e.symbol),el('strong','fresh-kind kind-'+e.kind,e.label),el('p','compact-live',e.live?'Свежесть подтверждена':'История · проверьте текущие условия'),el('p','',e.detail));card.dataset.live=String(!!e.live);card.dataset.id=e.id;card.append(coin(e.symbol),body,icon('arrow'));card.addEventListener('click',()=>openCoin(e.symbol));alertList.insertBefore(card,alertList.children[index]||null);}
  }
  const openCoin=symbol=>document.dispatchEvent(new CustomEvent('lab-coin',{detail:{symbol,interval:'1'}}));
  document.addEventListener('lab-market-alert-feed',e=>{marketEvents=Array.isArray(e.detail)?e.detail:[];if(visible())renderAlerts(Date.now()/1000);});
  function renderBook(now){
   const source=cardView(now).sources.book,usable=source.available,signature=usable?[selected,book.updated,bookChange?.time,bState?.updated].join('|'):'unavailable|'+selected+'|'+source.status+'|'+source.note;if(signature===bookSignature)return;bookSignature=signature;
   const heading=el('div','panel-heading');heading.append(el('h2','','Стакан · '+selected),el('small','muted','Глубина ±0,1%'));bookBox.replaceChildren(heading);
   if(!usable){line(bookBox,bookError||(!book||book.status==='pending'?'Ожидание снимка стакана…':source.status==='error'?'Стакан недоступен: '+(source.note||'неверный ответ'):'СТАКАН УСТАРЕЛ · объёмы скрыты'),'negative');return;}
   const near=book.bands['0.001'],totals=el('div','book-summary');for(const [side,label]of [['bid','Покупки · Bid'],['ask','Продажи · Ask']]){const total=el('div','book-total '+side);total.append(el('span','',label),el('b','',(near.covered?'':'≥ ')+fmt(near[side],0)+' USDT'));totals.append(total);}bookBox.append(totals);if(!near.covered)line(bookBox,'Полученные уровни не покрывают всю зону: объёмы — нижняя оценка.','book-summary-note');
   const top=el('div','book-top'),max=Math.max(1,...['bid','ask'].flatMap(s=>(book.top?.[s]||[]).map(l=>l.notional)));
   for(const side of ['bid','ask']){const col=el('div');col.append(el('h3','','Цена / объём '+side));for(const l of book.top?.[side]||[]){const row=el('div','book-level '+side),bar=svgNode('svg',{viewBox:'0 0 100 20',preserveAspectRatio:'none','aria-hidden':'true'});bar.append(svgNode('rect',{width:l.notional/max*100,height:20,class:side==='bid'?'meter-buy':'meter-sell'}));row.append(bar,el('span','book-price',fmt(l.price,8)),el('span','',fmt(l.notional,0)));col.append(row);}if(!book.top?.[side]?.length)line(col,'Нет уровней');top.append(col);}bookBox.append(top);
   line(bookBox,'Mid '+fmt(book.mid,8)+' · спред '+fmt(book.spread,4)+'% · '+fmt(now-book.updated,1)+' с · REST','book-timestamp');
   const details=el('details','book-details');details.open=bookOpen;details.append(el('summary','','Глубина, крупные уровни и изменения'));details.addEventListener('toggle',()=>{if(details.isConnected)bookOpen=details.open;});
   const bands=el('div','book-bands');for(const [key,b]of Object.entries(book.bands)){const c=el('div','book-band');c.append(el('b','','±'+fmt(Number(key)*100,2)+'%'),el('span','positive','Bid '+fmt(b.bid,0)+' USDT'),el('span','negative','Ask '+fmt(b.ask,0)+' USDT'));const meter=svgNode('svg',{viewBox:'0 0 100 8','aria-label':'Объёмы bid и ask',role:'img'}),share=b.bid+b.ask?b.bid/(b.bid+b.ask):.5;meter.append(svgNode('rect',{width:share*100,height:8,class:'meter-buy'}),svgNode('rect',{x:share*100,width:(1-share)*100,height:8,class:'meter-sell'}));c.append(meter);if(!b.covered)c.append(el('small','muted','Зона не покрыта: нижняя оценка'));bands.append(c);}details.append(bands);
   if(bookChange&&fresh(bookChange.time,now,8))line(details,'За '+fmt(bookChange.seconds,1)+' с видимая глубина ±0,1%: bid '+fmt(bookChange.bid,0)+' / ask '+fmt(bookChange.ask,0)+' USDT. Включает новые заявки, отмены, исполнения и сдвиг зоны.');
   const walls=el('div','book-wall-groups');for(const [side,rows]of Object.entries(book.walls)){const group=el('div');group.append(el('h3',side==='bid'?'positive':'negative',(side==='bid'?'Покупки':'Продажи')+' · крупные уровни'));for(const w of rows)line(group,fmt(w.price,8)+' / '+fmt(w.notional,0)+' USDT');if(!rows.length)line(group,'В зоне нет уровней.');walls.append(group);}details.append(walls);
   const r=bState?.observations?.find(r=>r.symbol===selected);if((bState?.feed_phase||bState?.phase)==='running'&&fresh(bState.updated,now,8)&&fresh(r?.time,now,3)&&r.ready){const f=r.flow60;if(finite(f?.buy)&&finite(f?.sell))line(details,'Исполнено за 60 с потока B: покупки '+fmt(f.buy,0)+' / продажи '+fmt(f.sell,0)+' USDT · сделок '+fmt(f.count,0)+'.');}
   line(details,'Объёмы уровней показаны в USDT. Зоны вложены и не складываются. Крупный уровень — сумма заявок по одной цене; это не доказательство поддержки или манипуляции. Снимки REST не восстанавливают все изменения стакана.');bookBox.append(details);
  }
  function renderBots(now){
   summaryValues.models.textContent=String(Object.values(models).filter(Boolean).length);const signature=Object.entries(models).map(([id,s])=>id+JSON.stringify({...s,updated:fresh(s?.updated,now,8)?s.updated:0})).join('|');if(signature===botSignature)return;botSignature=signature;const heading=el('div','panel-heading');heading.append(el('h2','','Модели и позиции'),action('Открыть журнал','journals'));botsBox.replaceChildren(heading);
   const grid=el('div','screener-bot-grid');for(const id of ['A','B','C','D']){const s=models[id],p=positionView(s,now),active=s&&fresh(s.updated,now,8),card=el('article','screener-bot'),head=el('div','bot-heading');head.append(el('h3','','Модель '+id),el('span','bot-status '+(!active||s?.phase==='halted'?'negative':s.phase==='running'?'positive':'muted'),!s?'Нет отчёта':s.phase==='halted'?'Остановлена':!active?'Устарела':s.phase==='running'?'PAPER':s.phase==='paused'?'Отключена':s.phase==='draining'?'Завершает':'Прогрев'));card.append(head);
    const position=el('div','bot-position');if(p){position.append(el('p','position-label '+(p.current?(p.side==='LONG'?'positive':'negative'):'muted'),p.symbol+' · '+p.side+(p.current?'':' · сохранена')));const facts=el('div','position-facts');for(const [label,value]of [['Вход',fmt(p.entry,8)],['Номинал',fmt(p.notional,2)+' USDT']]){const cell=el('div','',label);cell.append(el('b','',value));facts.append(cell);}position.append(facts);}else position.append(el('p','empty-position',!active?'Нет свежего состояния':s.position?'Позиция: некорректные данные':'Открытой позиции нет'));card.append(position);
    if(s?.reason)line(card,s.reason,'bot-reason');let last=null;for(const t of s?.trades||s?.journal_trades||[])if(finite(t.closed)&&(!last||t.closed>last.closed))last=t;if(last)line(card,'Последняя: '+last.symbol+' · net '+fmt(last.net,4)+' USDT','bot-last-close');grid.append(card);
   }botsBox.append(grid);line(botsBox,'PAPER · состояния и позиции моделей. Оборот рынка и заявки стакана не являются доходностью бота.','muted');
  }
  function renderPlan(now){
   const result=planDirty?{status:'settings_error',reasons:['Настройки изменены · примените расчёт'],data:null}:paperPlan({snapshot,chart,book,selectionPacket,symbol:selected,interval:timeframe.value,now,models,settings:planSettings,tickerError,chartError,bookError});
   const data=result.data,tf=timeframe.value==='60'?'1ч':timeframe.value+'м',base=selected.slice(0,-4),number=v=>!finite(v)?'—':v!==0&&Math.abs(v)<1e-8?v.toExponential(3).replace('.',','):fmt(v,Math.abs(v)>=1000?2:Math.abs(v)>=1?4:Math.abs(v)>=.01?6:8),money=v=>finite(v)&&Math.abs(v)>=.001?fmt(v,3):number(v);
   manualDraft.disabled=result.status!=='ready';currentManualPlan=result.status==='ready'?{symbol:selected,side:data.side,low:data.low,high:data.high,stop:data.stop,target:data.targets[0].price,stamp:data.stamp,interval:timeframe.value,settings:{...planSettings},reason:'Ручной вход по плану '+tf+': EMA20/50, VWAP и подтверждённая зона'}:null;
   planBox.dataset.state=result.status;planBox.dataset.symbol=selected;planBox.dataset.interval=timeframe.value;
   planContext.textContent=selected+' · '+tf+' · капитал '+fmt(planSettings.capital,2)+' USDT · риск до '+fmt(planSettings.risk_pct,2)+'% · лимит '+fmt(planSettings.max_notional,2)+' USDT';
   const statusText=({ready:'Готов для PAPER',watch:'Ожидание входа',pending:'Проверяется',neutral:'Сценарий не найден',rejected:'План не подходит',invalidated:'Условие отменено',settings_error:'Проверьте расчёт'}[result.status]||'Проверяется')+' · '+result.reasons.join('; ');if(planStatus.textContent!==statusText)planStatus.textContent=statusText;
   const goal=index=>{const t=data?.targets[index];return [t?number(t.price):'—',t?'Прибыль '+money(t.profit)+' USDT · '+fmt(t.rr,3)+'× после издержек':data?'Нет второй подтверждённой зоны':'Ожидаем расчёт'];};
   const fields={direction:[data?.direction||'—',data?(data.side===1?'EMA20 > EMA50 · выше VWAP · рост за 5 свечей':'EMA20 < EMA50 · ниже VWAP · снижение за 5 свечей'):'Нужны согласованные закрытые свечи'],
    entry:[data?number(data.low)+'–'+number(data.high):'—','Возврат к подтверждённой зоне · '+tf],stop:[data?number(data.stop):'—','0,5 ATR за зоной входа'],target1:goal(0),target2:goal(1),
    size:[data?number(data.quantity)+' '+base:'—',data?'Номинал '+money(data.notional)+' USDT · без плеча':'Зависит от риска и лимита входа'],
    risk:[data?money(data.risk):'—',data?fmt(data.risk_pct,3)+'% капитала · бюджет '+money(data.budget)+' USDT':'Убыток по стопу с издержками и резервом funding'],
    rr:[data?fmt(data.targets[0].rr,3)+'×':'—',data?'Цель 1 · минимум '+fmt(planSettings.min_rr,2)+'×':'Прибыль / риск после всех принятых издержек']};
   for(const [key,[value,hint]]of Object.entries(fields)){const node=planFields[key];node.value.textContent=value;node.hint.textContent=hint;node.item.dataset.available=String(value!=='—');}
   planFields.direction.value.className=data?(data.side===1?'positive':'negative'):'';
   planCosts.textContent=data?'В риск включены издержки по стопу '+money(data.costs)+' USDT и резерв одного funding-платежа '+money(data.funding_reserve)+' USDT.':'Расчёт учитывает комиссию, спред, допуск проскальзывания и резерв одного funding-платежа.';
  }
  function render(){if(!visible())return;const now=Date.now()/1000;renderTable(now);renderCard(now);renderLevels(now);renderPlan(now);renderAlerts(now);renderBook(now);renderBots(now);}
  async function get(path){const res=await scope.labFetch(path);if(!res.ok)throw Error('HTTP '+res.status);return res.json();}
  const selectionQuery=()=>new URLSearchParams({...selectionFilters,search:search.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,24),watch:[...favorites].slice(0,8).join(',')}).toString();
  async function refreshSelection(){if(selectionBusy||!visible())return;selectionBusy=true;const query=selectionQuery();try{const next=await get('/api/market-selection?'+query);if(query===selectionQuery()){selectionPacket=next;selectionError=next.status==='error'?'Отбор временно недоступен':'';render();}}catch(e){if(query===selectionQuery()){selectionPacket=null;selectionError='Не удалось обновить отбор · повторяем запрос';render();}}finally{selectionBusy=false;}}
  function applySelection(reset=false){let values={...selectionDefaults};if(!reset){values={};for(const [key,{input,scale}]of Object.entries(selectionInputs)){input.setAttribute('aria-invalid','false');if(!input.checkValidity()){input.setAttribute('aria-invalid','true');selectionMessage.textContent='Проверьте поле: '+selectionFields.find(x=>x[0]===key)[1];input.focus();return;}values[key]=input.valueAsNumber*scale;}}try{selectionFilters=validateSelection(values);}catch(e){selectionMessage.textContent=e.message;return;}for(const [key,{input,scale}]of Object.entries(selectionInputs)){input.value=String(selectionFilters[key]/scale);input.setAttribute('aria-invalid','false');}try{localStorage.setItem('lab-selection-v1',JSON.stringify(selectionFilters));}catch{}selectionPacket=null;lastRatings.clear();selectionError='';selectionMessage.textContent=reset?'Пороги сброшены. Проверяем данные…':'Пороги применены. Проверяем данные…';tableSignature='';render();refreshSelection();document.dispatchEvent(new CustomEvent('lab-selection-changed'));}
  selectionApply.addEventListener('click',()=>applySelection());selectionReset.addEventListener('click',()=>applySelection(true));selectionMode.addEventListener('change',render);
  async function listPoll(){try{const next=await get('/api/screener');snapshot=next;tickerError='';if(Array.isArray(snapshot.rows)&&snapshot.updated!==tickerStamp){tickerStamp=snapshot.updated;const symbols=new Set();for(const r of snapshot.rows){if(!safeSymbol(r.symbol)||!finite(r.price))continue;symbols.add(r.symbol);let h=priceHistory.get(r.symbol)||[];if(h.length&&snapshot.updated-h.at(-1)[0]>45)h=[];h.push([snapshot.updated,r.price]);priceHistory.set(r.symbol,h.slice(-40));}for(const s of priceHistory.keys())if(!symbols.has(s))priceHistory.delete(s);}render();}catch(e){tickerError='Скринер недоступен: '+e.message;render();}finally{setTimeout(listPoll,2000);}}
  async function detailPoll(repeat=true){const token=generation,s=selected,interval=timeframe.value;try{const results=await Promise.allSettled([get('/api/market-chart?symbol='+encodeURIComponent(s)+'&interval='+interval),get('/api/market-book?symbol='+encodeURIComponent(s))]);if(token!==generation)return;for(const [i,r]of results.entries()){if(i===0){if(r.status==='fulfilled'){chart=r.value;chartError='';}else chartError='Свечи недоступны: '+r.reason.message;}else{if(r.status==='fulfilled'){book=r.value;bookError='';if(book?.status==='ok'&&book.symbol===s&&book.updated!==previousBook?.updated){const now=Date.now()/1000;if(previousBook?.symbol===s&&previousBook.status==='ok'&&book.updated>previousBook.updated&&book.updated-previousBook.updated<=12&&fresh(book.updated,now,8)){const b=book.bands['0.001'],p=previousBook.bands['0.001'];bookChange={time:book.updated,seconds:book.updated-previousBook.updated,bid:b.bid-p.bid,ask:b.ask-p.ask};}else bookChange=null;previousBook=book;}}else bookError='Стакан недоступен: '+r.reason.message;}}render();}finally{if(repeat)setTimeout(detailPoll,2000);}}
  async function botPoll(){try{const results=await Promise.allSettled(['/api/paper','/api/model-b','/api/research','/api/signals'].map(get)),states=results.map(r=>r.status==='fulfilled'?r.value:null);models=botModels(...states);bState=states[1];researchState=states[2];wState=states[3];render();}finally{setTimeout(botPoll,2000);}}
  function choose(symbol){if(!safeSymbol(symbol))return;selected=symbol;focusSelected=true;try{localStorage.setItem('lab-selected-coin',symbol);}catch{}generation++;chart=null;book=null;previousBook=null;bookChange=null;chartError='';bookError='';chartSignature='';chartInfoSignature='';bookSignature='';render();detailPoll(false);}
  search.addEventListener('input',()=>{render();refreshSelection();document.dispatchEvent(new CustomEvent('lab-selection-changed'));});preset.addEventListener('change',render);minimum.addEventListener('change',render);sorting.addEventListener('change',()=>{mobileSort.value=sorting.value;render();});mobileSort.addEventListener('change',()=>{sorting.value=mobileSort.value;render();});
  document.addEventListener('lab-coin',e=>{const symbol=e.detail?.symbol;if(safeSymbol(symbol)){if(e.detail.interval==='1'){timeframe.value='1';for(const [v,n]of Object.entries(timeButtons))n.setAttribute('aria-pressed',String(v==='1'));}go('market');choose(symbol);panel.scrollIntoView({block:'start',behavior:'smooth'});}});
  expand.addEventListener('click',()=>document.dispatchEvent(new CustomEvent('lab-symbol',{detail:selected})));
  document.addEventListener('lab-tab',e=>{if(e.detail==='market'){render();detailPoll(false);refreshSelection();}});document.addEventListener('visibilitychange',()=>{if(visible()){render();detailPoll(false);refreshSelection();}});window.addEventListener('resize',()=>{chartSignature='';render();});setInterval(render,1000);setInterval(refreshSelection,2000);listPoll();botPoll();detailPoll();refreshSelection();
 });
})(typeof window==='undefined'?globalThis:window);
