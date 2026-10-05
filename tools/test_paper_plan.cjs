const {test}=require('node:test'),assert=require('node:assert/strict');
const {paperPlan,planDefaults,validatePlan}=require('../src/trading-panel/screener.js');
const {fixture}=require('./paper_plan_fixture.cjs');

const clone=o=>structuredClone(o);
test('LONG and SHORT use confirmed zones and net rather than gross reward/risk',()=>{
 for(const side of [1,-1]){
  const p=paperPlan(fixture(side));assert.equal(p.status,'ready');assert.equal(p.data.side,side);assert.equal(p.data.targets.length,2);
  const d=p.data;assert.ok(side*(d.entry-d.stop)>0);assert.ok(d.targets.every(t=>side*(t.price-d.entry)>0));assert.ok(d.risk<=d.budget);assert.ok(d.notional<=100);
  assert.ok(d.targets[0].rr<(side*(d.targets[0].price-d.entry))/(side*(d.entry-d.stop)));
  assert.ok(Math.abs(d.targets[0].profit/d.risk-d.targets[0].rr)<1e-10);assert.equal(d.funding_reserve,0);
 }
});
test('sizing respects the requested risk, notional and cash including entry fee',()=>{
 for(const side of [1,-1])for(const capital of [10,100,600,1e6])for(const risk_pct of [.01,.5,5]){
  const f=fixture(side);f.settings={...planDefaults,capital,risk_pct,max_notional:capital};
  const p=paperPlan(f),d=p.data;assert.ok(d);assert.ok(d.risk<=capital*risk_pct/100*(1+1e-12));assert.ok(d.notional*(1+f.settings.fee_pct/100)<=capital*(1+1e-12));assert.ok(d.quantity>0);assert.ok(Number.isFinite(d.risk));
 }
 const f=fixture();f.settings={...planDefaults,risk_pct:.01,max_notional:600};const d=paperPlan(f).data;assert.ok(Math.abs(d.risk-.06)<1e-12);
});
test('fees, slippage, spread and adverse funding reduce net RR; receiving funding gives no profit credit',()=>{
 for(const side of [1,-1]){
  const f=fixture(side),plain=paperPlan(f).data;
  for(const key of ['fee_pct','slippage_pct']){const next=clone(f);next.settings[key]*=3;assert.ok(paperPlan(next).data.targets[0].rr<plain.targets[0].rr);}
  for(const direction of [side,-side]){const next=clone(f);next.snapshot.rows[0].funding=.001*direction;const d=paperPlan(next).data;assert.ok(d);if(direction===side){assert.ok(d.funding_reserve>0);assert.ok(d.targets[0].rr<plain.targets[0].rr);}else{assert.equal(d.funding_reserve,0);assert.equal(d.targets[0].rr,plain.targets[0].rr);}}
 }
 const f=fixture();f.settings.fee_pct=f.settings.slippage_pct=0;assert.equal(paperPlan(f).status,'ready');
});
test('all four timeframes work; gaps, open candles and mismatched identity cannot form a ready plan',()=>{
 for(const interval of ['1','5','15','60'])assert.equal(paperPlan(fixture(1,interval)).status,'ready');
 for(const mutate of [f=>f.chart.symbol='ETHUSDT',f=>f.chart.interval='1',f=>f.chart.candle_end+=300,f=>f.chart.candles.at(-1).time+=300,f=>f.chart.candles[10].time+=1,f=>f.chart.candles[0].low=-1,f=>f.chart.price+=1,f=>f.chart.candles=f.chart.candles.slice(-30)]){const f=fixture();mutate(f);assert.notEqual(paperPlan(f).status,'ready');assert.equal(paperPlan(f).data,null);}
});
test('stale, future, pending and failed refresh sources hide the PAPER calculation independently',()=>{
 for(const key of ['snapshot','chart','book'])for(const change of [{updated:359900},{updated:360034},{status:'pending'},{status:'error'},{refresh_error:'offline'}]){const f=fixture();Object.assign(f[key],change);assert.equal(paperPlan(f).status,'pending');assert.equal(paperPlan(f).data,null);}
 for(const key of ['tickerError','chartError','bookError']){const f=fixture();f[key]='HTTP 503';assert.equal(paperPlan(f).status,'pending');}
});
test('complete matching selection is required and high ranking never overrides a failed filter',()=>{
 for(const mutate of [f=>f.selectionPacket=null,f=>f.selectionPacket.rows={},f=>f.selectionPacket.source_time-=1,f=>f.selectionPacket.rows[0].selection.ticker_time-=1,f=>f.selectionPacket.rows[0].selection.samples=4,f=>f.selectionPacket.rows[0].selection.checks.pop(),f=>f.selectionPacket.rows[0].selection.rating.score=99]){const f=fixture();mutate(f);assert.equal(paperPlan(f).status,'pending');}
 const f=fixture();f.selectionPacket.rows[0].selection.status='rejected';f.selectionPacket.rows[0].selection.checks[0].state='fail';assert.equal(paperPlan(f).status,'rejected');assert.match(paperPlan(f).reasons[0],/turnover/);
});
test('missing trend or geometry stays unavailable; a missing second zone is not fabricated',()=>{
 for(const mutate of [f=>f.chart.atr=0,f=>f.chart.vwap=null,f=>f.chart.vwap=100,f=>f.chart.levels=[],f=>f.chart.levels[0].pivots=0,f=>f.chart.levels=f.chart.levels.filter(l=>l.side==='support'),f=>f.snapshot.rows[0].funding=null]){const f=fixture();mutate(f);assert.equal(paperPlan(f).status,'neutral');assert.equal(paperPlan(f).data,null);}
 const f=fixture();f.chart.levels.pop();const p=paperPlan(f);assert.equal(p.status,'ready');assert.equal(p.data.targets.length,1);
 const narrow=fixture();narrow.chart.levels[1]={side:'resistance',low:100.02,high:100.03,price:100.025,pivots:1};assert.equal(paperPlan(narrow).status,'rejected');
});
test('entry zone boundaries, crossed stop, reached first target and occupied PAPER position have distinct states',()=>{
 const quote=(f,p)=>{f.snapshot.rows[0].price=p;f.book.mid=p;f.book.top.bid[0].price=p*.9999;f.book.top.ask[0].price=p*1.0001;};
 for(const side of [1,-1]){
  const base=fixture(side),d=paperPlan(base).data;
  for(const p of [d.low,d.high]){const f=clone(base);quote(f,p);assert.equal(paperPlan(f).status,'ready');}
  const watch=clone(base);quote(watch,side===1?d.high+.1:d.low-.1);assert.equal(paperPlan(watch).status,'watch');
  for(const p of [d.stop,d.targets[0].price]){const f=clone(base);quote(f,p);assert.equal(paperPlan(f).status,'invalidated');}
  const occupied=clone(base);occupied.models={B:{phase:'running',updated:occupied.now,position:{symbol:'BTCUSDT',side,quantity:1,entry:100}}};assert.equal(paperPlan(occupied).status,'watch');occupied.models.B.phase='halted';assert.equal(paperPlan(occupied).status,'ready');
 }
});
test('actual calculated quantity must fit verified visible depth and slippage budget',()=>{
 for(const side of [1,-1]){
  const f=fixture(side);f.book.top.ask[0].quantity=.001;assert.equal(paperPlan(f).status,'rejected');
  const partial=fixture(side);partial.book.bands['0.001'].covered=false;assert.equal(paperPlan(partial).status,'pending');
  const impact=fixture(side);const best=impact.book.top.ask[0].price;impact.book.top.ask=[{price:best,quantity:.001},{price:best*1.01,quantity:100}];assert.equal(paperPlan(impact).status,'rejected');assert.match(paperPlan(impact).reasons[0],/impact/);
 }
 const crossed=fixture();crossed.book.top.bid[0].price=crossed.book.top.ask[0].price;assert.equal(paperPlan(crossed).status,'rejected');
 const skew=fixture();skew.book.mid+=2;assert.equal(paperPlan(skew).status,'pending');
 const mismatch=fixture();for(const side of ['bid','ask'])mismatch.book.top[side][0].price*=1.01;assert.equal(paperPlan(mismatch).status,'pending');assert.equal(paperPlan(mismatch).data,null);
});
test('minimum net RR boundary is inclusive and does not change the risk budget',()=>{
 const f=fixture(),rr=paperPlan(f).data.targets[0].rr;f.settings.min_rr=rr;assert.equal(paperPlan(f).status,'ready');
 f.settings.min_rr=rr+1e-9;assert.equal(paperPlan(f).status,'rejected');assert.equal(paperPlan(f).data.budget,3);
});
test('invalid settings and nonfinite geometry never yield numeric size or risk',()=>{
 assert.deepEqual(validatePlan({}),planDefaults);
 for(const value of [null,[],{capital:NaN},{capital:Infinity},{capital:'600'},{risk_pct:0},{risk_pct:6},{max_notional:601},{fee_pct:-1},{slippage_pct:Infinity},{min_rr:.5},{unknown:1},{constructor:1},{toString:1}])assert.throws(()=>validatePlan(value));
 for(const value of [NaN,Infinity,-1]){const f=fixture();f.chart.atr=value;assert.equal(paperPlan(f).data,null);}
 const f=fixture();f.settings.capital=NaN;assert.equal(paperPlan(f).status,'settings_error');assert.equal(paperPlan(f).data,null);
});
