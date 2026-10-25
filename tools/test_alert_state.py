import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_market_alerts import evidence
from market_alerts import MarketAlerts
from market_data import MarketData
import alert_state
import selection


class AlertStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'alerts.json'
        self.monitor = MarketAlerts(self.path)
        self.key = self.monitor.register(selection.parse_filters(), '', 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self, monitor, now, **changes):
        monitor.update(self.key, **evidence(now, **changes), now=now)
        return monitor.snapshot(self.key, now)

    def test_restart_does_not_replay_events_and_fresh_cancel_rearms(self):
        first = self.tick(self.monitor, 1000)
        self.assertTrue(first['events'])
        monitor = MarketAlerts(self.path)
        restored = monitor.snapshot(self.key, 1001)
        self.assertEqual(restored['events'], [])
        self.assertEqual(restored['rows'], [])
        self.assertEqual(restored['epoch'], first['epoch'])
        self.assertEqual(restored['cursor'], first['cursor'])
        same = self.tick(monitor, 1002)
        self.assertEqual(same['cursor'], first['cursor'])
        self.assertEqual(same['events'], [])
        bad = self.tick(monitor, 1004, depth=3000)
        self.assertIn('cancelled', [e['kind'] for e in bad['events']])
        again = self.tick(monitor, 1006)
        self.assertIn('ready', [e['kind'] for e in again['events']])
        self.assertEqual(again['persistence']['status'], 'durable')

    def test_gap_after_restart_is_not_rearm_and_unchanged_tick_does_not_write(self):
        first = self.tick(self.monitor, 1000)
        monitor = MarketAlerts(self.path)
        monitor.update(self.key, **evidence(1000), now=1100)  # expired proof
        with patch.object(alert_state, 'write') as write:
            fresh = self.tick(monitor, 1102)
            self.assertEqual(fresh['cursor'], first['cursor'])
            write.assert_not_called()

    def test_last_scope_stays_active_and_warms_saved_watch_without_browser(self):
        watch_key = self.monitor.register(selection.parse_filters(), 'SOL', 1001, 'SOLUSDT', 'activity')
        monitor = MarketAlerts(self.path)
        self.assertEqual([row[0] for row in monitor.active(5000)], [watch_key])
        cache = MarketData(clock=lambda:100, alert_state_path=self.path)
        try:
            with patch.object(cache, 'selection_snapshot') as snapshot:
                cache._selection_tick()
                snapshot.assert_called_once_with(filters=selection.parse_filters(), search='SOL', watch='SOLUSDT', priority='activity')
        finally:cache.close()

    def test_write_failure_is_visible_retries_and_preserves_previous_file(self):
        before = self.path.read_text()
        with patch.object(alert_state.os, 'replace', side_effect=OSError('disk full')):
            packet = self.tick(self.monitor, 1000)
        self.assertEqual(packet['persistence']['status'], 'error')
        self.assertEqual(self.path.read_text(), before)
        packet = self.tick(self.monitor, 1002)
        self.assertEqual(packet['persistence']['status'], 'durable')
        self.assertEqual(list(self.path.parent.glob('.alerts-*')), [])

    def test_corrupt_store_is_reported_and_not_overwritten(self):
        for content in ('{bad', json.dumps({'version':1}), json.dumps([])):
            self.path.write_text(content)
            monitor = MarketAlerts(self.path)
            self.assertEqual(monitor.persistence()['status'], 'error')
            monitor.register(selection.parse_filters(), '', 1000)
            self.assertEqual(self.path.read_text(), content)
            self.assertFalse(monitor.scopes[self.key]['states'])

    def test_assistant_episode_survives_without_current_proof(self):
        edge = dict(setup='momentum_up', momentum_episode='up',last_breakout='BTCUSDT:breakout_up:1:960',
                    last_momentum='BTCUSDT:momentum_up:1:900', sources={},current=None)
        self.monitor.scopes[self.key]['assistant_states']['BTCUSDT'] = edge
        self.monitor._save()
        monitor = MarketAlerts(self.path)
        self.assertEqual(monitor.scopes[self.key]['assistant_states']['BTCUSDT'], edge)

    def test_real_breakout_and_momentum_do_not_repeat_after_restart(self):
        from test_assistant_signals import bars, packet, quote
        for breakout in (True, False):
            with self.subTest(breakout=breakout):
                path = self.path.with_name(str(breakout)+'.json')
                monitor = MarketAlerts(path)
                values = bars()
                values[-1].update(open=100.5, close=100.5, high=100.7, low=100.3, turnover=2010)
                chart = packet(values)
                if not breakout:chart['indicators'].update(breakout_up=False, breakout_down=False)
                now = chart['updated']
                key = monitor.register(selection.parse_filters(), '', now)
                tickers = dict(status='ok',updated=now,rows=[quote()])
                monitor.update(key,tickers,{'BTCUSDT':chart},{},{},now)
                first = monitor.snapshot(key,now)
                self.assertEqual(first['events'][0]['kind'],'breakout_up' if breakout else 'momentum_up')
                monitor = MarketAlerts(path)
                monitor.update(key,tickers,{'BTCUSDT':chart},{},{},now+1)
                self.assertEqual(monitor.snapshot(key,now+1)['cursor'], first['cursor'])
                self.assertEqual(monitor.snapshot(key,now+1)['events'], [])
