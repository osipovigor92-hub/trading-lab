const {test}=require('node:test'),assert=require('node:assert/strict');
const {bookRows,flowRows,seriesPoints,fresh}=require('../src/trading-panel/workspace.js');
test('book uses each nested band separately, never sums zones',()=>{
 const r={bands:{'0.0002':{bid:100,ask:300,covered:true},'0.001':{bid:1000,ask:1000,covered:false}}};const bands=bookRows(r);
 assert.equal(bands[0].share,.25);assert.equal(bands[1].valid,false);assert.equal(bands[2].bid,1000);assert.equal(bands[2].covered,false);
});
test('missing, zero and invalid depth cannot fabricate an imbalance',()=>{
 for(const b of [{bid:0,ask:0},{bid:-1,ask:10},{bid:NaN,ask:1},{bid:'100',ask:20}])assert.equal(bookRows({bands:{'0.001':b}})[2].share,null);
});
test('rolling windows retain separate deltas and zero-volume means no share',()=>{
 const fs=flowRows({flow5:{buy:500,sell:200,count:3},flow15:{buy:0,sell:0,count:0}});
 assert.equal(fs[0].delta,300);assert.equal(fs[1].delta,0);assert.equal(fs[1].share,null);assert.equal(fs[2].valid,false);
});
test('plot handles flat, negative, single and invalid series',()=>{
 assert.equal(seriesPoints([]),'');assert.equal(seriesPoints([NaN]),'');assert.equal(seriesPoints([1,1]),'8,50 592,50');
 assert.equal(seriesPoints([-2,2]),'8,92 592,8');assert.equal(seriesPoints([1]),'8,50');
});
test('freshness rejects missing, future and stale samples',()=>{
 assert.equal(fresh(undefined,100,3),false);assert.equal(fresh(102,100,3),false);assert.equal(fresh(95,100,3),false);assert.equal(fresh(99,100,3),true);
});
