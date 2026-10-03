document.addEventListener('DOMContentLoaded',()=>{
 const page=document.getElementById('page-overview');if(!page)return;
 const box=document.createElement('section');box.className='box';box.id='all-model-status';
 const h=document.createElement('h2');h.textContent='Все модели · серверный PAPER';box.append(h);
 const body=document.createElement('div');body.className='model-summary';box.append(body);page.prepend(box);
 let states={};const render=()=>{body.replaceChildren();const now=Date.now()/1000;
  for(const id of ['A','B','C','D']){const s=states[id],card=document.createElement('article');card.className='model-tile';const title=document.createElement('h3');title.textContent='Модель '+id;const p=document.createElement('p');const fresh=s&&Number.isFinite(s.updated)&&now-s.updated>=-1&&now-s.updated<=8;
   p.textContent=!s?'Нет отчёта / не установлена':!fresh?'Отчёт устарел':s.phase==='running'?'Работает':s.phase==='paused'?'Отключена':s.phase==='draining'?'Завершает позицию':s.phase==='halted'?'Остановлена: '+(s.reason||'см. журнал'):'Ожидание данных';p.className=fresh&&s.phase==='running'?'positive':'muted';card.append(title,p);body.append(card);}
 };
 async function poll(){const paths={A:'/api/paper',B:'/api/model-b',CD:'/api/research'};await Promise.all(Object.entries(paths).map(async([id,url])=>{try{const r=await labFetch(url);if(!r.ok)throw Error();const s=await r.json();if(id==='CD'){for(const key of ['C','D'])states[key]=s.models?.[key]?{...s.models[key],updated:s.updated}:null;}else states[id]=s;}catch{if(id==='CD'){states.C=null;states.D=null;}else states[id]=null;}}));render();setTimeout(poll,2000);}
 poll();setInterval(()=>{if(!document.hidden)render();},1000);
});
