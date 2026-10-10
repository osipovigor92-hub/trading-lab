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
 function assistantView(value,sourceTime,tickerTime,now){
  const pending=note=>({status:'pending',score:null,indicators:{},score_components:[],setup:'waiting',reasons:[note],missing:[note],eligible:null});
  if(!value||value.status!=='ok'||sourceTime!==tickerTime||!fresh(tickerTime,now,45))return pending('Ожидаем анализ свежих котировок');
  if(!value.sources||value.sources.quote!==tickerTime||!fresh(value.sources.chart,now,75)||!fresh(value.sources.candle,now,120)||value.candle_end!==value.sources.candle||value.timeframe!=='1'||value.sources.chart<value.sources.candle||value.sources.chart-value.sources.candle>=60||Math.abs(value.sources.chart-tickerTime)>45)return pending('Анализ устарел · повторяем проверку');
  const parts=value.score_components,keys=['volume','range','movement','turnover'],caps=[40,30,20,10],v=value.indicators;
  if(!Number.isInteger(value.score)||value.score<0||value.score>100||!Array.isArray(parts)||parts.length!==4||new Set(parts.map(p=>p?.key)).size!==4||parts.some(p=>!keys.includes(p?.key)||p.max!==caps[keys.indexOf(p.key)]||!Number.isInteger(p.points)||p.points<0||p.points>p.max)||parts.reduce((s,p)=>s+p.points,0)!==value.score||!v||!['rsi14','ema20','ema50','vwap60','atr14','atr14_pct','rvol5','change5_pct','range5_pct'].every(k=>finite(v[k])))return pending('Ожидаем полные измерения');
  return value;
 }
 function chartReady(chart,symbol,interval,now){
  const step=Number(interval)*60,bars=chart?.candles;return ['1','5','15','60'].includes(interval)&&chart?.status==='ok'&&chart.symbol===symbol&&chart.interval===interval&&!chart.error&&!chart.refresh_error&&fresh(chart.updated,now,75)&&fresh(chart.candle_end,now,step+75)&&chart.updated>=chart.candle_end&&chart.updated-chart.candle_end<step&&Array.isArray(bars)&&bars.length>=60&&bars.length<=180&&bars.every((b,i)=>b&&['time','open','high','low','close','volume','turnover'].every(k=>finite(b[k]))&&b.time%step===0&&b.low>0&&b.low<=Math.min(b.open,b.close)&&b.high>=Math.max(b.open,b.close)&&b.volume>=0&&b.turnover>=0&&(!i||b.time-bars[i-1].time===step))&&bars.at(-1).time+step===chart.candle_end;
 }
 function assistantRows(rows,{search='',preset='all',minimum=0,minScore=0,sort='score',favorites=new Set()}={}){
  return rows.filter(r=>safeSymbol(r.symbol)&&r.symbol.includes(search.toUpperCase())&&finite(r.turnover)&&r.turnover>=minimum&&(!minScore||finite(r.assistant?.score)&&r.assistant.score>=minScore)&&(preset==='all'||preset==='favorites'&&favorites.has(r.symbol)||preset==='active'&&r.assistant?.activity==='active'&&r.assistant.eligible===true||preset==='breakout'&&r.assistant?.setup?.startsWith('breakout_')||preset==='momentum'&&r.assistant?.setup?.startsWith('momentum_'))).sort((a,b)=>(sort==='turnover'?b.turnover-a.turnover:sort==='change'?Math.abs(b.change)-Math.abs(a.change):(b.assistant?.score??-1)-(a.assistant?.score??-1))||b.turnover-a.turnover||a.symbol.localeCompare(b.symbol));
 }
 function indicatorSeries(bars){
  const out={ema20:[],ema50:[],vwap60:[]};
  for(const n of [20,50]){let value=null;bars.forEach((b,i)=>{if(i===n-1)value=bars.slice(0,n).reduce((s,x)=>s+x.close,0)/n;else if(i>=n)value+=(b.close-value)*2/(n+1);out['ema'+n].push(value);});}
  bars.forEach((b,i)=>{const window=bars.slice(Math.max(0,i-59),i+1),volume=window.reduce((s,x)=>s+x.volume,0);out.vwap60.push(i>=59&&volume>0?window.reduce((s,x)=>s+x.turnover,0)/volume:null);});return out;
 }
 function riskEstimate({capital,risk,entry,stop,target,side=1,fee=.055,slippage=.05}){
  if(![capital,risk,entry,stop,target,fee,slippage].every(finite)||capital<10||capital>1e6||risk<=0||risk>5||entry<=0||stop<=0||target<=0||![1,-1].includes(side)||side*(entry-stop)<=0||side*(target-entry)<=0||fee<0||fee>1||slippage<0||slippage>5)return null;
  const cost=entry*(fee+slippage)*2/100,loss=side*(entry-stop)+cost,reward=side*(target-entry)-cost,budget=capital*risk/100,quantity=Math.min(budget/loss,capital/(entry*(1+(fee+slippage)/100)));
  const result={quantity,notional:quantity*entry,loss:quantity*loss,rr:reward/loss,reward:quantity*reward};return Object.values(result).every(finite)&&quantity>0&&result.loss>0&&result.loss<=budget*(1+1e-12)?result:null;
 }
 const api={stableRows,fresh,ratingScore,ratingView,coinCardView,paperPlan,planDefaults,validatePlan,filterRows,botModels,positionView,domain,chartBars,barCount,selectionDefaults,validateSelection,selectionView,assistantView,assistantRows,indicatorSeries,riskEstimate,chartReady};
 if(typeof module!=='undefined')module.exports=api;
 if(typeof document==='undefined')return;
 scope.LabScreener=api;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-market');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const button=(label,cls='secondary-button',handler)=>{const b=el('button',cls,label);b.type='button';if(handler)b.addEventListener('click',handler);return b;};
  const store=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v));}catch{health.textContent='Сохранение недоступно · настройки действуют до закрытия страницы';}};
  const read=(k,fallback)=>{try{return JSON.parse(localStorage.getItem(k))??fallback;}catch{return fallback;}};
  const saved=read('lab-favorites-v1',[]),favorites=new Set(Array.isArray(saved)?saved.filter(safeSymbol).slice(0,8):[]);
  let filters;try{filters=validateSelection(read('lab-selection-v1',{}));}catch{filters={...selectionDefaults};}
  let snapshot=null,packet=null,chart=null,quoteError='',chartError='',selected=read('lab-selected-coin','BTCUSDT'),interval='1',generation=0,selectionGeneration=0,quoteBusy=false,selectionBusy=false,detailBusy=false,order=[],mode='stable',scale=1,offset=0,observations=[],lastDetail=0;
  if(!safeSymbol(selected))selected='BTCUSDT';
  const priorOrder=read('lab-screener-order-v1',{});if(Array.isArray(priorOrder.order))order=priorOrder.order.filter(safeSymbol);mode=priorOrder.mode==='auto'?'auto':'stable';
  const heading=el('div','screener-heading');heading.append(el('div','', ''),el('span','screener-session','USDT perpetual · закрытые свечи'));
  heading.firstChild.append(el('h1','','Поиск торговых сетапов'),el('p','muted','Найдите активность. Закрепите монеты. Проверьте сигнал и риск.'));page.append(heading);
  const controls=el('form','screener-controls'),search=el('input');search.type='search';search.placeholder='Монета или тикер…';search.setAttribute('aria-label','Поиск монеты');search.maxLength=24;
  const select=(label,options)=>{const n=el('select');n.setAttribute('aria-label',label);for(const [value,text]of options){const o=el('option','',text);o.value=value;n.append(o);}return n;};
  const preset=select('Сценарий поиска',[['all','Все монеты'],['active','Активный объём'],['breakout','Пробой уровня'],['momentum','Импульс'],['favorites','Мои монеты']]);
  const minScore=select('Минимум активности',[[0,'Активность: любая'],[40,'Активность ≥ 40'],[60,'Активность ≥ 60'],[80,'Активность ≥ 80']]);
  const turnover=select('Минимум оборота',[[0,'Оборот: любой'],[2e7,'Оборот ≥ 20 млн'],[5e7,'Оборот ≥ 50 млн'],[1e8,'Оборот ≥ 100 млн']]);turnover.value=String([0,2e7,5e7,1e8].includes(filters.turnover_min)?filters.turnover_min:2e7);
  const find=button('Найти сетапы','primary-button');find.type='submit';controls.append(search,preset,minScore,turnover,find);page.append(controls);
  const filterDetails=el('details','screener-filter-details');filterDetails.append(el('summary','','Пороги ликвидности'));const spreadLabel=el('label','','Максимальный спред, %'),spreadInput=el('input');spreadInput.type='number';spreadInput.min='0';spreadInput.max='10';spreadInput.step='.01';spreadInput.value=String(filters.spread_max);spreadInput.setAttribute('aria-label','Максимальный спред');spreadLabel.append(spreadInput);filterDetails.append(spreadLabel,el('p','muted','Сетапы требуют достаточного оборота и спреда. Индекс активности измеряет объём и движение; высокий балл сам по себе не подтверждает вход.'));page.append(filterDetails);
  const meta=el('div','screener-meta'),health=el('span','muted','Загружаем котировки…');health.id='screener-health';health.setAttribute('role','status');
  const sorting=select('Сортировка монет',[['score','По активности'],['turnover','По обороту'],['change','По изменению 24ч']]);sorting.value=['score','turnover','change'].includes(priorOrder.sort)?priorOrder.sort:'score';
  const modeButton=button('Порядок: закреплён','screener-order'),resort=button('Пересортировать','screener-order');meta.append(health,sorting,modeButton,resort);page.append(meta);
  const grid=el('div','screener-grid'),watchPanel=el('aside','screener-watch screener-panel'),watchHead=el('div','screener-panel-heading'),watchCount=el('small','muted');watchHead.append(el('h2','','Мои монеты'),watchCount);watchPanel.append(watchHead,el('p','muted','До 8 монет · анализ в приоритете'));const watchList=el('div','screener-watch-list');watchPanel.append(watchList);
  const tablePanel=el('section','screener-results screener-panel'),tableHead=el('div','screener-panel-heading'),resultsCount=el('small','muted');tableHead.append(el('h2','','Скринер'),resultsCount);const analysisNote=el('p','muted analysis-note','Проверяем до 8 монет одновременно. Остальные ожидают анализа.');tablePanel.append(tableHead,analysisNote);
  const scroll=el('div','screener-table-scroll'),table=el('table');table.id='screener-table';table.setAttribute('aria-label','Монеты и активность');const thead=el('thead'),tr=el('tr');for(const text of ['Монета','Цена','24ч','Активн.','RVOL','RSI','Спред','Сценарий'])tr.append(el('th','',text));thead.append(tr);const tbody=el('tbody');table.append(thead,tbody);scroll.append(table);tablePanel.append(scroll);
  const detail=el('section','screener-detail screener-panel'),detailHead=el('div','screener-panel-heading'),detailTitle=el('h2'),detailWatch=button('Наблюдать','screener-order',()=>toggleWatch(selected));detailHead.append(detailTitle,detailWatch);const priceLine=el('div','screener-price'),priceValue=el('strong'),priceChange=el('span');priceLine.append(priceValue,priceChange);
  const timeframes=el('div','screener-timeframes');for(const [value,text]of [['1','1м'],['5','5м'],['15','15м'],['60','1ч']]){const b=button(text,'screener-order',()=>{interval=value;generation++;chart=null;scale=1;offset=0;lastDetail=0;render();refreshDetail();});b.dataset.interval=value;timeframes.append(b);}
  const canvas=el('canvas');canvas.id='screener-chart';canvas.setAttribute('role','img');canvas.setAttribute('aria-label','Свечной график выбранной монеты');canvas.tabIndex=0;
  const chartBox=el('div','screener-chart-box'),chartTools=el('div','screener-chart-tools');chartTools.append(button('−','screener-order',()=>zoom(.8)),button('+','screener-order',()=>zoom(1.25)),button('К последней свече','screener-order',()=>{scale=1;offset=0;drawChart();}));chartBox.append(canvas,chartTools);
  const legend=el('p','screener-chart-legend','EMA20 · EMA50 · VWAP60'),chartNote=el('p','muted screener-chart-note'),signal=el('div','screener-signal'),signalLabel=el('strong'),signalText=el('p','muted');signal.append(signalLabel,signalText);
  const groups=el('div','screener-indicator-groups'),metricNodes=new Map();
  for(const [title,fields]of [['Тренд',[['ema20','EMA20'],['ema50','EMA50'],['vwap60','VWAP · 60 свечей']]],['Объём и движение',[['rvol5','RVOL 5 / 20'],['rsi14','RSI14'],['atr14_pct','ATR14, %'],['change5_pct','Изменение 5м, %']]],['Ликвидность',[['turnover','Оборот 24ч'],['spread','Спред, %'],['funding','Funding, %']]]]){const group=el('div','screener-indicator-group');group.append(el('h3','',title));for(const [key,text]of fields){const row=el('div','screener-metric'),v=el('b','','—');row.append(el('span','',text),v);metricNodes.set(key,v);group.append(row);}groups.append(group);}
  const scoreBox=el('div','screener-score'),scoreHead=el('div','screener-panel-heading'),scoreValue=el('strong','','— / 100');scoreHead.append(el('h3','','Индекс активности'),scoreValue);const scoreParts=el('div'),scoreNote=el('p','muted','Баллы за объём, диапазон, движение и оборот. Не вероятность прибыли.');scoreBox.append(scoreHead,scoreParts,scoreNote);
  const reasonDetails=el('details','screener-reasons');reasonDetails.append(el('summary','','Почему этот сценарий'));const reasons=el('ul');reasonDetails.append(reasons);
  const levels=el('div','screener-levels');
  detail.append(detailHead,priceLine,timeframes,chartBox,legend,chartNote,signal,groups,levels,scoreBox,reasonDetails);
  const riskBox=el('details','screener-risk');riskBox.append(el('summary','','Калькулятор риска'));const riskFields=el('form','screener-risk-fields'),riskInputs={};
  for(const [key,text,value]of [['capital','Капитал, USDT',600],['risk','Риск, %',.5],['entry','Вход',null],['stop','Стоп',null],['target','Цель',null],['fee','Комиссия за сторону, %',.055],['slippage','Проскальзывание за сторону, %',.05]]){const label=el('label','',text),input=el('input');input.type='number';input.min='0';input.step='any';input.setAttribute('aria-label',text);if(value!==null)input.value=value;label.append(input);riskInputs[key]=input;riskFields.append(label);}
  const direction=select('Направление расчёта',[[1,'LONG'],[-1,'SHORT']]),riskResult=el('p','muted');riskResult.setAttribute('role','status');riskFields.append(direction);riskBox.append(riskFields,riskResult,el('p','muted','Расчёт по заданным ценам, с комиссией и проскальзыванием. Уточните свои тарифы; funding и глубина исполнения в этой оценке не учтены.'));riskFields.addEventListener('submit',e=>e.preventDefault());riskFields.addEventListener('input',calculateRisk);riskFields.addEventListener('change',calculateRisk);detail.append(riskBox);
  const prepare=button('Подготовить ручной PAPER-вход','secondary-button',()=>{const values=Object.fromEntries(Object.entries(riskInputs).map(([k,n])=>[k,Number(n.value)])),side=Number(direction.value),pad=values.entry*.0002;const draft={symbol:selected,side,low:values.entry-pad,high:values.entry+pad,stop:values.stop,target:values.target,stamp:chart.candle_end,interval,settings:{capital:values.capital,risk_pct:values.risk,max_notional:Math.min(100,values.capital),fee_pct:values.fee,slippage_pct:values.slippage,min_rr:1.5},reason:'Ручной сценарий '+selected+' по заданным уровням'};document.dispatchEvent(new CustomEvent('lab-paper-draft',{detail:draft}));scope.LabNavigation.activate('positions');});prepare.disabled=true;riskBox.append(prepare,el('p','muted','PAPER: зона ±0,02% от заданного входа, лимит 100 USDT, минимум прибыль / риск 1,5. На следующем экране проверьте и подтвердите вход. Сервер пересчитает риск и исполнение.'));
  riskBox.insertBefore(button('Взять текущую цену','screener-order',()=>{const row=allRows(Date.now()/1000).find(r=>r.symbol===selected);if(row){riskInputs.entry.value=row.price;calculateRisk();}}),riskFields);
  const journal=el('section','screener-journal screener-panel'),journalHead=el('div','screener-panel-heading');journalHead.append(el('h2','','События наблюдения'),button('Все алерты','text-button',()=>scope.LabNavigation.activate('alerts')));const eventList=el('div','screener-events');journal.append(journalHead,el('p','muted','События остаются в истории после завершения актуальности.'),eventList);const leftWork=el('div','screener-left-work');leftWork.append(watchPanel,tablePanel,journal);grid.append(leftWork,detail);page.append(grid);
  const rowsBySymbol=new Map(),watchNodes=new Map();
  const setupNames={momentum_up:'Импульс ↑',momentum_down:'Импульс ↓',breakout_up:'Пробой ↑',breakout_down:'Пробой ↓',watch:'Наблюдать',waiting:'Ожидание'};
  const millions=n=>finite(n)?fmt(n/1e6,1)+' млн':'—',price=n=>fmt(n,n<1?8:n<100?4:2),change=n=>finite(n)?(n>0?'+':'')+fmt(n,2)+'%':'—';
  const visible=()=>!document.hidden&&!page.hidden;
  function query(){return new URLSearchParams({...filters,search:search.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,24),watch:[...favorites].join(',')}).toString();}
  function persistOrder(){store('lab-screener-order-v1',{mode,sort:sorting.value,order});}
  function toggleWatch(symbol,on=!favorites.has(symbol)){
   if(!safeSymbol(symbol))return;if(on&&!favorites.has(symbol)&&favorites.size>=8){health.textContent='В наблюдении уже 8 монет · уберите одну для добавления';return;}
   if(on)favorites.add(symbol);else favorites.delete(symbol);store('lab-favorites-v1',[...favorites]);changed();
  }
  function changed(){selectionGeneration++;packet=null;store('lab-selection-v1',filters);document.dispatchEvent(new CustomEvent('lab-selection-changed'));render();refreshSelection();}
  function openCoin(symbol){if(!safeSymbol(symbol))return;selected=symbol;store('lab-selected-coin',symbol);generation++;chart=null;chartError='';scale=1;offset=0;lastDetail=0;for(const key of ['entry','stop','target'])riskInputs[key].value='';scope.LabNavigation.activate('market');render();refreshDetail();}
  function allRows(now){if(!snapshot||snapshot.status!=='ok'||snapshot.refresh_error||quoteError||!fresh(snapshot.updated,now,45))return [];
   const map=new Map((packet?.status==='ok'&&Array.isArray(packet.rows)?packet.rows:[]).map(r=>[r.symbol,r.assistant]));return (Array.isArray(snapshot.rows)?snapshot.rows:[]).filter(r=>safeSymbol(r.symbol)).map(r=>({...r,assistant:assistantView(map.get(r.symbol),packet?.source_time,snapshot.updated,now)}));}
  function render(){const now=Date.now()/1000,all=allRows(now),rows=assistantRows(all,{search:search.value,preset:preset.value,minimum:Number(turnover.value),minScore:Number(minScore.value),sort:sorting.value,favorites}),ordered=mode==='stable'?stableRows(rows,order):rows;
   if(mode==='stable'){for(const row of ordered)if(!order.includes(row.symbol))order.push(row.symbol);order=order.slice(-300);persistOrder();}
   health.textContent=quoteError?'Котировки недоступны · повторяем запрос':!all.length?'Ожидаем свежие котировки': 'Котировки '+new Date(snapshot.updated*1000).toLocaleTimeString('ru-RU')+' · обновление 5с';health.dataset.status=all.length?'ok':'pending';
   modeButton.textContent='Порядок: '+(mode==='stable'?'закреплён':'авто');modeButton.setAttribute('aria-pressed',String(mode==='stable'));resultsCount.textContent=rows.length+' монет';analysisNote.textContent='Свежий анализ: '+all.filter(r=>r.assistant.status==='ok').length+' · одновременно до '+(packet?.analysis_limit||8)+' монет · избранные в приоритете';
   const keep=new Set(ordered.map(r=>r.symbol));for(const [s,node]of rowsBySymbol)if(!keep.has(s)){node.tr.remove();rowsBySymbol.delete(s);}tbody.querySelector('[data-empty]')?.remove();
   for(const [i,r]of ordered.entries()){let item=rowsBySymbol.get(r.symbol);if(!item){const tr=el('tr');tr.dataset.symbol=r.symbol;const first=el('td'),star=button('☆','screener-star',()=>toggleWatch(r.symbol)),open=button(r.symbol.replace('USDT',''),'screener-coin coin-button',()=>openCoin(r.symbol));open.setAttribute('aria-label','Открыть '+r.symbol);first.append(star,open,el('small','muted',' / USDT'));tr.append(first);const cells=[];for(let n=0;n<7;n++){const td=el('td');tr.append(td);cells.push(td);}item={tr,star,cells};rowsBySymbol.set(r.symbol,item);}const a=r.assistant,v=a.indicators;item.tr.classList.toggle('selected-coin',r.symbol===selected);item.star.textContent=favorites.has(r.symbol)?'★':'☆';item.star.setAttribute('aria-label',favorites.has(r.symbol)?'Убрать '+r.symbol+' из наблюдения':'Наблюдать '+r.symbol);item.star.setAttribute('aria-pressed',String(favorites.has(r.symbol)));
    const values=[price(r.price),change(r.change),finite(a.score)?String(a.score):'—',finite(v.rvol5)?fmt(v.rvol5,2)+'×':'—',fmt(v.rsi14,1),fmt(r.spread,3)+'%',setupNames[a.setup]||'Ожидание'];values.forEach((text,n)=>{item.cells[n].textContent=text;});item.cells[1].className=r.change>=0?'positive':'negative';item.cells[2].className=finite(a.score)?'activity-score':'';item.cells[6].className='setup-cell '+a.setup;item.cells[2].title=a.status==='ok'?'Индекс активности · 0–100':a.reasons?.join('; ');if(tbody.children[i]!==item.tr)tbody.insertBefore(item.tr,tbody.children[i]||null);
   }
   if(!ordered.length){const row=el('tr');row.dataset.empty='true';const cell=el('td','screener-empty',all.length?'Нет монет по этим фильтрам. Снизьте пороги или выберите «Все монеты».':'Ждём данные Bybit. Последние сигналы сохранены в истории.');cell.colSpan=8;row.append(cell);tbody.append(row);}
   renderWatch(all);renderDetail(all,now);renderEvents();
  }
  function renderWatch(all){watchCount.textContent=favorites.size+' / 8';const map=new Map(all.map(r=>[r.symbol,r]));watchList.querySelector('.screener-empty')?.remove();for(const [s,n]of watchNodes)if(!favorites.has(s)){n.remove();watchNodes.delete(s);}for(const [i,s]of [...favorites].entries()){let node=watchNodes.get(s);if(!node){node=button('','screener-watch-item',()=>openCoin(s));node.dataset.symbol=s;node.append(el('strong','',s.replace('USDT','')),el('b'),el('small','muted'));watchNodes.set(s,node);}const r=map.get(s);node.querySelector('b').textContent=r?change(r.change):'—';node.querySelector('b').className=r?.change>=0?'positive':'negative';node.querySelector('small').textContent=r?.assistant?.status==='ok'?(setupNames[r.assistant.setup]+' · '+r.assistant.score):'Ожидание данных';node.classList.toggle('selected',s===selected);if(watchList.children[i]!==node)watchList.insertBefore(node,watchList.children[i]||null);}if(!favorites.size)watchList.append(el('p','screener-empty','Нажмите ☆ у монеты, чтобы следить за её сетапами.'));}
  function renderDetail(all,now){const row=all.find(r=>r.symbol===selected),a=row?.assistant||assistantView(null,null,null,now),v=a.indicators;
   detail.dataset.symbol=selected;detail.dataset.interval=interval;detailTitle.textContent=selected.replace('USDT','')+' / USDT';detailWatch.textContent=favorites.has(selected)?'★ В наблюдении':'☆ Наблюдать';detailWatch.setAttribute('aria-pressed',String(favorites.has(selected)));detailWatch.setAttribute('aria-label',favorites.has(selected)?'Убрать '+selected+' из наблюдения':'Наблюдать '+selected);priceValue.textContent=row?price(row.price):'—';priceChange.textContent=row?change(row.change)+' за 24ч':'Нет свежей котировки';priceChange.className=row?.change>=0?'positive':'negative';
   for(const b of timeframes.children){b.classList.toggle('selected',b.dataset.interval===interval);b.setAttribute('aria-pressed',String(b.dataset.interval===interval));}
   signalLabel.textContent=setupNames[a.setup]||'Ожидание анализа';signal.dataset.setup=a.setup;signalText.textContent=a.status==='ok'?'Сценарий 1м · закрытие '+new Date(a.candle_end*1000).toLocaleTimeString('ru-RU')+(a.eligible?' · ликвидность в пределах порогов':' · ликвидность вне порогов'):a.reasons.join('; ');
   for(const [key,node]of metricNodes){node.textContent=key==='turnover'?millions(row?.turnover):key==='spread'?fmt(row?.spread,3):key==='funding'?finite(row?.funding)?fmt(row.funding*100,4):'—':finite(v[key])?fmt(v[key],['ema20','ema50','vwap60'].includes(key)?v[key]<1?8:4:2)+(key==='rvol5'?'×':''):'—';}
   scoreValue.textContent=(finite(a.score)?a.score:'—')+' / 100';const signature=JSON.stringify(a.score_components);if(scoreParts.dataset.signature!==signature){scoreParts.dataset.signature=signature;scoreParts.replaceChildren();for(const p of a.score_components){const item=el('div','screener-score-part'),caption=el('div');caption.append(el('span','',p.label),el('b','',p.points+' / '+p.max));const bar=el('div','screener-score-track'),fill=el('span');fill.style.width=p.points/p.max*100+'%';bar.append(fill);item.title=p.formula+' · '+fmt(p.value,3)+' / '+fmt(p.cap,3);item.append(caption,bar);scoreParts.append(item);}}
   const reasonSig=JSON.stringify(a.reasons);if(reasons.dataset.signature!==reasonSig){reasons.dataset.signature=reasonSig;reasons.replaceChildren(...a.reasons.map(r=>el('li','',r)));}
   const validChart=!chartError&&chartReady(chart,selected,interval,now);
   chartNote.textContent=validChart?'Закрытые '+(interval==='60'?'часовые':interval+'м')+' свечи · '+new Date(chart.candle_end*1000).toLocaleTimeString('ru-RU')+' · сигнал оценивается на 1м':chartError||'Ожидаем свежие закрытые свечи';chartNote.dataset.status=validChart?'ok':'pending';
   levels.replaceChildren();if(validChart&&Array.isArray(chart.levels)){const close=chart.levels.filter(l=>finite(l.price)).sort((a,b)=>Math.abs(a.price-row?.price)-Math.abs(b.price-row?.price)).slice(0,2);for(const level of close)levels.append(el('div','screener-metric', (level.side==='support'?'Поддержка: ':'Сопротивление: ')+price(level.low)+' – '+price(level.high)));}
   drawChart(validChart);calculateRisk();
  }
  function calculateRisk(){const values=Object.fromEntries(Object.entries(riskInputs).map(([k,n])=>[k,n.value===''?null:Number(n.value)])),result=riskEstimate({...values,side:Number(direction.value)});riskResult.textContent=result?'Объём '+fmt(result.quantity,6)+' монет · '+fmt(result.notional)+' USDT · риск '+fmt(result.loss)+' USDT · прибыль / риск '+fmt(result.rr,2):'Укажите вход, стоп и цель в выбранном направлении.';riskResult.dataset.status=result?'ok':'pending';const pad=values.entry*.0002,side=Number(direction.value),row=allRows(Date.now()/1000).find(r=>r.symbol===selected);prepare.disabled=!(result&&result.rr>=1.5&&values.slippage>=0&&values.risk>=.01&&row&&Math.abs(row.price-values.entry)<=pad&&side*(values.entry-side*pad-values.stop)>0&&side*(values.target-values.entry-side*pad)>0&&chartNote.dataset.status==='ok');}
  function renderEvents(){const entries=observations.slice(0,6),keep=new Set(entries.map(e=>e.id));for(const n of [...eventList.children])if(!keep.has(n.dataset.id))n.remove();for(const [i,e]of entries.entries()){let node=[...eventList.children].find(n=>n.dataset.id===e.id);if(!node){node=button('','screener-event',()=>openCoin(e.symbol));node.dataset.id=e.id;node.dataset.kind=e.kind;node.append(el('time','muted',new Date(e.time*1000).toLocaleTimeString('ru-RU')),el('b','',e.symbol.replace('USDT','')),el('span','',e.label),el('small','muted'));node.title=e.detail;}node.dataset.live=String(!!e.live);node.querySelector('small').textContent=e.live?'Актуально':'История';if(eventList.children[i]!==node)eventList.insertBefore(node,eventList.children[i]||null);}if(!entries.length)eventList.append(el('p','screener-empty','Новых событий пока нет. Добавьте монеты в наблюдение.'));}
  function zoom(factor){scale=clamp(scale*factor,.3,8);drawChart();}
  let lastChartRender='';
  function drawChart(valid=chartNote.dataset.status==='ok'){
   const renderKey=JSON.stringify([valid,chart?.updated,chart?.candle_end,chart?.symbol,chart?.interval,canvas.clientWidth,scale,offset]);if(lastChartRender===renderKey)return;lastChartRender=renderKey;
   const rect=canvas.getBoundingClientRect();if(rect.width<=0)return;const width=Math.round(rect.width),height=230,dpr=Math.min(window.devicePixelRatio||1,2);canvas.width=width*dpr;canvas.height=height*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#10171f';ctx.fillRect(0,0,width,height);if(!valid||!Array.isArray(chart?.candles)||!chart.candles.length){ctx.fillStyle='#a4b5c8';ctx.font='12px Segoe UI';ctx.textAlign='center';ctx.fillText('Ожидание свечей',width/2,height/2);return;}
   const bars=chartBars(chart.candles,width,scale,offset),bounds=domain(bars),left=7,right=65,top=10,bottom=height-48,plotWidth=Math.max(40,width-left-right),step=plotWidth/bars.length,x=i=>left+(i+.5)*step,y=p=>top+(bounds.high-p)/(bounds.high-bounds.low)*(bottom-top);
   ctx.font='10px Segoe UI';for(let i=0;i<5;i++){const pos=top+i*(bottom-top)/4;ctx.strokeStyle='#263340';ctx.beginPath();ctx.moveTo(left,pos);ctx.lineTo(width-right,pos);ctx.stroke();ctx.fillStyle='#a4b5c8';ctx.textAlign='left';ctx.fillText(price(bounds.high-i*(bounds.high-bounds.low)/4),width-right+5,pos+3);}
   const maxVolume=Math.max(...bars.map(b=>b.volume),1);bars.forEach((b,i)=>{const color=b.close>=b.open?'#35cc98':'#ec6a74';ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(x(i),y(b.high));ctx.lineTo(x(i),y(b.low));ctx.stroke();ctx.fillStyle=color;ctx.fillRect(x(i)-Math.max(1,step*.28),Math.min(y(b.open),y(b.close)),Math.max(2,step*.56),Math.max(1,Math.abs(y(b.close)-y(b.open))));ctx.globalAlpha=.38;ctx.fillRect(x(i)-step*.28,height-25-b.volume/maxVolume*18,Math.max(2,step*.56),b.volume/maxVolume*18);ctx.globalAlpha=1;});
   const series=indicatorSeries(chart.candles),start=chart.candles.indexOf(bars[0]);for(const [key,color]of [['ema20','#4bd0f5'],['ema50','#a78bcc'],['vwap60','#e9bc68']]){ctx.strokeStyle=color;ctx.lineWidth=1.3;ctx.beginPath();let begun=false;bars.forEach((b,i)=>{const v=series[key][start+i];if(!finite(v))return;const py=y(v);if(!begun){ctx.moveTo(x(i),py);begun=true;}else ctx.lineTo(x(i),py);});ctx.stroke();}ctx.lineWidth=1;ctx.fillStyle='#a4b5c8';ctx.textAlign='left';ctx.fillText(new Date(bars[0].time*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),left,height-4);ctx.textAlign='right';ctx.fillText(new Date(bars.at(-1).time*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'}),width-right,height-4);
  }
  let drag=null;canvas.addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();zoom(e.deltaY<0?1.15:1/1.15);},{passive:false});canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,offset};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag||!chart)return;const count=barCount(canvas.clientWidth,scale,chart.candles.length);offset=clamp(drag.offset+(e.clientX-drag.x)*count/Math.max(50,canvas.clientWidth-65),0,chart.candles.length-count);drawChart();});canvas.addEventListener('pointerup',()=>drag=null);canvas.addEventListener('pointercancel',()=>drag=null);canvas.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','+','-','Home'].includes(e.key)){e.preventDefault();if(e.key==='+'||e.key==='-')zoom(e.key==='+'?1.25:.8);else{offset=e.key==='Home'?0:Math.max(0,offset+(e.key==='ArrowLeft'?5:-5));drawChart();}}});
  async function refreshQuotes(){if(quoteBusy||!visible())return;quoteBusy=true;try{const next=await scope.labJson('/api/screener',{},'Котировки');if(next.status!=='ok')throw Error('Ожидаем котировки');snapshot=next;quoteError='';}catch(e){quoteError=e.message;}finally{quoteBusy=false;render();refreshSelection();}}
  async function refreshSelection(){if(selectionBusy||!visible())return;selectionBusy=true;const q=query(),g=selectionGeneration;try{const next=await scope.labJson('/api/market-selection?'+q,{},'Анализ');if(q===query()&&g===selectionGeneration)packet=next;}catch{if(g===selectionGeneration)packet=null;}finally{selectionBusy=false;render();}}
  async function refreshDetail(){if(detailBusy||!visible())return;detailBusy=true;const g=generation,s=selected,i=interval;try{const next=await scope.labJson('/api/market-chart?'+new URLSearchParams({symbol:s,interval:i}),{},'График');if(g!==generation||s!==selected||i!==interval)return;if(next.status!=='ok')throw Error('Свечи пока недоступны');chart=next;chartError='';lastDetail=Date.now();}catch(e){if(g===generation){chart=null;chartError=e.message;}}finally{detailBusy=false;render();if(g!==generation)refreshDetail();}}
  let searchTimer;search.addEventListener('input',()=>{search.value=search.value.toUpperCase().replace(/[^A-Z0-9]/g,'');render();clearTimeout(searchTimer);searchTimer=setTimeout(changed,250);});controls.addEventListener('submit',e=>{e.preventDefault();changed();refreshQuotes();refreshDetail();});for(const n of [preset,minScore])n.addEventListener('change',render);turnover.addEventListener('change',()=>{filters.turnover_min=Number(turnover.value);changed();});spreadInput.addEventListener('change',()=>{const v=Number(spreadInput.value);if(spreadInput.value===''||!finite(v)||v<0||v>10){spreadInput.value=filters.spread_max;return;}filters.spread_max=v;changed();});sorting.addEventListener('change',()=>{persistOrder();render();});modeButton.addEventListener('click',()=>{mode=mode==='stable'?'auto':'stable';persistOrder();render();});resort.addEventListener('click',()=>{order=[];render();});
  document.addEventListener('lab-watch',e=>toggleWatch(e.detail?.symbol,true));document.addEventListener('lab-coin',e=>openCoin(e.detail?.symbol));document.addEventListener('lab-market-alert-feed',e=>{observations=Array.isArray(e.detail)?e.detail:[];renderEvents();});document.addEventListener('lab-tab',()=>{if(visible()){render();refreshQuotes();refreshDetail();}});document.addEventListener('visibilitychange',()=>{if(visible()){render();refreshQuotes();refreshDetail();}});window.addEventListener('storage',e=>{if(e.key==='lab-favorites-v1'){favorites.clear();for(const s of read(e.key,[]).filter(safeSymbol).slice(0,8))favorites.add(s);changed();}});new ResizeObserver(()=>drawChart()).observe(canvas);
  setInterval(()=>{if(visible()){refreshQuotes();if(Date.now()-lastDetail>=7000)refreshDetail();}},5000);setInterval(()=>{if(visible())render();},1000);render();refreshQuotes();refreshDetail();
 });
})(typeof window==='undefined'?globalThis:window);
