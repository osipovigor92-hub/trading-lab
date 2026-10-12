const {test}=require('node:test'),assert=require('node:assert/strict');
const {displayCandles}=require('../src/trading-panel/screener.js');
const {marketObservation}=require('../src/trading-panel/workspace.js');
test('a forming candle animates the chart without entering the closed-bar calculation',()=>{
 const closed={time:0,open:100,high:101,low:99,close:100,volume:10,turnover:1000};
 const current={time:60,open:100,high:102,low:99,close:101,volume:1,turnover:101,confirmed:false};
 const data={updated:65,interval:'1',candle_end:60,candles:[closed],current_candle:current};
 assert.equal(displayCandles(data,66).length,2);assert.equal(data.candles.length,1);
 assert.equal(displayCandles(data,121).length,1);assert.equal(displayCandles({...data,current_candle:{...current,time:120}},66).length,1);
 assert.equal(displayCandles({...data,current_candle:{...current,low:103}},66).length,1);
});
test('LIVE book observation is independent of the halted model and missing tape stays unavailable',()=>{
 const book={status:'ok',symbol:'BTCUSDT',updated:100,mid:100,spread:.02,bands:{'0.001':{bid:1000,ask:2000,covered:true}}};
 const packet={book,live:null};const r=marketObservation(packet,'BTCUSDT',102);
 assert.equal(r.price,100);assert.equal(r.ready,false);assert.equal(r.flow60,undefined);
 assert.equal(marketObservation(packet,'ETHUSDT',102),null);assert.equal(marketObservation(packet,'BTCUSDT',109),null);
 const stream={status:'live',updated:102,rows:[{symbol:'BTCUSDT',book_time:102,ready:false,flow_window:3,flow60:{buy:200,sell:100,count:2}}]};
 assert.equal(marketObservation({...packet,live:stream},'BTCUSDT',103).flow60.buy,200);
 assert.equal(marketObservation({...packet,live:{...stream,updated:90}},'BTCUSDT',103).flow60,undefined);
});
