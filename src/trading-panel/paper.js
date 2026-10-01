(() => {
  const box = document.createElement('section');
  box.className = 'box';
  document.getElementById('scanner').before(box);
  const title = document.createElement('h2');
  title.textContent = 'PAPER · эксперимент скальпинга';
  const status = document.createElement('p');
  const body = document.createElement('div');
  box.append(title,status,body);
  const fmt = (x,n=2) => Number(x).toLocaleString('ru-RU',{
    maximumFractionDigits:n
  });
  function line(text) {
    const p = document.createElement('p');
    p.textContent = text;
    body.append(p);
  }
  async function refresh() {
    try {
      const response = await labFetch('/api/paper',{
        cache:'no-store',signal:AbortSignal.timeout(5000)
      });
      if (!response.ok) throw new Error('HTTP '+response.status);
      const s = await response.json();
      const age = Date.now()/1000-s.updated;
      const fresh = age >= -3 && age <= 10;
      status.className = fresh && s.phase === 'running' ? 'positive' : 'negative';
      status.textContent = s.phase === 'halted' ? 'ЭКСПЕРИМЕНТ ОСТАНОВЛЕН' :
        !fresh ? 'ДАННЫЕ УСТАРЕЛИ' :
        s.phase === 'running' ? 'Виртуальный эксперимент работает' : 'Ожидание данных';
      body.replaceChildren();
      if (s.reason) line(s.reason);
      line('Отдельный виртуальный капитал: '+fmt(s.equity)+
        ' USDT; P&L: '+fmt(s.equity-s.config.capital)+' USDT.');
      line('Закрыто сделок: '+s.closed+'; прибыльных: '+s.wins+
        '; убыточных: '+s.losses+'.');
      line('Комиссии модели: '+fmt(s.fees,4)+
        ' USDT; funding, оценка: '+fmt(s.funding,4)+' USDT.');
      if (s.position) {
        line('Позиция: '+s.position.symbol+' '+
          (s.position.side === 1 ? 'LONG' : 'SHORT')+
          '; вход '+fmt(s.position.entry,8)+' USDT.');
      } else {
        line('Открытой позиции нет.');
      }
      if (!fresh || s.phase === 'halted') {
        line('Капитал — последняя сохранённая оценка. При DATA_GAP позиция может остаться незакрытой.');
      }
      line('Исполнение моделируется по котировкам с фиксированным проскальзыванием. '+
        'Funding приблизительный; очередь заявок не моделируется. Реальных ордеров нет.');
      for (const e of s.events.slice(-8).reverse()) {
        line(new Date(e.time*1000).toLocaleString('ru-RU')+' · '+e.text);
      }
    } catch (error) {
      status.className = 'negative';
      status.textContent = 'PAPER недоступен: '+error.message;
      body.replaceChildren();
    } finally {
      setTimeout(refresh,3000);
    }
  }
  refresh();
})();
