const test=require('node:test'),assert=require('node:assert/strict');
const {cleanManual,densityLevels}=require('../src/trading-panel/chart-levels.js');
const source={exchange:'bybit',symbol:'BTCUSDT'},now=1800000030;
const row=(patch={})=>({id:'one',...source,side:'ask',price:101,notional:200000,distance_pct:1,status:'active',last_seen:now,...patch});
const packet=rows=>({status:'ok',updated:now,rows});
test('density overlays isolate both venue and symbol and exclude missing/outside-depth amounts',()=>{
 const result=densityLevels(packet([row(),row({id:'other-venue',exchange:'binance'}),row({id:'other-coin',symbol:'ETHUSDT'}),row({id:'missing',status:'missing'}),row({id:'tiny',notional:90000}),row({id:'far',distance_pct:7})]),source,now);
 assert.deepEqual(result.map(r=>r.id),['one']);assert.equal(result[0].confirmed,true);
});
test('receipt and per-level source time expire separately, errors never confirm retained densities',()=>{
 const p=packet([row()]);for(const value of [{...p,status:'unavailable'},{...p,updated:now-31},packet([row({last_seen:now-26})]),packet([row({last_seen:now+3})]),packet([row({status:'unobserved'})])])assert.equal(densityLevels(value,source,now)[0].confirmed,false);
 assert.equal(densityLevels({...p,status:'partial'},source,now)[0].confirmed,true);
});
test('density overlays are bounded to the three largest levels on each side',()=>{
 const rows=Array.from({length:20},(_,i)=>row({id:String(i),side:i%2?'ask':'bid',notional:100000+i*10000})),levels=densityLevels(packet(rows),source,now);assert.equal(levels.length,6);assert.deepEqual(levels.filter(r=>r.side==='ask').map(r=>r.id),['19','17','15']);
});
test('manual annotation storage rejects broken types, IDs and prices and has a hard limit',()=>{
 const valid={id:'one',type:'resistance',price:101};assert.deepEqual(cleanManual([valid,{...valid,price:NaN},{...valid,type:'order'},{...valid,id:'<script>'},{...valid,price:-1}]),[valid]);assert.equal(cleanManual(Array.from({length:30},(_,i)=>({...valid,id:String(i)}))).length,12);assert.deepEqual(cleanManual({}),[]);
});


require('node:test')('level IDs work on HTTP without randomUUID',()=>{
 const assert=require('node:assert/strict'),{levelId,cleanManual}=require('../src/trading-panel/chart-levels.js');
 const crypto=require('node:crypto').webcrypto;
 const source={getRandomValues:crypto.getRandomValues.bind(crypto)};
 const ids=Array.from({length:100},()=>levelId(source));
 assert.equal(new Set(ids).size,100);
 assert.equal(cleanManual([{id:ids[0],type:'support',price:10}]).length,1);
});
