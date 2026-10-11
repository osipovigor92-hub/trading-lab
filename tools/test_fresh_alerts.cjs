const {test}=require('node:test'),assert=require('node:assert/strict');
const {observationFeed,currentEvents,consume,archive,signalDirection,recommendation,currentRecommendation,eventTitle}=require('../src/trading-panel/fresh-alerts.js');
const event=(sequence=1)=>({id:'epoch:'+sequence,sequence,symbol:'BTCUSDT',kind:'ready',label:'Кандидат готов',detail:'Все проверки',time:1000,expires:1008,sources:{quote:1000,chart:1000,candle:980,book:1000,fetched:1000}});
const packet=(events=[event()],cursor=1)=>({status:'ok',epoch:'epoch',scope:'filters',updated:1000,cursor,events});
const signal=(kind='momentum_up')=>({...event(),kind,exchange:'bybit',setup:kind,signal_id:'BTCUSDT:'+kind+':1:960',candle_end:960,sources:{quote:1000,chart:1000,candle:960},
 recommendation:{direction:kind.endsWith('_up')?'LONG':'SHORT',setup:kind,exchange:'bybit',timeframe:'1',signal_id:'BTCUSDT:'+kind+':1:960',candle_end:960,expires:1008,reason:'EMA и объём подтверждены',invalidation:'Закрытие вернулось за EMA20'}});

test('only confirmed directional setups carry matching source-bound recommendations',()=>{
 for(const kind of ['breakout_up','momentum_up','breakout_down','momentum_down']){const s=signal(kind),direction=kind.endsWith('_up')?'LONG':'SHORT';assert.equal(signalDirection(kind),direction);assert.equal(recommendation(s,1000).direction,direction);assert.equal(eventTitle(s,true,1000),'Рекомендация '+direction);assert.equal(eventTitle(s,false,1000),direction+' · история');}
 for(const kind of ['ready','near_level','watch','waiting','entry'])assert.equal(recommendation({...signal(),kind},1000),null);
 const s=signal();for(const change of [{direction:'SHORT'},{setup:'momentum_down'},{exchange:'binance'},{timeframe:'5'},{signal_id:'other'},{candle_end:900},{reason:''},{invalidation:''},{expires:999}])assert.equal(recommendation({...s,recommendation:{...s.recommendation,...change}},1000),null);
 assert.equal(recommendation({...s,exchange:'okx'},1000),null);assert.equal(eventTitle({...s,recommendation:null},true,1000),'LONG · сценарий');
 assert.equal(recommendation({...s,symbol:'ETHUSDT'},1000),null);assert.equal(recommendation({...s,sources:{...s.sources,candle:980}},1000),null);
 for(const source of ['quote','chart','candle'])assert.equal(recommendation({...s,sources:{...s.sources,[source]:800}},1000),null);
});

test('current recommendation survives event expiry only with independently fresh assistant proof',()=>{
 const s=signal(),row={symbol:'BTCUSDT',assistant:{...s,kind:undefined,status:'ok',eligible:true,recommendation:{...s.recommendation,expires:1045}}};
 assert.equal(currentRecommendation(row,1009).direction,'LONG');assert.deepEqual(currentEvents(packet([s]),1009),[],'expired event is historical');
 for(const change of [{status:'pending'},{eligible:false},{setup:'watch'},{recommendation:null}])assert.equal(currentRecommendation({...row,assistant:{...row.assistant,...change}},1000),null);
 assert.equal(currentRecommendation({...row,symbol:'ETHUSDT'},1000),null);
 assert.equal(currentRecommendation(row,1046),null);assert.equal(currentRecommendation({...row,assistant:{...row.assistant,sources:{...s.sources,quote:900}}},1000),null);
});
test('visible observations survive expiry and connection loss without claiming freshness',()=>{
 const history=archive([], [event()],1000);
 assert.equal(observationFeed(history,packet(),1000)[0].live,true);
 for(const [p,now]of [[packet(),1009],[null,1001],[{...packet(),events:[]},1001]]){
  const result=observationFeed(history,p,now);assert.equal(result.length,1);assert.equal(result[0].id,event().id);assert.equal(result[0].time,1000);assert.equal(result[0].live,false);
 }
 assert.deepEqual(observationFeed(history,null,90000),[]);
});
test('current events require fresh packet and every original source',()=>{
 assert.equal(currentEvents(packet(),1000).length,1);
 for(const source of ['quote','chart','candle','book','fetched'])assert.deepEqual(currentEvents(packet([{...event(),sources:{...event().sources,[source]:800}}]),1000),[]);
 for(const bad of [{time:800},{time:1100},{expires:999},{symbol:'<script>'},{kind:'entry'},{sequence:NaN}])assert.deepEqual(currentEvents(packet([{...event(),...bad}]),1000),[]);
 assert.deepEqual(currentEvents(packet(),1009),[]);assert.deepEqual(currentEvents({...packet(),updated:994},1000),[]);
});
test('clearing the archive keeps active events visible without replaying notifications',()=>{
 const p=packet(),cursor=consume(p,null,1000).cursor;
 const repeat=consume(p,cursor,1001);
 assert.deepEqual(repeat.captured,[]);assert.deepEqual(repeat.notify,[]);
 const visible=observationFeed([],p,1001);
 assert.equal(visible.length,1);assert.equal(visible[0].live,true);assert.equal(visible[0].time,1000);
 assert.deepEqual(archive([],repeat.captured,1001),[],'cleared archive stays empty');
 assert.deepEqual(observationFeed([],p,1009),[],'cleared event disappears when no longer current');
 assert.equal(observationFeed([event()],packet([{...event(),detail:'Current detail'}]),1001)[0].detail,'Current detail','current payload wins duplicate identity');
});
test('initial load, repeat, reload and server restart do not notify',()=>{
 const first=consume(packet(),null,1000);assert.equal(first.captured.length,1);assert.deepEqual(first.notify,[]);
 const saved=JSON.parse(JSON.stringify(first.cursor));assert.deepEqual(consume(packet(),saved,1000).captured,[]);
 assert.deepEqual(consume({...packet(),epoch:'restart'},saved,1000).notify,[]);
 assert.deepEqual(consume({...packet(),scope:'changed'},saved,1000).notify,[]);
});
test('only newer fresh events notify; late response cannot rewind cursor',()=>{
 const cursor=consume(packet(),null,1000).cursor,next=consume(packet([event(2),event()],2),cursor,1000);
 assert.deepEqual(next.notify.map(e=>e.sequence),[2]);assert.deepEqual(consume(packet(),next.cursor,1000).cursor,next.cursor);
 assert.deepEqual(consume(packet([{...event(3),expires:999}],3),next.cursor,1000).notify,[]);
});
test('history keeps actual event time, distinct identities and bounded previous observations',()=>{
 const a=archive([], [event(),event(),null],1000);assert.equal(a.length,1);assert.equal(a[0].time,1000);
 assert.equal(archive(a,[event(2)],1001).length,2);
 assert.equal(archive(a,[],100000).length,0);
 assert.equal(archive([],Array.from({length:90},(_,i)=>event(i+1)),1001).length,50);
});
