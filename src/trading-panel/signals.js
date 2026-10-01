document.addEventListener('DOMContentLoaded', () => {
  const parent = document.getElementById('page-live');
  if (!parent) {
    console.error('Signals: page-live not found');
    return;
  }
  const box = document.createElement('section');
  box.className = 'box';
  const heading = document.createElement('h2');
  heading.textContent = 'Проверка сигналов · окно 30 секунд';
  const status = document.createElement('p');
  const body = document.createElement('div');
  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent =
    'LONG / SHORT — направление для наблюдения, не команда на сделку. '+
    'Правила экспериментальные. Лента использует перекрывающиеся окна около 60 секунд. '+
    'Проверка не оценивает будущую прибыль и не управляет PAPER-ботом.';
  box.append(heading,status,note,body);
  parent.prepend(box);

  const fmt = (v,n=2) => v == null ? '—' :
    Number(v).toLocaleString('ru-RU',{maximumFractionDigits:n});
  function line(parent,text) {
    const p = document.createElement('p');
    p.textContent = text;
    parent.append(p);
  }
  const labels = {
    WATCH_LONG:'LONG · условия выполнены',
    WATCH_SHORT:'SHORT · условия выполнены',
    WARMING:'Накопление данных',
    FILTERED:'Условия не выполнены'
  };

  async function refresh() {
    try {
      const response = await fetch('/api/signals',{
        cache:'no-store', signal:AbortSignal.timeout(5000)
      });
      if (!response.ok) throw new Error('HTTP '+response.status);
      const s = await response.json();
      const now = Date.now()/1000;
      const age = now-s.updated;
      const fresh = age >= -3 && age <= 8;
      status.textContent = !fresh ? 'ДАННЫЕ УСТАРЕЛИ' :
        s.status === 'ok' ? 'Наблюдение работает' :
        'Ожидание: '+(s.message || 'свежего LIVE');
      status.className = fresh && s.status === 'ok' ? 'positive' : 'negative';
      body.replaceChildren();
      if (!fresh) return;

      for (const r of s.rows || []) {
        const current = now-r.book_time >= -3 && now-r.book_time <= 5;
        const card = document.createElement('article');
        const h = document.createElement('h3');
        h.textContent = r.symbol+' · '+
          (current ? labels[r.status] : 'СТАКАН УСТАРЕЛ');
        card.append(h);
        if (!current) {
          body.append(card);
          continue;
        }
        line(card,'Спред сейчас / максимум: '+fmt(r.spread,4)+
          '% / '+fmt(r.spread_max,4)+'%.');
        line(card,'Глубина ±0.1% сейчас: покупка '+fmt(r.bid_depth,0)+
          ' / продажа '+fmt(r.ask_depth,0)+' USDT.');
        line(card,'Минимумы за окно: '+fmt(r.bid_min,0)+' / '+
          fmt(r.ask_min,0)+' USDT; меньший минимум — '+
          fmt(r.depth_multiple,1)+' номиналов по '+s.notional+' USDT.');
        line(card,'Дисбаланс сейчас / медиана: '+fmt(r.imbalance,1)+
          '% / '+fmt(r.imbalance_median,1)+
          '%. Устойчивость направления: '+fmt(r.stability,0)+'% снимков.');
        line(card,'Лента: покупки '+fmt(r.buy,0)+' / продажи '+
          fmt(r.sell,0)+' USDT; перевес '+fmt(r.flow,1)+
          '%; сделок '+r.trades+'.');
        line(card,'Изменение цены за ~10 сек.: '+fmt(r.move10,3)+
          '%; за окно '+fmt(r.window,1)+' сек.: '+fmt(r.move30,3)+'%.');

        if (r.reasons.length) {
          line(card,'Причины: '+r.reasons.join('; ')+'.');
        }
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.textContent = 'Крупные уровни и ограничения измерения';
        details.append(summary);
        for (const [side,w] of Object.entries(r.walls || {})) {
          line(details,(side === 'bid' ? 'Покупка' : 'Продажа')+
            ': цена '+fmt(w.price,8)+'; объём '+fmt(w.value,0)+
            ' USDT; крупнейший уровень на этой цене наблюдается '+
            fmt(w.observed_seconds,0)+' сек.');
        }
        line(details,'Это агрегированные заявки на цене, не один участник. '+
          'Между снимками объём мог исчезать и возвращаться. '+
          'Объём в зоне не гарантирует исполнение без проскальзывания.');
        if (!r.covered) line(details,
          'Полученные уровни не всегда покрывали всю зону ±0.1%: глубина — нижняя оценка.');
        card.append(details);
        body.append(card);
      }
    } catch (error) {
      status.textContent = 'Анализ недоступен: '+error.message;
      status.className = 'negative';
      body.replaceChildren();
    } finally {
      setTimeout(refresh,2000);
    }
  }
  refresh();
});
