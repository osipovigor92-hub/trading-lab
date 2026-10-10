const test=require('node:test'),assert=require('node:assert/strict');
const {validChart,natr,metricValue,rankRows,formatPrice}=require('../src/trading-panel/chart-grid.js');
test('tiny contract prices stay nonzero and distinct in chart labels',()=>{
 assert.notEqual(formatPrice(2.345e-8),formatPrice(0));assert.notEqual(formatPrice(2.345e-8),formatPrice(3.345e-8));assert.match(formatPrice(2.345e-8),/2,345E-8/);assert.equal(formatPrice(NaN),'—');
});
const now=1800000030,end=Math.floor(now/300)*300;
function packet(interval='5',exchange='bybit',symbol='BTCUSDT'){
 const period=Number(interval)*60,candle_end=Math.floor(now/period)*period;
 return {exchange,symbol,interval,status:'ok',updated:now,candle_end,candles:Array.from({length:80},(_,i)=>({t:candle_end-(80-i)*period,open:100,close:100,high:102,low:98,volume:10,turnover:1000}))};
}
test('source identity, closed bars, timestamp, and refresh failure gate the chart',()=>{
 const p=packet();assert.equal(validChart(p,'bybit','BTCUSDT','5',now),true);
 for(const bad of [{...p,exchange:'binance'},{...p,updated:now-80},{...p,refresh_error:'outage'},{...p,candle_end:end+300}])assert.equal(validChart(bad,'bybit','BTCUSDT','5',now),false);
 const gap=packet();gap.candles[10].t-=300;assert.equal(validChart(gap,'bybit','BTCUSDT','5',now),false);
 const open=packet();open.candles.at(-1).t+=300;assert.equal(validChart(open,'bybit','BTCUSDT','5',now),false);
});
test('NATR Wilder smoothing handles gaps from previous close and normalizes by last close',()=>{
 const bars=packet().candles;assert.equal(natr(bars,14),4);bars.at(-1).close=110;bars.at(-1).high=111;bars.at(-1).low=109;
 const expected=((4*13+11)/14)/110*100;assert.ok(Math.abs(natr(bars,14)-expected)<1e-10);assert.equal(natr(bars.slice(0,10),14),null);
});
test('metrics require their documented timeframe and do not reuse another exchange',()=>{
 const row={symbol:'BTCUSDT',turnover24:3e7,change24:2,trades24:null},cache=new Map([['bybit:BTCUSDT:5',packet()]]);
 assert.equal(metricValue(row,'natr5_14',cache,'bybit',now),4);assert.equal(metricValue(row,'natr1_30',cache,'bybit',now),null);assert.equal(metricValue(row,'natr5_14',cache,'binance',now),null);assert.equal(metricValue(row,'trades24',cache,'bybit',now),null);
 const one=packet('1');one.candles.at(-1).close=101;one.candles.at(-1).high=102;cache.set('bybit:BTCUSDT:1',one);assert.equal(metricValue(row,'change5',cache,'bybit',now),1.0000000000000009);
});
test('unknown chart metrics sort after verified values without inventing a zero score',()=>{
 const cache=new Map([['bybit:BTCUSDT:5',packet()]]),rows=[{symbol:'ETHUSDT',turnover24:1e9},{symbol:'BTCUSDT',turnover24:1e8}];assert.deepEqual(rankRows(rows,'natr5_14',cache,'bybit',now).map(r=>r.symbol),['BTCUSDT','ETHUSDT']);
});
test('a new closed boundary invalidates the old series even while receipt time is fresh',()=>{
 const p=packet('1');p.updated=p.candle_end+17;assert.equal(validChart(p,'bybit','BTCUSDT','1',p.candle_end+20),true);assert.equal(validChart(p,'bybit','BTCUSDT','1',p.candle_end+65),false);
});
