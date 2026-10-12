const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');

// Count calls at the native chart boundary, rather than timing this machine.
// Repeated snapshots must not resubmit all five visible series or resize them.
function renderer() {
 const calls={resize:0,paneHeight:0,setData:0,update:0,range:0},series=[];
 class Element {
  constructor(){this.dataset={};this.children=[];this.clientWidth=600;this.clientHeight=300;this.className='';this.classList={add(){},toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(name,value){this[name]=value;}
  addEventListener(){} removeEventListener(){} focus(){}
 }
 let range=null,crosshair;
 const scale={getVisibleLogicalRange:()=>range,setVisibleLogicalRange:r=>{range=r;calls.range++;},subscribeVisibleLogicalRangeChange(){},unsubscribeVisibleLogicalRangeChange(){}};
 const pane={setHeight(){calls.paneHeight++;}};
 const chart={
  resize(){calls.resize++;},panes:()=>[pane,pane],timeScale:()=>scale,
  addSeries(kind){
   const item={kind,data:[],setData(data){calls.setData++;this.data=data.slice();},
    update(bar){calls.update++;const last=this.data.at(-1);assert.ok(!last||bar.time>=last.time);if(last?.time===bar.time)this.data[this.data.length-1]=bar;else this.data.push(bar);},
    applyOptions(){},priceScale:()=>({applyOptions(){},setVisibleRange(){}}),
    createPriceLine(options){let current=options;return{options:()=>current,applyOptions(next){current=next;}};},removePriceLine(){},priceToCoordinate:v=>v,coordinateToPrice:v=>v};
   series.push(item);return item;
  },removeSeries(item){series.splice(series.indexOf(item),1);},subscribeCrosshairMove(fn){crosshair=fn;},unsubscribeCrosshairMove(){},subscribeClick(){},unsubscribeClick(){},remove(){}
 };
 let now=1800000000;
 const context={Date:class extends Date{static now(){return now*1000;}},document:{createElement:()=>new Element()},ResizeObserver:class{observe(){}disconnect(){}},
  LightweightCharts:{createChart:()=>chart,ColorType:{Solid:0},LineStyle:{Dotted:1,Dashed:2,Solid:3},CrosshairMode:{Normal:0},CandlestickSeries:'candle',HistogramSeries:'volume',LineSeries:'line',version:()=> 'test'}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/trading-panel/exchange-chart.js'),'utf8'),context);
 const host=new Element(),api=context.LabExchangeChart.create(host,{exchange:'bybit',symbol:'BTCUSDT',interval:'1',indicators:true});
 const clear=()=>{for(const key of Object.keys(calls))calls[key]=0;};
 return{api,host,calls,series,clear,crosshair:time=>crosshair({time}),scale,setNow:value=>{now=value;}};
}
function packet(count=80) {
 return {exchange:'bybit',symbol:'BTCUSDT',interval:'1',status:'ok',updated:1800000000,
  candles:Array.from({length:count},(_,i)=>({t:1799995200+i*60,open:100+i,high:103+i,low:98+i,close:101+i,volume:10+i,turnover:(10+i)*(101+i)}))};
}
const settings={confirmed:true,volume:true,indicators:true};
const clone=value=>JSON.parse(JSON.stringify(value));
const readoutSpan=(r,className)=>r.host.children[1].children.find(n=>n.className===className);
test('unchanged snapshots skip native data and size work, while freshness and levels still change',()=>{
 const r=renderer(),p=packet();r.api.setPacket(p,settings);r.clear();
 for(let i=0;i<100;i++)r.api.setPacket({...clone(p),updated:p.updated+i},settings);
 assert.equal(r.calls.setData,0,'identical polls resubmit zero series');assert.equal(r.calls.update,0);assert.equal(r.calls.resize,0);assert.equal(r.calls.paneHeight,0);
 r.api.setPacket({...clone(p),stale:true},{...settings,confirmed:false,levels:[{id:'support',type:'support',price:100}]});
 assert.equal(r.host.dataset.chartConfirmed,'false');assert.equal(r.host.dataset.chartManualLevels,'1');assert.equal(r.calls.setData,0);
 r.api.dispose();
});
test('last candle revision and simple append use native updates for candles, volume and indicators',()=>{
 const r=renderer(),p=packet();r.api.setPacket(p,settings);r.clear();
 const next=clone(p);next.candles.at(-1).close+=1;next.candles.at(-1).turnover+=20;r.api.setPacket(next,settings);
 assert.equal(r.calls.setData,0);assert.equal(r.calls.update,4,'unchanged volume is not resubmitted');assert.equal(r.series[0].data.at(-1).close,next.candles.at(-1).close);
 r.clear();const last=next.candles.at(-1);next.candles.push({...last,t:last.t+60,open:last.close,high:last.high+1,close:last.close+1,volume:100,turnover:18000});r.api.setPacket(next,settings);
 assert.equal(r.calls.setData,0);assert.equal(r.calls.update,5);assert.equal(r.series[0].data.length,81);assert.equal(r.series[1].data.at(-1).value,100);
 r.api.dispose();
});
test('window rolls and historical corrections replace data while preserving UTC anchors and crosshair',()=>{
 const r=renderer(),p=packet();r.api.setPacket(p,settings);r.scale.setVisibleLogicalRange({from:10,to:30});r.crosshair(p.candles[20].t);const old=r.api.getViewport();r.clear();
 const next=clone(p);next.candles.shift();const last=next.candles.at(-1);next.candles.push({...last,t:last.t+60});r.api.setPacket(next,settings);
 assert.equal(r.calls.setData,5);assert.equal(r.calls.update,0);assert.equal(r.api.getViewport().timeFrom,old.timeFrom);assert.equal(r.api.getViewport().timeTo,old.timeTo);assert.equal(Number(r.host.dataset.chartSelectedTime),p.candles[20].t);
 r.clear();next.candles[10].close+=.5;r.api.setPacket(next,settings);assert.equal(r.calls.setData,3,'only candle and EMA histories changed');assert.equal(r.calls.update,0);
 r.api.dispose();
});
test('toggles populate new auxiliary series and source switches clear old values',()=>{
 const r=renderer(),p=packet();r.api.setPacket(p,{...settings,volume:false,indicators:false});r.clear();r.api.setPacket(p,settings);
 assert.equal(r.calls.setData,4);assert.equal(r.series.length,5);assert.equal(r.series[1].data.length,80);assert.equal(r.series[4].data.length,21);
 r.api.setPacket({...p,exchange:'okx',candles:[]},{...settings,confirmed:false});assert.ok(r.series.every(s=>s.data.length===0));assert.equal(r.host.dataset.chartSource,'okx:BTCUSDT:1');
 r.api.dispose();
});
function live(p,now=1800000000) {
 const last=p.candles.at(-1);
 return {exchange:p.exchange,symbol:p.symbol,interval:p.interval,status:'connected',
  candle:{t:last.t+60,open:last.close,high:last.high+2,low:last.low,close:last.close+1,volume:null,turnover:null,source_ts:now,received_at:now,closed:false},
  quote:{price:last.close+1,source_ts:now,received_at:now}};
}
test('forming ticks update only their own candle, keep closed indicators and historical crosshair',()=>{
 const r=renderer(),p=packet(),view=live(p);r.api.setPacket(p,settings);r.scale.setVisibleLogicalRange({from:10,to:30});r.crosshair(p.candles[20].t);const old=r.api.getViewport();r.clear();
 r.api.setLive(view);assert.equal(r.calls.setData,0);assert.equal(r.calls.update,1);assert.equal(r.series[0].data.length,81);assert.equal(r.series[1].data.length,80);assert.equal(r.series[4].data.length,21);
 assert.equal(r.host.dataset.chartLive,'true');assert.equal(r.host.dataset.chartLivePrice,String(view.quote.price));assert.equal(r.host.dataset.chartConfirmed,'true');assert.equal(Number(r.host.dataset.chartSelectedTime),p.candles[20].t);assert.equal(r.api.getViewport().timeFrom,old.timeFrom);
 assert.equal(readoutSpan(r,'exchange-chart-live-state').hidden,true,'historical crosshair has no forming label');
 const quoteSpan=readoutSpan(r,'exchange-chart-live-quote');assert.match(quoteSpan.textContent,/ UTC/);assert.doesNotMatch(quoteSpan.textContent,/Цена сейчас/);assert.equal(quoteSpan.hidden,false);assert.equal(Number(r.host.dataset.chartSelectedClose),p.candles[20].close,'latest quote leaves selected historical OHLC intact');
 r.crosshair(view.candle.t);assert.equal(r.host.dataset.chartSelectedVolume,undefined,'unknown base volume is not fabricated');assert.match(readoutSpan(r,'exchange-chart-source').textContent,/формируется/);
 assert.equal(readoutSpan(r,'exchange-chart-live-state').hidden,false);assert.equal(readoutSpan(r,'exchange-chart-live-state').textContent,'формируется');
 r.clear();for(let i=0;i<100;i++)r.api.setLive(clone(view));assert.equal(r.calls.setData,0);assert.equal(r.calls.update,0);assert.equal(r.calls.resize,0);
 view.candle.close+=.25;r.api.setLive(view);assert.equal(r.calls.update,1);assert.equal(r.calls.setData,0);assert.equal(r.series[2].data.at(-1).time,p.candles.at(-1).t,'EMA proof excludes the forming candle');
 r.api.dispose();
});
test('live quote and candle expiry remain independent, source switches and gaps reject live bars',()=>{
 const r=renderer(),p=packet(),view=live(p);r.api.setPacket(p,settings);r.api.setLive(view);r.setNow(1800000011);r.api.setLive(view);
 assert.equal(r.host.dataset.chartLive,'true');assert.equal(r.host.dataset.chartLivePrice,undefined,'quote expires after ten seconds');
 assert.equal(readoutSpan(r,'exchange-chart-live-quote').hidden,true);assert.equal(readoutSpan(r,'exchange-chart-live-quote').textContent,'');
 const freshQuote={...view,quote:{...view.quote,received_at:1800000076,source_ts:1800000076}};r.setNow(1800000076);r.api.setLive(freshQuote);
 assert.equal(r.host.dataset.chartLive,'false');assert.equal(r.host.dataset.chartLivePrice,String(view.quote.price));assert.equal(r.series[0].data.length,80,'expired candle is removed despite fresh ticker');
 r.setNow(1800000000);for(const bad of [{...view,exchange:'binance'},{...view,interval:'5'},{...view,candle:{...view.candle,t:view.candle.t+60}},{...view,candle:{...view.candle,received_at:1800000003}},{...view,candle:{...view.candle,source_ts:NaN}},{...view,candle:{...view.candle,source_ts:null}}]){r.api.setLive(bad);assert.equal(r.host.dataset.chartLive,'false');}
 r.api.setLive({...view,candle:{...view.candle,source_ts:null,timestamp_origin:'receipt'}});assert.equal(r.host.dataset.chartLive,'true','providers without a publish timestamp use their original receipt explicitly');
 r.api.setPacket({...p,exchange:'okx'},settings);assert.equal(r.host.dataset.chartLive,'false');assert.equal(r.host.dataset.chartLivePrice,undefined);
 r.api.dispose();
});
test('explicit close waits briefly for REST and merges without moving UTC viewport anchors',()=>{
 const r=renderer(),p=packet(),view=live(p);r.api.setPacket(p,settings);r.api.setLive(view);const before=r.api.getViewport();r.clear();
 const end=view.candle.t+60;r.setNow(end+3);r.api.setLive({...view,candle:{...view.candle,closed:true,source_ts:end+3,received_at:end+3},quote:null});assert.match(readoutSpan(r,'exchange-chart-source').textContent,/закрылась · проверяем/);
 assert.equal(readoutSpan(r,'exchange-chart-live-state').hidden,false);assert.equal(readoutSpan(r,'exchange-chart-live-state').textContent,'закрылась · проверяем');
 const next=clone(p);next.candles.shift();next.candles.push({t:view.candle.t,open:view.candle.open,high:view.candle.high,low:view.candle.low,close:view.candle.close,volume:20,turnover:3600});r.api.setPacket(next,settings);
 assert.equal(r.host.dataset.chartLive,'false');assert.equal(r.series[0].data.length,80);assert.equal(r.api.getViewport().timeFrom,before.timeFrom);assert.equal(r.api.getViewport().timeTo,before.timeTo);assert.equal(r.series[1].data.at(-1).value,20);
 assert.equal(readoutSpan(r,'exchange-chart-live-state').hidden,true,'REST closed candle has no forming label');
 r.api.setLive({...view,candle:{...view.candle,closed:true,source_ts:end+11,received_at:end+11},quote:null});assert.equal(r.host.dataset.chartLive,'false');
 r.api.dispose();
});
test('a fresh quote is readable before history loads and disconnect hides it',()=>{
 const r=renderer(),view=live(packet());r.api.setLive(view);const span=readoutSpan(r,'exchange-chart-live-quote');
 assert.equal(span.hidden,false);assert.doesNotMatch(span.textContent,/Цена сейчас/);assert.equal(r.host.dataset.chartConfirmed,'false');assert.equal(r.host.dataset.chartSelectedClose,undefined);assert.equal(r.host.dataset.chartLive,'false','a quote cannot synthesize candle history');
 r.api.setLive({...view,status:'unavailable'});assert.equal(span.hidden,true);assert.equal(span.textContent,'');assert.equal(r.host.dataset.chartLivePrice,undefined);
 r.api.dispose();
});
