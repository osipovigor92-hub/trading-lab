'use strict';
(function (scope) {
  const PERIODS = {1:60, 5:300, 15:900, 60:3600, 240:14400, 1440:86400};
  const LABELS = {1:'1м',5:'5м',15:'15м',60:'1ч',240:'4ч',1440:'1д'};
  const finite = n => typeof n === 'number' && Number.isFinite(n);
  const number = n => finite(n) ? (Math.abs(n) > 0 && Math.abs(n) < .00001
    ? n.toLocaleString('ru-RU', {notation:'scientific', maximumSignificantDigits:6})
    : n.toLocaleString('ru-RU', {maximumSignificantDigits:8})) : '—';
  const utc = t => new Date(t * 1000).toLocaleString('ru-RU', {
    timeZone:'UTC', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'
  }) + ' UTC';
  function barsFrom(packet, period) {
    if (!Array.isArray(packet?.candles) || !packet.candles.length || packet.candles.length > 180) return null;
    const result = [];
    for (const b of packet.candles) {
      if (!b || !Number.isInteger(b.t) || b.t <= 0 || b.t % period !== 0 ||
          !['open','high','low','close'].every(k => finite(b[k]) && b[k] > 0) ||
          !finite(b.volume) || b.volume < 0 || b.high < Math.max(b.open,b.close,b.low) ||
          b.low > Math.min(b.open,b.close,b.high) || (result.length && b.t - result.at(-1).time !== period)) return null;
      result.push({time:b.t, open:b.open, high:b.high, low:b.low, close:b.close, volume:b.volume, turnover:b.turnover});
    }
    return result;
  }
  const samePoint=(a,b)=>!!a && !!b && Object.keys(a).length===Object.keys(b).length && Object.keys(a).every(key=>a[key]===b[key]);
  const sameBars=(raw,bars)=>Array.isArray(raw) && raw.length>0 && raw.length===bars.length && raw.every((b,i)=>b &&
    b.t===bars[i].time && ['open','high','low','close','volume','turnover'].every(key=>b[key]===bars[i][key]));
  // update() touches the last point only. A rolling window or historical revision
  // needs setData(), while an unchanged snapshot needs no native data call.
  function syncSeries(series, next, previous) {
    if (next.length===previous.length && next.every((b,i)=>samePoint(b,previous[i]))) return false;
    if (previous.length && next.length>=previous.length && next[previous.length-1]?.time===previous.at(-1).time &&
        previous.slice(0,-1).every((b,i)=>samePoint(b,next[i]))) {
      if (!samePoint(previous.at(-1),next[previous.length-1])) series.update(next[previous.length-1]);
      for (let i=previous.length;i<next.length;i++) series.update(next[i]);
    } else series.setData(next);
    return true;
  }
  function indicatorData(bars) {
    const output = {ema20:[], ema50:[], vwap60:[]};
    for (const period of [20,50]) {
      let sum=0, value=null;
      bars.forEach((b,i) => {
        if (i < period) sum += b.close;
        if (i === period-1) value = sum/period;
        else if (i >= period) value += (b.close-value)*2/(period+1);
        if (value !== null) output['ema'+period].push({time:b.time,value});
      });
    }
    for (let i=59; i<bars.length; i++) {
      const window=bars.slice(i-59,i+1);
      if (!window.every(b => finite(b.turnover) && b.turnover >= 0)) continue;
      const volume=window.reduce((s,b)=>s+b.volume,0);
      if (volume > 0) output.vwap60.push({time:bars[i].time,value:window.reduce((s,b)=>s+b.turnover,0)/volume});
    }
    return output;
  }
  function create(host, options={}) {
    if (!host || !scope.LightweightCharts) throw new Error('Локальная библиотека графиков недоступна');
    const L=scope.LightweightCharts, element=(tag,cls,text='')=>{
      const n=document.createElement(tag); n.className=cls; n.textContent=text; return n;
    };
    host.classList.add('lab-exchange-chart');
    host.tabIndex=0;
    host.setAttribute('role','group');
    host.setAttribute('aria-label','График свечей · плюс и минус: масштаб, стрелки: сдвиг, Home: последние свечи');
    const plot=element('div','exchange-chart-plot'), watermark=element('div','exchange-chart-watermark');
    watermark.setAttribute('aria-hidden','true');
    const empty=element('div','exchange-chart-empty','Ожидаем свечи…');
    empty.setAttribute('role','status');
    const readout=element('div','exchange-chart-readout');
    readout.setAttribute('aria-live','off');
    const sourceLabel=element('span','exchange-chart-source'), timeLabel=element('span','exchange-chart-time');
    const quoteLabel=element('span','exchange-chart-live-quote');quoteLabel.hidden=true;
    const liveState=element('span','exchange-chart-live-state');liveState.hidden=true;
    const values={};
    readout.append(liveState,quoteLabel,sourceLabel,timeLabel);
    for (const [key,label] of [['open','O'],['high','H'],['low','L'],['close','C'],['volume','V']]) {
      values[key]=element('span','exchange-chart-'+key,label+' —'); readout.append(values[key]);
    }
    const credit=element('a','exchange-chart-attribution','TradingView Lightweight Charts™ · Copyright (с) 2025 TradingView, Inc.');
    credit.href='https://www.tradingview.com/'; credit.target='_blank'; credit.rel='noopener noreferrer';
    host.replaceChildren(plot,readout,credit);
    const chart=L.createChart(plot, {
      autoSize:false,
      layout:{background:{type:L.ColorType.Solid,color:'#101214'},textColor:'#a7b3be',fontFamily:'Inter, Segoe UI, sans-serif',fontSize:11,attributionLogo:true},
      grid:{vertLines:{visible:false},horzLines:{color:'#2a2d31',style:L.LineStyle.Dotted}},
      crosshair:{mode:L.CrosshairMode.Normal,vertLine:{color:'#69737e',style:L.LineStyle.Dashed},horzLine:{color:'#69737e',style:L.LineStyle.Dashed}},
      rightPriceScale:{borderVisible:false,scaleMargins:{top:.12,bottom:.08}},
      leftPriceScale:{visible:false},
      timeScale:{borderVisible:false,timeVisible:true,secondsVisible:false,rightOffset:3,barSpacing:5,minBarSpacing:2,shiftVisibleRangeOnNewBar:false,lockVisibleTimeRangeOnResize:true},
      localization:{locale:'ru-RU',timeFormatter:t=>utc(Number(t)),priceFormatter:number},
      handleScroll:{mouseWheel:false,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},
      handleScale:{mouseWheel:true,pinch:true,axisPressedMouseMove:{time:true,price:true},axisDoubleClickReset:{time:true,price:true}},
      kineticScroll:{mouse:false,touch:true}
    });
    const candles=chart.addSeries(L.CandlestickSeries, {
      upColor:'#26a69a',downColor:'#ef5350',wickUpColor:'#26a69a',wickDownColor:'#ef5350',borderVisible:false,
      priceLineVisible:true,lastValueVisible:true,priceLineStyle:L.LineStyle.Dashed,
      priceFormat:{type:'custom',formatter:number,minMove:.00000001}
    });
    plot.append(watermark,empty);
    let source='', period=PERIODS[String(options.interval)]||300, bars=[], byTime=new Map(), selectedTime=null;
    let volume=null, indicatorLines=[], disposed=false, confirmed=false, updating=false;
    let candleData=[],volumeData=[],indicatorValues={ema20:[],ema50:[],vwap60:[]},size={width:0,height:0},volumeHeight=0,precision=null;
    let liveView=null,liveCandle=null,quoteLine=null;
    const priceLines=new Map();
    let initial={exchange:options.exchange||'',symbol:options.symbol||'',interval:String(options.interval||'5')};
    function getViewport() {
      const range=chart.timeScale().getVisibleLogicalRange();
      return {from:range?.from??null,to:range?.to??null,timeFrom:range&&bars.length?bars[0].time+range.from*period:null,
        timeTo:range&&bars.length?bars[0].time+range.to*period:null,bars:bars.length,panes:chart.panes().length,source,confirmed};
    }
    function publishViewport() {
      if (disposed) return;
      const v=getViewport();
      for (const [attr,key] of [['from','from'],['to','to'],['timeFrom','timeFrom'],['timeTo','timeTo'],['bars','bars'],['panes','panes']]) {
        if (v[key] === null) delete host.dataset['chart'+attr[0].toUpperCase()+attr.slice(1)];
        else host.dataset['chart'+attr[0].toUpperCase()+attr.slice(1)]=String(v[key]);
      }
    }
    function showReadout(time=selectedTime) {
      const b=byTime.get(time)||((time===null||time===liveCandle?.time)?liveCandle:null)||bars.at(-1);
      const isLive=b===liveCandle && !!b;
      liveState.hidden=!isLive;
      liveState.textContent=isLive?(b.closed?'закрылась · проверяем':'формируется'):'';
      sourceLabel.textContent=(initial.exchange ? initial.exchange.toUpperCase()+' · ' : '')+initial.symbol+' · '+(LABELS[initial.interval]||initial.interval)+(confirmed?'':updating?' · обновляем закрытую свечу':' · не подтверждено')+(isLive?(b.closed?' · закрылась · проверяем':' · формируется'):'');
      host.dataset.chartConfirmed=String(confirmed);
      host.classList.toggle('is-unconfirmed',!confirmed);
      timeLabel.textContent=b?utc(b.time)+(isLive?' · обновление '+new Date((b.source_ts??b.received_at)*1000).toLocaleTimeString('ru-RU',{timeZone:'UTC'})+' UTC':''):'—';
      if (b) host.dataset.chartSelectedTime=String(b.time); else delete host.dataset.chartSelectedTime;
      for (const [key,label] of [['open','O'],['high','H'],['low','L'],['close','C'],['volume','V']]) {
        values[key].textContent=label+' '+(b?number(b[key]):'—');
        if (b && finite(b[key])) host.dataset['chartSelected'+key[0].toUpperCase()+key.slice(1)]=String(b[key]);
        else delete host.dataset['chartSelected'+key[0].toUpperCase()+key.slice(1)];
      }
      readout.title=[...(!quoteLabel.hidden?[quoteLabel.textContent]:[]),sourceLabel.textContent,timeLabel.textContent,...Object.values(values).map(n=>n.textContent)].join(' · ');
      readout.setAttribute('aria-label',readout.title);
    }
    function freshLive(sample,age,now) {
      if (!sample || !finite(sample.received_at) || sample.received_at<=0 || sample.received_at>now+2 || now-sample.received_at>age) return false;
      if (sample.source_ts===null) return sample.timestamp_origin==='receipt';
      return finite(sample.source_ts) && sample.source_ts>0 && sample.source_ts<=now+2 && now-sample.source_ts<=age;
    }
    function liveFrom(view,now) {
      const b=view?.candle,last=bars.at(-1),current=Math.floor(now/period)*period;
      if (!b || !last || !freshLive(b,75,now) || !Number.isInteger(b.t) || b.t%period!==0 || b.t!==last.time+period ||
          !['open','high','low','close'].every(key=>finite(b[key])&&b[key]>0) || b.high<Math.max(b.open,b.close,b.low) || b.low>Math.min(b.open,b.close,b.high) ||
          !['volume','turnover'].every(key=>b[key]===null||(finite(b[key])&&b[key]>=0)) ||
          !(b.closed===false&&b.t===current || b.closed===true&&b.t===current-period&&now-(b.t+period)<=10)) return null;
      return {time:b.t,open:b.open,high:b.high,low:b.low,close:b.close,volume:b.volume,turnover:b.turnover,closed:b.closed,source_ts:b.source_ts,received_at:b.received_at};
    }
    function liveMatches(view) {
      return view && view.exchange===initial.exchange && view.symbol===initial.symbol && String(view.interval)===initial.interval && view.status==='connected';
    }
    function updateLiveState() {
      const now=Date.now()/1000,valid=liveMatches(liveView);
      liveCandle=valid?liveFrom(liveView,now):null;
      const quote=valid&&freshLive(liveView.quote,10,now)&&finite(liveView.quote.price)&&liveView.quote.price>0?liveView.quote:null;
      if (quote) {
        const options={price:quote.price,color:'#55cee9',lineWidth:1,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true,title:''};
        if (!quoteLine) quoteLine=candles.createPriceLine(options);
        else if (quoteLine.options().price!==quote.price) quoteLine.applyOptions(options);
        host.dataset.chartLivePrice=String(quote.price);
        quoteLabel.hidden=false;
        quoteLabel.textContent=number(quote.price)+' · '+new Date((quote.source_ts??quote.received_at)*1000).toLocaleTimeString('ru-RU',{timeZone:'UTC'})+' UTC';
        quoteLabel.title=(quote.source_ts===null?'Получено: ':'Данные биржи: ')+utc(quote.source_ts??quote.received_at);
      } else {if(quoteLine)candles.removePriceLine(quoteLine);quoteLine=null;delete host.dataset.chartLivePrice;quoteLabel.hidden=true;quoteLabel.textContent='';quoteLabel.title='';}
      host.dataset.chartLive=String(!!liveCandle);
      host.dataset.chartLiveStatus=valid?'connected':liveView?.status==='connecting'?'connecting':'unavailable';
    }
    function displayCandles() {
      const data=bars.map(({time,open,high,low,close})=>({time,open,high,low,close}));
      if (liveCandle) {const {time,open,high,low,close}=liveCandle;data.push({time,open,high,low,close});}
      return data;
    }
    function setLive(view) {
      if (disposed) return;
      liveView=view;updateLiveState();
      const range=chart.timeScale().getVisibleLogicalRange(),last=candleData.length-1,next=displayCandles();
      const atLatest=range && range.to>=last-1.5;
      const changed=syncSeries(candles,next,candleData);candleData=next;
      if (changed && range && atLatest && next.length-1!==last) chart.timeScale().setVisibleLogicalRange({from:range.from+next.length-1-last,to:range.to+next.length-1-last});
      else if (changed && range) chart.timeScale().setVisibleLogicalRange(range);
      showReadout();publishViewport();
    }
    function updateVolumeHeight() {
      if (!volume || plot.clientHeight<=0) return;
      const height=Math.max(42,Math.round(plot.clientHeight*.22));
      if (height!==volumeHeight) {chart.panes()[1]?.setHeight(height);volumeHeight=height;}
    }
    function resize() {
      if (disposed) return;
      const width=plot.clientWidth,height=plot.clientHeight;
      if (width>0 && height>0 && (width!==size.width || height!==size.height)) {chart.resize(width,height);size={width,height};}
      updateVolumeHeight(); publishViewport();
    }
    function reset() {
      if (disposed || !bars.length) return;
      candles.priceScale().applyOptions({autoScale:true});
      const count=candleData.length;
      chart.timeScale().setVisibleLogicalRange({from:Math.max(-.5,count-90-.5),to:count-1+3});
      publishViewport();
    }
    function zoom(factor) {
      if (disposed || !finite(factor) || factor<=0 || !bars.length) return;
      const range=chart.timeScale().getVisibleLogicalRange(); if (!range) return;
      const width=Math.min(360,Math.max(8,(range.to-range.from)*factor)),middle=(range.from+range.to)/2;
      chart.timeScale().setVisibleLogicalRange({from:middle-width/2,to:middle+width/2}); publishViewport();
    }
    function pan(delta) {
      if (disposed || !finite(delta) || !bars.length) return;
      const range=chart.timeScale().getVisibleLogicalRange(); if (!range) return;
      chart.timeScale().setVisibleLogicalRange({from:range.from+delta,to:range.to+delta}); publishViewport();
    }
    function updateLevels(settings) {
      const wanted=new Map();
      for(const level of (settings.autoLevels||[]).slice(0,6)){
        if(!finite(level.price)||level.price<=0||!['support','resistance'].includes(level.type))continue;
        wanted.set('auto:'+level.id,{price:level.price,color:level.type==='support'?'#59d5a1':'#f1848b',lineWidth:2,lineStyle:L.LineStyle.Dashed,axisLabelVisible:true,title:'Авто '+(level.interval==='60'?'1ч':'15м')+' · '+level.touches+' кас.'});
      }
      for (const level of (settings.levels||[]).slice(0,12)) {
        if (!finite(level.price)||level.price<=0||!['support','resistance'].includes(level.type)) continue;
        wanted.set('manual:'+level.id,{price:level.price,color:level.type==='support'?'#a78bcc':'#e9bc68',lineWidth:2,lineStyle:L.LineStyle.Solid,axisLabelVisible:true,title:level.type==='support'?'Подд.':'Сопр.'});
      }
      for (const level of (settings.densities||[]).slice(0,6)) {
        if (!finite(level.price)||level.price<=0||!['bid','ask'].includes(level.side)) continue;
        const amount=finite(level.notional)?Math.round(level.notional/1000)+'к':'';
        wanted.set('density:'+level.id,{price:level.price,color:level.confirmed?(level.side==='bid'?'#59d5a1':'#f1848b'):'#a7b3be',lineWidth:1,lineStyle:L.LineStyle.Dotted,axisLabelVisible:true,title:(level.confirmed?'':'? ')+(level.side==='bid'?'Пок. ':'Прод. ')+amount});
      }
      for (const [key,line] of priceLines) if (!wanted.has(key)) {candles.removePriceLine(line);priceLines.delete(key);}
      for (const [key,options] of wanted) {
        const existing=priceLines.get(key);
        if (!existing) priceLines.set(key,candles.createPriceLine(options));
        else if (Object.entries(options).some(([key,value])=>existing.options()[key]!==value)) existing.applyOptions(options);
      }
      host.dataset.chartManualLevels=String([...wanted.keys()].filter(key=>key.startsWith('manual:')).length);
      host.dataset.chartDensityLevels=String([...wanted.keys()].filter(key=>key.startsWith('density:')).length);
    }
    function fitLevels() {
      if (disposed||!bars.length||!priceLines.size) return;
      const range=chart.timeScale().getVisibleLogicalRange();
      const visible=bars.filter((_,i)=>!range||i>=Math.floor(range.from)&&i<=Math.ceil(range.to));
      const values=[...visible.flatMap(b=>[b.low,b.high]),...priceLines.values()].map(v=>typeof v==='number'?v:v.options().price);
      const low=Math.min(...values),high=Math.max(...values),padding=Math.max(high-low,high*.001)*.1;
      candles.priceScale().setVisibleRange({from:Math.max(low*.5,low-padding),to:high+padding});
    }
    function setPacket(packet, settings={}) {
      if (disposed) return;
      // A dialog becomes measurable before the auto-size observer runs. Establish
      // its real width before setting the initial 90-bar viewport.
      resize();
      const identity={exchange:packet?.exchange??initial.exchange,symbol:packet?.symbol??initial.symbol,interval:String(packet?.interval??initial.interval)};
      const nextSource=[identity.exchange,identity.symbol,identity.interval].join(':');
      const changed=source!==nextSource;
      if (changed) {
        initial=identity; source=nextSource; period=PERIODS[identity.interval]||300;
        liveView=null;liveCandle=null;if(quoteLine)candles.removePriceLine(quoteLine);quoteLine=null;
        bars=[]; byTime.clear(); selectedTime=null; candleData=[]; precision=null; candles.setData([]);
        if (volume) volume.setData([]);volumeData=[];
        for (const s of indicatorLines) s.setData([]);indicatorValues={ema20:[],ema50:[],vwap60:[]};
      }
      host.dataset.chartSource=source;
      host.setAttribute('aria-label','График свечей · '+identity.exchange.toUpperCase()+' · '+identity.symbol+' · '+(LABELS[identity.interval]||identity.interval)+' · плюс и минус: масштаб, стрелки: сдвиг, Home: последние свечи');
      watermark.textContent=identity.symbol.replace(/USDT$/,'')+' / USDT';
      const parsed=Object.hasOwn(PERIODS,identity.interval)?(sameBars(packet?.candles,bars)?bars:barsFrom(packet,period)):null;
      confirmed=!!parsed && settings.confirmed===true && packet.status==='ok' && !packet.stale && !packet.refresh_error;
      updating=!!parsed && !confirmed && settings.updating===true && !packet.error && !packet.refresh_error;
      const wantedVolume=settings.volume??options.volume??true;
      let volumeCreated=false,indicatorsCreated=false;
      if (wantedVolume && !volume) {
        volume=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false},1);
        volume.priceScale().applyOptions({borderVisible:false,scaleMargins:{top:.1,bottom:0}});
        volumeCreated=true;volumeHeight=0;
      } else if (!wantedVolume && volume) {chart.removeSeries(volume); volume=null;volumeData=[];volumeHeight=0;}
      const wantIndicators=settings.indicators??options.indicators??false;
      if (wantIndicators && !indicatorLines.length) {
        indicatorLines=['#4bd0f5','#a78bcc','#e9bc68'].map(color=>chart.addSeries(L.LineSeries,{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}));
        indicatorsCreated=true;
      } else if (!wantIndicators && indicatorLines.length) {for (const s of indicatorLines) chart.removeSeries(s); indicatorLines=[];indicatorValues={ema20:[],ema50:[],vwap60:[]};}
      const barsChanged=!!parsed && parsed!==bars;
      if (barsChanged) {
          const range=chart.timeScale().getVisibleLogicalRange(),first=bars[0]?.time,last=candleData.length-1;
          const atLatest=range && range.to>=last-1.5;
          const anchor=range && first!==undefined ? {from:first+range.from*period,to:first+range.to*period} : null;
          bars=parsed; byTime=new Map(bars.map(b=>[b.time,b]));
          updateLiveState();
          const nextData=displayCandles();
          const nativeChanged=syncSeries(candles,nextData,candleData);candleData=nextData;
          const magnitude=bars.at(-1).close;
          // Display precision only; this does not claim to be an exchange order tick size.
          const minMove=Math.pow(10,Math.floor(Math.log10(magnitude))-7);
          if (precision!==minMove) {candles.applyOptions({priceFormat:{type:'custom',formatter:number,minMove}});precision=minMove;}
          if (changed || !range) reset();
          else if (nativeChanged && atLatest) chart.timeScale().setVisibleLogicalRange({from:nextData.length-1+(range.from-last),to:nextData.length-1+(range.to-last)});
          else if (nativeChanged && anchor) chart.timeScale().setVisibleLogicalRange({from:(anchor.from-bars[0].time)/period,to:(anchor.to-bars[0].time)/period});
      }
      if (volume && (barsChanged || volumeCreated)) {
        const next=bars.map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'#26a69a80':'#ef535080'}));syncSeries(volume,next,volumeData);volumeData=next;
      }
      if (indicatorLines.length && (barsChanged || indicatorsCreated)) {
        const all=indicatorData(bars); ['ema20','ema50','vwap60'].forEach((key,i)=>syncSeries(indicatorLines[i],all[key],indicatorValues[key]));indicatorValues=all;
      }
      updateLevels(settings);
      // The same REST candle window may be polled while a live sample expires.
      // Re-evaluate its own stamps without re-submitting closed auxiliary series.
      if (!barsChanged) setLive(liveView);
      empty.hidden=bars.length>0;
      empty.textContent=packet?.error?'Свечи недоступны · повторяем запрос':'Ожидаем свечи…';
      showReadout(); updateVolumeHeight(); publishViewport();
    }
    const crosshair=event=>{if(disposed)return;selectedTime=typeof event.time==='number'&&(byTime.has(event.time)||liveCandle?.time===event.time)?event.time:null;showReadout();};
    const click=event=>{if(disposed||!bars.length||!event.point||event.paneIndex!==0)return;const value=candles.coordinateToPrice(event.point.y);if(finite(value)&&value>0)options.onPriceClick?.(value);};
    const keydown=event=>{
      if (event.target.closest('button,a,input,select,textarea') || event.ctrlKey || event.metaKey || event.altKey) return;
      if (['+','=','Add'].includes(event.key)) zoom(.8);
      else if (['-','_','Subtract'].includes(event.key)) zoom(1.25);
      else if (event.key==='Home') reset();
      else if (event.key==='ArrowLeft') pan(-10);
      else if (event.key==='ArrowRight') pan(10);
      else return;
      event.preventDefault(); event.stopPropagation();
    };
    const focus=event=>{if(!event.target.closest('a,button'))host.focus({preventScroll:true});};
    chart.subscribeCrosshairMove(crosshair);
    chart.subscribeClick(click);
    chart.timeScale().subscribeVisibleLogicalRangeChange(publishViewport);
    host.addEventListener('keydown',keydown); plot.addEventListener('pointerdown',focus);
    const observer=new ResizeObserver(resize); observer.observe(plot);
    function dispose() {
      if (disposed) return;
      observer.disconnect();
      chart.unsubscribeCrosshairMove(crosshair); chart.unsubscribeClick(click); chart.timeScale().unsubscribeVisibleLogicalRangeChange(publishViewport);
      host.removeEventListener('keydown',keydown); plot.removeEventListener('pointerdown',focus);
      chart.remove(); disposed=true; host.replaceChildren(); delete host.labExchangeChart;
    }
    const api={setPacket,setLive,reset,dispose,resize,zoom,pan,getViewport,fitLevels,getLevels:()=>[...priceLines].map(([id,line])=>({id,...line.options()})),priceToCoordinate:value=>candles.priceToCoordinate(value)};
    host.labExchangeChart=api;
    host.dataset.chartEngine='lightweight-charts-'+L.version();
    setPacket(null,{confirmed:false,volume:options.volume,indicators:options.indicators});
    return api;
  }
  scope.LabExchangeChart={create};
})(typeof window==='undefined'?globalThis:window);

