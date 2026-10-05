/* Local vectors only: the dashboard does not load external fonts or coin assets. */
(function(scope){
 'use strict';
 const ns='http://www.w3.org/2000/svg';
 const paths={
  overview:['M4 4h6v16H4z','M14 4h6v6h-6z','M14 14h6v6h-6z'],
  market:['M21 21l-5-5','M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13'],
  positions:['M3 7h18v14H3z','M8 7V3h8v4','M3 12h18','M10 12v3h4v-3'],
  alerts:['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9','M10 21h4'],
  chart:['M4 4v16h16','M7 15l4-5 4 3 5-7'],
  live:['M5 5h14v4H5z','M5 10h14v4H5z','M5 15h14v4H5z'],
  research:['M12 3l9 5v9l-9 5-9-5V8z','M3 8l9 5 9-5','M12 13v9'],
  journals:['M5 3h14v18H5z','M9 7h6','M9 11h6','M9 15h3'],
  settings:['M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z','M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0'],
  grid:['M4 4h6v6H4z','M14 4h6v6h-6z','M4 14h6v6H4z','M14 14h6v6h-6z'],
  tests:['M9 3h6','M10 3v6L4 20h16L14 9V3','M8 15h8'],
  more:['M5 12h.01','M12 12h.01','M19 12h.01'],
  arrow:['M5 12h14','M14 7l5 5-5 5'],
  star:['M12 3l2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z'],
  expand:['M8 3H3v5','M16 21h5v-5','M3 3l6 6','M21 21l-6-6'],
  filter:['M4 5h16','M7 12h10','M10 19h4'],
  close:['M6 6l12 12','M18 6 6 18']
 };
 function icon(name,cls='ui-icon'){
  const svg=document.createElementNS(ns,'svg');
  for(const [k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.6','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',class:cls}))svg.setAttribute(k,v);
  for(const d of paths[name]||paths.overview){const p=document.createElementNS(ns,'path');p.setAttribute('d',d);svg.append(p);}return svg;
 }
 function brand(){
  const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 32 36');svg.setAttribute('class','brand-mark');svg.setAttribute('aria-hidden','true');
  for(const [d,fill]of [['M16 1 30 9 16 17 2 9z','#35e4da'],['M2 12 14 19v15L2 27z','#19b7b5'],['M18 19 30 12v15l-12 7z','#72f5e7']]){const p=document.createElementNS(ns,'path');p.setAttribute('d',d);p.setAttribute('fill',fill);svg.append(p);}return svg;
 }
 function coin(symbol){
  const code=String(symbol).replace(/USDT$/,''),e=document.createElement('span');e.className='coin-mark coin-'+code.toLowerCase();e.setAttribute('aria-hidden','true');
  if(code==='BTC')e.textContent='₿';else if(code==='ETH')e.textContent='◆';
  else if(code==='SOL'){for(let i=0;i<3;i++)e.append(document.createElement('i'));}
  else if(code==='ONDO'){for(let i=0;i<3;i++)e.append(document.createElement('i'));}
  else e.textContent=code.slice(0,2);return e;
 }
 scope.LabUI={icon,brand,coin};
})(typeof window==='undefined'?globalThis:window);
