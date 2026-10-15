/* Synthetic source evidence: stamp metadata always follows the supplied row. */
function withSignificance(row, overrides={}) {
 const stamp=row.last_seen,active=row.status==='active';
 return {...row,significance:{status:active?'significant':'inactive',kind:active?'large_wall':null,observed_kind:'large_wall',relative_size:10,local_median_notional:row.notional/10,neighbor_count:6,visible_depth_share:.25,side_depth_notional:row.notional*4,side_level_count:10,observations:1,first_source_ts:stamp,last_source_ts:stamp,source_stamps:[stamp],pattern:{},...overrides}};
}
function withRepricingSignificance(row) {
 const stamp=row.last_seen,stamps=[stamp-20,stamp-10,stamp],direction=row.side==='bid'?1:-1;
 return withSignificance(row,{kind:row.status==='active'?'machine_pattern_suspect':null,observed_kind:'machine_pattern_suspect',observations:3,first_source_ts:stamps[0],source_stamps:stamps,near_pressure_share:.75,pattern:{samples:3,repricings:2,side_pressure_observations:3,ambiguous:false,price_path:stamps.map((source_ts,index)=>({source_ts,price_text:String(row.price-direction*(2-index)*.02)}))}});
}
module.exports={withSignificance,withRepricingSignificance};
