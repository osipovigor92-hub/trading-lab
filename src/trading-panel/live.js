(() => {
  const box = document.createElement('section');
  box.className = 'box';
  document.getElementById('scanner').before(box);
  const title = document.createElement('h2');
  title.textContent = 'LIVE · стакан и исполненные сделки';
  const status = document.createElement('p');
  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent =
    'Три кандидата выбираются при запуске службы и наблюдаются до её перезапуска. ' +
    'Данные WebSocket; панель обновляется раз в 2 секунды. ' +
    'История агрегатов: каждые 10 секунд, 48 часов. Торговых сигналов и ордеров нет.';
  const body = document.createElement('div');
  box.append(title,status,note,body);

  const fmt = (x,n=2) => Number(x).toLocaleString('ru-RU',{
    maximumFractionDigits:n
  });
  function line(parent,text) {
    const p = document.createElement('p');
    p.textContent = text;
    parent.append(p);
  }
  const labels = {
    waiting:'Ожидание кандидатов',
    connecting:'Подключение',
    warming:'Накопление данных',
    live:'Поток работает',
    offline:'Переподключение'
  };

  async function refresh() {
    try {
      const response = await fetch('/api/live',{
        cache:'no-store',signal:AbortSignal.timeout(5000)
      });
      if (!response.ok) throw new Error('HTTP '+response.status);
      const s = await response.json();
      const now = Date.now()/1000;
      const fresh = now-s.updated >= -3 && now-s.updated <= 10;
      status.className = fresh && s.status === 'live' ? 'positive' : 'negative';
      status.textContent = (fresh ? (labels[s.status] || s.status) : 'ДАННЫЕ УСТАРЕЛИ')+
        ' · '+(s.message || '');
      body.replaceChildren();
      if (!fresh || s.status === 'offline') return;

      for (const r of s.rows || []) {
        const card = document.createElement('article');
        const heading = document.createElement('h3');
        heading.textContent = r.symbol;
        card.append(heading);
        if (!r.book_time || now-r.book_time > 5 || now-r.book_time < -3) {
          line(card,'Ожидание свежего стакана.');
          body.append(card);
          continue;
        }
        line(card,r.reason+' · цена '+fmt(r.price,8)+' USDT');
        line(card,'Спред: '+fmt(r.spread,4)+'%. Глубина ±0.1%: покупки '+
          fmt(r.bid_depth,0)+' / продажи '+fmt(r.ask_depth,0)+' USDT.');
        if (!r.covered) {
          line(card,'200 уровней не покрывают всю зону: глубина — нижняя оценка.');
        }
        line(card,'Дисбаланс заявок: '+fmt(r.imbalance,1)+'%.');
        line(card,'Лента за накопленные '+fmt(r.flow_window,0)+
          ' сек.: агрессивные покупки '+fmt(r.buy60,0)+
          ' / продажи '+fmt(r.sell60,0)+' USDT; сделок '+r.trades60+'.');
        line(card,'Дельта исполнений: '+fmt(r.delta60,0)+
          ' USDT. Положительное значение означает перевес покупок инициаторов.');

        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Крупные уровни и их сокращения';
        details.append(summary);
        for (const [side,w] of Object.entries(r.walls || {})) {
          line(details,(side === 'bid' ? 'Покупка' : 'Продажа')+
            ': '+fmt(w.price,8)+' USDT; объём '+fmt(w.value,0)+' USDT.');
        }
        for (const e of (r.events || []).slice().reverse()) {
          line(details,new Date(e.time*1000).toLocaleTimeString('ru-RU')+
            ' · '+(e.side === 'bid' ? 'Покупка' : 'Продажа')+
            ' '+fmt(e.price,8)+': '+fmt(e.before,0)+' → '+fmt(e.after,0)+' USDT.');
        }
        line(details,'Сокращение уровня может быть исполнением или отменой. '+
          'Это сравнение с предыдущим наблюдением примерно 2 секунды назад; '+
          'оно не доказывает манипуляцию. Поток сделок не сопоставлен с отдельными заявками.');
        card.append(details);
        body.append(card);
      }
    } catch (error) {
      status.className = 'negative';
      status.textContent = 'LIVE недоступен: '+error.message;
      body.replaceChildren();
    } finally {
      setTimeout(refresh,2000);
    }
  }
  refresh();
})();
