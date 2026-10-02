'use strict';
const params=new URLSearchParams(location.search);
const raw=params.get('symbol')||'LINKUSDT';
const symbol=/^[A-Z0-9]{2,24}USDT$/.test(raw)?raw:'LINKUSDT';
const interval=['1','5','15','60'].includes(params.get('interval'))?params.get('interval'):'5';
const status=document.getElementById('chart-status');
const credit=document.getElementById('credit');
credit.href='https://www.tradingview.com/chart/?symbol='+encodeURIComponent('BYBIT:'+symbol+'.P');
credit.textContent=symbol+' perpetual · TradingView';
// External code runs only inside the cross-origin provider frame.
const config={autosize:true,width:'100%',height:'100%',symbol:'BYBIT:'+symbol+'.P',interval,timezone:'Etc/UTC',theme:'dark',style:'1',allow_symbol_change:false,hide_top_toolbar:false,hide_side_toolbar:true,hide_volume:false,save_image:false,withdateranges:true,support_host:'https://www.tradingview.com'};
const frame=document.createElement('iframe');
frame.title='TradingView '+symbol;
frame.referrerPolicy='no-referrer';
frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-popups');
frame.src='https://www.tradingview-widget.com/embed-widget/advanced-chart/?locale=ru#'+encodeURIComponent(JSON.stringify(config));
frame.style.cssText='width:100%;height:100%;border:0';
frame.onload=()=>{status.textContent='Внешние данные TradingView · время UTC · независимы от PAPER-модели';};
document.querySelector('.tradingview-widget-container__widget').append(frame);
