/* Navigation and presentation preferences; no trading configuration writes. */
document.addEventListener('DOMContentLoaded',()=>{
 'use strict';
 const nav=document.getElementById('dashboard-tabs'),main=document.querySelector('main'),api=window.LabNavigation;
 if(!nav||!main||!api)return;
 const make=(tag,cls='',text='')=>{const e=document.createElement(tag);e.className=cls;e.textContent=text;return e;};
 const go=key=>api.activate(key);
 document.body.classList.add('lab-shell');main.id='app-main';main.tabIndex=-1;
 nav.className='lab-sidebar';document.body.prepend(nav);
 const brand=make('div','sidebar-brand');brand.append(LabUI.brand(),make('b','','Trading Lab'));nav.prepend(brand);
 const links=make('div','sidebar-links');nav.append(links);
 const buttons=[...nav.querySelectorAll('button')];
 for(const button of buttons){
  const key=button.getAttribute('aria-controls').replace('page-',''),label=api.names[key];
  button.className='nav-item'+(button.classList.contains('selected')?' selected':'');
  button.dataset.page=key;button.replaceChildren(LabUI.icon(key),make('span','nav-label',key==='live'?'Стакан LIVE':label));
  button.setAttribute('aria-label',label);links.append(button);
  if(key==='alerts'){const badge=make('span','nav-count','0');badge.setAttribute('aria-hidden','true');button.append(badge);}
 }
 const footer=make('div','sidebar-footer');footer.append(make('span','mode-pill','PAPER'),make('small','','NODE 02'));nav.append(footer);
 const header=main.querySelector('header');header.classList.add('mobile-brand');
 const title=header.querySelector('div');title.replaceChildren(LabUI.brand(),make('b','','Trading Lab'));
 header.querySelector('.badge').className='mode-pill';
 const mobile=make('nav','mobile-nav');mobile.setAttribute('aria-label','Основная навигация');
 const mobileButtons={};
 for(const key of ['overview','market','alerts','research','more']){
  const b=make('button','mobile-nav-item');b.type='button';b.setAttribute('aria-label',key==='more'?'Ещё':api.names[key]);
  b.append(LabUI.icon(key),make('span','',key==='more'?'Ещё':api.names[key]));
  if(key==='alerts'){const badge=make('small','nav-count','0');badge.setAttribute('aria-hidden','true');b.append(badge);}
  mobileButtons[key]=b;mobile.append(b);
 }
 document.body.append(mobile);
 const more=make('dialog','more-menu');more.setAttribute('aria-label','Другие разделы');
 const moreHead=make('div','more-heading');moreHead.append(make('h2','','Другие разделы'));
 const close=make('button','icon-button');close.type='button';close.setAttribute('aria-label','Закрыть меню');close.append(LabUI.icon('close'));close.addEventListener('click',()=>more.close());moreHead.append(close);more.append(moreHead);
 for(const key of ['chart','live','journals','grid','tests','settings']){const b=make('button','more-link');b.type='button';b.append(LabUI.icon(key),make('span','',key==='live'?'Стакан LIVE':api.names[key]));b.addEventListener('click',()=>{more.close();go(key);});more.append(b);}
 more.addEventListener('click',e=>{if(e.target===more){const r=more.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)more.close();}});document.body.append(more);
 for(const [key,b]of Object.entries(mobileButtons))b.addEventListener('click',()=>key==='more'?more.showModal():go(key));
 const reflect=()=>{const key=api.current();for(const [k,b]of Object.entries(mobileButtons)){const on=k===key||(k==='more'&&!['overview','market','alerts','research'].includes(key));b.classList.toggle('selected',on);b.setAttribute('aria-pressed',String(on));}main.dataset.page=key;};
 document.addEventListener('lab-tab',()=>{reflect();window.scrollTo({top:0,behavior:'instant'});});reflect();
 document.addEventListener('lab-alerts',e=>{const count=Number.isInteger(e.detail)&&e.detail>=0?e.detail:0;for(const badge of document.querySelectorAll('.nav-count')){badge.textContent=String(count);badge.classList.toggle('has-alerts',count>0);}});
 const graph=document.getElementById('page-chart');
 const graphHead=make('div','page-heading');graphHead.append(make('h2','','График и анализ'),make('p','muted','Выбери контракт и таймфрейм'));graph.append(graphHead);
 for(const selector of ['.terminal-toolbar','.terminal-layout']){const node=document.querySelector(selector);if(node)graph.append(node);}
 const journals=document.getElementById('page-journals'),journalHead=make('div','page-heading');journalHead.append(make('h2','','Журнал моделей'),make('p','muted','Закрытые PAPER-сделки, расходы и результаты'));journals.append(journalHead);
 for(const id of ['model-journals','lab-report','research-journals']){const node=document.getElementById(id);if(node)journals.append(node);}
 const settings=document.getElementById('page-settings'),settingsBox=make('section','box settings-box');
 settingsBox.append(make('h2','','Настройки интерфейса'),make('p','muted','Оформление сохраняется в этом браузере.'));
 const density=make('select');density.setAttribute('aria-label','Плотность интерфейса');
 for(const [value,text]of [['comfortable','Комфортная'],['compact','Компактная']]){const o=make('option','',text);o.value=value;density.append(o);}
 const start=make('select');start.setAttribute('aria-label','Стартовый раздел');
 for(const key of ['market','overview','alerts','chart','research','journals']){const o=make('option','',api.names[key]);o.value=key;start.append(o);}
 for(const [text,control]of [['Плотность интерфейса',density],['Стартовый раздел',start]]){const label=make('label','settings-field',text);label.append(control);settingsBox.append(label);}
 const storage=make('p','muted'),reset=make('button','secondary-button','Сбросить оформление');reset.type='button';settingsBox.append(reset,storage);settings.append(settingsBox);
 const readPrefs=()=>{try{density.value=localStorage.getItem('lab-ui-density')==='compact'?'compact':'comfortable';const key=localStorage.getItem('lab-start-page')||'market';start.value=[...start.options].some(o=>o.value===key)?key:'market';}catch{density.value='comfortable';start.value='market';storage.textContent='Сохранение настроек недоступно.';}document.body.dataset.density=density.value;};
 const savePrefs=()=>{document.body.dataset.density=density.value;try{localStorage.setItem('lab-ui-density',density.value);localStorage.setItem('lab-start-page',start.value);storage.textContent='Оформление сохранено.';}catch{storage.textContent='Оформление применено на эту сессию: браузер запретил сохранение.';}};
 density.addEventListener('change',savePrefs);start.addEventListener('change',savePrefs);
 reset.addEventListener('click',()=>{density.value='comfortable';start.value='market';savePrefs();});readPrefs();
});
