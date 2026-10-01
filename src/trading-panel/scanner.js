(() => {
  const box = document.getElementById('scanner');
  const title = document.createElement('h2');
  title.textContent = 'Сканер рынка Bybit';
  const status = document.createElement('p');
  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent =
    'USDT perpetual · до 30 пар по обороту · 30 дней часовых свечей. ' +
    'Сравнение 8/12/16/22/30/40 сеток. Прохождение фильтров не означает прибыль. ' +
    'Автоматического переключения торгового бота нет.';
  const list = document.createElement('div');
  box.append(title, status, note, list);

  const fmt = (x, n=2) => Number(x).toLocaleString('ru-RU', {
    maximumFractionDigits:n
  });
  function line(parent, text) {
    const p = document.createElement('p');
    p.textContent = text;
    parent.append(p);
  }
  async function update() {
    try {
      const response = await labFetch('/api/scanner', {
        cache:'no-store', signal:AbortSignal.timeout(8000)
      });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const s = await response.json();
      list.replaceChildren();
      if (s.status === 'pending') {
        status.textContent = 'Первый анализ выполняется…';
        return;
      }
      const age = s.server_time - (s.quote_time || s.finished);
      const fresh = age >= 0 && age < 1800;
      const usable = fresh && ['ok', 'partial'].includes(s.status);
      status.className = usable ? 'positive' : 'negative';
      status.textContent =
        (!fresh ? 'ДАННЫЕ УСТАРЕЛИ. ' : '') +
        (s.status === 'error' ? 'Ошибка анализа. ' :
         s.status === 'partial' ? 'Анализ неполный. ' : '') +
        'Завершено: ' + new Date(s.finished*1000).toLocaleString('ru-RU') +
        '. Проверено: ' + (s.analyzed || 0) +
        '; прошли фильтры: ' + (s.candidates || 0) + '.';

      if (!usable) {
        line(list, 'Актуальные рекомендации недоступны.');
      } else {
        line(list, 'Доступных контрактов: ' + s.universe +
          '; прошли первичный отбор: ' + s.eligible +
          '; взято для анализа: ' + s.selected + '.');
        for (const [reason, count] of Object.entries(s.preliminary_rejections || {})) {
          line(list, reason + ': ' + count);
        }
        if (!s.candidates) {
          line(list, 'Подходящих кандидатов среди проверенных пар сейчас нет.');
        }
        for (const r of s.rows) {
          const card = document.createElement('details');
          const heading = document.createElement('summary');
          heading.textContent = r.symbol + ' · ' +
            (r.candidate ? 'ДЛЯ PAPER-ПРОВЕРКИ' : 'ОТСЕВ');
          heading.className = r.candidate ? 'positive' : 'muted';
          card.append(heading);
          line(card, r.reason);
          line(card, 'Цена снимка: ' + fmt(r.price,8) +
            ' USDT; оборот 24 ч: ' + fmt(r.turnover/1e6,1) + ' млн USDT.');
          line(card, 'Спред: ' + fmt(r.spread,3) +
            '%; ATR 24 ч на часовиках: ' + fmt(r.atr) + '%.');
          line(card, 'Диапазон 7 / 30 дней: ' + fmt(r.range7) +
            '% / ' + fmt(r.range30) + '%. Изменение 24 ч / 7 дней: ' +
            fmt(r.move24) + '% / ' + fmt(r.move7) + '%.');
          line(card, 'Направленность ER за неделю: ' + fmt(r.er7,3) +
            ' (0 — извилистый путь, 1 — одно направление). ' +
            'Максимальный часовой размах за неделю: ' + fmt(r.shock) + '%.');
          line(card, '|Funding| за сутки при неизменной ставке: ' +
            fmt(r.funding_day,3) +
            '% от номинала позиции. Это не фактически списанная комиссия.');
          line(card, 'Расчётный шаг при 22 сетках в диапазоне недели: ' +
            fmt(r.step_test,3) + '%. Модель издержек полного оборота: ' +
            fmt(r.cycle_cost,3) + '% без funding. Это не готовые настройки.');
          if (r.grid_options) {
            line(card, 'Варианты сетки: минимальный шаг по диапазону / издержки:');
            for (const o of r.grid_options) {
              line(card, o.grids + ' сеток: ' + fmt(o.step,3) +
                '% / ' + fmt(r.cycle_cost,3) + '% — ' +
                (o.passes ? 'порог издержек пройден' : 'шаг слишком мал'));
            }
            line(card, 'Все остальные фильтры также обязательны. ' +
              'Диапазон взят из прошлой недели и не гарантирует будущих границ. ' +
              'Размер ордеров, точность цены и соответствие капиталу ещё не проверены.');
          }
          list.append(card);
        }
      }
      for (const error of s.errors || []) line(list, 'Ошибка данных: ' + error);
    } catch (error) {
      status.className = 'negative';
      status.textContent = 'Сканер недоступен: ' + error.message;
      list.replaceChildren();
    } finally {
      setTimeout(update, 15000);
    }
  }
  update();
})();
