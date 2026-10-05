const {test}=require('node:test'),assert=require('node:assert/strict');
const {currentEvents,consume,archive}=require('../src/trading-panel/fresh-alerts.js');
const event=(sequence=1)=>({id:'epoch:'+sequence,sequence,symbol:'BTCUSDT',kind:'ready',label:'Кандидат готов',detail:'Все проверки',time:1000,expires:1008,sources:{quote:1000,chart:1000,candle:980,book:1000,fetched:1000}});
const packet=(events=[event()],cursor=1)=>({status:'ok',epoch:'epoch',scope:'filters',updated:1000,cursor,events});
test('current events require fresh packet and every original source',()=>{
 assert.equal(currentEvents(packet(),1000).length,1);
 for(const source of ['quote','chart','candle','book','fetched'])assert.deepEqual(currentEvents(packet([{...event(),sources:{...event().sources,[source]:800}}]),1000),[]);
 for(const bad of [{time:800},{time:1100},{expires:999},{symbol:'<script>'},{kind:'entry'},{sequence:NaN}])assert.deepEqual(currentEvents(packet([{...event(),...bad}]),1000),[]);
 assert.deepEqual(currentEvents(packet(),1009),[]);assert.deepEqual(currentEvents({...packet(),updated:994},1000),[]);
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
