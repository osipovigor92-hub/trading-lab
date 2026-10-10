"""Closed-candle calculations, stale-source safety and alert episode semantics."""
import copy
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trading-panel'))
import market_data
from market_alerts import MarketAlerts
import selection


def bars(closes=None, count=180):
    closes = closes or [100 + .05 * math.sin(index) for index in range(count)]
    return [dict(time=index * 60, open=close, high=close + .2, low=close - .2,
                 close=close, volume=20 if index >= len(closes)-5 else 10,
                 turnover=close * (20 if index >= len(closes)-5 else 10))
            for index, close in enumerate(closes)]


def packet(values=None):
    values = values or bars()
    stamp = values[-1]['time'] + 65
    return market_data.chart_analysis('BTCUSDT', '1', values, stamp)


def quote():
    return dict(symbol='BTCUSDT', price=100.5, turnover=100_000_000, spread=.02,
                change=1, range24=3, open_interest=1e6, funding=.0001, volume24=1000)


class IndicatorTests(unittest.TestCase):
    def test_known_wilder_rsi_and_sma_seeded_ema(self):
        known = [44.34,44.09,44.15,43.61,44.33,44.83,45.1,45.42,45.84,
                 46.08,45.89,46.03,45.61,46.28,46.28]
        values = bars(known + [46.28] * 45)
        data = packet(values)['indicators']
        self.assertAlmostEqual(data['rsi14'], 70.46413502109705)
        data = packet(bars([100] * 50 + [110] * 10))['indicators']
        self.assertAlmostEqual(data['ema20'], 100 + 10 * (1 - (19 / 21) ** 10))
        self.assertAlmostEqual(data['ema50'], 100 + 10 * (1 - (49 / 51) ** 10))
        self.assertEqual(data['rsi14'], 100)

    def test_wilder_atr_keeps_decaying_old_shock_legacy_atr_unchanged(self):
        values = bars([100] * 60)
        values[17]['high'] = 150
        data = packet(values)
        expected = .4 + (50.2 - .4) / 14 * (13 / 14) ** 42
        self.assertAlmostEqual(data['indicators']['atr14'], expected)
        self.assertAlmostEqual(data['atr'], .4, msg='legacy selection SMA remains unchanged')

    def test_exchange_vwap_and_base_quantity_rvol_exclude_forming_bar(self):
        values = bars([100] * 60)
        for bar in values[-5:]:
            bar['close'] = bar['open'] = 101
            bar['high'], bar['low'], bar['turnover'] = 101.2, 100.8, 2020
        data = packet(values)['indicators']
        self.assertEqual(data['rvol5'], 2)
        self.assertAlmostEqual(data['vwap60'], (55 * 1000 + 5 * 2020) / (55 * 10 + 5 * 20))
        current = dict(time=3600, open=101, high=120, low=100, close=119, volume=5000, turnover=595000)
        self.assertIsNone(market_data.candle_indicators(values + [current], '1', 3605))
        self.assertIsNone(market_data.candle_indicators(values[:-1], '1', 3605))
        for mutation in ('gap', 'nan', 'negative', 'short'):
            changed = copy.deepcopy(values)
            if mutation == 'gap': changed[20]['time'] += 60
            if mutation == 'nan': changed[20]['close'] = float('nan')
            if mutation == 'negative': changed[20]['volume'] = -1
            if mutation == 'short': changed = changed[-59:]
            self.assertIsNone(market_data.candle_indicators(changed, '1', 3605), mutation)

    def test_breakout_requires_first_closed_crossing_and_extension_guard(self):
        values = bars()
        values[-1].update(open=100.5, close=100.5, high=100.7, low=100.3, turnover=2010)
        chart = packet(values)
        stamp = chart['updated']
        result = selection.assistant(quote(), stamp, chart, stamp)
        self.assertEqual(result['setup'], 'breakout_up')
        self.assertTrue(result['eligible'])
        self.assertLessEqual(result['extension_atr'], 1.5)
        self.assertEqual(result['signal_id'], 'BTCUSDT:breakout_up:1:10800')
        self.assertEqual(sum(part['points'] for part in result['score_components']), result['score'])
        self.assertEqual(sum(part['max'] for part in result['score_components']), 100)
        values[-1].update(open=104, close=104, high=104.2, low=103.8, turnover=2080)
        result = selection.assistant(quote(), stamp, packet(values), stamp)
        self.assertEqual(result['setup'], 'watch')
        self.assertTrue(any('не догонять' in reason for reason in result['reasons']))
        values[-2].update(open=100.5, close=100.5, high=100.7, low=100.3, turnover=2010)
        values[-1].update(open=101, close=101, high=101.2, low=100.8, turnover=2020)
        self.assertFalse(packet(values)['indicators']['breakout_up'], 'continued breakout is not a first crossing')

    def test_missing_stale_error_wrong_symbol_never_produces_signal(self):
        chart = packet()
        stamp = chart['updated']
        for changes in ({'updated':stamp-76}, {'updated':stamp+3}, {'candle_end':stamp+1},
                        {'candle_end':stamp-121}, {'symbol':'ETHUSDT'}, {'interval':'5'},
                        {'refresh_error':'outage'}, {'indicators':None}):
            value = selection.assistant(quote(), stamp, dict(chart, **changes), stamp)
            self.assertEqual(value['status'], 'pending', str(changes))
            self.assertIsNone(value['score'])
            self.assertIsNone(value['signal_id'])
            self.assertEqual(value['indicators'], {})
        value = selection.assistant(quote(), stamp, chart, stamp, quote_available=False)
        self.assertEqual(value['status'], 'pending')
        zero = bars([100] * 60)
        for bar in zero: bar['volume'] = bar['turnover'] = 0
        chart = packet(zero)
        self.assertEqual(selection.assistant(quote(), chart['updated'], chart, chart['updated'])['status'], 'pending')

    def test_wide_spread_low_turnover_keep_measurements_but_no_setup(self):
        values = bars()
        values[-1].update(open=100.5, close=100.5, high=100.7, low=100.3, turnover=2010)
        chart = packet(values)
        for changes in ({'spread':.04}, {'turnover':19_999_999}):
            value = selection.assistant(dict(quote(), **changes), chart['updated'], chart, chart['updated'])
            self.assertEqual(value['status'], 'ok')
            self.assertFalse(value['eligible'])
            self.assertEqual(value['setup'], 'watch')

    def test_direction_is_separate_from_score_and_rsi_is_context(self):
        for direction in ('up', 'down'):
            values = bars([100+index if direction == 'up' else 300-index for index in range(180)])
            for bar in values:
                bar['high'] = bar['close'] + (2 if direction == 'up' else .2)
                bar['low'] = bar['close'] - (.2 if direction == 'up' else 2)
            chart = packet(values)
            value = selection.assistant(quote(), chart['updated'], chart, chart['updated'])
            self.assertEqual(value['setup'], 'momentum_' + direction)
            self.assertEqual(value['indicators']['rsi14'], 100 if direction == 'up' else 0)
            self.assertTrue(any('RSI у края' in reason for reason in value['reasons']))
            self.assertGreaterEqual(value['score'], 0)
            self.assertLessEqual(value['score'], 100)
        values = bars()
        values[-1].update(open=99.5, close=99.5, high=99.7, low=99.3, turnover=1990)
        chart = packet(values)
        value = selection.assistant(quote(), chart['updated'], chart, chart['updated'])
        self.assertEqual(value['setup'], 'breakout_down')

    def test_extension_guard_survives_the_next_real_closed_candle(self):
        values = bars()
        values[-1].update(open=104, close=104, high=104.2, low=103.8, turnover=2080)
        first = packet(values)
        value = selection.assistant(quote(), first['updated'], first, first['updated'])
        self.assertEqual(value['setup'], 'watch')
        original_level = value['breakout_level']
        values.append(dict(time=10800, open=104.1, close=104.1, high=104.3, low=103.9,
                           volume=20, turnover=2082))
        following = packet(values[-180:])
        value = selection.assistant(dict(quote(), price=104.1), following['updated'], following, following['updated'])
        self.assertFalse(following['indicators']['breakout_up'])
        self.assertEqual(value['breakout_level'], original_level)
        self.assertGreater(value['extension_atr'], 1.5)
        self.assertEqual(value['setup'], 'watch', 'a rolling range must not turn the extended move into momentum')
        self.assertTrue(any('не догонять' in reason for reason in value['reasons']))
        alerts = MarketAlerts()
        key = alerts.register(selection.parse_filters(), '', first['updated'])
        for chart in (first, following):
            now = chart['updated']
            alerts.update(key, dict(status='ok', updated=now, rows=[quote()]), {'BTCUSDT':chart}, {}, {}, now)
            self.assertEqual(alerts.snapshot(key, now)['cursor'], 0)

    def test_quiet_high_volume_has_no_momentum_setup_or_alert(self):
        values = bars([100+index*.0001 for index in range(180)])
        for bar in values:
            bar.update(high=bar['close']+.001, low=bar['close']-.001)
        chart = packet(values)
        now = chart['updated']
        value = selection.assistant(quote(), now, chart, now)
        self.assertEqual(value['trend'], 'up')
        self.assertEqual(value['activity'], 'quiet')
        self.assertEqual(value['indicators']['rvol5'], 2)
        self.assertEqual(value['setup'], 'watch')
        self.assertTrue(any('диапазон 5м≥0,2%' in reason for reason in value['reasons']))
        alerts = MarketAlerts()
        key = alerts.register(selection.parse_filters(), '', now)
        alerts.update(key, dict(status='ok', updated=now, rows=[quote()]), {'BTCUSDT':chart}, {}, {}, now)
        self.assertEqual(alerts.snapshot(key, now)['cursor'], 0)

    def test_assistant_alert_wrapper_filters_only_events_and_preserves_full_cursor(self):
        cache = market_data.MarketData()
        kinds = ('ready', 'almost', 'book_worse', 'cancelled', 'near_level',
                 'momentum_up', 'momentum_down', 'breakout_up', 'breakout_down')
        full = dict(status='ok', cursor=25, epoch='fixture', scope='fixture',
                    rows=[{'symbol':'BTCUSDT'}], events=[dict(id=str(index), kind=kind) for index, kind in enumerate(kinds)])
        try:
            with patch.object(cache, 'alerts_snapshot', return_value=full) as snapshot:
                packet = cache.assistant_alerts_snapshot(search='BTC', watch='BTCUSDT')
                self.assertEqual(packet['cursor'], full['cursor'])
                self.assertEqual(packet['rows'], full['rows'])
                self.assertEqual([event['kind'] for event in packet['events']], list(kinds[4:]))
                self.assertEqual(len(full['events']), 9, 'shared legacy snapshot is unchanged')
                self.assertEqual(snapshot.call_args.kwargs['priority'], 'activity')
        finally:
            cache.close()

    def test_activity_shortlist_wrappers_preserve_watch_budget_and_legacy_order(self):
        stamp = packet()['updated']
        rows = [dict(quote(), symbol='COIN' + str(index) + 'USDT',
                     turnover=100_000_000-index, change=index/2, range24=1+index/4)
                for index in range(15)]
        rows.append(dict(quote(), symbol='QUIETUSDT', turnover=200_000_000, change=0, range24=1))
        rows.append(dict(quote(), symbol='WIDEUSDT', spread=.5, change=20, range24=30))
        filters = selection.parse_filters()
        legacy = selection.shortlist(rows, stamp, filters, '', [], stamp)
        active = selection.assistant_shortlist(rows, stamp, filters, '', ['COIN0USDT'], stamp)
        self.assertEqual(legacy[0], 'COIN0USDT')
        self.assertEqual(active[0], 'COIN0USDT')
        self.assertEqual(active[1], 'COIN14USDT')
        self.assertEqual(len(active), 8)
        self.assertNotIn('WIDEUSDT', active)
        cache = market_data.MarketData()
        try:
            with patch.object(cache, 'get', return_value=dict(status='ok', updated=stamp, rows=rows)) as get:
                result = cache.assistant_snapshot(now=stamp, watch='COIN0USDT')
                self.assertEqual(result['analyzing'], active)
                self.assertEqual(result['priority'], 'activity')
                get.assert_called_once_with('screener')
                self.assertEqual(len(cache.entries), 0, 'snapshot never schedules per-row REST')
                cache.entries[('screener', '', '')] = dict(data=dict(status='ok', updated=stamp, rows=rows),
                                                          error='', future=None, until=999999)
                events = cache.assistant_alerts_snapshot(now=stamp, watch='COIN0USDT')
                self.assertEqual(events['priority'], 'activity')
                self.assertEqual(events['analyzing'], active)
            self.assertEqual(len(cache.entries), 1, 'no chart or book jobs added by a snapshot')
        finally:
            cache.close()

    def test_selection_attaches_assistant_and_failed_cache_refresh_blocks_only_new_signal(self):
        chart = packet()
        stamp = chart['updated']
        tickers = dict(status='ok', updated=stamp, rows=[quote()])
        cache = market_data.MarketData()
        cache.entries[('chart', 'BTCUSDT', '1')] = dict(data=chart, error='', future=None, until=999999)
        try:
            with patch.object(cache, 'get', return_value=tickers):
                result = cache.selection_snapshot(now=stamp)
                self.assertEqual(result['rows'][0]['assistant']['status'], 'ok')
                self.assertEqual(result['rows'][0]['selection']['status'], 'pending', 'no book is needed by assistant')
                cache.entries[('chart', 'BTCUSDT', '1')]['error'] = 'outage'
                self.assertEqual(cache.selection_snapshot(now=stamp)['rows'][0]['assistant']['status'], 'pending')
        finally:
            cache.close()


class AssistantAlertTests(unittest.TestCase):
    def setUp(self):
        self.alerts = MarketAlerts()
        self.filters = selection.parse_filters()
        self.values = bars()
        self.values[-1].update(open=100.5, close=100.5, high=100.7, low=100.3, turnover=2010)
        self.chart = packet(self.values)
        self.now = self.chart['updated']
        self.key = self.alerts.register(self.filters, '', self.now)
        self.tickers = dict(status='ok', updated=self.now, rows=[quote()])

    def update(self, chart=None, now=None):
        self.alerts.update(self.key, self.tickers, {'BTCUSDT':chart or self.chart}, {}, {}, self.now if now is None else now)
        return self.alerts.snapshot(self.key, self.now if now is None else now)

    def test_breakout_without_book_repeated_polls_and_outage_do_not_repeat(self):
        result = self.update()
        event = result['events'][0]
        self.assertEqual(event['kind'], 'breakout_up')
        self.assertEqual(set(event['sources']), {'quote', 'chart', 'candle'})
        self.assertEqual(event['timeframe'], '1')
        self.assertEqual(event['candle_end'], 10800)
        self.assertEqual(event['expires'], self.now + 30)
        for index in range(1, 5):
            self.assertEqual(self.update(now=self.now+index)['cursor'], 1)
        self.assertEqual(self.update(dict(self.chart, refresh_error='outage'))['events'], [])
        self.assertEqual(self.update()['cursor'], 1)
        self.assertEqual(self.update(now=self.now+31)['events'], [])
        archived = self.alerts.scopes[self.key]['events'][0]
        self.assertEqual(archived['time'], self.now, 'freshness never rewrites the original event time')

    def test_momentum_continuation_new_candle_and_stale_gap_keep_episode(self):
        chart = copy.deepcopy(self.chart)
        chart['indicators'].update(breakout_up=False, breakout_down=False)
        self.assertEqual(self.update(chart)['events'][0]['kind'], 'momentum_up')
        self.update(dict(chart, refresh_error='outage'))
        self.assertEqual(self.update(chart)['cursor'], 1)
        # A refreshed packet on a later closed candle remains the same momentum episode.
        self.now += 60
        self.tickers['updated'] = self.now
        chart.update(updated=self.now, candle_end=chart['candle_end']+60)
        chart['indicators']['window_end'] += 60
        self.assertEqual(self.update(chart)['cursor'], 1)
        self.assertEqual(self.update(chart)['events'], [])

    def test_partial_chart_and_source_rollback_do_not_restart_episode(self):
        self.assertEqual(self.update()['cursor'], 1)
        self.assertEqual(self.update(dict(self.chart, indicators=None))['events'], [])
        self.assertEqual(self.update()['cursor'], 1)
        old = dict(self.chart, updated=self.now-1)
        self.assertEqual(self.update(old)['events'], [])
        self.assertEqual(self.update()['cursor'], 1)

    def test_breakout_is_inside_a_continuing_momentum_episode(self):
        momentum = copy.deepcopy(self.chart)
        momentum['indicators'].update(breakout_up=False, breakout_down=False)
        self.assertEqual(self.update(momentum)['events'][0]['kind'], 'momentum_up')
        self.assertEqual(self.update(self.chart)['cursor'], 2, 'the breakout may emit its own observation')
        # Continuing momentum on a new closed candle does not start a new episode.
        self.now += 60
        self.tickers['updated'] = self.now
        momentum.update(updated=self.now, candle_end=momentum['candle_end']+60)
        momentum['indicators']['window_end'] += 60
        self.assertEqual(self.update(momentum)['cursor'], 2)


if __name__ == '__main__':
    unittest.main()
