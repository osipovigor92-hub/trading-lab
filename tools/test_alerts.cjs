const {test}=require('node:test');const assert=require('node:assert/strict');
const {classifyB:B,classifyWatch:W}=require('../src/trading-panel/alerts.js');
const row=()=>({symbol:'TEST',price:10,spread:.01,time:1000,trade_age:.2,ready:true,signal:'LONG',chart:{end:990,side:1},reasons:[]});
const state=()=>({updated:1000,phase:'running',cooldown_until:0,position:null});
test('valid B long and short',()=>{assert.equal(B(state(),row(),1000).kind,'entry');assert.equal(B(state(),{...row(),signal:'SHORT',chart:{end:990,side:-1}},1000).tone,'short');});
test('stale and future book blocked',()=>{for(const time of [990,1003])assert.equal(B(state(),{...row(),time},1000).kind,'stale');});
test('old trades and candles blocked',()=>{assert.equal(B(state(),{...row(),trade_age:11},1000).kind,'stale');assert.equal(B(state(),{...row(),chart:{end:800,side:1}},1000).kind,'stale');});
test('open position and cooldown block new entry',()=>{assert.equal(B({...state(),position:{}},row(),1000).kind,'blocked');assert.equal(B({...state(),cooldown_until:1010},row(),1000).kind,'blocked');assert.equal(B({...state(),cooldown_until:undefined},row(),1000).kind,'blocked');});
test('halt and contradictory packet cannot issue entry',()=>{assert.notEqual(B({...state(),phase:'halted'},row(),1000).kind,'entry');assert.notEqual(B(state(),{...row(),chart:{end:990,side:-1}},1000).kind,'entry');assert.notEqual(B(state(),{...row(),reasons:undefined},1000).kind,'entry');});
test('watch only allowed pending conditions',()=>{const r={...row(),signal:'WAIT',reasons:['Нет пробоя локального экстремума последних секунд']};assert.equal(B(state(),r,1000).kind,'watch');r.reasons.push('Широкий спред');assert.equal(B(state(),r,1000).kind,'wait');});
test('orderbook watcher never becomes entry',()=>{const r={book_time:1000,status:'WATCH_LONG',reasons:[]};assert.equal(W({status:'ok',updated:1000},r,1000).kind,'watch');assert.equal(W({status:'ok',updated:1000},r,1010).kind,'stale');});
test('chart error and invalid numeric values blocked',()=>{assert.notEqual(B(state(),{...row(),chart_error:'Bad candles'},1000).kind,'entry');assert.equal(B(state(),{...row(),price:NaN},1000).kind,'stale');});
const {transition}=require('../src/trading-panel/alerts.js');
test('entry direction change emits a new alert, repeats do not',()=>{
 assert.equal(transition('entry:LONG','entry','LONG').event,null);
 assert.equal(transition('entry:LONG','entry','SHORT').event,'entry');
});
test('entry cancellation reported once and waiting does not invent entries',()=>{
 assert.equal(transition('entry:LONG','stale','LONG').event,'cancel');
 assert.equal(transition('stale:LONG','stale','LONG').event,null);
 assert.equal(transition(undefined,'wait','LONG').event,null);
});
