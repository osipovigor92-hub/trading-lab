
function bView(r, s, now) {
  const age=now-r.time, ca=now-r.chart?.end;
  const valid=s.phase==='running' && now-s.updated>=-3 && now-s.updated<=8 &&
    Number.isFinite(age) && age>=-1 && age<=3 && Number.isFinite(ca) && ca>=0 && ca<=120;
  if(!valid) return ['neutral','НЕТ СВЕЖИХ ДАННЫХ',0];
  if(!r.ready) return ['neutral',r.warmup_remaining>0 ? 'ПРОГРЕВ' : 'НЕТ СВЕЖИХ СДЕЛОК',1];
  if(r.signal==='LONG') return ['long','LONG · условия выполнены',5];
  if(r.signal==='SHORT') return ['short','SHORT · условия выполнены',5];
  const reasons=r.reasons||[], side=r.chart?.side;
  const allowed=['Откат к EMA20 ещё не подтверждён','Нет возобновления движения после отката',
    'Нет пробоя локального экстремума последних секунд'];
  if(side && reasons.length && reasons.every(x=>allowed.includes(x)))
    return ['watch','НАБЛЮДЕНИЕ · '+(side===1?'LONG':'SHORT'),4];
  return ['neutral','ОЖИДАНИЕ · '+reasons.length+' причин',2];
}
document.addEventListener('DOMContentLoaded', () => {
  const page=document.getElementById('page-tests');
  if (!page) return;
  const box=document.createElement('section'); box.className='box b-monitor'; box.id='model-b-monitor';
  const title=document.createElement('h2'); title.textContent='Модель B · откат и возобновление';
  const status=document.createElement('p');
  const body=document.createElement('div');
  box.append(title,status,body); page.prepend(box);
  const fmt=(x,n=2)=>x==null?'—':Number(x).toLocaleString('ru-RU',{maximumFractionDigits:n});
  const line=(parent,text)=>{const p=document.createElement('p');p.textContent=text;parent.append(p);};

  const samples=new Map(), since=Date.now();
  function countSample(r,s,now){
    if(s.phase!=='running'||now-s.updated<0||now-s.updated>8||!Number.isFinite(r.time)||now-r.time<0||now-r.time>3)return;
    let v=samples.get(r.symbol);
    if(!v){v={last:0,n:0,reasons:new Map()};samples.set(r.symbol,v);}
    if(s.updated<=v.last)return;
    v.last=s.updated;v.n++;
    const reasons=[...new Set(r.reasons||[])];
    if(!r.ready){
      const old=reasons.indexOf('Накопление потока или нет свежих сделок');if(old>=0)reasons.splice(old,1);
      reasons.push(r.warmup_remaining>0?'Прогрев потока':'Нет свежих сделок');
    }
    for(const text of reasons)v.reasons.set(text,(v.reasons.get(text)||0)+1);
  }
  async function refresh(){
    try{
      const res=await labFetch('/api/model-b',{cache:'no-store',signal:AbortSignal.timeout(5000)});
      if(!res.ok) throw new Error('HTTP '+res.status);
      const s=await res.json(), now=Date.now()/1000;
      const fresh=now-s.updated>=-3 && now-s.updated<=8;
      status.textContent=s.phase==='halted'?'ОСТАНОВЛЕНО · '+s.reason:
        !fresh?'ДАННЫЕ УСТАРЕЛИ':s.phase==='paused'?'Модель отключена · поток котировок сохранён':s.phase==='draining'?'Отключены новые входы · завершается позиция':s.phase==='running'?'PAPER работает':'Ожидание · '+s.reason;
      status.className=fresh&&s.phase==='running'?'positive':'negative';
      // Restore user-opened details after repaint.
      const open=new Set([...body.querySelectorAll('details[open]')].map(x=>x.dataset.key));
      body.replaceChildren();
      line(body,'Капитал '+fmt(s.equity)+' USDT · результат '+fmt(s.equity-s.config.capital,4)+
           ' USDT · комиссии '+fmt(s.fees,4)+' USDT (уже учтены).');
      const wins=s.trades.filter(x=>x.net>0).length;
      line(body,'Закрыто '+s.trades.length+' · прибыльных '+wins+' · убыточных '+s.trades.filter(x=>x.net<0).length+'.');
      line(body,'Отдельный эксперимент B1. Новые входы пропускаются перед funding. '+
        'Исполнение: видимые уровни стакана плюс 0,05% остаточного проскальзывания на сторону; комиссия 0,055%. '+
        'Количество теоретическое, биржевой шаг не моделируется. Реальных ордеров нет.');
      if(!fresh||s.phase==='halted') line(body,'Показана последняя оценка. При обрыве открытая позиция не закрывается фиктивно.');
      if(s.position){const p=s.position;
        line(body,'Позиция '+p.symbol+' '+(p.side===1?'LONG':'SHORT')+' · вход '+fmt(p.entry,8)+
          ' · возраст '+fmt(now-p.opened,0)+' сек.');
        line(body,'Лучший / худший наблюдённый net: '+fmt(p.mfe_net,4)+' / '+fmt(p.mae_net,4)+' USDT.');
      }

      const legend=line(body,'Зелёный LONG / красный SHORT — условия модели выполнены; жёлтый — наблюдение, ещё не вход. Серый — ожидание или нет готовности.');
      line(body,'Выполненные условия не гарантируют открытие: учитываются текущая позиция и пауза между сделками.');
      const sorted=[...(s.observations||[])].sort((a,b)=>bView(b,s,now)[2]-bView(a,s,now)[2] || a.symbol.localeCompare(b.symbol));
      for(const r of sorted){
        countSample(r,s,now);

        const d=document.createElement('details'); d.dataset.key=r.symbol; d.open=open.has(r.symbol);
        const h=document.createElement('summary');

        const [tone,label]=bView(r,s,now);d.className='b-card b-'+tone;
        h.textContent=r.symbol+' · '+label;d.append(h);
        const reasons=(r.reasons||[]).filter(x=>x!=='Накопление потока или нет свежих сделок');
        if(!r.ready) reasons.unshift(r.warmup_remaining>0?'Прогрев: осталось '+fmt(r.warmup_remaining,0)+' сек.':
          'Нет свежих сделок: последняя '+(r.trade_age==null?'ещё не получена':fmt(r.trade_age,1)+' сек. назад'));
        const quick=document.createElement('div');quick.className='b-quick';
        quick.textContent='Спред '+fmt(r.spread,4)+'% · ATR '+fmt(r.chart?.atr_pct,3)+'% · расходы '+fmt(r.roundtrip_pct,3)+'%';
        d.append(quick);

        line(d,reasons.join('; ')||'Условия выполнены. Это условие эксперимента, не оценка вероятности прибыли.');

        if(r.warmup_remaining!=null)line(d,'Прогрев: '+fmt(r.warmup_remaining,0)+' сек. осталось · возраст последней сделки '+fmt(r.trade_age,1)+' сек.');
        if(r.bands){
          line(d,'Спред '+fmt(r.spread,4)+'% · модель расходов полного оборота '+fmt(r.roundtrip_pct,4)+'%.');
          for(const [key,v] of Object.entries(r.bands)) line(d,
            'Зона ±'+fmt(Number(key)*100,2)+'%: bid '+fmt(v.bid,0)+' / ask '+fmt(v.ask,0)+
            ' USDT · дисбаланс '+fmt(v.imbalance*100,1)+'%'+(v.covered?'':' · глубина неполная'));
          for(const n of [5,15,60]){const f=r['flow'+n];
            line(d,'Лента '+n+' сек.: buy '+fmt(f.buy,0)+' / sell '+fmt(f.sell,0)+' USDT · '+f.count+' сделок.');}
          line(d,'OFI 5 / 15 / 60 сек.: '+fmt(r.ofi5,3)+' / '+fmt(r.ofi15,3)+' / '+fmt(r.ofi60,3)+
            ' в единицах монеты. OFI — изменение лучших котировок, не объём исполненных сделок.');
          if(r.chart&&r.chart.end) line(d,'VWAP 60 мин '+fmt(r.chart.vwap60,8)+' · ATR(14) '+fmt(r.chart.atr_pct,3)+
            '% · относительный оборот 5 мин '+fmt(r.chart.rvol5)+'×.');
          if(r.chart_error) line(d,'Обновление свечей: '+r.chart_error);
        }

        const v=samples.get(r.symbol);
        if(v){line(d,'Причины отказа: '+v.n+' наблюдений с открытия страницы. Одно наблюдение может иметь несколько причин.');
          for(const [reason,n] of [...v.reasons].sort((a,b)=>b[1]-a[1]).slice(0,6))line(d,fmt(100*n/v.n,1)+'% · '+reason+' ('+n+'/'+v.n+')');}
        body.append(d);
      }
      const summary=document.createElement('details');summary.dataset.key='diagnostics';summary.open=open.has('diagnostics');
      const sh=document.createElement('summary');sh.textContent='Статистика наблюдений · '+fmt((Date.now()-since)/60000,1)+' мин.';summary.append(sh);
      line(summary,'Выборка примерно раз в 3 секунды, только свежие состояния. Не полная история и не доля прибыльных сделок. При перезагрузке страницы начинается заново.');
      body.append(summary);
      for(const t of s.trades.slice(-10).reverse()){
        const d=document.createElement('details');d.dataset.key=String(t.opened);d.open=open.has(d.dataset.key);
        d.className='b-card '+(t.net>0?'b-long':t.net<0?'b-short':'b-neutral');
        const h=document.createElement('summary');h.textContent=t.symbol+' '+(t.side===1?'LONG':'SHORT')+
          ' · '+fmt(t.net,4)+' USDT · '+t.reason;d.append(h);
        line(d,'Вход '+fmt(t.entry,8)+' / выход '+fmt(t.exit,8)+' · '+fmt(t.closed-t.opened,1)+' сек.');
        line(d,'Gross '+fmt(t.gross,4)+' · комиссии '+fmt(t.entry_fee+t.exit_fee,4)+
          ' · лучший/худший наблюдённый net '+fmt(t.mfe_net,4)+' / '+fmt(t.mae_net,4)+' USDT.');
        body.append(d);
      }
    }catch(e){status.textContent='Модель B недоступна: '+e.message;status.className='negative';body.replaceChildren();}
    finally{setTimeout(refresh,3000);}
  }
  refresh();
});
