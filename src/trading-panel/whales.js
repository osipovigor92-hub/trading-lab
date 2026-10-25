/* Separate executed prints from displayed liquidity. No order actions. */
(function(scope){
 const labels={large_trade:'Крупная сделка',large_wall:'Крупная заявка',wall_missing:'Плотность исчезла'};
 function visibleEvents(packet,minimum,kind,now){
  if(!Number.isFinite(minimum)||minimum<50000||!Array.isArray(packet?.events))return [];
  return packet.events.filter(e=>labels[e.kind]&&(kind==='all'||kind===e.kind)&&typeof e.id==='string'&&Number.isFinite(e.notional)&&(e.kind==='large_trade'?e.notional>=minimum:Number.isFinite(e.size_multiple)&&e.size_multiple>=10)&&Number.isFinite(e.time)&&now-e.time>=-2&&now-e.time<=300);
 }
 if(typeof module!=='undefined')module.exports={visibleEvents};
 if(typeof document==='undefined')return;
 document.addEventListener('DOMContentLoaded',()=>{
  const page=document.getElementById('page-alerts');if(!page)return;
  const el=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
  const box=el('section','box whale-monitor'),head=el('h2','','Крупные сделки и заявки'),health=el('p','muted','Подключаем наблюдение…');health.setAttribute('role','status');
  const controls=el('div','screener-risk-fields'),label=el('label','','Минимум для исполненных сделок, USDT'),minimum=el('input');minimum.type='number';minimum.min='50000';minimum.step='10000';minimum.value='100000';minimum.setAttribute('aria-label','Порог крупных событий, USDT');
  try{const saved=Number(localStorage.getItem('lab-whale-min'));if(Number.isFinite(saved)&&saved>=50000)minimum.value=String(saved);}catch{}
  label.append(minimum);const kind=el('select');kind.setAttribute('aria-label','Тип крупного события');for(const [value,text]of Object.entries({all:'Все крупные события',...labels})){const o=el('option','',text);o.value=value;kind.append(o);}
  const sound=el('button','secondary-button','Звук крупных событий: выключен');sound.type='button';sound.setAttribute('aria-pressed','false');controls.append(label,kind,sound);
  const note=el('p','muted','Лента исполнений Bybit. Заявки: от ×10 среднего остальных уровней той же стороны, без порога суммы. Объём не определяет владельца. Исчезновение заявки не доказывает исполнение.'),feed=el('div','whale-feed');
  box.append(head,health,controls,note,feed);page.append(box);
  let packet=null,busy=false,error='',epoch=null,cursor=0,audio=null,soundOn=false,lastSuccess=0;
  const money=v=>v.toLocaleString('ru-RU',{maximumFractionDigits:0});
  function render(){
   if(page.hidden||document.hidden)return;
   const now=Date.now()/1000,connected=!error&&packet&&now-packet.updated<=8,coverage=Object.values(packet?.coverage||{}),ready=coverage.filter(v=>v.fresh&&now-v.checked<=30).length;
   health.textContent=connected?'Лента: '+ready+' / '+(packet.targets?.length||0)+' монет · последние 1000 исполнений, возможны пропуски':'Нет свежего ответа монитора';
   if(packet?.persistence_error)health.textContent+=' · состояние не сохраняется';
   if(coverage.some(v=>v.gap||v.window_full))health.textContent+=' · окно ленты заполнено, полнота не подтверждена';
   const value=Number(minimum.value),events=visibleEvents(packet,value,kind.value,now),body=document.createDocumentFragment();
   if(!Number.isFinite(value)||value<50000)body.append(el('p','muted','Минимальный порог — 50 000 USDT.'));
   else if(!events.length)body.append(el('p','muted','Подходящих наблюдений за последние 5 минут нет.'));
   for(const e of events){const row=el('article','fresh-event');row.dataset.whaleId=e.id;const current=connected&&now-e.time<=30;
    row.append(el('strong','',labels[e.kind]+' · '+e.symbol+' · '+money(e.notional)+' USDT'+(e.kind!=='large_trade'?' · ×'+e.size_multiple.toFixed(1):'')),el('p','muted',(e.exchange||'')+' · '+(e.kind==='large_trade'?(e.side==='Buy'?'Покупка taker':'Продажа taker'):(e.side==='bid'?'Заявки покупки':'Заявки продажи'))+' · цена '+e.price+' · '+new Date(e.time*1000).toLocaleTimeString('ru-RU')+(current?'':' · история')));
    if(e.kind!=='large_trade')row.append(el('p','muted','Среднее остальных уровней этой стороны: '+money(e.baseline_notional)+' USDT · уровней: '+e.baseline_levels));
    if(e.kind==='wall_missing')row.append(el('p','muted','Аномальный уровень отсутствует в двух снимках. Причина — отмена или исполнение — неизвестна.'));
    body.append(row);
   }
   LabUI.syncChildren(feed,body);
  }
  function beep(){if(!audio||!soundOn)return;try{const o=audio.createOscillator(),g=audio.createGain();o.connect(g);g.connect(audio.destination);g.gain.setValueAtTime(.04,audio.currentTime);o.start();o.stop(audio.currentTime+.12);}catch{}}
  sound.addEventListener('click',async()=>{try{audio??=new (window.AudioContext||window.webkitAudioContext)();await audio.resume();soundOn=!soundOn;sound.textContent='Звук крупных событий: '+(soundOn?'включён':'выключен');sound.setAttribute('aria-pressed',String(soundOn));}catch{sound.textContent='Звук недоступен';}});
  minimum.addEventListener('input',()=>{try{if(Number(minimum.value)>=50000)localStorage.setItem('lab-whale-min',minimum.value);}catch{}render();});kind.addEventListener('change',render);
  async function poll(){if(busy)return;busy=true;try{const next=await scope.labJson('/api/whales',{background:true},'Крупные события'),now=Date.now()/1000;if(next.status!=='ok'||!Number.isFinite(next.updated)||Math.abs(now-next.updated)>8)throw Error('stale');
    const newEvents=visibleEvents(next,Number(minimum.value),kind.value,now).filter(e=>now-e.time<=30&&Number(e.id.split(':').pop())>cursor);
    if(epoch===next.epoch&&now-lastSuccess<=8&&newEvents.length)beep();
    epoch=next.epoch;cursor=next.cursor;lastSuccess=now;packet=next;error='';
   }catch{error='unavailable';lastSuccess=0;}finally{busy=false;render();}}
  setInterval(poll,2000);setInterval(render,1000);poll();
 });
})(typeof window!=='undefined'?window:globalThis);
