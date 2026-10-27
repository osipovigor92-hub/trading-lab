/* Server-backed favorites. Only explicit deltas leave the browser. */
(() => {
 'use strict';
 const keys=['lab-favorites-v1','lab-exchange-favorites-v1','lab-density-watch-v1'];
 const read=(key,fallback)=>{try{return JSON.parse(localStorage.getItem(key))??fallback;}catch{return fallback;}};
 const list=key=>{const v=read(key,[]);return Array.isArray(v)?v:[];};
 const baseline=Object.fromEntries(keys.map(key=>[key,list(key)]));
 let queue=read('lab-favorites-outbox',[]),busy=false,status,recover;
 if(!Array.isArray(queue))queue=[];
 const show=text=>{if(status)status.textContent=text;};
 const persist=()=>localStorage.setItem('lab-favorites-outbox',JSON.stringify(queue));
 const id=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
 function enqueue(changes){if(changes.length){queue.push({id:id(),changes});persist();}}
 window.LabFavorites={changed(key){
  if(!keys.includes(key))return;
  try{
   const before=baseline[key],after=list(key);
   enqueue([...before.filter(v=>!after.includes(v)).map(value=>({key,value,present:false})),
    ...after.filter(v=>!before.includes(v)).map(value=>({key,value,present:true}))]);
   baseline[key]=after;
   show('Избранное: сохраняем…');void sync();
  }catch{show('Избранное не сохранено: хранилище браузера недоступно');}
 }};
 async function request(options){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
  try{const response=await fetch('/api/favorites',{cache:'no-store',...options,signal:controller.signal});
   let data;
   try{data=await response.json();}catch{throw Error('HTTP '+response.status+' · сервер вернул не JSON; проверьте обновление панели');}
   if(!response.ok||!['ok','accepted'].includes(data.status)){
    const error=Error(data.error||('HTTP '+response.status+' · сервер недоступен'));error.http=response.status;throw error;
   }
   if(!data.groups||!keys.every(key=>Array.isArray(data.groups[key])))throw Error('неполный ответ сервера');
   return data;
  }finally{clearTimeout(timer);}
 }
 async function sync(){
  if(busy)return;busy=true;
  try{
   let data=await request();
   if(!read('lab-favorites-migrated',false)){
    // Import before applying any remote snapshot; an empty phone sends no removals.
    enqueue(keys.flatMap(key=>list(key).map(value=>({key,value,present:true}))));
    localStorage.setItem('lab-favorites-migrated','true');
   }
   const token=data.token;
   let rebased=false;
   while(queue.length){
    try{data=await request({method:'POST',headers:{'Content-Type':'application/json','X-Lab-Control':token},body:JSON.stringify(queue[0])});}
    catch(error){
     // Only a definitive rejection permits a new id. A lost acknowledgement
     // must retain its original id so retries cannot resurrect removed coins.
     if(error.http===409&&!rebased&&queue.length>1){
      const changes=new Map();
      for(const item of queue)for(const change of item.changes)changes.set(change.key+'|'+change.value,change);
      queue=[{id:id(),changes:[...changes.values()]}];persist();rebased=true;continue;
     }
     if(recover)recover.hidden=error.http!==409;
     throw error;
    }
    queue.shift();persist();
   }
   for(const key of keys){
    const oldValue=localStorage.getItem(key),newValue=JSON.stringify(data.groups[key]);
    baseline[key]=data.groups[key].slice();
    if(oldValue!==newValue){localStorage.setItem(key,newValue);window.dispatchEvent(new StorageEvent('storage',{key,oldValue,newValue}));}
   }
   if(recover)recover.hidden=true;
   show('Избранное синхронизировано · ПК и телефон');
  }catch(error){show('Избранное: синхронизация недоступна · '+error.message);}
  finally{busy=false;}
 }
 document.addEventListener('DOMContentLoaded',()=>{
  status=document.createElement('p');status.id='favorites-sync-status';status.className='muted';status.setAttribute('role','status');
  recover=document.createElement('button');recover.type='button';recover.hidden=true;
  recover.textContent='Отменить несохранённые изменения и загрузить общее избранное';
  recover.addEventListener('click',async()=>{
   if(busy)return;busy=true;recover.disabled=true;
   try{
    const data=await request();
    for(const key of keys){const oldValue=localStorage.getItem(key),newValue=JSON.stringify(data.groups[key]);localStorage.setItem(key,newValue);baseline[key]=data.groups[key].slice();window.dispatchEvent(new StorageEvent('storage',{key,oldValue,newValue}));}
    queue=[];persist();localStorage.setItem('lab-favorites-migrated','true');recover.hidden=true;
    show('Избранное синхронизировано · загружен общий список');
   }catch(error){show('Избранное: '+error.message);}finally{busy=false;recover.disabled=false;}
  });
  document.getElementById('app-main')?.prepend(status,recover);
  void sync();setInterval(sync,5000);
 });
 window.addEventListener('online',()=>void sync());
})();
