(() => {
  const anchor = document.getElementById('scanner');
  const box = document.createElement('section');
  box.className = 'box';
  anchor.after(box);
  const title = document.createElement('h2');
  title.textContent = 'Скальпинг · анализ стакана';
  const status = document.createElement('p');
  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent =
    'Периодический отбор, не сигнал входа. 5 снимков по 200 уровней. ' +
    'Заявки могут исчезнуть; лента совершённых сделок пока не анализируется. ' +
    'Обновление анализа — через минуту после завершения предыдущего.';
  const list = document.createElement('div');
  box.append(title,status,note,list);
  const fmt = (x,n=2) => Number(x).toLocaleString('ru-RU',{
    maximumFractionDigits:n
  });
  function line(parent,text) {
    const p = document.createElement('p');
    p.textContent = text;
    parent.append(p);
  }
  function wall(w) {
    return w ? fmt(w.price,8)+' USDT / '+fmt(w.notional,0)+' USDT'
             : 'нет в выбранной зоне';
  }

  async function update() {
    try {
      const response = await labFetch('/api/scalp',{
        cache:'no-store',signal:AbortSignal.timeout(8000)
      });
      if (!response.ok) throw new Error('HTTP '+response.status);
      const s = await response.json();
      list.replaceChildren();
      if (s.status === 'pending') {
        status.textContent = 'Первый анализ запускается…';
        return;
      }
      const now = Date.now()/1000;
      const age = now-s.finished;
      const fresh = age >= -10 && age <= 180;
      status.className = fresh && s.status === 'ok' ? 'positive' : 'negative';
      status.textContent =
        (!fresh ? 'ДАННЫЕ УСТАРЕЛИ. ' : '') +
        (s.status === 'partial' ? 'Неполный анализ. ' :
         s.status === 'error' ? 'Ошибка анализа. ' : '') +
        'Завершено: '+new Date(s.finished*1000).toLocaleString('ru-RU');

      if (fresh && s.status !== 'error') {
        line(list,'Проверено по минутным свечам: '+s.minute_checked+
          ' из '+s.universe+'; выбрано для стакана: '+s.selected+'.');
        if (!s.rows.length) {
          line(list,'Результатов стакана нет. Проверь ошибки и фильтр ATR.');
        }
        for (const r of s.rows) {
          const current = now-r.sampled_at >= -10 && now-r.sampled_at <= 120
            && now-r.candle_end <= 180;
          const card = document.createElement('details');
          const summary = document.createElement('summary');
          summary.textContent = r.symbol+' · '+
            (!current ? 'СНИМОК УСТАРЕЛ' :
             r.candidate ? 'ДЛЯ ДАЛЬНЕЙШЕЙ ПРОВЕРКИ' : 'ОТСЕВ');
          summary.className = current && r.candidate ? 'positive' : 'muted';
          card.append(summary);
          line(card,r.reason);
          line(card,'Снимок: '+new Date(r.sampled_at*1000).toLocaleTimeString('ru-RU')+
            '; окно наблюдения '+fmt(r.window,1)+' сек.; снимков '+r.samples+'.');
          line(card,'Минутный ATR(14): '+fmt(r.atr,3)+
            '%; диапазон 15 мин: '+fmt(r.range15)+
            '%; изменение 15 мин: '+fmt(r.move15)+'%.');
          line(card,'Максимальный спред: '+fmt(r.max_spread,3)+'%.');
          line(card,'Минимум видимых заявок в зоне ±0.1% за серию: покупки '+
            fmt(r.min_bid,0)+' / продажи '+fmt(r.min_ask,0)+' USDT.');
          line(card,'Последний снимок: покупки '+fmt(r.last_bid,0)+
            ' / продажи '+fmt(r.last_ask,0)+' USDT.');
          line(card,'Дисбаланс последнего снимка: '+fmt(r.imbalance*100,1)+
            '%. Плюс — больше заявок покупателей; это не прогноз направления.');
          line(card,'Крупнейший уровень покупки: '+wall(r.bid_wall)+
            '; продажи: '+wall(r.ask_wall)+'. Уровень объединяет заявки по одной цене.');
          line(card,'Худший расчётный impact ордера номиналом '+s.notional+
            ' USDT: '+(r.impact === null ? 'недостаточно уровней' : fmt(r.impact,4)+'%')+
            ' относительно лучшей цены своей стороны, без комиссий и задержки.');
          line(card,r.covered ?
            'Полученные уровни покрыли зону ±0.1% во всех снимках.' :
            '200 уровней не покрыли всю зону: показанные объёмы — нижняя оценка.');
          list.append(card);
        }
      }
      for (const error of s.errors || []) line(list,'Ошибка: '+error);
    } catch (error) {
      status.className = 'negative';
      status.textContent = 'Анализ стакана недоступен: '+error.message;
      list.replaceChildren();
    } finally {
      setTimeout(update,10000);
    }
  }
  update();
})();
