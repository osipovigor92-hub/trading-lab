"""One bounded native-engine test. Never accepts exchange credentials or live commands."""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import urlopen
import uuid
from zipfile import ZipFile

ROOT = Path('/var/lib/trading-platforms')
HERE = Path(__file__).resolve().parent
ENGINES = ('freqtrade', 'hummingbot', 'jesse')


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, 'tolist'):
        return clean(value.tolist())
    if hasattr(value, 'item'):
        return clean(value.item())
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(clean(value), f, ensure_ascii=False, allow_nan=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def period():
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=7), end


def validate_candles(rows, start, end):
    if not rows or len(rows) > 12000:
        raise ValueError('Неверное количество свечей')
    for i, r in enumerate(rows):
        if len(r) != 6 or not all(math.isfinite(v) for v in r):
            raise ValueError('Неверная свеча')
        t, o, c, h, l, v = r
        if min(o, c, h, l) <= 0 or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Неверный OHLCV')
        if t != start + i * 60000 or t + 60000 > end:
            raise ValueError('Разрыв минутных свечей; заполнение выдуманными данными запрещено')
    if rows[-1][0] + 60000 != end:
        raise ValueError('Неполный период свечей')
    return rows


def bybit_candles(start, end):
    first, finish = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    cursor, found = finish - 1, {}
    for _ in range(13):
        query = urlencode(dict(category='linear', symbol='BTCUSDT', interval='1',
                               start=first, end=cursor, limit=1000))
        with urlopen('https://api.bybit.com/v5/market/kline?' + query, timeout=15) as f:
            response = json.load(f)
        if response.get('retCode') != 0:
            raise ValueError('Bybit candles: ' + str(response.get('retMsg'))[:100])
        batch = response['result']['list']
        if not batch:
            break
        oldest = min(int(r[0]) for r in batch)
        if oldest > cursor:
            raise ValueError('Повтор страницы свечей')
        for r in batch:
            t, o, h, l, c, v = [float(x) for x in r[:6]]
            if first <= t < finish:
                found[t] = [t, o, c, h, l, v]
        if oldest <= first:
            break
        cursor = oldest - 1
        time.sleep(.15)
    return validate_candles([found[k] for k in sorted(found)], first, finish)


def ft_config():
    return dict(dry_run=True, dry_run_wallet=600, stake_currency='USDT', stake_amount=100,
        max_open_trades=1, tradable_balance_ratio=.99, trading_mode='futures', margin_mode='isolated',
        timeframe='5m', fee=.00055, cancel_open_orders_on_exit=True,
        exchange=dict(name='bybit', key='', secret='', pair_whitelist=['BTC/USDT:USDT'], pair_blacklist=[]),
        pairlists=[dict(method='StaticPairList')],
        entry_pricing=dict(price_side='same', use_order_book=True, order_book_top=1,
                           price_last_balance=0, check_depth_of_market=dict(enabled=False, bids_to_ask_delta=1)),
        exit_pricing=dict(price_side='same', use_order_book=True, order_book_top=1),
        unfilledtimeout=dict(entry=10, exit=10, unit='minutes'),
        order_types=dict(entry='limit', exit='limit', stoploss='market', stoploss_on_exchange=False),
        api_server=dict(enabled=False), telegram=dict(enabled=False))


def parse_ft(folder):
    files = sorted(folder.glob('*.zip')) + sorted(folder.glob('*.json'))
    for path in reversed(files):
        if path.suffix == '.zip':
            with ZipFile(path) as archive:
                candidates = [json.loads(archive.read(n)) for n in archive.namelist()
                              if n.endswith('.json') and archive.getinfo(n).file_size <= 16 * 1024**2]
        else:
            candidates = [json.loads(path.read_text())]
        for obj in candidates:
            if 'LabEMATest' in obj.get('strategy', {}):
                result = obj['strategy']['LabEMATest']
                return dict(count=result['total_trades'], net=result['profit_total_abs'],
                    profit_factor=result.get('profit_factor'), drawdown_pct=result.get('max_drawdown_account', 0) * 100,
                    win_rate=result.get('wins', 0) / result['total_trades'] * 100 if result['total_trades'] else None,
                    equity=result.get('final_balance')), result.get('trades', [])
    raise ValueError('Freqtrade не создал отчёт теста')


def freqtrade(run_dir, update):
    config = run_dir / 'config.json'; atomic(config, ft_config())
    start, end = period()
    settings = dict(strategy='LabEMATest · EMA20/50', pair='BTC/USDT:USDT', interval='5m',
                    mode='backtest', start=start.timestamp(), end=end.timestamp(), fee_pct=.055,
                    assumptions='Исторические свечи; без очереди заявок. Параметры не оптимизированы.')
    update(settings=settings, reason='Freqtrade загружает исторические свечи')
    common = [sys.executable, '-m', 'freqtrade']
    def command(args):
        with (run_dir / 'native.log').open('a') as log:
            subprocess.run(common + args + ['--userdir', str(run_dir)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
    command(['download-data', '--config', str(config), '--timerange',
             (start - timedelta(days=1)).strftime('%Y%m%d') + '-' + end.strftime('%Y%m%d'),
             '--pairs', 'BTC/USDT:USDT', '--timeframes', '5m', '--trading-mode', 'futures'])
    update(reason='Freqtrade исполняет исторический тест')
    results = run_dir / 'results'; results.mkdir()
    command(['backtesting', '--config', str(config), '--strategy', 'LabEMATest',
             '--strategy-path', str(HERE), '--timerange', start.strftime('%Y%m%d') + '-' + end.strftime('%Y%m%d'),
             '--export', 'trades', '--export-directory', str(results), '--cache', 'none'])
    return parse_ft(results)


def jesse(run_dir, update):
    import numpy as np
    import jesse.helpers as jh
    from jesse.research import backtest
    from jesse_strategy import LabEMA
    start, end = period()
    update(reason='Загрузка закрытых минутных свечей Bybit', settings=dict(
        strategy='LabEMA · EMA20/50', pair='BTC-USDT', interval='5m', mode='backtest',
        start=start.timestamp(), end=end.timestamp(), fee_pct=.055,
        assumptions='Бесплатный research backtest; без проскальзывания и очереди заявок.'))
    rows = bybit_candles(start - timedelta(minutes=300), end)
    exchange, pair = 'Bybit USDT Perpetual', 'BTC-USDT'
    key = jh.key(exchange, pair)
    array = np.array(rows, dtype=float)
    data = {key: dict(exchange=exchange, symbol=pair, candles=array[300:])}
    warmup = {key: dict(exchange=exchange, symbol=pair, candles=array[:300])}
    config = dict(starting_balance=600, fee=.00055, type='futures', futures_leverage=1,
                  futures_leverage_mode='isolated', exchange=exchange, warm_up_candles=50)
    update(reason='Jesse исполняет исторический тест')
    native = backtest(config, [dict(exchange=exchange, symbol=pair, timeframe='5m', strategy=LabEMA)],
                      [], candles=data, warmup_candles=warmup, generate_equity_curve=True)
    atomic(run_dir / 'native-result.json', native)
    m = native['metrics']
    return dict(count=m.get('total', 0), net=m.get('net_profit', 0 if m.get('total') == 0 else None),
                win_rate=m['win_rate']*100 if m.get('win_rate') is not None else None,
                profit_factor=m.get('profit_factor'),
                drawdown_pct=abs(m['max_drawdown']) if m.get('max_drawdown') is not None else None), native.get('trades', [])


async def hummingbot_async(run_dir, update):
    # Real native PaperTradeExchange consumes public books/trades. No authenticated connector.
    from decimal import Decimal
    from hummingbot.connector.exchange.paper_trade import create_paper_trade_market
    from hummingbot.core.clock import Clock, ClockMode
    from hummingbot.core.event.event_logger import EventLogger
    from hummingbot.core.event.events import MarketEvent
    from hummingbot.core.event.events import OrderBookEvent
    from hummingbot.strategy.market_trading_pair_tuple import MarketTradingPairTuple
    from hummingbot.strategy.pure_market_making import PureMarketMakingStrategy
    market = create_paper_trade_market('binance', ['BTC-USDT'])
    clock = Clock(ClockMode.REALTIME, 1)
    events = EventLogger(); market.add_listener(MarketEvent.OrderFilled, events)
    clock.add_iterator(market)
    with clock:
        begin = time.time()
        update(reason='Прогрев публичного стакана Binance', settings=dict(strategy='Pure Market Making',
            pair='BTC-USDT · Binance spot', mode='paper', duration=1200, bid_spread_pct=.1, ask_spread_pct=.1,
            assumptions='PAPER-исполнения Hummingbot; изменение оценки включает стоимость запаса BTC.'))
        while not market.ready:
            if time.time() - begin > 90:
                raise ValueError('Нет готового публичного стакана за 90 секунд')
            await clock.run_til(time.time() + 1)
        mid = market.get_mid_price('BTC-USDT')
        if not mid.is_finite() or mid <= 0:
            raise ValueError('Invalid mid price')
        market.set_balance('USDT', Decimal('300'))
        market.set_balance('BTC', Decimal('300') / mid)
        observed = [0.0]
        def public_trade(event):
            stamp = float(event.timestamp)
            if -1 <= time.time() - stamp <= 15:
                observed[0] = stamp
        from hummingbot.core.event.event_forwarder import EventForwarder
        listener = EventForwarder(public_trade)
        market.order_books['BTC-USDT'].add_listener(OrderBookEvent.TradeEvent, listener)
        strategy = PureMarketMakingStrategy()
        strategy.init_params(MarketTradingPairTuple(market, 'BTC-USDT', 'BTC', 'USDT'),
            bid_spread=Decimal('.001'), ask_spread=Decimal('.001'), order_amount=Decimal('100') / mid,
            order_refresh_time=15, filled_order_delay=15, inventory_skew_enabled=True,
            inventory_target_base_pct=Decimal('.5'), inventory_range_multiplier=Decimal('1'),
            hb_app_notification=False)
        clock.add_iterator(strategy)
        finish, last_good = time.time() + 1200, time.time()
        while time.time() < finish:
            await clock.run_til(time.time() + 2)
            quote = market.get_mid_price('BTC-USDT')
            if (not market.ready or not quote.is_finite() or quote <= 0 or
                    not observed[0] or time.time() - observed[0] > 15):
                if time.time() - last_good > 10:
                    raise ValueError('Публичный стакан потерян')
                continue
            last_good = time.time()
            equity = float(market.get_balance('USDT') + market.get_balance('BTC') * quote)
            fills = [dict(time=e.timestamp, side=e.trade_type.name, price=float(e.price),
                          amount=float(e.amount), fee=e.trade_fee.to_json()) for e in events.event_log]
            metrics = dict(fills=len(fills), equity=equity, net=equity-600,
                           turnover=sum(f['price']*f['amount'] for f in fills), valuation=True)
            update(reason='PAPER market making работает', metrics=metrics)
            atomic(run_dir / 'fills.json', fills)
        return metrics, fills


def probe(engine):
    if engine == 'freqtrade':
        from LabEMATest import LabEMATest
        from freqtrade import __version__
    elif engine == 'jesse':
        from jesse_strategy import LabEMA
        from jesse.version import __version__
        from jesse.research import backtest
    else:
        from hummingbot.connector.exchange.paper_trade import create_paper_trade_market
        from hummingbot.strategy.pure_market_making import PureMarketMakingStrategy
        try:
            __version__ = importlib.metadata.version('hummingbot')
        except importlib.metadata.PackageNotFoundError:
            __version__ = 'source environment'
    return dict(engine=engine, version=__version__, mode='paper' if engine == 'hummingbot' else 'backtest')


def main():
    p = argparse.ArgumentParser(); p.add_argument('engine', choices=ENGINES); p.add_argument('--probe', action='store_true')
    args = p.parse_args()
    if args.probe:
        print(json.dumps(probe(args.engine))); return
    root = ROOT / args.engine
    uid, started = str(uuid.uuid4()), time.time()
    directory = root / uid; directory.mkdir()
    os.chdir(directory)
    state = dict(id=uid, engine=args.engine, started=started, phase='running', reason='Запуск нативного движка', metrics=None)
    def update(**kwargs):
        state.update(kwargs, updated=time.time()); atomic(root / 'state.json', state)
    def cancelled(sig, _frame):
        raise KeyboardInterrupt('Тест остановлен пользователем')
    signal.signal(signal.SIGTERM, cancelled)
    try:
        update(version=probe(args.engine)['version'])
        if args.engine == 'hummingbot':
            metrics, trades = asyncio.run(hummingbot_async(directory, update))
        else:
            metrics, trades = globals()[args.engine](directory, update)
        atomic(directory / 'trades.json', trades)
        update(phase='completed', finished=time.time(), reason='Тест завершён', metrics=metrics)
    except KeyboardInterrupt:
        update(phase='cancelled', finished=time.time(), reason='Тест отменён; последняя оценка сохранена')
    except Exception as exc:
        update(phase='failed', finished=time.time(), reason=type(exc).__name__ + ': ' + str(exc)[:200])
    finally:
        atomic(directory / 'report.json', state)
        runs_path = root / 'runs.json'
        runs = json.loads(runs_path.read_text()) if runs_path.exists() else []
        runs.append(state); atomic(runs_path, runs[-100:])
        # Keep 100 bounded test runs. Delete only UUID directories owned by this worker.
        retained = {r['id'] for r in runs[-100:]}
        import shutil
        for d in root.iterdir():
            try:
                uuid.UUID(d.name)
            except ValueError:
                continue
            if d.is_dir() and not d.is_symlink() and d.name not in retained:
                shutil.rmtree(d)


if __name__ == '__main__':
    main()
