const {test}=require('node:test'),assert=require('node:assert/strict');
const {evaluate:E,confirm,VERSION}=require('../src/trading-panel/research.js');
const state=()=>({updated:1000,phase:'running'});
function row(side=1){return {symbol:'TESTUSDT',time:1000,price:100,spread:.01,roundtrip_pct:.2,ready:true,trade_age:.2,ofi5:side*50,bands:{'0.0005':{bid:side===1?12000:6000,ask:side===1?6000:12000,covered:true}},flow5:{buy:side===1?2500:500,sell:side===1?500:2500,count:15},flow15:{buy:side===1?5000:1000,sell:side===1?1000:5000,count:30},chart:{end:990,price:100-side*.3,ema20:100,ema50:100-side*.5,atr:1,vwap60:100-side*.5,rvol5:2,side,next_funding:5000}};}
test('C trend conditions symmetrical for long and short, with explicit research version',()=>{for(const side of [1,-1]){const r=E('C',state(),row(side),1000);assert.equal(r.pass,true);assert.equal(r.side,side);assert.equal(r.version,VERSION);assert.equal(r.signal,undefined);}});
test('D requires range, deviation and initial return; uses actual book and flow amounts',()=>{for(const side of [1,-1]){const r=row(side);Object.assign(r.chart,{vwap60:100+side,ema50:100.1,rvol5:1});assert.equal(E('D',state(),r,1000).pass,true);r.chart.rvol5=2;assert.equal(E('D',state(),r,1000).pass,false);}});
test('stale, future, missing, halted or broken chart sources cannot match',()=>{
 for(const s of [null,{}, {...state(),phase:'halted'},{...state(),updated:990},{...state(),updated:1003}])assert.equal(E('C',s,row(),1000).pass,false);
 for(const patch of [{time:990},{time:1003},{ready:false},{trade_age:11},{chart_error:'bad'},{price:NaN},{price:0},{spread:-1},{spread:.1},{roundtrip_pct:undefined},{roundtrip_pct:0}])assert.equal(E('C',state(),{...row(),...patch},1000).pass,false);
 assert.equal(E('C',state(),{},1000).pass,false);
});
test('uncovered or negative depth, invalid flow and imminent funding block matching',()=>{
 for(const change of [r=>r.bands['0.0005'].covered=false,r=>r.bands['0.0005'].bid=-1,r=>r.flow5.buy=NaN,r=>r.flow15.count=1,r=>r.chart.next_funding=1100,r=>r.chart.end=800,r=>r.ofi5=NaN]){const r=row();change(r);assert.equal(E('C',state(),r,1000).pass,false);}
});
test('ATR and VWAP distance cost gates cannot be bypassed by a directional score',()=>{
 const r=row();r.roundtrip_pct=2;assert.equal(E('C',state(),r,1000).pass,false);Object.assign(r.chart,{vwap60:101,ema50:100.1,rvol5:1});assert.equal(E('D',state(),r,1000).pass,false);
});
test('confirmation requires distinct ordered observations and duration; resets on gap or reversal',()=>{
 const result={pass:true,side:1};let s=confirm(null,result,1000,1000);s=confirm(s,result,1000,1000);assert.equal(s.count,1);
 s=confirm(s,result,1002,1002);assert.equal(s.confirmed,false);s=confirm(s,result,1004,1004);assert.equal(s.confirmed,true);
 assert.equal(confirm(s,result,1012,1012).count,1);assert.equal(confirm(s,{pass:true,side:-1},1006,1006).count,1);assert.equal(confirm(s,{pass:false,side:1},1006,1006).confirmed,false);
 assert.equal(confirm(s,result,1003,1004).count,1);assert.equal(confirm(s,result,1004,1009).confirmed,false);
});
