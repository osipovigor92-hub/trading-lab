const {test}=require('node:test');const assert=require('node:assert/strict');const vm=require('node:vm');const fs=require('node:fs');const path=require('node:path');
function setup(hidden=false,{clock=performance,responder}={}){const listeners=new Set();let calls=0;
const document={hidden,addEventListener:(name,fn)=>listeners.add(fn),removeEventListener:(name,fn)=>listeners.delete(fn)};
const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/trading-panel/data-client.js'),'utf8'),{document,window,performance:clock,AbortSignal,fetch:async(url,options)=>{calls++;const number=calls;await Promise.resolve();return responder?responder(url,options,number):new Response('{"ok":true}')},Map,Promise});
return {document,window,listeners,calls:()=>calls};}
test('duplicate requests share network and bodies can be read independently',async()=>{const s=setup();const [a,b]=await Promise.all([s.window.labFetch('/api/x'),s.window.labFetch('/api/x')]);assert.equal(s.calls(),1);assert.deepEqual(await a.json(),{ok:true});assert.deepEqual(await b.json(),{ok:true});await (await s.window.labFetch('/api/x')).json();assert.equal(s.calls(),1);});
test('explicit refresh bypasses the short response cache while sharing simultaneous reads',async()=>{const s=setup();await s.window.labFetch('/api/x');const [a,b]=await Promise.all([s.window.labFetch('/api/x',{fresh:true}),s.window.labFetch('/api/x',{fresh:true})]);assert.equal(s.calls(),2);assert.deepEqual(await a.json(),{ok:true});assert.deepEqual(await b.json(),{ok:true});});
test('background requests wait until page becomes visible',async()=>{const s=setup(true);const p=s.window.labFetch('/api/x');await Promise.resolve();assert.equal(s.calls(),0);s.document.hidden=false;for(const fn of [...s.listeners])fn();await p;assert.equal(s.calls(),1);});
test('only the read-only alert endpoint can poll while hidden',async()=>{const s=setup(true);await s.window.labFetch('/api/market-alerts?search=BTC',{background:true});assert.equal(s.calls(),1);const blocked=s.window.labFetch('/api/manual-paper',{background:true});await Promise.resolve();assert.equal(s.calls(),1);s.document.hidden=false;for(const fn of [...s.listeners])fn();await blocked;assert.equal(s.calls(),2);});
test('HTML returned by a gateway becomes an actionable API error',async()=>{const s=setup();await assert.rejects(()=>s.window.labParseJson(new Response('<html><h1>Gateway</h1></html>',{headers:{'content-type':'text/html'}}),'Управление моделями'),/SSH-туннель/);});

test('response cache is bounded at 48 URLs and keeps recently used responses',async()=>{
 const s=setup(false,{clock:{now:()=>0},responder:(url,options,number)=>new Response(JSON.stringify({url,number}))});
 for(let i=0;i<48;i++)assert.equal((await (await s.window.labFetch('/api/coin/'+i)).json()).number,i+1);
 assert.equal((await (await s.window.labFetch('/api/coin/0')).json()).number,1);assert.equal(s.calls(),48);
 await s.window.labFetch('/api/coin/48');assert.equal(s.calls(),49);
 assert.equal((await (await s.window.labFetch('/api/coin/0')).json()).number,1,'LRU hit retains its detached response');
 assert.equal((await (await s.window.labFetch('/api/coin/47')).json()).number,48);assert.equal(s.calls(),49,'recent URLs avoid network');
 assert.equal((await (await s.window.labFetch('/api/coin/1')).json()).number,50,'oldest unused response was evicted at the 49th URL');
 for(let i=49;i<149;i++)await s.window.labFetch('/api/coin/'+i);
 const before=s.calls();await s.window.labFetch('/api/coin/0');assert.equal(s.calls(),before+1,'long sessions cannot retain every unique URL');
});

test('cache hits do not extend the original 750ms response lifetime',async()=>{
 let now=0;const s=setup(false,{clock:{now:()=>now},responder:(url,options,number)=>new Response(JSON.stringify({number}))});
 assert.equal((await (await s.window.labFetch('/api/x')).json()).number,1);
 now=600;assert.equal((await (await s.window.labFetch('/api/x')).json()).number,1);
 now=749;assert.equal((await (await s.window.labFetch('/api/x')).json()).number,1);assert.equal(s.calls(),1);
 now=750;assert.equal((await (await s.window.labFetch('/api/x')).json()).number,2,'expiry follows receipt, not last cache use');assert.equal(s.calls(),2);
 now=1500;await s.window.labFetch('/api/y');await s.window.labFetch('/api/x');assert.equal(s.calls(),4,'expired entries are removed before unrelated inserts');
});

test('HTTP failures are not cached while simultaneous failed reads still share a GET',async()=>{
 const s=setup(false,{responder:()=>new Response('{"error":"rate limit"}',{status:429})});
 assert.equal((await s.window.labFetch('/api/x')).status,429);assert.equal((await s.window.labFetch('/api/x')).status,429);assert.equal(s.calls(),2);
 const [a,b]=await Promise.all([s.window.labFetch('/api/x'),s.window.labFetch('/api/x')]);assert.equal(s.calls(),3);assert.deepEqual(await a.json(),{error:'rate limit'});assert.deepEqual(await b.json(),{error:'rate limit'});
});

test('commands never share the response cache or a simultaneous command',async()=>{
 const s=setup();await s.window.labFetch('/api/x');await Promise.all([s.window.labFetch('/api/x',{method:'POST',body:'{"x":1}'}),s.window.labFetch('/api/x',{method:'POST',body:'{"x":1}'})]);assert.equal(s.calls(),3);
 await s.window.labFetch('/api/x');assert.equal(s.calls(),3,'command responses do not replace cached GET');
});

test('visibility changes invalidate successful cached responses',async()=>{
 const s=setup();await s.window.labFetch('/api/x');for(const fn of [...s.listeners])fn();await s.window.labFetch('/api/x');assert.equal(s.calls(),2);
});
