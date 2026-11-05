/* Visible liquidity and sampled repricing evidence; never an actor identifier. */
(function(scope){
 'use strict';
 const finite=n=>typeof n==='number'&&Number.isFinite(n),count=(n,min=0,max=12)=>Number.isInteger(n)&&n>=min&&n<=max;
 const kinds=['large_wall','machine_pattern_suspect'];
 function view(row,now=Date.now()/1000,{historical=false}={}){
  const s=row?.significance;if(!s||!['significant','inactive'].includes(s.status)||!finite(row.notional)||row.notional<100000||!finite(row.distance_pct)||row.distance_pct<0||row.distance_pct>.5||!finite(s.last_source_ts)||s.last_source_ts!==row.last_seen)return null;
  const kind=s.status==='inactive'?s.observed_kind:s.kind;if(!kinds.includes(kind)||!count(s.observations,1)||!finite(s.first_source_ts)||s.first_source_ts>s.last_source_ts||!Array.isArray(s.source_stamps)||s.source_stamps.length!==s.observations||s.source_stamps.some((t,i)=>!finite(t)||t>s.last_source_ts||i&&t<=s.source_stamps[i-1])||s.source_stamps.at(-1)!==s.last_source_ts)return null;
  const relative=finite(s.relative_size)&&s.relative_size>=5&&count(s.neighbor_count,3,12)&&finite(s.local_median_notional)&&s.local_median_notional>0&&Math.abs(row.notional/s.local_median_notional-s.relative_size)<=Math.max(1e-6,s.relative_size*1e-6);
  const share=finite(s.visible_depth_share)&&s.visible_depth_share>=.2&&s.visible_depth_share<=1&&count(s.side_level_count,5,1000)&&finite(s.side_depth_notional)&&s.side_depth_notional>=row.notional&&Math.abs(row.notional/s.side_depth_notional-s.visible_depth_share)<=1e-6;
  if(!relative&&!share)return null;
  const p=s.pattern||{};if(kind==='machine_pattern_suspect'){
   if(!count(p.samples,3)||!count(p.repricings,2,11)||p.repricings>=p.samples||!count(p.side_pressure_observations,3)||p.side_pressure_observations!==p.samples||p.ambiguous!==false||!finite(s.near_pressure_share)||s.near_pressure_share<.6||s.near_pressure_share>1||!Array.isArray(p.price_path)||p.price_path.length<3||p.price_path.length>3)return null;
   if(p.price_path.some((point,i)=>!point||!finite(point.source_ts)||point.source_ts>s.last_source_ts||s.last_source_ts-point.source_ts>120||!finite(Number(point.price_text))||Number(point.price_text)<=0||i&&(point.source_ts<=p.price_path[i-1].source_ts||Number(point.price_text)===(Number(p.price_path[i-1].price_text)))))return null;
   if(Number(p.price_path.at(-1).price_text)!==row.price)return null;
  }
  const current=row.status==='active'&&s.status==='significant'&&finite(now)&&now-s.last_source_ts>=-2&&now-s.last_source_ts<=25;
  if(!historical&&!current)return null;
  return {kind,current,priority:kind==='machine_pattern_suspect'?2:1,relative:relative?s.relative_size:null,share:share?s.visible_depth_share:null,observations:s.observations,samples:kind==='machine_pattern_suspect'?p.samples:s.observations,repricings:kind==='machine_pattern_suspect'?p.repricings:0,pressure:kind==='machine_pattern_suspect'?s.near_pressure_share:null,title:kind==='machine_pattern_suspect'?'Смещается к цене':'Крупная у цены'};
 }
 function matches(row,focus='significant',now=Date.now()/1000,historical=row.status!=='active'){const evidence=view(row,now,{historical});return !!evidence&&(focus==='significant'||focus==='patterns'&&evidence.kind==='machine_pattern_suspect'||focus==='large'&&evidence.kind==='large_wall');}
 const api={view,matches};if(typeof module!=='undefined')module.exports=api;else scope.LabDensitySignals=api;
})(typeof window==='undefined'?globalThis:window);
