const el = id => document.getElementById(id);
const fmt = (n, digits=2) => Number(n).toLocaleString(
  'ru-RU', {minimumFractionDigits:digits, maximumFractionDigits:digits}
);
const put = (id, value) => { el(id).textContent = value; };

function rows(id, values) {
  const body = el(id);
  body.replaceChildren();
  for (const valuesRow of values) {
    const tr = document.createElement('tr');
    for (const value of valuesRow) {
      const td = document.createElement('td');
      td.textContent = value;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

async function refresh() {
  try {
    const response = await labFetch('/api/state', {
      cache:'no-store', signal:AbortSignal.timeout(8000)
    });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const s = await response.json();
    const c = s.config;
    const age = Math.max(0, s.server_time - s.last_seen);
    const fresh = age <= 45;
    const pnl = s.equity - c.capital;
    const dd = Math.max(0, (1 - s.equity / s.peak) * 100);

    el('status').className = 'notice ' + (
      !s.halted && fresh ? 'ok' : 'bad'
    );
    put('status', s.halted
      ? 'Тест остановлен: ' + s.reason
      : fresh ? 'Данные бота обновляются · виртуальная торговля'
      : 'Нет свежих данных. Проверь службу бота.');
    put('updated', 'Последний снимок: ' +
      new Date(s.last_seen * 1000).toLocaleString('ru-RU') +
      ' · ' + Math.round(age) + ' сек. назад');

    put('equity', fmt(s.equity));
    put('pnl', (pnl > 0 ? '+' : '') + fmt(pnl));
    el('pnl').className = pnl >= 0 ? 'positive' : 'negative';
    put('position', fmt(s.position,1));
    put('fills', s.fills);
    put('symbol', c.symbol + ' · нейтральная сетка');
    put('balance', fmt(s.balance) + ' USDT');
    put('capital', fmt(c.capital) + ' USDT');
    put('average', s.position ? fmt(s.average,4) : 'Нет позиции');
    put('fees', fmt(s.fees,4) + ' USDT');
    put('funding', fmt(s.funding_estimate,4) + ' USDT');
    put('drawdown', fmt(dd) + '%');
    put('range', fmt(c.lower,3) + ' — ' + fmt(c.upper,3));
    put('quantity', fmt(c.quantity,1) + ' LINK');
    put('limit', fmt(c.max_position,1) + ' LINK');
    put('stop', fmt(Math.max(
      c.capital - c.max_loss, s.peak * (1-c.trailing)
    )) + ' USDT');

    for (const [id, side] of [['buys',1],['sells',-1]]) {
      const orders = s.orders.filter(o => o.side === side)
        .sort((a,b) => side === 1 ? b.level-a.level : a.level-b.level);
      rows(id, orders.map(o => [
        fmt(s.levels[o.level],4),
        fmt(c.quantity,1),
        Math.abs(s.position + side*c.quantity) <= c.max_position+1e-8
          ? 'Разрешён' : 'Блок позиции'
      ]));
    }
    rows('events', s.events.slice(-30).reverse().map(e => [
      new Date(e.time*1000).toLocaleString('ru-RU'),
      e.side === 'BUY' ? 'Покупка' : 'Продажа',
      fmt(e.quantity,1), fmt(e.price,4), fmt(e.position,1)
    ]));
    put('empty', s.events.length ? (
      'Показано до 30 последних grid-исполнений. Аварийное закрытие — в журнале службы.'
    ) : 'Исполнений пока нет: бот ждёт движения цены.');
  } catch (error) {
    el('status').className = 'notice bad';
    put('status', 'Панель недоступна: проверь SSH-туннель и службу панели.');
    put('updated', 'Показанные ранее числа не обновляются.');
  } finally {
    setTimeout(refresh, 5000);
  }
}
refresh();


/* DASHBOARD_V2 */
(() => {
  document.addEventListener('DOMContentLoaded', () => {
    const main = document.querySelector('main');
    if (!main || document.getElementById('dashboard-tabs')) return;
    const make = (tag, cls='', text='') => {
      const n = document.createElement(tag);
      n.className = cls;
      n.textContent = text;
      return n;
    };
    const old = [...main.children];
    const footer = main.querySelector('footer');
    const pages = {};
    const names = {overview:'Обзор',alerts:'Алерты',market:'Скринер',live:'LIVE',grid:'Grid',tests:'Тесты',research:'Модели'};
    const nav = make('nav','dashboard-tabs');
    nav.id = 'dashboard-tabs';
    nav.setAttribute('aria-label','Разделы панели');
    for (const key of Object.keys(names)) {
      pages[key] = make('div','dashboard-page');
      pages[key].id = 'page-'+key;
      pages[key].hidden = true;
      main.insertBefore(pages[key],footer);
    }
    for (const n of old) {
      if (n.tagName === 'HEADER' || n.tagName === 'FOOTER') continue;
      const title = n.querySelector('h2')?.textContent || '';
      let key = 'grid';
      if (n.id === 'scanner' || title.startsWith('Скальпинг')) key='market';
      else if (title.startsWith('LIVE')) key='live';
      else if (title.startsWith('PAPER') || title.startsWith('Журнал')) key='tests';
      pages[key].append(n);
    }
    const header = main.querySelector('header');
    if (header) {
      header.after(nav);
      const h1 = header.querySelector('h1');
      if (h1) h1.textContent='Торговая лаборатория';
    } else main.prepend(nav);
    const buttons = {};
    function activate(key) {
      if (!names[key]) key='overview';
      try { sessionStorage.setItem('lab-tab',key); } catch (_) {}
      document.dispatchEvent(new CustomEvent('lab-tab',{detail:key}));
      for (const k of Object.keys(names)) {
        pages[k].hidden = k !== key;
        buttons[k].classList.toggle('selected',k===key);
        buttons[k].setAttribute('aria-pressed',String(k===key));
      }
    }
    for (const [key,label] of Object.entries(names)) {
      const b = make('button','',label);
      b.type='button';
      b.setAttribute('aria-controls','page-'+key);
      b.addEventListener('click',()=>activate(key));
      buttons[key]=b;
      nav.append(b);
    }
    const top = make('section','box overview-head');
    top.append(make('small','','ЭКСПЕРИМЕНТ СКАЛЬПИНГА · PAPER'));
    const state = make('h2','','Подключение…');
    const stamp = make('p','muted');
    top.append(state,stamp);
    pages.overview.append(top);
    const cards = make('section','cards summary-cards');
    const values = {};
    for (const [key,label] of [
      ['equity','Капитал, USDT'],['pnl','Результат, USDT'],
      ['closed','Закрыто сделок'],['dd','Просадка от пика']
    ]) {
      const c=make('article');
      const v=make('strong','','—');
      c.append(make('label','',label),v);
      values[key]=v; cards.append(c);
    }
    pages.overview.append(cards);
    const position = make('section','box');
    const costs = make('section','box');
    const health = make('section','box');
    pages.overview.append(position,costs,health);
    pages.overview.append(make('p','muted',
      'Виртуальный эксперимент. Здесь показан скальпинг; отдельный grid-бот находится во вкладке Grid.'));
    const testing = make('section','box');
    const ledger = make('section','box');
    pages.tests.prepend(testing,ledger);
    const fmt=(x,n=2)=>Number(x).toLocaleString('ru-RU',{maximumFractionDigits:n});
    function line(parent,text,cls='') { parent.append(make('p',cls,text)); }
    const labels={running:'Эксперимент работает',waiting:'Ожидание данных',halted:'Эксперимент остановлен'};
    const get = async path => {
      const r=await labFetch(path,{cache:'no-store',signal:AbortSignal.timeout(5000)});
      if (!r.ok) throw new Error('HTTP '+r.status);
      return r.json();
    };
    async function updatePaper() {
      try {
        const s=await get('/api/paper');
        const age=Date.now()/1000-s.updated;
        const fresh=age>=-3 && age<=10;
        state.textContent=s.phase==='halted' ? labels.halted :
          fresh ? (labels[s.phase] || s.phase) : 'Данные устарели';
        state.className=fresh && s.phase==='running' ? '' : 'negative';
        stamp.textContent='Снимок: '+new Date(s.updated*1000).toLocaleString('ru-RU')+
          (s.reason ? ' · '+s.reason : '');
        values.equity.textContent=fmt(s.equity);
        const pnl=s.equity-s.config.capital;
        values.pnl.textContent=(pnl>0?'+':'')+fmt(pnl,4);
        values.pnl.className=pnl<0?'negative':pnl>0?'positive':'';
        values.closed.textContent=s.closed;
        values.dd.textContent=fmt(Math.max(0,1-s.equity/s.peak)*100,3)+'%';
        position.replaceChildren(make('h2','','Позиция'));
        if (s.position) {
          const p=s.position;
          line(position,p.symbol+' · '+(p.side===1?'LONG':'SHORT'),'position-name');
          line(position,'Вход '+fmt(p.entry,8)+' USDT · количество '+fmt(p.quantity,8));
          line(position,'Открыта '+new Date(p.opened*1000).toLocaleTimeString('ru-RU')+
            ' · возраст '+Math.max(0,Math.round(Date.now()/1000-p.opened))+' сек.');
        } else {
          line(position,'Открытой позиции нет');
          const rest=Math.max(0,Math.ceil(s.cooldown_until-Date.now()/1000));
          line(position,rest ? 'Пауза до новых входов: '+rest+' сек.' :
            'Ожидаем совпадения условий входа.','muted');
        }
        if (!fresh || s.phase==='halted') line(position,'Показана последняя сохранённая оценка.','negative');
        costs.replaceChildren(make('h2','','Расходы и результат'));
        line(costs,'Прибыльных / убыточных: '+s.wins+' / '+s.losses+
          ' · доля прибыльных: '+(s.closed?fmt(s.wins/s.closed*100,1)+'%':'—'));
        line(costs,'Комиссии: '+fmt(s.fees,4)+' USDT · funding, оценка: '+fmt(s.funding,4)+' USDT');
        line(costs,'Комиссии уже включены в результат. Проскальзывание включено в модельные цены.','muted');
        testing.replaceChildren(make('h2','','Контрольная модель A'));
        line(testing,'Версия '+s.config.version+' · '+s.closed+' закрытых сделок. Доказанного преимущества пока нет.');
        line(testing,'Условия: перевес ленты, дисбаланс стакана, движение цены и три подтверждения.');
        line(testing,'Номинал '+s.config.notional+' USDT · цель +'+s.config.take_profit+
          ' / стоп −'+s.config.stop_loss+' USDT · удержание до '+s.config.max_hold+' сек.');
        line(testing,'Комиссия '+fmt(s.config.fee*100,3)+'% и проскальзывание '+
          fmt(s.config.slippage*100,3)+'% на сторону. Funding приблизительный.');
        line(testing,'Текущее состояние модели B показано в её блоке. Изменения правил проверяются на последующих данных.','muted');
      } catch (error) {
        state.textContent='PAPER недоступен: '+error.message;
        state.className='negative';
        stamp.textContent='Числа ниже не обновляются.';
      } finally { setTimeout(updatePaper,5000); }
    }
    async function updateHealth() {
      health.replaceChildren(make('h2','','Качество данных'));
      try {
        const s=await get('/api/live');
        const age=Date.now()/1000-s.updated;
        const ready=s.status==='live' && age>=-3 && age<=10;
        line(health,ready?'LIVE: свежий поток':'LIVE: '+s.status+' · проверь вкладку LIVE');
        line(health,'Под наблюдением: '+(s.rows || []).map(r=>r.symbol).join(', '));
        line(health,'Свежесть соединения не является торговым сигналом.','muted');
      } catch (_) { line(health,'Состояние LIVE недоступно.','negative'); }
      setTimeout(updateHealth,10000);
    }
    async function updateLedger() {
      ledger.replaceChildren(make('h2','','Покрытие журнала'));
      try {
        const s=await get('/api/journal');
        line(ledger,'Точных записей: '+s.recorded+' · закрытий до установки: '+s.legacy_closed);
        line(ledger,'Net записанных сделок: '+fmt(s.net,4)+' USDT · средняя: '+
          (s.average===null?'—':fmt(s.average,4)+' USDT'));
        line(ledger,'Profit factor: '+(s.profit_factor===null?'—':fmt(s.profit_factor))+
          '. Это отношение суммы положительных net к модулю суммы отрицательных net.');
        line(ledger,'Открытая позиция и старые сделки в эту статистику не входят.','muted');
      } catch (_) {
        line(ledger,'Отчёт журнала пока недоступен. Обзор продолжает показывать состояние PAPER.');
      }
      setTimeout(updateLedger,10000);
    }
    let selected='overview';
    try { selected=sessionStorage.getItem('lab-tab')||selected; } catch (_) {}
    activate(selected);
    updatePaper(); updateHealth(); updateLedger();
  });
})();
