/* Local Bybit chart; the optional external provider stays isolated. */
(() => {
 'use strict';
 const params=new URLSearchParams(location.search),raw=params.get('symbol')||'LINKUSDT';
 const symbol=/^[A-Z0-9]{2,24}USDT$/.test(raw)?raw:'LINKUSDT';
 const interval=['1','5','15','60'].includes(params.get('interval'))?params.get('interval'):'5';
 const status=document.getElementById('chart-status'),credit=document.getElementById('credit'),host=document.querySelector('.tradingview-widget-container__widget');
 credit.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BYBIT:'+symbol+'.P');
 credit.textContent=symbol+' perpetual · открыть TradingView';
 if(params.get('provider')==='tradingview'){
  const config={autosize:true,width:'100%',height:'100%',symbol:'BYBIT:'+symbol+'.P',interval,timezone:'Etc/UTC',theme:'dark',style:'1',allow_symbol_change:false,hide_top_toolbar:false,hide_side_toolbar:true,hide_volume:false,save_image:false,withdateranges:true,support_host:'https://www.tradingview.com'};
  const frame=document.createElement('iframe');frame.title='TradingView '+symbol;frame.referrerPolicy='no-referrer';frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-popups');
  frame.src='https://www.tradingview-widget.com/embed-widget/advanced-chart/?locale=ru#'+encodeURIComponent(JSON.stringify(config));frame.className='provider-frame';
  frame.onload=()=>{status.textContent='Внешние данные TradingView · время UTC · независимы от PAPER-модели';};host.append(frame);return;
 }
 const finite=x=>typeof x==='number'&&Number.isFinite(x),ns='http://www.w3.org/2000/svg';
 const fresh=t=>finite(t)&&Date.now()/1000-t>=-2&&Date.now()/1000-t<=75;
 const make=(tag,attrs={},text='')=>{const node=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;return node;};
 const fmt=x=>x.toLocaleString('ru-RU',{maximumFractionDigits:Math.abs(x)>=1000?2:Math.abs(x)>=1?4:8});
 let data=null,error='',busy=false,timer=null,signature='';
 const visible=()=>!document.hidden&&!window.frameElement?.closest('[hidden]');
 function render(){
  const valid=data?.status==='ok'&&data.symbol===symbol&&data.interval===interval&&Array.isArray(data.candles)&&data.candles.length>=60;
  const current=valid&&fresh(data.updated),now=Date.now()/1000;
  status.className=current?'':'is-stale';
  status.textContent=!valid?(error||'Получаем свечи Bybit…'):!current?'Свечи устарели · последний снимок '+new Date(data.updated*1000).toLocaleTimeString('ru-RU'):symbol+' · '+interval+'м · обновлено '+new Date(data.updated*1000).toLocaleTimeString('ru-RU')+' · '+Math.max(0,Math.round(now-data.updated))+' с'+(error||data.refresh_error?' · восстанавливаем связь':' · текущая свеча ещё не закрыта');
  if(!valid)return;
  const step=Number(interval)*60,forming=data.current_candle,bars=data.candles.slice(-89);
  if(current&&forming&&forming.time===data.candle_end&&forming.time<=now&&now<forming.time+step&&[forming.open,forming.high,forming.low,forming.close,forming.turnover].every(finite))bars.push(forming);
  const width=Math.max(260,host.clientWidth),right=width-80,key=JSON.stringify([bars,width,current]);if(key===signature)return;signature=key;
  const high=Math.max(...bars.map(b=>b.high)),low=Math.min(...bars.map(b=>b.low)),pad=Math.max((high-low)*.08,high*.0005),span=high-low+pad*2;
  const y=p=>12+(high+pad-p)/span*214,x=i=>9+(i+.5)*(right-18)/bars.length,barWidth=Math.max(1,(right-18)/bars.length*.7),maxVolume=Math.max(1,...bars.map(b=>b.turnover));
  const svg=make('svg',{viewBox:'0 0 '+width+' 288',role:'img','aria-label':symbol+' · свечи Bybit · '+interval+' минут'});
  for(let i=0;i<5;i++){const value=low-pad+span*i/4,py=y(value);svg.append(make('line',{x1:8,x2:right,y1:py,y2:py,class:'grid'}),make('text',{x:right+5,y:py+4,class:'axis'},fmt(value)));}
  bars.forEach((b,i)=>{const cls=b.close>=b.open?'up':'down';svg.append(make('line',{x1:x(i),x2:x(i),y1:y(b.high),y2:y(b.low),class:cls}),make('rect',{x:x(i)-barWidth/2,y:Math.min(y(b.open),y(b.close)),width:barWidth,height:Math.max(1,Math.abs(y(b.close)-y(b.open))),class:cls}),make('rect',{x:x(i)-barWidth/2,y:260-b.turnover/maxVolume*25,width:barWidth,height:b.turnover/maxVolume*25,class:cls+' volume'}));});
  for(const i of [0,Math.floor(bars.length/2),bars.length-1])svg.append(make('text',{x:Math.max(8,x(i)-18),y:282,class:'axis'},new Date(bars[i].time*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})));
  const last=bars.at(-1),py=y(last.close);svg.append(make('line',{x1:8,x2:right,y1:py,y2:py,class:'last'}),make('text',{x:right+5,y:py-3,class:'price'},fmt(last.close)));
  const fragment=document.createDocumentFragment();fragment.append(svg);LabUI.syncChildren(host,fragment);
 }
 async function poll(){
  if(busy||!visible())return;clearTimeout(timer);busy=true;
  try{const next=await labJson('/api/market-chart?symbol='+encodeURIComponent(symbol)+'&interval='+interval,{},'График Bybit');if(next.status==='ok'&&next.symbol===symbol&&next.interval===interval){data=next;error='';}else error=next.error||'Загружаем свечи…';}
  catch(e){error=e.message;}
  finally{busy=false;render();timer=setTimeout(poll,data?2000:500);}
 }
 window.addEventListener('resize',render);window.addEventListener('message',e=>{if(e.source===parent&&e.origin===location.origin&&e.data==='lab-chart-resume')poll();});document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});setInterval(()=>{if(visible())render();},1000);poll();
})();
