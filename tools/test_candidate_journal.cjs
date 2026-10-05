const {test}=require('node:test'),assert=require('node:assert/strict');
const {closingSummary}=require('../src/trading-panel/candidate-journal.js');
test('Only confirmed closed PAPER net contributes; open/unknown figures never become zero results',()=>{
 assert.deepEqual(closingSummary([{complete:true,net:2},{complete:true,net:-1},{complete:false,net:null},{complete:true,net:0,observation_gap:'Restart'}]),{exact:3,incomplete:1,gaps:1,net:1});
 assert.deepEqual(closingSummary([{complete:false,net:100},{complete:true,net:null}]),{exact:0,incomplete:2,gaps:0,net:null});
});
