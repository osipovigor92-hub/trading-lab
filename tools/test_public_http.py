"""Production handler query contracts, without network or a listening socket."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
import market_data
import manual_paper
import exchange_data
import densities


class PublicHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = Mock()
        cls.monitor = Mock()
        for method in ('exchange_snapshot', 'chart_snapshot'):
            getattr(cls.adapter, method).return_value = {'status': 'pending', 'exchange': 'bybit'}
        cls.monitor.request.return_value = {'status': 'pending', 'rows': [], 'history': []}
        spec = importlib.util.spec_from_file_location('public_query_panel', Path(__file__).resolve().parents[1]/'src/trading-panel/server.py')
        cls.panel = importlib.util.module_from_spec(spec)
        with patch.object(market_data, 'MarketData', return_value=SimpleNamespace()), patch.object(manual_paper, 'ManualPaper', return_value=SimpleNamespace()), patch.object(exchange_data, 'get_exchange_data', return_value=cls.adapter), patch.object(densities, 'DensityMonitor', return_value=cls.monitor) as create:
            spec.loader.exec_module(cls.panel)
            create.assert_called_once_with(cls.adapter, background=False)

    def request(self, path, host='127.0.0.1:8787'):
        class Capture(self.panel.Handler):
            def send(self, code, body, content_type):
                self.result = (code, body, content_type)
        handler = Capture.__new__(Capture)
        handler.headers = {'Host': host}
        handler.path = path
        handler.do_GET()
        return handler.result

    def test_density_filters_dispatch_exact_strings_without_refresh_parameter(self):
        self.assertEqual(self.request('/api/densities?exchanges=bybit,okx&symbols=BTCUSDT&watch=okx%3ABTCUSDT')[0], 200)
        self.monitor.request.assert_called_with(exchanges='bybit,okx', symbols='BTCUSDT', watch='okx:BTCUSDT')
        self.assertEqual(self.request('/api/densities?exchanges=bybit&refresh=1')[0], 400)

    def test_exchange_identity_and_interval_are_forwarded(self):
        self.assertEqual(self.request('/api/exchange-screener?exchange=gate')[0], 200)
        self.adapter.exchange_snapshot.assert_called_with('gate')
        for interval in ('1', '5', '15', '60', '240', '1440'):
            with self.subTest(interval=interval):
                self.assertEqual(self.request('/api/exchange-chart?exchange=okx&symbol=BTCUSDT&interval='+interval)[0], 200)
                self.adapter.chart_snapshot.assert_called_with('okx', 'BTCUSDT', interval)

    def test_duplicate_unknown_oversize_queries_and_invalid_host_are_rejected(self):
        for path in ('/api/densities?watch=A&watch=B', '/api/exchange-chart?exchange=bybit&unknown=x', '/api/exchange-screener?symbol=BTCUSDT', '/api/densities?symbols='+'A'*3001):
            self.assertEqual(self.request(path)[0], 400, path[:80])
        self.assertEqual(self.request('/api/densities', host='example.com')[0], 403)

    def test_adapter_validation_returns400_without_leaking_error_as_success(self):
        self.adapter.chart_snapshot.side_effect = ValueError('unsupported interval')
        try:
            code, body, _ = self.request('/api/exchange-chart?symbol=BTCUSDT&interval=7')
            self.assertEqual(code, 400)
            self.assertEqual(json.loads(body)['status'], 'error')
        finally:
            self.adapter.chart_snapshot.side_effect = None


if __name__ == '__main__':
    unittest.main()
