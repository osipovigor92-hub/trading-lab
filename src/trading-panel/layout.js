/* Local presentation preferences; no model state or trading configuration writes. */
document.addEventListener('DOMContentLoaded',()=>{
 'use strict';
 const main=document.getElementById('app-main'),api=window.LabNavigation;
 if(!main||!api)return;
 const make=(tag,cls='',text='')=>{const node=document.createElement(tag);node.className=cls;node.textContent=text;return node;};
 const mobile=make('nav','mobile-nav');mobile.setAttribute('aria-label','Основная навигация');
 const buttons={};
 for(const [key,label]of Object.entries(api.names)){
  const button=make('button','mobile-nav-item');button.type='button';button.setAttribute('aria-label',label);button.setAttribute('aria-controls','page-'+key);
  button.append(LabUI.icon(key),make('span','',label));
  if(key==='alerts'){const badge=make('small','nav-count','0');badge.setAttribute('aria-hidden','true');button.append(badge);}
  button.addEventListener('click',()=>api.activate(key));buttons[key]=button;mobile.append(button);
 }
 document.body.append(mobile);
 const reflect=()=>{const selected=api.current();for(const [key,button]of Object.entries(buttons)){const active=key===selected;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));}main.dataset.page=selected;};
 document.addEventListener('lab-tab',()=>{reflect();window.scrollTo({top:0,behavior:'instant'});});reflect();
 document.addEventListener('lab-alerts',event=>{const count=Number.isInteger(event.detail)&&event.detail>=0?event.detail:0;for(const badge of document.querySelectorAll('.nav-count')){badge.textContent=String(count);badge.classList.toggle('has-alerts',count>0);}});
 const settings=document.getElementById('page-settings'),heading=make('div','page-heading');heading.append(make('h2','','Рабочее место'),make('p','muted','Настройки сохраняются в этом браузере.'));settings.append(heading);
 const box=make('section','box settings-box');box.append(make('h3','','Оформление и навигация'));
 const density=make('select');density.id='ui-density';density.setAttribute('aria-label','Плотность интерфейса');
 for(const [value,text]of [['comfortable','Комфортная'],['compact','Компактная']]){const option=make('option','',text);option.value=value;density.append(option);}
 const start=make('select');start.id='ui-start-page';start.setAttribute('aria-label','Стартовый раздел');
 for(const [key,label]of Object.entries(api.names)){const option=make('option','',label);option.value=key;start.append(option);}
 for(const [text,control]of [['Плотность интерфейса',density],['Стартовый раздел',start]]){const label=make('label','settings-field',text);label.htmlFor=control.id;label.append(control);box.append(label);}
 const reset=make('button','secondary-button','Сбросить оформление'),status=make('p','muted');reset.type='button';status.setAttribute('role','status');box.append(reset,status);settings.append(box);
 const tools=make('section','box settings-box');tools.append(make('h3','','Параметры помощника'),make('p','muted','Фильтры активности, список наблюдения и расчёт риска находятся в скринере. Звук и условия событий — в алертах.'));
 const actions=make('div','settings-actions');for(const [key,label]of [['market','Открыть фильтры скринера'],['alerts','Открыть настройки алертов']]){const button=make('button','secondary-button',label);button.type='button';button.addEventListener('click',()=>api.activate(key));actions.append(button);}tools.append(actions);settings.append(tools);
 const read=()=>{try{density.value=localStorage.getItem('lab-ui-density')==='compact'?'compact':'comfortable';const key=localStorage.getItem('lab-start-page')||'market';start.value=Object.prototype.hasOwnProperty.call(api.names,key)?key:'market';}catch(_){density.value='comfortable';start.value='market';status.textContent='Сохранение настроек недоступно.';}document.body.dataset.density=density.value;};
 const save=()=>{document.body.dataset.density=density.value;try{localStorage.setItem('lab-ui-density',density.value);localStorage.setItem('lab-start-page',start.value);status.textContent='Оформление сохранено.';}catch(_){status.textContent='Оформление применено на эту сессию: браузер запретил сохранение.';}};
 density.addEventListener('change',save);start.addEventListener('change',save);reset.addEventListener('click',()=>{density.value='comfortable';start.value='market';save();});read();
});
