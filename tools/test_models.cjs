const {test}=require('node:test'),assert=require('node:assert/strict');
const {buttons,testSlot}=require('../src/trading-panel/models.js');
const row=(phase,kind='model')=>({kind,phase,actions:{start:true,stop:true,restart:true}});
test('actual state governs model buttons; stale and pending commands stay disabled',()=>{
 assert.deepEqual(buttons(row('running')),{start:false,stop:true,restart:true});
 assert.deepEqual(buttons(row('paused')),{start:true,stop:false,restart:true});
 assert.deepEqual(buttons(row('running'),false),{start:false,stop:false,restart:false});
 assert.equal(buttons({...row('draining'),pending:true,requested:'stop'}).stop,false);
 assert.equal(buttons({...row('running'),busy:true}).restart,false);
});
test('unprepared engines cannot start; running test can only be stopped',()=>{
 assert.deepEqual(buttons({kind:'engine',phase:'not_installed',actions:{}}),{start:false,stop:false,restart:false});
 assert.equal(buttons(row('idle','engine')).restart,false);
 assert.equal(buttons({kind:'engine',phase:'running',actions:{start:false,stop:true,restart:false}}).stop,true);
});
test('one test slot disables other engines, preserves cancellation and never enables rejected actions',()=>{
 const ft={id:'freqtrade',...row('running','engine'),actions:{start:false,stop:true,restart:false}},
       j={id:'jesse',...row('idle','engine')},hb={id:'hummingbot',kind:'engine',phase:'not_installed',actions:{}};
 const occupied=testSlot(j,[ft,j,hb]);assert.equal(occupied.occupiedBy,'freqtrade');
 assert.deepEqual(buttons(occupied.item),{start:false,stop:true,restart:false});
 assert.equal(buttons(testSlot(ft,[ft,j]).item).stop,true,'running test remains cancellable');
 assert.equal(buttons(testSlot(hb,[{...ft,phase:'completed'}]).item).start,false);
 assert.equal(buttons(testSlot(j,[{...ft,phase:'completed'},j]).item).start,true);
 assert.equal(buttons(testSlot(j,[{...ft,phase:'idle',busy:true},j]).item).start,false);
 assert.equal(buttons(testSlot(j,[{...ft,phase:'starting'},j]).item).start,false);
 assert.deepEqual(testSlot(row('running'),[ft]).item,row('running'),'model controls keep their own lifecycle');
});
