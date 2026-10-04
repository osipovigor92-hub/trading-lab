const {test}=require('node:test'),assert=require('node:assert/strict');
const {filterRows,qualityScore,positionView,fresh,domain,botModels,chartBars}=require('../src/trading-panel/screener.js');
const rows=[{symbol:'BTCUSDT',turnover:1e8,spread:.01,range24:2,change:4},{symbol:'ONDOUSDT',turnover:3e7,spread:.02,range24:8,change:-5},{symbol:'THINUSDT',turnover:1e6,spread:.15,range24:20,change:10}];
test('screeners distinguish activity, tight spread, movers and bot universe',()=>{
 assert.deepEqual(filterRows(rows,{preset:'active'}).map(r=>r.symbol),['ONDOUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'liquid'}).map(r=>r.symbol),['BTCUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'down'}).map(r=>r.symbol),['ONDOUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'bots',bots:new Set(['BTCUSDT'])}).map(r=>r.symbol),['BTCUSDT']);
 assert.deepEqual(filterRows(rows,{search:'ondo',minimum:5e7}),[]);
 assert.deepEqual(filterRows(rows,{sort:'range24'}).map(r=>r.symbol),['THINUSDT','ONDOUSDT','BTCUSDT']);
 assert.deepEqual(filterRows(rows,{sort:'quality'}).map(r=>r.symbol),['BTCUSDT','ONDOUSDT','THINUSDT']);
 assert.ok(qualityScore(rows[0])>qualityScore(rows[2]),'liquidity/spread quality is not a price forecast');
});
test('position notional and stale halted position remain separate',()=>{
 const s={phase:'running',updated:100,position:{symbol:'BTCUSDT',side:1,quantity:2,entry:100,opened:90}};
 assert.equal(positionView(s,100).notional,200);assert.equal(positionView(s,100).current,true);
 assert.equal(positionView({...s,phase:'halted'},100).current,false);assert.equal(positionView(s,120).current,false);
 assert.equal(positionView({...s,position:{...s.position,quantity:NaN}},100),null);
 const models=botModels(s,null,{updated:99,models:{C:{phase:'running'}}});assert.equal(models.C.updated,99);assert.equal(models.D,null);
});
test('stale or future timestamps never validate; flat charts have a finite padded domain',()=>{
 assert.equal(fresh(80,100,8),false);assert.equal(fresh(103,100,8),false);assert.equal(fresh(undefined,100,8),false);
 const d=domain([{low:100,high:100}]);assert.ok(Number.isFinite(d.low)&&d.high>d.low);
});
test('chart scale changes the visible candle range without changing source data',()=>{
 const bars=Array.from({length:180},(_,i)=>({time:i,low:1,high:2}));
 assert.equal(chartBars(bars,1000,1).length,90);
 assert.equal(chartBars(bars,1000,2).length,45);
 assert.equal(chartBars(bars,1000,.5).length,180);
 assert.equal(chartBars(bars,390,1).length,45);
 assert.equal(chartBars(bars,390,3).length,20);
 assert.equal(bars.length,180);
});
test('chart window pans back in history and sort direction flips',()=>{
 const bars=Array.from({length:180},(_,i)=>({time:i,low:1,high:2}));
 assert.equal(chartBars(bars,1000,1).at(-1).time,179);
 assert.equal(chartBars(bars,1000,1,10).at(-1).time,169);
 assert.equal(chartBars(bars,1000,1,999).at(-1).time,89);
 assert.equal(chartBars(bars,1000,1,-5).at(-1).time,179);
 assert.deepEqual(filterRows(rows,{sort:'turnover',dir:'asc'}).map(r=>r.symbol),['THINUSDT','ONDOUSDT','BTCUSDT']);
 assert.deepEqual(filterRows(rows,{sort:'change'}).map(r=>r.symbol),['THINUSDT','BTCUSDT','ONDOUSDT']);
 assert.deepEqual(filterRows(rows,{sort:'quality',dir:'asc'}).map(r=>r.symbol),['THINUSDT','ONDOUSDT','BTCUSDT']);
});
