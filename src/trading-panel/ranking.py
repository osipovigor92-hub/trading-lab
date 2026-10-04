"""Transparent ranking of observed market conditions, with no execution actions."""
import math

CHECKS = ('turnover', 'spread', 'range', 'oi', 'funding', 'volume24',
          'atr', 'rvol', 'depth', 'book_spread', 'impact', 'coverage')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def fresh(stamp, now, seconds):
    return finite(stamp) and -2 <= now-stamp <= seconds


def points(value):
    return math.floor(max(0, min(25, value)) + .5)


def component(key, name, score, label, values):
    return dict(key=key, name=name, points=points(score) if score is not None else None,
                maximum=25, label=label, values=values)


def evaluate(verdict, now):
    checks = {c['key']:c for c in verdict['checks']}
    def value(key):
        c=checks.get(key, {})
        v=c.get('value')
        return v if c.get('state') in ('pass', 'fail') and finite(v) and v >= 0 else None

    ticker_ok=fresh(verdict.get('ticker_time'),now,45)
    chart_ok=(fresh(verdict.get('chart_time'),now,75) and
              fresh(verdict.get('candle_end'),now,120))
    book_ok=(verdict.get('samples') == 5 and fresh(verdict.get('book_time'),now,12)
             and checks.get('coverage',{}).get('value') is True)
    turnover=value('turnover') if ticker_ok else None
    quoted=value('spread') if ticker_ok else None
    spread=value('book_spread') if book_ok else None
    worst=max(quoted,spread) if quoted is not None and spread is not None else None
    rvol=value('rvol') if chart_ok else None
    depth=value('depth') if book_ok else None
    impact=value('impact') if book_ok else None
    liquidity=(25*max(0,min(1,(math.log10(turnover)-math.log10(2e6))/2))
               if turnover is not None and turnover > 0 else 0 if turnover == 0 else None)
    spread_points=25*max(0,1-worst/.05) if worst is not None else None
    volume_points=25*min(1,rvol/2) if rvol is not None else None
    book_points=(15*min(1,depth/20000)+10*max(0,1-impact/.05)
                 if depth is not None and impact is not None else None)
    confirmed=book_ok and all(checks.get(k,{}).get('state')=='pass'
                             for k in ('depth','book_spread','impact','coverage'))
    parts=[
        component('liquidity','Ликвидность',liquidity,
                  'Ликвидность высокая' if turnover is not None and turnover>=1e8 else
                  'Оборот достаточный' if turnover is not None and turnover>=2e7 else
                  'Оборот низкий' if turnover is not None else 'Ожидаем оборот',
                  dict(turnover=turnover)),
        component('spread','Спред',spread_points,
                  'Спред узкий' if worst is not None and worst<=.02 else
                  'Спред умеренный' if worst is not None and worst<=.03 else
                  'Спред широкий' if worst is not None else 'Ожидаем спред стакана',
                  dict(quoted=quoted,worst=worst)),
        component('volume','Объём',volume_points,
                  'Объём растёт' if rvol is not None and rvol>=1.2 else
                  'Объём около среднего' if rvol is not None and rvol>=.9 else
                  'Объём ниже среднего' if rvol is not None else 'Ожидаем минутный объём',
                  dict(rvol=rvol)),
        component('book','Стакан',book_points,
                  'Стакан подтверждает' if confirmed else
                  'Условия стакана не выполнены' if book_points is not None else
                  'Ожидаем полный стакан · 5 снимков',
                  dict(depth=depth,impact=impact,samples=verdict.get('samples',0))),
    ]
    missing=[checks.get(k,{}).get('label',k) for k in CHECKS if
             checks.get(k,{}).get('state') not in ('pass','fail') or
             (k!='coverage' and value(k) is None)]
    complete=(not missing and ticker_ok and chart_ok and book_ok and
              len(checks)==len(CHECKS) and all(p['points'] is not None for p in parts))
    return dict(status='ok' if complete else 'pending',
                score=sum(p['points'] for p in parts) if complete else None,
                components=parts, version=1,
                note='Сумма четырёх частей по 25 баллов' if complete else
                'Неполный рейтинг · ожидаем '+(', '.join(missing) if missing else 'свежие источники и полный стакан'))
