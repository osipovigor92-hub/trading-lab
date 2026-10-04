const {test}=require('node:test'),assert=require('node:assert/strict');
const {buttons,testSlot,executor,operationsSummary,controllerCurrent,activeTest,lastTest,workerHealth,centerState}=require('../src/trading-panel/models.js');
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
 assert.equal(stale.readyPc,0);assert.equal(stale.readyVds,0);
});

const engine=(id='freqtrade')=>({id,kind:'engine',phase:'idle',test_active:false,executors:{
 vds:{phase:'idle',installed:false,memory_ok:false,actions:{}},
 pc:{phase:'idle',installed:true,memory_ok:true,generation:7,actions:{start:true,restart:true,stop:false},runs:[]}
}});
test('freshness rejects expired, future and malformed controller timestamps',()=>{
 assert.equal(controllerCurrent({updated:100},108),true);
 for(const stamp of [99,110,NaN,Infinity,'100',null,undefined])assert.equal(controllerCurrent({updated:stamp},108),false);
 assert.equal(controllerCurrent(null,108),false);
});
test('the control center reserves a lost PC task across engines and executors',()=>{
 const ft=engine(),jesse=engine('jesse');ft.executors.pc={...ft.executors.pc,phase:'lost',test_active:true,memory_ok:false,actions:{stop:true}};
 const state={engines:[ft,jesse]};assert.equal(activeTest(state).execution,'pc');
 const selected=centerState(state,'jesse','pc');assert.equal(selected.canLaunch,false);assert.equal(selected.canStop,true);assert.equal(selected.blockedBy.id,'freqtrade');
 assert.equal(centerState(state,'freqtrade','vds').canLaunch,false,'same engine on a second executor cannot consume another slot');
 assert.equal(centerState(state,'freqtrade','pc',false).canStop,false,'an expired controller cannot cancel a task');
 ft.executors.pc={...ft.executors.pc,phase:'cancelled',test_active:false};assert.equal(centerState(state,'jesse','pc').canLaunch,true);
});
test('pending broker commands and worker leases cannot look like a free slot',()=>{
 const ft={...engine(),busy:true};const state={engines:[ft,engine('jesse')]};
 assert.equal(centerState(state,'freqtrade','pc').canLaunch,false);assert.equal(centerState(state,'jesse','pc').canLaunch,false);
 assert.equal(executor(ft,'pc').busy,true,'executor overlay preserves broker busy state');
 const queued={engines:[engine('jesse')],worker:{job:{engine:'freqtrade',phase:'queued'}}};
 assert.equal(centerState(queued,'jesse','pc').canLaunch,false);assert.equal(centerState(queued,'jesse','pc').canStop,false,'no unadvertised cancel action is invented');
 queued.worker.job.phase='completed';assert.equal(activeTest(queued),null);
 const accepted={...engine(),localPending:{execution:'pc'}};
 const pending=centerState({engines:[accepted,engine('jesse')]},'jesse','pc');
 assert.equal(pending.canLaunch,false);assert.equal(pending.canStop,false);assert.equal(pending.active.execution,'pc');assert.equal(pending.active.item.phase,'pending');
});
test('a disconnected controller is distinct from an offline PC; RAM requires current online state',()=>{
 const state={worker:{configured:true,online:true,last_seen:100,memory:{total_gb:8,available_gb:7}},engines:[engine()]};
 assert.equal(workerHealth(state).phase,'online');assert.equal(workerHealth(state,false).phase,'unknown');assert.equal(workerHealth(state,false).memory,null);
 state.worker.online=false;assert.equal(workerHealth(state).phase,'offline');assert.equal(workerHealth(state).memory,null);assert.equal(workerHealth(state).lastSeen,100);
 assert.equal(operationsSummary(state).readyPc,0);assert.equal(workerHealth(null).phase,'unconfigured');
});
test('results come from the latest finished run on the selected executor, preserving cancellation and zero values',()=>{
 const ft=engine(),result={execution:'pc',phase:'completed',metrics:{net:0,count:0,drawdown_pct:0,profit_factor:null}};
 ft.executors.pc={...ft.executors.pc,phase:'running',metrics:{net:123,count:99},runs:[{execution:'pc',phase:'running',metrics:{net:500}},result]};
 const state={engines:[ft]};assert.equal(lastTest(executor(ft,'pc')),result);
 assert.equal(centerState(state,'freqtrade','pc',false).result.metrics.net,0,'archive stays explicitly separate from current execution');
 assert.equal(lastTest(executor(ft,'vds')),null,'PC results do not appear as VDS results');
 const cancelled={execution:'pc',phase:'cancelled',metrics:null};ft.executors.pc.runs.unshift(cancelled);
 assert.equal(lastTest(executor(ft,'pc')),cancelled,'cancellation never borrows metrics from an earlier success');
 ft.executors.pc={...ft.executors.pc,phase:'completed',runs:[result]};
 assert.equal(centerState(state,'freqtrade','pc').launchAction,'restart');assert.equal(centerState(state,'freqtrade','pc',false).canLaunch,false);
});
