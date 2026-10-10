"""Eligibility filters and their measured inputs; no direction or order execution."""
import math
import re
import ranking

DEFAULT_FILTERS = dict(turnover_min=20_000_000.0, spread_max=.03,
                       range_min=1.0, range_max=30.0, atr_min=.08, atr_max=.8,
                       rvol_min=1.0, oi_min=1_000_000.0, funding_max=.05,
                       depth_min=5000.0, impact_max=.05)
LIMITS = dict(turnover_min=1e13, spread_max=10, range_min=1000, range_max=1000,
              atr_min=100, atr_max=100, rvol_min=1000, oi_min=1e13,
              funding_max=100, depth_min=1e12, impact_max=100)
BOOK_SAMPLES = 5
ANALYSIS_LIMIT = 8


def parse_watch(value=''):
    if not isinstance(value, str):
        raise ValueError('Некорректный список наблюдения')
    symbols = value.split(',') if value else []
    if (len(symbols) > ANALYSIS_LIMIT or len(set(symbols)) != len(symbols) or
            any(not re.fullmatch(r'[A-Z0-9]{2,24}USDT', s) for s in symbols)):
        raise ValueError('Наблюдение: до 8 разных USDT-пар')
    return symbols


def shortlist(rows, stamp, filters, search, watch, now):
    available = {r['symbol'] for r in rows}
    pinned = [s for s in watch if s in available]
    eligible = [r['symbol'] for r in rows if search in r['symbol'] and
                all(c['state'] == 'pass' for c in ticker_checks(r, stamp, filters, now))]
    return list(dict.fromkeys(pinned + eligible))[:ANALYSIS_LIMIT]


def activity_proxy(row):
    """A ticker-only discovery priority, separate from the confirmed activity index."""
    change, span = row.get('change'), row.get('range24')
    if not finite(change) or not finite(span) or span < 0:
        return 0.0
    return min(abs(change), 20) / 20 + min(span, 30) / 30


def assistant_shortlist(rows, stamp, filters, search, watch, now):
    available = {row['symbol'] for row in rows}
    pinned = [symbol for symbol in watch if symbol in available]
    eligible = [row for row in rows if search in row['symbol'] and
                all(c['state'] == 'pass' for c in ticker_checks(row, stamp, filters, now))]
    eligible.sort(key=lambda row: (-activity_proxy(row), -row['turnover'], row['symbol']))
    return list(dict.fromkeys(pinned + [row['symbol'] for row in eligible]))[:ANALYSIS_LIMIT]


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def fresh(stamp, now, seconds):
    return finite(stamp) and -2 <= now - stamp <= seconds


def parse_filters(values=None):
    values = values or {}
    if set(values) - set(DEFAULT_FILTERS):
        raise ValueError('Неизвестный фильтр отбора')
    result = dict(DEFAULT_FILTERS)
    for key, raw in values.items():
        if isinstance(raw, bool):
            raise ValueError('Фильтры должны быть числами')
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError('Фильтры должны быть числами') from None
        if not math.isfinite(value) or not 0 <= value <= LIMITS[key]:
            raise ValueError('Значение фильтра вне допустимого диапазона: ' + key)
        result[key] = value
    if result['range_min'] > result['range_max'] or result['atr_min'] > result['atr_max']:
        raise ValueError('Минимум диапазона или ATR превышает максимум')
    return result


def check(key, label, value, low=None, high=None, unit='', available=True):
    known = available and finite(value)
    passed = known and (low is None or value >= low) and (high is None or value <= high)
    return dict(key=key, label=label, value=value if known else None, min=low,
                max=high, unit=unit, state='pass' if passed else 'fail' if known else 'pending')


def ticker_checks(row, stamp, filters, now):
    available = fresh(stamp, now, 45)
    funding = row.get('funding')
    volume = row.get('volume24')
    return [
        check('turnover', 'Оборот 24ч', row.get('turnover'), filters['turnover_min'],
              unit='USDT', available=available),
        check('spread', 'Спред котировки', row.get('spread'), high=filters['spread_max'],
              unit='%', available=available),
        check('range', 'Диапазон 24ч', row.get('range24'), filters['range_min'],
              filters['range_max'], '%', available),
        check('oi', 'Открытый интерес', row.get('open_interest'), filters['oi_min'],
              unit='USDT', available=available),
        check('funding', '|Funding| за интервал контракта', abs(funding)*100 if finite(funding) else None,
              high=filters['funding_max'], unit='%', available=available),
        check('volume24', 'Объём 24ч', volume, low=1e-15,
              unit='монет', available=available),
    ]


def book_summary(books, now):
    valid = [b for b in books if b.get('status') == 'ok' and fresh(b.get('updated'), now, 60)]
    if len(valid) != BOOK_SAMPLES or not fresh(valid[-1].get('updated'), now, 12):
        return None
    for a, b in zip(valid, valid[1:]):
        if (not finite(a.get('seq')) or not finite(b.get('seq')) or
                b['seq'] <= a['seq'] or b['updated'] - a['updated'] < 1.5):
            return None
    bands = [b.get('bands', {}).get('0.001', {}) for b in valid]
    impacts = [b.get(k) for b in valid for k in ('buy_impact', 'sell_impact')]
    if (any(not finite(b.get(k)) or b[k] < 0 for b in bands for k in ('bid', 'ask'))
            or any(not finite(b.get('spread')) or b['spread'] < 0 for b in valid)):
        return None
    return dict(updated=valid[-1]['updated'], samples=len(valid),
                depth=min(min(b['bid'], b['ask']) for b in bands),
                covered=all(b.get('covered') is True for b in bands),
                impact=max(impacts) if all(finite(x) for x in impacts) else None,
                spread=max(b['spread'] for b in valid))


def assistant(row, stamp, chart, now, quote_available=True, filters=None):
    """Explain observed activity; no book dependency, prediction or order advice."""
    chart = chart if isinstance(chart, dict) else {}
    filters = filters or DEFAULT_FILTERS
    sources = dict(quote=stamp, chart=chart.get('updated'), candle=chart.get('candle_end'))
    limits = dict(quote=45, chart=75, candle=120)
    freshness = {key: dict(time=value, age_seconds=now-value if finite(value) else None,
                           max_age_seconds=limits[key], fresh=fresh(value, now, limits[key]))
                 for key, value in sources.items()}
    if not quote_available:
        freshness['quote']['fresh'] = False
    if chart.get('error') or chart.get('refresh_error') or chart.get('status') != 'ok':
        freshness['chart']['fresh'] = freshness['candle']['fresh'] = False
    missing = []
    if (not quote_available or not fresh(stamp, now, 45) or
            any(not finite(row.get(key)) for key in ('price', 'turnover', 'spread', 'change', 'range24')) or
            row.get('price', 0) <= 0 or row.get('turnover', 0) <= 0 or row.get('spread', -1) < 0):
        missing.append('Свежая котировка')
    if (chart.get('status') != 'ok' or chart.get('symbol') != row.get('symbol') or
            chart.get('interval') != '1' or chart.get('error') or chart.get('refresh_error') or
            not fresh(chart.get('updated'), now, 75) or not fresh(chart.get('candle_end'), now, 120)):
        missing.append('Свежие закрытые свечи 1м')
    elif (not 0 <= chart['updated'] - chart['candle_end'] < 60 or
          not finite(stamp) or abs(chart['updated'] - stamp) > 45):
        missing.append('Согласованные времена котировки и свечей')
    indicators = chart.get('indicators')
    fields = ('rsi14', 'ema20', 'ema50', 'ema_gap_pct', 'vwap60', 'vwap_distance_pct',
              'atr14', 'atr14_pct', 'rvol5', 'change5_pct', 'range5_pct', 'close')
    if (not isinstance(indicators, dict) or any(not finite(indicators.get(key)) for key in fields) or
            not finite(indicators.get('closed_bars')) or not 60 <= indicators['closed_bars'] <= 180 or
            indicators.get('window_end') != chart.get('candle_end') or
            any(indicators.get(key, 0) <= 0 for key in ('ema20', 'ema50', 'vwap60', 'close')) or
            any(indicators.get(key, -1) < 0 for key in ('atr14', 'atr14_pct', 'rvol5', 'range5_pct')) or
            not 0 <= indicators.get('rsi14', -1) <= 100):
        missing.append('Полное окно индикаторов и объём')
    result = dict(status='pending' if missing else 'ok', timeframe='1',
                  updated=chart.get('updated') if not missing else None,
                  candle_end=chart.get('candle_end') if not missing else None,
                  sources=sources, freshness=freshness, indicators={} if missing else dict(indicators),
                  trend='unknown', activity='unknown', setup='waiting', score=None,
                  eligible=None, score_components=[], reasons=[], missing=missing, version=1,
                  signal_id=None, breakout_level=None, extension_atr=None,
                  note='Индекс активности 0–100; не вероятность прибыли')
    if missing:
        result['reasons'] = ['Ожидаем: ' + ', '.join(missing)]
        return result
    values = indicators
    price = values['close']
    trend = ('up' if price > values['ema20'] > values['ema50'] and price > values['vwap60'] else
             'down' if price < values['ema20'] < values['ema50'] and price < values['vwap60'] else 'mixed')
    rvol, movement, span = values['rvol5'], values['change5_pct'], values['range5_pct']
    activity = 'active' if rvol >= 1.5 and span >= .2 else 'quiet' if rvol < .8 or span < .1 else 'normal'
    # The index ranks activity symmetrically for rising and falling coins. Fixed,
    # disclosed caps prevent a high RSI from being mistaken for a better entry.
    def part(key, label, value, cap, maximum):
        return dict(key=key, label=label, value=value, cap=cap, max=maximum,
                    formula='min(1, value / cap) × ' + str(maximum),
                    points=math.floor(max(0, min(1, value / cap)) * maximum + .5))
    components = [part('volume', 'RVOL 5 / 20', rvol, 3, 40),
                  part('range', 'Диапазон 5м', span, 1.5, 30),
                  part('movement', '|Изменение 5м|', abs(movement), 1, 20),
                  part('turnover', 'Оборот 24ч', row['turnover'], 100_000_000, 10)]
    liquid = row['turnover'] >= filters['turnover_min'] and row['spread'] <= filters['spread_max']
    breakout_side = ('up' if values.get('breakout_up') is True else
                     'down' if values.get('breakout_down') is True else None)
    reference_side = breakout_side or (trend if trend in ('up', 'down') else None)
    context = values.get('breakout_context_' + reference_side) if reference_side else None
    context = context if isinstance(context, dict) else None
    extension = (context.get('extension_atr') if context else
                 values.get('extension_' + breakout_side + '_atr') if breakout_side else None)
    extended = finite(extension) and extension > 1.5
    setup = ('breakout_' + breakout_side if liquid and rvol >= 1.5 and breakout_side and
             finite(extension) and not extended else
             'watch' if extended else
             'momentum_up' if liquid and activity == 'active' and trend == 'up' and movement >= .1 else
             'momentum_down' if liquid and activity == 'active' and trend == 'down' and movement <= -.1 else 'watch')
    reasons = ['EMA20 > EMA50, закрытие выше EMA20 и VWAP60' if trend == 'up' else
               'EMA20 < EMA50, закрытие ниже EMA20 и VWAP60' if trend == 'down' else
               'EMA и VWAP60 не подтверждают единое направление',
               'Объём 5м / предыдущие 20м: ' + format(rvol, '.3g') + '×',
               'Изменение 5м: ' + format(movement, '+.3g') + '%; RSI14: ' + format(values['rsi14'], '.3g')]
    if values['rsi14'] > 75 or values['rsi14'] < 25:
        reasons.append('RSI у края диапазона: риск запоздалого входа')
    breakout_level = (context.get('level') if context else
                      values.get('prior20_high' if breakout_side == 'up' else 'prior20_low') if breakout_side else None)
    if breakout_side and finite(breakout_level) and finite(extension):
        reasons.append('Первое закрытие за диапазоном 20м: ' + format(breakout_level, '.6g') +
                       '; удаление ' + format(extension, '.3g') + ' ATR14')
    elif context and finite(breakout_level) and finite(extension):
        reasons.append('Исходная граница пробоя: ' + format(breakout_level, '.6g') +
                       '; удаление ' + format(extension, '.3g') + ' ATR14')
    if extended:
        reasons.append('Цена ушла более чем на 1,5 ATR14 от пробоя: не догонять импульс')
    if not liquid:
        reasons.append('Оборот или спред не проходит пороги ликвидности')
    if activity != 'active' or abs(movement) < .1:
        reasons.append('Для импульса нужны RVOL≥1,5, диапазон 5м≥0,2% и |изменение 5м|≥0,1%')
    if setup == 'watch':
        reasons.append('Продолжить наблюдение; условия сетапа не подтверждены')
    else:
        reasons.append('Импульс на закрытых свечах; проверить уровень и риск перед входом')
    result.update(trend=trend, activity=activity, setup=setup, eligible=liquid,
                  score=sum(part['points'] for part in components), score_components=components, reasons=reasons,
                  breakout_level=breakout_level, extension_atr=extension,
                  signal_id=':'.join((row['symbol'], setup, '1', format(chart['candle_end'], '.0f')))
                  if setup not in ('watch', 'waiting') else None)
    return result


def evaluate(row, stamp, chart, books, filters, now):
    checks = ticker_checks(row, stamp, filters, now)
    chart = chart or {}
    chart_ok = (chart.get('symbol') == row.get('symbol') and chart.get('interval') == '1'
                and chart.get('status') == 'ok' and fresh(chart.get('updated'), now, 75)
                and fresh(chart.get('candle_end'), now, 120))
    bars = chart.get('candles', []) if chart_ok else []
    # Base quantity avoids treating a price increase alone as rising trading volume.
    volumes = [b.get('volume') for b in bars[-25:]]
    base = sum(volumes[:20])/20 if len(volumes) == 25 and all(finite(v) and v >= 0 for v in volumes) else 0
    rvol = (sum(volumes[-5:])/5)/base if base > 0 else None
    checks.extend([
        check('atr', 'ATR(14) · 1м', chart.get('atr_pct'), filters['atr_min'],
              filters['atr_max'], '%', chart_ok),
        check('rvol', 'Объём · 5 / 20 закрытых минут', rvol, filters['rvol_min'],
              unit='×', available=chart_ok),
    ])
    book = book_summary(books, now)
    checks.extend([
        check('depth', 'Глубина каждой стороны ±0,1%', book.get('depth') if book else None,
              filters['depth_min'], unit='USDT'),
        check('book_spread', 'Худший спред · 5 снимков', book.get('spread') if book else None,
              high=filters['spread_max'], unit='%'),
        check('impact', 'Худший impact · около 100 USDT', book.get('impact') if book else None,
              high=filters['impact_max'], unit='%'),
    ])
    checks.append(dict(key='coverage', label='Покрытие стакана ±0,1% · 5 снимков',
                       value=book['covered'] if book else None,
                       state='pass' if book and book['covered'] else 'fail' if book else 'pending'))
    state = 'rejected' if any(c['state'] == 'fail' for c in checks) else (
        'pending' if any(c['state'] == 'pending' for c in checks) else 'passed')
    verdict = dict(status=state, checks=checks, ticker_time=stamp,
                chart_time=chart.get('updated') if chart_ok else None,
                candle_end=chart.get('candle_end') if chart_ok else None,
                book_time=book['updated'] if book else None,
                samples=book['samples'] if book else len(books),
                funding_interval_hours=row.get('funding_interval_hours'))
    verdict['rating'] = ranking.evaluate(verdict, now)
    return verdict
