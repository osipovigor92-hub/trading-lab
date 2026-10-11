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
    const values={};
    readout.append(sourceLabel,timeLabel);
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
    let volume=null, densityLine=null, indicatorLines=[], disposed=false, confirmed=false, fingerprint='';
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
      const b=byTime.get(time)||bars.at(-1);
      sourceLabel.textContent=(initial.exchange ? initial.exchange.toUpperCase()+' · ' : '')+initial.symbol+' · '+(LABELS[initial.interval]||initial.interval)+(confirmed?'':' · не подтверждено');
      host.dataset.chartConfirmed=String(confirmed);
      host.classList.toggle('is-unconfirmed',!confirmed);
      timeLabel.textContent=b?utc(b.time):'—';
      if (b) host.dataset.chartSelectedTime=String(b.time); else delete host.dataset.chartSelectedTime;
      for (const [key,label] of [['open','O'],['high','H'],['low','L'],['close','C'],['volume','V']]) {
        values[key].textContent=label+' '+(b?number(b[key]):'—');
        if (b) host.dataset['chartSelected'+key[0].toUpperCase()+key.slice(1)]=String(b[key]);
        else delete host.dataset['chartSelected'+key[0].toUpperCase()+key.slice(1)];
      }
      readout.title=[sourceLabel.textContent,timeLabel.textContent,...Object.values(values).map(n=>n.textContent)].join(' · ');
      readout.setAttribute('aria-label',readout.title);
    }
    function updateVolumeHeight() {
      if (volume && plot.clientHeight > 0) chart.panes()[1]?.setHeight(Math.max(42,Math.round(plot.clientHeight*.22)));
    }
    function resize() {
      if (disposed) return;
      const width=plot.clientWidth,height=plot.clientHeight;
      if (width>0 && height>0) chart.resize(width,height);
      updateVolumeHeight(); publishViewport();
    }
    function reset() {
      if (disposed || !bars.length) return;
      candles.priceScale().applyOptions({autoScale:true});
      chart.timeScale().setVisibleLogicalRange({from:Math.max(-.5,bars.length-90-.5),to:bars.length-1+3});
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
        bars=[]; byTime.clear(); selectedTime=null; fingerprint=''; candles.setData([]);
        if (volume) volume.setData([]);
        for (const s of indicatorLines) s.setData([]);
      }
      host.dataset.chartSource=source;
      host.setAttribute('aria-label','График свечей · '+identity.exchange.toUpperCase()+' · '+identity.symbol+' · '+(LABELS[identity.interval]||identity.interval)+' · плюс и минус: масштаб, стрелки: сдвиг, Home: последние свечи');
      watermark.textContent=identity.symbol.replace(/USDT$/,'')+' / USDT';
      const parsed=Object.hasOwn(PERIODS,identity.interval)?barsFrom(packet,period):null;
      confirmed=!!parsed && settings.confirmed===true && packet.status==='ok' && !packet.stale && !packet.refresh_error;
      const wantedVolume=settings.volume??options.volume??true;
      if (wantedVolume && !volume) {
        volume=chart.addSeries(L.HistogramSeries,{priceFormat:{type:'volume'},priceLineVisible:false,lastValueVisible:false},1);
        volume.priceScale().applyOptions({borderVisible:false,scaleMargins:{top:.1,bottom:0}});
      } else if (!wantedVolume && volume) {chart.removeSeries(volume); volume=null;}
      const wantIndicators=settings.indicators??options.indicators??false;
      if (wantIndicators && !indicatorLines.length) {
        indicatorLines=['#4bd0f5','#a78bcc','#e9bc68'].map(color=>chart.addSeries(L.LineSeries,{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}));
      } else if (!wantIndicators && indicatorLines.length) {for (const s of indicatorLines) chart.removeSeries(s); indicatorLines=[];}
      if (parsed) {
        const nextFingerprint=JSON.stringify(parsed);
        if (fingerprint!==nextFingerprint) {
          const range=chart.timeScale().getVisibleLogicalRange(),first=bars[0]?.time,last=bars.length-1;
          const atLatest=range && range.to>=last-1.5;
          const anchor=range && first!==undefined ? {from:first+range.from*period,to:first+range.to*period} : null;
          bars=parsed; byTime=new Map(bars.map(b=>[b.time,b])); fingerprint=nextFingerprint;
          candles.setData(bars.map(({time,open,high,low,close})=>({time,open,high,low,close})));
          const magnitude=bars.at(-1).close;
          // Display precision only; this does not claim to be an exchange order tick size.
          candles.applyOptions({priceFormat:{type:'custom',formatter:number,minMove:Math.pow(10,Math.floor(Math.log10(magnitude))-7)}});
          if (changed || !range) reset();
          else if (atLatest) chart.timeScale().setVisibleLogicalRange({from:bars.length-1+(range.from-last),to:bars.length-1+(range.to-last)});
          else if (anchor) chart.timeScale().setVisibleLogicalRange({from:(anchor.from-bars[0].time)/period,to:(anchor.to-bars[0].time)/period});
        }
      }
      if (volume) volume.setData(bars.map(b=>({time:b.time,value:b.volume,color:b.close>=b.open?'#26a69a80':'#ef535080'})));
      if (indicatorLines.length) {
        const all=indicatorData(bars); ['ema20','ema50','vwap60'].forEach((key,i)=>indicatorLines[i].setData(all[key]));
      }
      if (densityLine) {candles.removePriceLine(densityLine); densityLine=null;}
      const level=Number(settings.density?.price);
      if (settings.density && finite(level) && level>0) densityLine=candles.createPriceLine({price:level,color:settings.density.side==='bid'?'#59d5a1':'#f1848b',lineWidth:1,lineStyle:L.LineStyle.Dotted,axisLabelVisible:true,title:'Уровень '+(settings.density.side||'')+' · проверьте'});
      empty.hidden=bars.length>0;
      empty.textContent=packet?.error?'Свечи недоступны · повторяем запрос':'Ожидаем свечи…';
      showReadout(); updateVolumeHeight(); publishViewport();
    }
    const crosshair=event=>{if(disposed)return;selectedTime=typeof event.time==='number'&&byTime.has(event.time)?event.time:null;showReadout();};
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
    chart.timeScale().subscribeVisibleLogicalRangeChange(publishViewport);
    host.addEventListener('keydown',keydown); plot.addEventListener('pointerdown',focus);
    const observer=new ResizeObserver(resize); observer.observe(plot);
    function dispose() {
      if (disposed) return;
      observer.disconnect();
      chart.unsubscribeCrosshairMove(crosshair); chart.timeScale().unsubscribeVisibleLogicalRangeChange(publishViewport);
      host.removeEventListener('keydown',keydown); plot.removeEventListener('pointerdown',focus);
      chart.remove(); disposed=true; host.replaceChildren(); delete host.labExchangeChart;
    }
    const api={setPacket,reset,dispose,resize,zoom,pan,getViewport};
    host.labExchangeChart=api;
    host.dataset.chartEngine='lightweight-charts-'+L.version();
    setPacket(null,{confirmed:false,volume:options.volume,indicators:options.indicators});
    return api;
  }
  scope.LabExchangeChart={create};
})(typeof window==='undefined'?globalThis:window);
