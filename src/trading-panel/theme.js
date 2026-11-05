/* Apply the stored palette before the dashboard styles are painted. */
(() => {
 'use strict';
 const key='lab-ui-theme',root=document.documentElement,valid=value=>value==='dark'||value==='light';
 const read=()=>{try{const value=localStorage.getItem(key);return valid(value)?value:'dark';}catch(_){return 'dark';}};
 function apply(mode){
  if(!valid(mode)||root.dataset.theme===mode)return;
  root.dataset.theme=mode;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',mode==='light'?'#f1f5f8':'#101418');
  document.dispatchEvent(new CustomEvent('lab-theme',{detail:mode}));
 }
 apply(read());
 window.LabTheme={get:()=>root.dataset.theme,set(mode){
  if(!valid(mode))return false;
  apply(mode);try{localStorage.setItem(key,mode);return true;}catch(_){return false;}
 }};
 window.addEventListener('storage',event=>{if(event.key===key||event.key===null)apply(read());});
})();
