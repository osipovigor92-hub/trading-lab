/* Synthetic PAPER-plan measurements; never used by the dashboard. */
const {planDefaults}=require('../src/trading-panel/screener.js');
function fixture(side=1,interval='5',now=360031){
 const step=Number(interval)*60,end=Math.floor(now/step)*step;
 const reflect=p=>side===1?p:200-p,price=reflect(99.65);
 const candles=Array.from({length:60},(_,i)=>{const close=reflect(80+20*i/59);return {time:end-(60-i)*step,open:close,high:close+.5,low:close-.5,close,volume:1,turnover:close};});
 const base=[{side:'support',low:99.4,high:99.5,price:99.45,pivots:3},{side:'resistance',low:105,high:105.1,price:105.05,pivots:2},{side:'resistance',low:110,high:110.1,price:110.05,pivots:1}];
 const levels=side===1?base:base.map(l=>({...l,side:l.side==='support'?'resistance':'support',low:reflect(l.high),high:reflect(l.low),price:reflect(l.price)}));
 const checks=['turnover','spread','range','oi','funding','volume24','atr','rvol','depth','book_spread','impact','coverage'].map(key=>({key,label:key,state:'pass',value:key==='coverage'?true:1}));
 const verdict={status:'passed',samples:5,chart_time:now,candle_end:now-31,book_time:now,ticker_time:now,checks,rating:{version:1,status:'ok',score:80,components:['liquidity','spread','volume','book'].map(key=>({key,name:key,maximum:25,points:20,values:{}}))}};
 return {symbol:'BTCUSDT',interval,now,settings:{...planDefaults},selectionPacket:{status:'ok',source_time:now,rows:[{symbol:'BTCUSDT',selection:verdict}]},
  snapshot:{status:'ok',updated:now,rows:[{symbol:'BTCUSDT',price,spread:.02,open_interest:1e7,turnover:1e8,change:1,funding:0}]},
  chart:{status:'ok',symbol:'BTCUSDT',interval,updated:now,candle_end:end,candles,price:100,atr:1,atr_pct:1,vwap:reflect(90),levels,zone_width:.25,rvol:1.1,volume_window:60,turnover_window:60*reflect(90)},
  book:{status:'ok',symbol:'BTCUSDT',updated:now,seq:Math.floor(now*1000),mid:price,spread:.02,walls:{bid:[],ask:[]},bands:{'0.001':{bid:20000,ask:20000,covered:true}},top:{bid:[{price:price*.9999,quantity:100,notional:price*.9999*100}],ask:[{price:price*1.0001,quantity:100,notional:price*1.0001*100}]}}};
}
module.exports={fixture};
