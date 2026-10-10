/* The assistant shell owns navigation only; each visible tool owns its data. */
document.addEventListener('DOMContentLoaded', () => {
 'use strict';
 const nav=document.getElementById('dashboard-tabs');
 if(!nav)return;
 const names={market:'Скринер',alerts:'Алерты',positions:'Позиции',settings:'Настройки'},pages={},buttons={};
 for(const [key,label]of Object.entries(names)){
  const page=document.getElementById('page-'+key);
  if(!page)continue;
  pages[key]=page;
  const button=document.createElement('button');button.type='button';button.className='nav-item';button.dataset.page=key;
  button.setAttribute('aria-controls',page.id);button.setAttribute('aria-label',label);
  const text=document.createElement('span');text.className='nav-label';text.textContent=label;button.append(LabUI.icon(key),text);
  if(key==='alerts'){const badge=document.createElement('span');badge.className='nav-count';badge.textContent='0';badge.setAttribute('aria-hidden','true');button.append(badge);}
  button.addEventListener('click',()=>activate(key));buttons[key]=button;nav.append(button);
 }
 function activate(requested){
  const key=Object.prototype.hasOwnProperty.call(pages,requested)?requested:'market';
  try{sessionStorage.setItem('lab-tab',key);}catch(_){}
  for(const [name,page]of Object.entries(pages)){const selected=name===key;page.hidden=!selected;buttons[name].classList.toggle('selected',selected);buttons[name].setAttribute('aria-pressed',String(selected));}
  document.dispatchEvent(new CustomEvent('lab-tab',{detail:key}));
 }
 window.LabNavigation={activate,names,current:()=>Object.keys(pages).find(key=>!pages[key].hidden)};
 document.addEventListener('lab-navigate',event=>activate(event.detail));
 let selected='market';
 try{selected=localStorage.getItem('lab-start-page')||selected;}catch(_){}
 try{selected=sessionStorage.getItem('lab-tab')||selected;}catch(_){}
 activate(selected);
});
