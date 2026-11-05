const {test}=require('node:test'),assert=require('node:assert/strict'),{view,matches}=require('../src/trading-panel/density-signals.js');
const now=1800000030;
const row=(patch={})=>({status:'active',price:99.8,notional:200000,distance_pct:.2,last_seen:now,significance:{status:'significant',kind:'large_wall',observed_kind:'large_wall',relative_size:10,local_median_notional:20000,neighbor_count:6,visible_depth_share:.25,side_depth_notional:800000,side_level_count:10,observations:1,first_source_ts:now,last_source_ts:now,source_stamps:[now],pattern:{}},...patch});
test('only measured near large outliers or visible-side concentration qualify',()=>{
 assert.equal(view(row(),now).title,'Крупная у цены');for(const patch of [{significance:undefined},{notional:99999},{distance_pct:.51},{distance_pct:NaN}])assert.equal(view(row(patch),now),null);
 const ordinary=row();ordinary.significance={...ordinary.significance,status:'ordinary',observed_kind:null};assert.equal(view(ordinary,now),null);
 const sparse=row();sparse.significance={...sparse.significance,neighbor_count:2,side_level_count:4};assert.equal(view(sparse,now),null);
 const mismatch=row();mismatch.significance={...mismatch.significance,relative_size:9,visible_depth_share:.9};assert.equal(view(mismatch,now),null);
});
test('stale evidence stays historical and cannot become a current machine label',()=>{
 assert.equal(view(row(),now+26),null);assert.equal(view(row({status:'unavailable'}),now),null);assert.equal(view(row({status:'unavailable'}),now,{historical:true}).current,false);
 const r=row();r.significance={...r.significance,status:'inactive',kind:null};r.status='missing';assert.equal(view(r,now,{historical:true}).kind,'large_wall');assert.equal(matches(r,'patterns',now,true),false);
 for(const bad of [now+3,now-1]){const r=row();r.significance={...r.significance,last_source_ts:bad};assert.equal(view(r,now),null);}
});
test('a repeated-pattern label requires genuine increasing source and price paths, no ambiguous owner match',()=>{
 const r=row();r.significance={...r.significance,kind:'machine_pattern_suspect',observed_kind:'machine_pattern_suspect',near_pressure_share:.8,pattern:{samples:3,repricings:2,side_pressure_observations:3,ambiguous:false,price_path:[{source_ts:now-20,price_text:'99.6'},{source_ts:now-10,price_text:'99.7'},{source_ts:now,price_text:'99.8'}]}};
 assert.equal(view(r,now).repricings,2);assert.equal(matches(r,'patterns',now),true);assert.equal(matches(r,'large',now),false);
 for(const change of [{samples:2},{repricings:1},{ambiguous:true},{side_pressure_observations:2},{price_path:r.significance.pattern.price_path.map(p=>({...p,price_text:'99.8'}))}])assert.equal(view({...r,significance:{...r.significance,pattern:{...r.significance.pattern,...change}}},now),null);
});
