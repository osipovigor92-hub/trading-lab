/* Versioned research screeners. No orders, positions or fabricated returns. */
(function(scope){
'use strict';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const fresh=(t,now,max)=>finite(t)&&now-t>=-1&&now-t<=max;
const VERSION='2026-10-02.1';
const CATALOG=[
 {name:'Freqtrade',plan:'Бесплатный открытый Python-бот',url:'https://github.com/freqtrade/freqtrade',docs:'https://www.freqtrade.io/en/stable/strategy-101/',feature:'Backtesting, dry-run, веб-интерфейс и проверка lookahead/recursive bias. Подходит для воспроизводимых индикаторных стратегий по свечам.',fit:'Приоритет для следующего этапа тестирования EMA, RSI, Bollinger и объёмных фильтров. Это инструментарий, а не готовая прибыльная стратегия.'},
 {name:'Hummingbot',plan:'Открытый framework · Apache 2.0',url:'https://github.com/hummingbot/hummingbot',docs:'https://hummingbot.org/strategies/',feature:'Стратегии по стакану, market making, управление заявками и коннекторы бирж. Есть paper-trade для поддерживаемых сценариев.',fit:'Полезен для изучения исполнения и спреда. Поддержку Bybit и конкретного paper-режима нужно проверять отдельно; риск запасов и неблагоприятных исполнений остаётся.'},
 {name:'Jesse',plan:'Бесплатное открытое ядро исследований · MIT',url:'https://github.com/jesse-ai/jesse',docs:'https://jesse.trade/pricing',feature:'Python-стратегии, историческое тестирование и исследовательский модуль. Бесплатная оптимизация имеет ограничения по CPU.',fit:'Подходит как альтернативный движок исследований. Live-trading plugin платный: полностью бесплатной live-заменой здесь не считается.'}
];
function evaluate(id,s,r,now){
 const c=r?.chart||{},checks=[];
 const add=(label,pass)=>checks.push({label,pass:pass===true});
 const validPrice=finite(r?.price)&&r.price>0;
 const validChart=['price','ema20','ema50','atr','vwap60'].every(k=>finite(c[k])&&c[k]>0)&&finite(c.rvol5)&&c.rvol5>=0;
 const validCost=finite(r?.roundtrip_pct)&&r.roundtrip_pct>0;
 const band=r?.bands?.['0.0005'];
 const bandValid=finite(band?.bid)&&finite(band?.ask)&&band.bid>=0&&band.ask>=0&&band.bid+band.ask>0;
 const imbalance=bandValid?(band.bid-band.ask)/(band.bid+band.ask):null;
 const flow=seconds=>{const f=r?.['flow'+seconds];return f&&finite(f.buy)&&finite(f.sell)&&f.buy>=0&&f.sell>=0&&finite(f.count)&&Number.isInteger(f.count)&&f.count>=0&&f.buy+f.sell>0?{total:f.buy+f.sell,ratio:(f.buy-f.sell)/(f.buy+f.sell),count:f.count}:null;};
 const f5=flow(5),f15=flow(15);
 add('Работающий источник; состояние ≤8 с, стакан ≤3 с',s?.phase==='running'&&fresh(s.updated,now,8)&&fresh(r?.time,now,3));
 add('Прогрев завершён; последняя сделка ≤10 с',r?.ready===true&&finite(r.trade_age)&&r.trade_age>=0&&r.trade_age+Math.max(0,now-s?.updated)<=10);
 add('Корректные цены и закрытые свечи ≤120 с',validPrice&&validChart&&!r?.chart_error&&fresh(c.end,now,120));
 add('Спред ≤0,025%; расходы оборота известны',finite(r?.spread)&&r.spread>=0&&r.spread<=.025&&validCost);
 add('Зона ±0,05% покрыта; обе стороны ≥5 000 USDT',bandValid&&band.covered===true&&Math.min(band.bid,band.ask)>=5000);
 add('Лента 15 с: ≥1 500 USDT и ≥10 сделок',!!f15&&f15.total>=1500&&f15.count>=10);
 add('До funding больше 300 с',finite(c.next_funding)&&c.next_funding-now>300);
 let side=0;
 if(id==='C'){
  side=c.side===1?1:c.side===-1?-1:0;
  add('Тренд EMA/VWAP согласован с текущей ценой',validChart&&validPrice&&side!==0&&side*(c.ema20-c.ema50)>0&&side*(r.price-c.vwap60)>0);
  add('RVOL5 ≥1,5: активность выше часовой базы',validChart&&c.rvol5>=1.5);
  const impulse=validChart&&validPrice?side*(r.price-c.price)/c.atr:NaN;
  add('Импульс от последнего закрытия: 0,15–1 ATR',finite(impulse)&&impulse>=.15&&impulse<=1);
  add('ATR / цена ≥1,5 × расходы (фильтр масштаба)',validChart&&validPrice&&validCost&&c.atr/r.price*100>=1.5*r.roundtrip_pct);
 }else if(id==='D'){
  side=validChart&&validPrice?Math.sign(c.vwap60-r.price):0;
  add('Боковик: |EMA20−EMA50| ≤0,25 ATR; RVOL5 ≤1,2',validChart&&Math.abs(c.ema20-c.ema50)<=.25*c.atr&&c.rvol5<=1.2);
  const distance=validChart&&validPrice?Math.abs(r.price-c.vwap60)/c.atr:NaN;
  add('Отклонение от VWAP60: 0,75–2 ATR',finite(distance)&&distance>=.75&&distance<=2);
  add('Есть движение к VWAP от последнего закрытия',validChart&&validPrice&&side*(r.price-c.price)>0);
  add('Дистанция до VWAP ≥2 × расходы (не прогноз прибыли)',validChart&&validPrice&&validCost&&Math.abs(r.price-c.vwap60)/r.price*100>=2*r.roundtrip_pct);
 }else throw new Error('Unknown research model');
 add('Стакан ±0,05%: перевес ≥15% в сторону гипотезы',bandValid&&side!==0&&side*imbalance>=.15);
 add('OFI5 подтверждает направление',finite(r?.ofi5)&&side*r.ofi5>0);
 add('Лента: перевес 5 с ≥30%, 15 с ≥20%',!!f5&&!!f15&&side*f5.ratio>=.3&&side*f15.ratio>=.2);
 return {id,version:VERSION,side,checks,pass:checks.every(c=>c.pass),reasons:checks.filter(c=>!c.pass).map(c=>c.label)};
}
function confirm(previous,result,tick,now){
 if(!result.pass||!fresh(tick,now,3))return {side:0,count:0,last:tick,start:tick,confirmed:false};
 if(previous&&tick===previous.last)return previous;
 const continued=previous&&previous.side===result.side&&tick>previous.last&&tick-previous.last<=6;
 const next={side:result.side,count:continued?previous.count+1:1,last:tick,start:continued?previous.start:tick};
 next.confirmed=next.count>=3&&tick-next.start>=4;return next;
}
const api={evaluate,confirm,VERSION,CATALOG};if(typeof module!=='undefined')module.exports=api;
if(typeof document==='undefined')return;
document.addEventListener('DOMContentLoaded',()=>{
 const page=document.getElementById('page-research');if(!page)return;
 const make=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';n.textContent=text||'';return n;};
 const p=(parent,text,cls='muted')=>parent.append(make('p',cls,text));
 const link=(parent,text,url)=>{const a=make('a','research-link',text+' ↗');a.href=url;a.target='_blank';a.rel='noopener noreferrer';parent.append(a);};
 const hero=make('section','box');hero.append(make('small','eyebrow','ИССЛЕДОВАНИЯ / ВЕРСИЯ '+VERSION),make('h2','','Боты, индикаторы и новые гипотезы'));
 p(hero,'Открытый код позволяет проверить правила, но не подтверждает преимущество над A/B. Сравниваем инструменты и проверяем собственные условия на текущем потоке.');
 p(hero,'C и D — диагностические наблюдатели в браузере. Они не открывают PAPER-позиции, не имеют доходности и не входят в журнал сделок A/B. Закрытие страницы прекращает наблюдение.');page.append(hero);
 const intro=make('section','box');intro.append(make('h2','','C / Импульс в тренде · D / Возврат к VWAP'));
 p(intro,'C: направление EMA20/50 и VWAP + повышенный RVOL + импульс + лента/стакан. D: сближенные EMA + отклонение от VWAP + начало возврата + лента/стакан.');
 p(intro,'Пороговые значения — исходные исследовательские настройки, не результат оптимизации. Три разных снимка за ≥4 с подтверждают только устойчивость условий. ATR не предсказывает будущую прибыль.');
 const status=make('p','muted','Ожидание данных'),list=make('div','research-live');intro.append(status,list);page.append(intro);
 const details=make('details','box');details.append(make('summary','','Определения индикаторов и план проверки'));
 p(details,'EMA20/50 — экспоненциальные средние минутных закрытий; ATR14 — сглаженный истинный диапазон. VWAP60 здесь — оборот / количество за 60 закрытых минут, а не сессионный VWAP TradingView. RVOL5 — средний минутный оборот последних 5 закрытых минут / средний за предыдущие 60. Это не стандартный RVOL10 TradingView.');
 p(details,'OFI — изменения лучших уровней, лента — исполненные сделки. Это разные признаки. Большая заявка может исчезнуть; наблюдение не доказывает намерение участника.');
 p(details,'Перед сравнением доходности: отдельный серверный PAPER-исполнитель и журнал для C/D, единые расходы и номинал с A/B, фиксированная версия правил, последующие данные в тренде и боковике. Сравнивать net, просадку, средний результат, число сделок и разрывы данных; учитывать число проверенных вариантов. Пока эти этапы не выполнены, статус — «преимущество не проверено».');
 link(details,'VWAP: TradingView','https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/');link(details,'ATR: TradingView','https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/');link(details,'RVOL: TradingView','https://www.tradingview.com/support/solutions/43000635874-how-do-we-calculate-relative-volume-and-relative-volume-at-time/');link(details,'Исследование OFI · акции, не проверка нашей криптомодели','https://arxiv.org/abs/1011.6402');link(details,'Риск подгонки backtest','https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf');page.append(details);
 const catalog=make('section','box');catalog.append(make('h2','','Известные бесплатные инструменты'));
 p(catalog,'Официальные источники проверены 02.10.2026. Бесплатный код не отменяет расходы на сервер, данные и биржевые комиссии. Здесь каталог и ссылки: движки не установлены, API-ключи не подключены. У Jesse бесплатна исследовательская часть; live-плагин платный.');
 const grid=make('div','research-catalog');for(const item of CATALOG){const card=make('article','');card.append(make('h3','',item.name));p(card,item.plan,'');p(card,item.feature,'');p(card,item.fit);link(card,'Исходный код',item.url);link(card,'Документация',item.docs);grid.append(card);}catalog.append(grid);p(catalog,'Известные семейства правил для отдельных тестов: EMA + импульс; RSI/Bollinger + возврат к средней; market making с контролем позиции. C/D ниже — наши собственные упрощённые гипотезы на текущем потоке, а не запущенные Freqtrade/Hummingbot/Jesse.');link(catalog,'Открытые примеры Freqtrade','https://github.com/freqtrade/freqtrade-strategies');link(catalog,'Проверка заглядывания в будущее','https://www.freqtrade.io/en/stable/lookahead-analysis/');page.append(catalog);
 let data=null;const confirmations=new Map(),opened=new Set();
 function render(){
  const now=Date.now()/1000;list.querySelectorAll('details').forEach(d=>{if(d.open)opened.add(d.dataset.key);else opened.delete(d.dataset.key);});list.replaceChildren();
  if(!data||!fresh(data.updated,now,8)||data.phase!=='running'){status.textContent='Нет свежего работающего источника B. Условия C/D не подтверждены.';confirmations.clear();return;}
  const rows=Array.isArray(data.observations)?data.observations:[];status.textContent='Источник B · '+rows.length+' монет · '+new Date(data.updated*1000).toLocaleTimeString('ru-RU')+' · диагностический режим';
  const keys=new Set();for(const r of rows){if(!r||typeof r.symbol!=='string')continue;for(const id of ['C','D']){
   const result=evaluate(id,data,r,now),key=id+':'+r.symbol;keys.add(key);const state=confirm(confirmations.get(key),result,r.time,now);confirmations.set(key,state);
   const card=make('article','research-card'+(state.confirmed?' research-match':''));card.append(make('small','eyebrow','ГИПОТЕЗА '+id+' / '+(id==='C'?'ТРЕНД':'ВОЗВРАТ')),make('h3','',r.symbol+' · '+(result.side===1?'LONG':result.side===-1?'SHORT':'НЕТ НАПРАВЛЕНИЯ')));
   p(card,state.confirmed?'Совпадение условий · НЕ вход':result.pass?'Подтверждение снимками: '+state.count+' · нужно ≥3 за ≥4 с':'Ожидание · не выполнено '+result.reasons.length+' условий',state.confirmed?'research-highlight':'muted');
   const d=make('details','');d.dataset.key=key;d.open=opened.has(key);d.append(make('summary','','Все условия · '+result.checks.filter(c=>c.pass).length+'/'+result.checks.length));
   for(const c of result.checks)p(d,(c.pass?'✓ ':'○ ')+c.label,c.pass?'positive':'muted');card.append(d);list.append(card);
  }}for(const key of confirmations.keys())if(!keys.has(key))confirmations.delete(key);
 }
 async function poll(){try{const r=await (scope.labFetch||fetch)('/api/model-b');if(!r.ok)throw Error('HTTP '+r.status);data=await r.json();}catch{data=null;}render();setTimeout(poll,2000);}
 poll();setInterval(()=>{if(!document.hidden)render();},1000);
});
})(globalThis);
