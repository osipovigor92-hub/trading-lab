const {test}=require('node:test'),assert=require('node:assert/strict');
const {filterRows,ratingScore,ratingView,positionView,fresh,domain,botModels,chartBars,selectionView,selectionDefaults,validateSelection}=require('../src/trading-panel/screener.js');
const rows=[{symbol:'BTCUSDT',turnover:1e8,spread:.01,range24:2,change:4,selection:{status:'passed'},rating:{status:'ok',score:83}},{symbol:'ONDOUSDT',turnover:3e7,spread:.02,range24:8,change:-5,selection:{status:'passed'},rating:{status:'ok',score:55}},{symbol:'THINUSDT',turnover:1e6,spread:.15,range24:20,change:10,selection:{status:'rejected'},rating:{status:'ok',score:10}}];
test('screeners distinguish activity, tight spread, movers and bot universe',()=>{
 assert.deepEqual(filterRows(rows,{preset:'active'}).map(r=>r.symbol),['ONDOUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'liquid'}).map(r=>r.symbol),['BTCUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'down'}).map(r=>r.symbol),['ONDOUSDT']);
 assert.deepEqual(filterRows(rows,{preset:'bots',bots:new Set(['BTCUSDT'])}).map(r=>r.symbol),['BTCUSDT']);
 assert.deepEqual(filterRows(rows,{search:'ondo',minimum:5e7}),[]);
 assert.deepEqual(filterRows(rows,{sort:'range24'}).map(r=>r.symbol),['THINUSDT','ONDOUSDT','BTCUSDT']);
 assert.deepEqual(filterRows(rows,{sort:'quality'}).map(r=>r.symbol),['BTCUSDT','ONDOUSDT','THINUSDT']);
 assert.equal(ratingScore({turnover:1e10,spread:.001,quality:100}),null,'ticker-only data cannot fabricate a complete rating');
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
 assert.deepEqual(filterRows(rows,{sort:'quality',dir:'asc'}).map(r=>r.symbol),['ONDOUSDT','BTCUSDT','THINUSDT']);
});
test('rating sort keeps eligible candidates first and missing ratings last in either direction',()=>{
 const sample=[rows[0],rows[1],{...rows[0],symbol:'WAITUSDT',rating:{status:'pending',score:null}},
  {...rows[2],rating:{status:'ok',score:100}},
  {...rows[0],symbol:'PENDINGUSDT',selection:{status:'pending'},rating:{status:'ok',score:99}}];
 assert.deepEqual(filterRows(sample,{sort:'quality'}).map(r=>r.symbol),['BTCUSDT','ONDOUSDT','WAITUSDT','PENDINGUSDT','THINUSDT']);
 assert.deepEqual(filterRows(sample,{sort:'quality',dir:'asc'}).map(r=>r.symbol),['ONDOUSDT','BTCUSDT','WAITUSDT','PENDINGUSDT','THINUSDT']);
 assert.equal(ratingScore({rating:{status:'ok',score:0}}),0);
 for(const rating of [{status:'pending',score:99},{status:'ok',score:101},{status:'ok',score:NaN},{status:'ok',score:1.2}])assert.equal(ratingScore({rating}),null);
});
test('ratings expire independently of rejected/eligible labels and malformed sums cannot pass',()=>{
 const checks=['turnover','spread','range','oi','funding','volume24','atr','rvol','depth','book_spread','impact','coverage'].map(key=>({key,state:'pass',value:key==='coverage'?true:1}));
 const rating={status:'ok',score:83,version:1,components:['liquidity','spread','volume','book'].map((key,i)=>({key,name:key,maximum:25,points:[25,20,13,25][i],values:{}}))};
 const verdict={status:'rejected',checks,ticker_time:1000,chart_time:1000,candle_end:970,book_time:1000,samples:5,rating};
 assert.equal(ratingView(verdict,1000).score,83);
 for(const change of [{book_time:987},{chart_time:924},{candle_end:879},{ticker_time:954},{book_time:1003},{samples:4}])assert.equal(ratingView({...verdict,...change},1000).score,null);
 assert.equal(ratingView({...verdict,rating:{...rating,score:84}},1000).score,null);
 assert.equal(ratingView({...verdict,rating:{...rating,components:[...rating.components.slice(0,3),rating.components[0]]}},1000).score,null);
 assert.equal(ratingView({...verdict,rating:{...rating,components:[null,...rating.components.slice(1)]}},1000).score,null);
 assert.equal(ratingView({...verdict,checks:[...checks.slice(0,11),checks[0]]},1000).score,null);
 for(const value of [null,NaN,Infinity,-1,true])assert.equal(ratingView({...verdict,checks:checks.map(c=>c.key==='oi'?{...c,value}:c)},1000).score,null);
 assert.equal(ratingView({...verdict,checks:checks.map(c=>c.key==='coverage'?{...c,value:false}:c)},1000).score,null);
 const pending=checks.map(c=>c.key==='oi'?{...c,state:'pending',value:null}:c);
 assert.equal(ratingView({...verdict,checks:pending},1000).score,null);
 const view=selectionView(verdict,1000,1001,1001);assert.equal(ratingView(view,1001).score,null);
});
test('selection thresholds and old or mismatched verification cannot mark a coin passed',()=>{
 const verdict={status:'passed',samples:5,chart_time:1000,candle_end:970,book_time:1000,checks:Array.from({length:12},()=>({state:'pass'}))};
 assert.equal(selectionView(verdict,1000,1000,1000).status,'passed');
 for(const change of [{samples:4},{book_time:987},{chart_time:924},{candle_end:879},{checks:[]},{book_time:1003}])assert.equal(selectionView({...verdict,...change},1000,1000,1000).status,'pending');
 assert.equal(selectionView(verdict,1000,1001,1001).status,'pending');
 assert.equal(selectionView(verdict,1000,1000,1046).status,'pending');
 assert.equal(selectionView(null,1000,1000,1000).status,'pending');
 assert.deepEqual(validateSelection({}),selectionDefaults);
 for(const v of [{oi_min:NaN},{spread_max:-1},{range_min:31},{oi_min:Infinity},{rvol_min:'1'},{unknown:1}])assert.throws(()=>validateSelection(v));
});
