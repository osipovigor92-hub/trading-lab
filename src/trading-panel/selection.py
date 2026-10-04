"""Eligibility filters for public market data. No score, direction or order execution."""
import math

DEFAULT_FILTERS = dict(turnover_min=20_000_000.0, spread_max=.03,
                       range_min=1.0, range_max=30.0, atr_min=.08, atr_max=.8,
                       rvol_min=1.0, oi_min=1_000_000.0, funding_max=.05,
                       depth_min=5000.0, impact_max=.05)
LIMITS = dict(turnover_min=1e13, spread_max=10, range_min=1000, range_max=1000,
              atr_min=100, atr_max=100, rvol_min=1000, oi_min=1e13,
              funding_max=100, depth_min=1e12, impact_max=100)
BOOK_SAMPLES = 5
ANALYSIS_LIMIT = 8


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
    return dict(status=state, checks=checks, ticker_time=stamp,
                chart_time=chart.get('updated') if chart_ok else None,
                candle_end=chart.get('candle_end') if chart_ok else None,
                book_time=book['updated'] if book else None,
                samples=book['samples'] if book else len(books),
                funding_interval_hours=row.get('funding_interval_hours'))
