"""Pure closed-bar signals. No network access or order submission.

A level must have been confirmed no later than the preceding bar's close.
The caller persists the returned event key when accepting a signal.
"""
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def level_break(packet, level, *, now, direction='both', min_volume_x=1.5):
    """Return waiting/blocked/triggered; never use forming candles as proof."""
    def result(status, reason, **values):
        return dict(status=status, reason=reason, **values)
    if direction not in ('long', 'short', 'both') or not finite(min_volume_x) or min_volume_x < 1:
        raise ValueError('Invalid signal settings')
    if not finite(now) or not isinstance(packet, dict) or not isinstance(level, dict):
        return result('blocked', 'invalid_input')
    if (packet.get('status') != 'ok' or packet.get('error') or packet.get('refresh_error') or
            packet.get('stale') or not finite(packet.get('updated')) or
            not 0 <= now-packet['updated'] <= 75):
        return result('blocked', 'stale_source')
    interval = packet.get('interval')
    if str(interval) not in ('1', '5', '15', '60', '240', '1440'):
        return result('blocked', 'invalid_interval')
    step = int(interval)*60
    end = math.floor((now-2)/step)*step
    bars = packet.get('candles')
    if packet.get('candle_end') != end or not isinstance(bars, list) or len(bars) < 21:
        return result('blocked', 'incomplete_history')
    bars = bars[-21:]
    for i, bar in enumerate(bars):
        if (not isinstance(bar, dict) or not all(finite(bar.get(k)) for k in ('t','open','high','low','close','volume')) or
                bar['low'] <= 0 or bar['low'] > min(bar['open'],bar['close']) or
                bar['high'] < max(bar['open'],bar['close']) or bar['volume'] < 0 or
                bar['t'] % step != 0 or bar['t']+step > end or
                (i and bar['t']-bars[i-1]['t'] != step)):
            return result('blocked', 'invalid_bars')
    last, previous = bars[-1], bars[-2]
    if last['t']+step != end:
        return result('blocked', 'missing_latest_bar')
    for key in ('exchange','symbol'):
        if not isinstance(packet.get(key), str) or not packet[key] or level.get(key) != packet[key]:
            return result('blocked', 'source_mismatch')
    price, confirmed = level.get('price'), level.get('confirmed_at')
    if not finite(price) or price <= 0 or not finite(confirmed) or confirmed > last['t']:
        return result('blocked', 'unconfirmed_level')
    side = ('long' if previous['close'] <= price < last['close'] else
            'short' if previous['close'] >= price > last['close'] else None)
    if side is None or direction not in ('both',side):
        return result('waiting', 'no_cross')
    baseline = sum(b['volume'] for b in bars[:-1])/20
    if baseline <= 0 or last['volume'] < baseline*min_volume_x:
        return result('waiting', 'volume_not_confirmed')
    key = f"level_break:{packet['exchange']}:{packet['symbol']}:{step}:{end}:{side}:{price:.12g}"
    return result('triggered', 'closed_bar_cross', event_key=key, side=side,
                  signal_price=last['close'], closed_at=end, volume_x=last['volume']/baseline,
                  level=price)
