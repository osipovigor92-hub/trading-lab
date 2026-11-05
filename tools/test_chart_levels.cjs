const test=require('node:test'),assert=require('node:assert/strict');
const {cleanManual,densityLevels}=require('../src/trading-panel/chart-levels.js');
const {withSignificance}=require('./density_fixture.cjs');
const source={exchange:'bybit',symbol:'BTCUSDT'},now=1800000030;
const row=(patch={})=>withSignificance({id:'one',...source,side:'ask',price:100.2,notional:200000,distance_pct:.2,status:'active',last_seen:now,...patch});
const packet=rows=>({status:'ok',updated:now,rows});
test('bounded healthy snapshots cannot prove disappearance of omitted source rows',()=>{
 const {mergeDensityPacket}=require('../src/trading-panel/chart-levels.js'),prior=packet([row({age_seconds:120,first_seen:now-120,stable:true})]);
 const next=mergeDensityPacket(prior,packet([row({id:'other',symbol:'ETHUSDT'})]),source,now);
 assert.equal(next.rows.length,1);assert.equal(next.rows[0].status,'unavailable');assert.equal(next.rows[0].last_seen,now);assert.equal(next.rows[0].age_seconds,120);assert.equal(next.rows[0].stable,false);assert.equal(densityLevels(next,source,now)[0].confirmed,false);assert.equal(prior.rows[0].status,'active','copy does not mutate source proof');
 const repeated=mergeDensityPacket(next,packet([]),source,now+1);assert.equal(repeated.rows[0].last_seen,now);assert.equal(repeated.rows[0].age_seconds,120);
});
test('only fresh current missing rows remove retained lines; old tombstones and history cannot erase reappearance',()=>{
 const {mergeDensityPacket}=require('../src/trading-panel/chart-levels.js'),prior=packet([row()]);
 for(const next of [{...packet([row({status:'missing'})]),updated:now-31},{...packet([row({status:'missing'})]),status:'unavailable'},packet([row({status:'missing',last_seen:now-1})]),packet([row({last_seen:now-1})]),{...packet([]),history:[row({status:'missing'})]}]){const merged=mergeDensityPacket(prior,next,source,now);assert.equal(densityLevels(merged,source,now).length,1);assert.equal(densityLevels(merged,source,now)[0].confirmed,false);assert.equal(merged.rows[0].last_seen,now);}
 assert.equal(mergeDensityPacket(prior,packet([row({status:'missing'})]),source,now).rows.length,0);
 const recovered=mergeDensityPacket(prior,{...packet([row({last_seen:now+1})]),history:[row({status:'missing'})]},source,now+1);assert.equal(densityLevels(recovered,source,now+1)[0].confirmed,true);
});
test('omission retention is bounded to previous displayed lines and malformed oversized packets stay unconfirmed',()=>{
 const {mergeDensityPacket}=require('../src/trading-panel/chart-levels.js'),prior=packet(Array.from({length:100},(_,i)=>row({id:String(i),side:i%2?'ask':'bid',notional:200000+i})));
 assert.equal(mergeDensityPacket(prior,packet([]),source,now).rows.length,6);
 const next=mergeDensityPacket(prior,packet(Array(501).fill(row())),source,now);assert.equal(next.status,'unavailable');assert.equal(next.rows.length,6);assert.ok(densityLevels(next,source,now).every(r=>!r.confirmed));
});
test('density overlays isolate both venue and symbol and exclude missing/outside-depth amounts',()=>{
 const ordinary={...row({id:'ordinary-noise'}),significance:undefined},unqualified={...row({id:'unqualified'}),significance:{status:'significant',kind:'large_wall'}};
 const result=densityLevels(packet([row(),row({id:'other-venue',exchange:'binance'}),row({id:'other-coin',symbol:'ETHUSDT'}),row({id:'missing',status:'missing'}),row({id:'tiny',notional:90000}),row({id:'far',distance_pct:.51}),ordinary,unqualified]),source,now);
 assert.deepEqual(result.map(r=>r.id),['one']);assert.equal(result[0].confirmed,true);
});
test('receipt and per-level source time expire separately, errors never confirm retained densities',()=>{
 const p=packet([row()]);for(const value of [{...p,status:'unavailable'},{...p,updated:now-31},packet([row({last_seen:now-26})]),packet([row({last_seen:now+3})]),packet([row({status:'unobserved'})])])assert.equal(densityLevels(value,source,now)[0].confirmed,false);
 assert.equal(densityLevels({...p,status:'partial'},source,now)[0].confirmed,true);
});
test('inactive significance retains only grey history and incoherent source evidence cannot create a line',()=>{
 const active=row(),inactive={...active,significance:{...active.significance,status:'inactive',kind:null,observed_kind:'large_wall'}},future=row({id:'future-source',last_seen:now+3});
 const retained=densityLevels(packet([inactive,future]),source,now);assert.equal(retained.length,2);assert.ok(retained.every(level=>!level.confirmed),'inactive significance and future source observations cannot confirm fresh-looking active rows');
 const wrongStamp={...active,id:'wrong-source',significance:{...active.significance,last_source_ts:now-1}},wrongSamples={...active,id:'wrong-samples',significance:{...active.significance,source_stamps:[now-1]}};
 assert.deepEqual(densityLevels(packet([wrongStamp,wrongSamples]),source,now),[],'row/source stamp mismatches and incomplete sample evidence are hidden');
});
test('density overlays are bounded to the three largest levels on each side',()=>{
 const rows=Array.from({length:20},(_,i)=>row({id:String(i),side:i%2?'ask':'bid',notional:100000+i*10000})),levels=densityLevels(packet(rows),source,now);assert.equal(levels.length,6);assert.deepEqual(levels.filter(r=>r.side==='ask').map(r=>r.id),['19','17','15']);
});
test('manual annotation storage rejects broken types, IDs and prices and has a hard limit',()=>{
 const valid={id:'one',type:'resistance',price:101};assert.deepEqual(cleanManual([valid,{...valid,price:NaN},{...valid,type:'order'},{...valid,id:'<script>'},{...valid,price:-1}]),[valid]);assert.equal(cleanManual(Array.from({length:30},(_,i)=>({...valid,id:String(i)}))).length,12);assert.deepEqual(cleanManual({}),[]);
});
