const {test}=require('node:test'),assert=require('node:assert/strict');
const {buttons,testSlot,executor,operationsSummary}=require('../src/trading-panel/models.js');
const row=(phase,kind='model')=>({kind,phase,actions:{start:true,stop:true,restart:true}});
test('actual state governs model buttons; stale and pending commands stay disabled',()=>{
 assert.deepEqual(buttons(row('running')),{start:false,stop:true,restart:true,new_run:false});
 assert.deepEqual(buttons(row('paused')),{start:true,stop:false,restart:true,new_run:false});
 assert.deepEqual(buttons(row('running'),false),{start:false,stop:false,restart:false,new_run:false});
 assert.equal(buttons({...row('draining'),pending:true,requested:'stop'}).stop,false);
 assert.equal(buttons({...row('running'),busy:true}).restart,false);
});
test('PC selection uses PC memory and generation while the VPS remains unprepared',()=>{
 const raw={id:'jesse',kind:'engine',installed:false,memory_ok:false,generation:4,
  executors:{vds:{installed:false,memory_ok:false,phase:'not_installed',actions:{}},
   pc:{installed:true,memory_ok:true,generation:7,phase:'idle',actions:{start:true,stop:false,restart:true}}}};
 const pc=executor(raw,'pc');assert.equal(pc.execution,'pc');assert.equal(pc.generation,7);
 assert.equal(buttons(pc).start,true);assert.equal(buttons(executor(raw,'vds')).start,false);
 assert.equal(buttons(executor({...raw,executors:undefined},'pc')).start,false,'old broker cannot pretend PC support exists');
});
test('running or disconnected PC tasks occupy the shared slot and keep stop available',()=>{
 const pc={phase:'lost',installed:true,test_active:true,actions:{start:false,stop:true,restart:false}};
 const raw={id:'freqtrade',kind:'engine',test_active:true,executors:{pc,vds:{...row('idle','engine'),test_active:false}}};
 assert.equal(buttons(executor(raw,'vds')).start,false,'same engine cannot start again on another executor');
 assert.equal(buttons(executor(raw,'pc')).stop,true);
 const j={id:'jesse',...row('idle','engine')};assert.equal(buttons(testSlot(j,[raw,j]).item).start,false);
 assert.equal(buttons(executor(raw,'pc'),false).stop,false,'stale controller response cannot command a task');
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

test('operations summary reports only confirmed controller state',()=>{
 const state={models:[{phase:'running'},{phase:'warming'},{phase:'halted'},{phase:'paused'}],worker:{configured:true,online:true},engines:[
  {id:'freqtrade',test_active:true,phase:'running',executors:{vds:{installed:false,memory_ok:false},pc:{installed:true,memory_ok:true}}},
  {id:'jesse',phase:'idle',executors:{vds:{installed:true,memory_ok:true},pc:{installed:true,memory_ok:true}}},
  {id:'hummingbot',phase:'not_installed',executors:{vds:{installed:false,memory_ok:false},pc:{installed:false,memory_ok:false}}}]};
 const live=operationsSummary(state,true);assert.equal(live.activeModels,2);assert.equal(live.protectedModels,1);assert.equal(live.activeEngine,'freqtrade');assert.equal(live.workerOnline,true);assert.equal(live.readyPc,2);assert.equal(live.readyVds,1);
 const stale=operationsSummary(state,false);assert.equal(stale.workerOnline,false);assert.equal(stale.activeEngine,'freqtrade');
});
