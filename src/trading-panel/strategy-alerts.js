/* Server strategy history. No automatic trading or browser-generated signals. */
document.addEventListener('DOMContentLoaded',()=>{
 const root=document.getElementById('page-alerts');if(!root)return;
 const box=document.createElement('section');box.className='box';
 const title=document.createElement('h3');title.textContent='Сигналы стратегий';
 const status=document.createElement('p');status.setAttribute('role','status');
 const list=document.createElement('div');box.append(title,status,list);root.append(box);
 let busy=false,last='',primed=false,audio=null,soundEnabled=false;
 const heard=new Set(),sound=document.createElement('button');sound.type='button';sound.className='secondary-button';sound.textContent='Включить звук сигналов';sound.setAttribute('aria-pressed','false');box.insertBefore(sound,status);
 sound.addEventListener('click',async()=>{try{if(!soundEnabled){const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)throw Error('Звук не поддерживается');audio=audio||new Audio();await audio.resume();}soundEnabled=!soundEnabled;sound.setAttribute('aria-pressed',String(soundEnabled));sound.textContent=soundEnabled?'Выключить звук сигналов':'Включить звук сигналов';}catch{status.textContent='Браузер не разрешил звук. Повтори нажатие.';}});
 function notify(events,live,now){let ring=false;for(const event of events){if(typeof event.id!=='string')continue;if(primed&&live&&!heard.has(event.id)&&event.expires>=now&&now-event.time>=0&&now-event.time<=30)ring=true;heard.add(event.id);}while(heard.size>500)heard.delete(heard.values().next().value);primed=true;
  if(ring&&soundEnabled&&audio?.state==='running'){const oscillator=audio.createOscillator(),gain=audio.createGain();oscillator.connect(gain);gain.connect(audio.destination);oscillator.frequency.value=740;gain.gain.setValueAtTime(.08,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.2);oscillator.start();oscillator.stop(audio.currentTime+.22);oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};}
 }

 async function poll(){if(busy)return;busy=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
 try{const response=await fetch('/api/strategy-signals',{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('Сигналы стратегий недоступны');const data=await response.json();
 if(data.status!=='ok'||!Array.isArray(data.events))throw Error(data.error||'Нет данных');
 document.dispatchEvent(new CustomEvent('lab-strategy-signals',{detail:data}));
 const now=Date.now()/1000,live=Number.isFinite(data.updated)&&now-data.updated>=0&&now-data.updated<=15;
 notify(data.events,live&&data.state==='monitoring',now);
 const states={not_configured:'Сохраните настройки «Пробой уровня», чтобы начать наблюдение.',empty_scope:'Нет монет для наблюдения. Добавьте Bybit-монеты в избранное.',waiting_data:'Ожидаем свежие свечи по выбранным монетам.',monitoring:`Проверено ${data.monitored} монет · свежие данные: ${data.ready}. Пробой диапазона 20 минут.`};
 status.textContent=live?(states[data.state]||'Состояние монитора неизвестно'):'Нет свежего ответа монитора';
 const key=JSON.stringify([data.events,data.state,data.coverage,live,data.events.map(e=>e.expires>=now)]);if(key!==last){last=key;list.replaceChildren();
 for(const e of data.events.slice(0,30)){const row=document.createElement('article');row.className='strategy-event';const h=document.createElement('h4'),p=document.createElement('p'),levels=document.createElement('p');
 const active=live&&data.state==='monitoring'&&data.coverage?.some(r=>r.symbol===e.symbol&&r.status!=='blocked')&&e.expires>=now&&!e.outcome;const outcome={stop:'Касание стопа',target:'Касание цели',ambiguous:'Стоп и цель: порядок неизвестен',expired:'Срок истёк'}[e.outcome];h.textContent=`${e.symbol} · ${String(e.side).toUpperCase()} · ${outcome||(active?'Сигнал':'История')}`;
 p.textContent=e.detail+' '+new Date(e.closed_at*1000).toLocaleString('ru-RU');
 levels.textContent=`Цена сигнала: ${e.signal_price} · Стоп: ${e.stop} · Цель: ${e.target}`;row.append(h,p,levels);list.append(row);}
 if(!data.events.length)list.textContent='Подтверждённых сигналов пока нет.';
 }
 }catch(e){document.dispatchEvent(new CustomEvent('lab-strategy-signals',{detail:null}));status.textContent=e.name==='AbortError'?'Нет ответа сервера. Повторяем запрос.':e.message;last='';list.replaceChildren();}finally{clearTimeout(timer);busy=false;}}
 void poll();setInterval(poll,5000);
});
