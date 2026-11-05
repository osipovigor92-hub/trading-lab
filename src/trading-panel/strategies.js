/* Current assistant setups from the existing public-market monitor. */
(() => {
 'use strict';
 const setups={breakout_up:'Пробой вверх',breakout_down:'Пробой вниз',momentum_up:'Импульс вверх',momentum_down:'Импульс вниз'};
 const limits={quote:45,chart:75,candle:120},finite=Number.isFinite;
 const fresh=(time,now,limit)=>finite(time)&&now-time>=-2&&now-time<=limit;
 const time=new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC',hour:'2-digit',minute:'2-digit',second:'2-digit'});
 const clock=value=>finite(value)?time.format(value*1000)+' UTC':'—';
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-strategies'),monitor=window.LabMarketAlerts;if(!page||!monitor)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const heading=el('div','page-heading');heading.append(el('h2','','Стратегии'),el('p','muted','Пробои и импульсы на Bybit по закрытым свечам 1м. Список использует до восьми монет из текущего наблюдения и фильтров скринера.'));
  const section=el('section','box strategy-section'),toolbar=el('div','strategy-toolbar'),title=el('h3','','Текущие условия');
  const control=(label,options)=>{const wrapper=el('label','strategy-filter',label),select=el('select');select.setAttribute('aria-label',label);
   for(const [key,text]of options){const option=el('option','',text);option.value=key;select.append(option);}wrapper.append(select);toolbar.append(wrapper);return select;};
  toolbar.append(title);
  const kind=control('Сценарий стратегии',[['all','Все сценарии'],['breakout','Пробой'],['momentum','Импульс'],['watch','Наблюдение']]);
  const direction=control('Направление стратегии',[['all','Любое'],['LONG','LONG'],['SHORT','SHORT'],['none','Без сигнала']]);
  const status=el('p','strategy-status muted','Ожидаем данные монитора.');status.setAttribute('role','status');
  const rows=el('div','strategy-rows');section.append(toolbar,status,rows);
  const rules=el('details','box strategy-rules');rules.append(el('summary','','Условия пробоя и импульса'));
  const terms=el('dl');
  for(const [label,body]of [
   ['Пробой','Первое закрытие за диапазоном предыдущих 20 минут с буфером 0,1 ATR14. Относительный объём ≥ 1,5. После удаления цены дальше 1,5 ATR14 — наблюдение.'],
   ['Импульс','EMA20/50 и VWAP60 согласованы с направлением. Относительный объём ≥ 1,5, диапазон 5м ≥ 0,2%, движение по направлению ≥ 0,1%.'],
   ['Подтверждение','Для LONG или SHORT нужны свежая котировка, подтверждённая закрытая свеча и соблюдение порогов ликвидности. Причина и отмена показываются для действующего сигнала.']
  ]){const item=el('div');item.append(el('dt','',label),el('dd','muted',body));terms.append(item);}
  rules.append(terms);page.append(heading,section,rules);
  let signature='',expiryTimer;
  function render(){
   clearTimeout(expiryTimer);if(page.hidden||document.hidden)return;
   const now=Date.now()/1000,{packet,error}=monitor.conditions?.()||{},connected=!error&&packet?.status==='ok'&&fresh(packet.updated,now,5);
   const active=new Set(connected&&Array.isArray(packet.analyzing)?packet.analyzing.slice(0,8):[]),seen=new Set(),current=[];
   let deadline=connected?packet.updated+5:Infinity;
   for(const row of connected&&Array.isArray(packet.rows)?packet.rows:[]){
    const symbol=row?.symbol;if(typeof symbol!=='string'||!/^[A-Z0-9]{2,24}USDT$/.test(symbol)||!active.has(symbol)||seen.has(symbol))continue;seen.add(symbol);
    const a=row.assistant,valid=a?.status==='ok'&&a.exchange==='bybit'&&a.timeframe==='1'&&a.sources?.candle===a.candle_end&&Object.entries(limits).every(([key,limit])=>fresh(a.sources?.[key],now,limit));
    const rec=valid?monitor.currentRecommendation(row,now):null;
    if(valid)deadline=Math.min(deadline,...Object.entries(limits).map(([key,limit])=>a.sources[key]+limit),rec?.expires??Infinity);
    current.push({symbol,setup:rec?a.setup:'watch',label:rec?setups[a.setup]:valid?'Наблюдение':'Ждём подтверждения',direction:rec?.direction||'none',
     score:valid&&finite(a.score)?a.score:null,close:valid?a.candle_end:null,expires:rec?.expires??null,
     reason:rec?.reason||(valid&&Array.isArray(a.reasons)?a.reasons.filter(x=>typeof x==='string').slice(0,3).join('; '):'Нет свежей подтверждённой котировки или закрытой свечи.'),
     invalidation:rec?.invalidation||''});
   }
   const visible=current.filter(row=>(kind.value==='all'||row.setup.startsWith(kind.value))&&(direction.value==='all'||row.direction===direction.value));
   const message=error?'Монитор недоступен. Ожидаем свежий ответ.':!connected?'Ожидаем свежий ответ монитора.':current.length?('Подтверждено '+current.filter(row=>row.direction!=='none').length+' · монет в наблюдении '+current.length+' из 8'):'Нет монет для анализа. Измените фильтры или добавьте монету в наблюдение.';
   if(status.textContent!==message)status.textContent=message;
   status.dataset.status=connected?'ok':'unavailable';
   const next=JSON.stringify([visible,connected,current.length]);
   if(next!==signature){
    signature=next;const fragment=el('div');
    for(const row of visible){
     const article=el('div','strategy-row');article.dataset.key=row.symbol;article.dataset.symbol=row.symbol;article.dataset.direction=row.direction;
     const coin=el('button','text-button strategy-coin',row.symbol.replace(/USDT$/,'')+' / USDT');coin.type='button';coin.dataset.coin=row.symbol;coin.setAttribute('aria-label','Открыть '+row.symbol+' в скринере');
     const summary=el('div','strategy-setup');summary.append(el('b',row.direction==='LONG'?'positive':row.direction==='SHORT'?'negative':'',row.direction==='none'?row.label:row.direction+' · '+row.label),el('small','muted',row.close?'Свеча '+clock(row.close):'Свеча не подтверждена'));
     const score=el('span','strategy-score muted',row.score===null?'Активность —':'Активность '+row.score+' / 100');
     const details=el('details','strategy-proof');details.append(el('summary','','Основание'));
     details.append(el('p','muted',row.reason||'Подтверждённого направления сейчас нет.'));
     if(row.expires)details.append(el('p','muted','Действует до '+clock(row.expires)));
     if(row.invalidation)details.append(el('p','','Отмена: '+row.invalidation));
     article.append(coin,summary,score,details);fragment.append(article);
    }
    if(!visible.length&&current.length)fragment.append(el('p','strategy-empty muted','Нет монет по выбранным фильтрам.'));
    LabUI.syncChildren(rows,fragment);
   }
   if(finite(deadline))expiryTimer=setTimeout(render,Math.max(20,(deadline-now)*1000+10));
  }
  rows.addEventListener('click',event=>{const coin=event.target.closest('button[data-coin]');if(coin)document.dispatchEvent(new CustomEvent('lab-coin',{detail:{symbol:coin.dataset.coin}}));});
  kind.addEventListener('change',render);direction.addEventListener('change',render);
  for(const event of ['lab-market-conditions','lab-tab','visibilitychange'])document.addEventListener(event,render);
  window.addEventListener('pagehide',()=>clearTimeout(expiryTimer));render();
 });
})();
