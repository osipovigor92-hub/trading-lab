const {test}=require('node:test'),assert=require('node:assert/strict');
const {buttons}=require('../src/trading-panel/models.js');
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
