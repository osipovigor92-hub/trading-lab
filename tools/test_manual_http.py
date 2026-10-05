import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trading-panel'))
import market_data
import manual_paper
from test_manual_paper import Market, plan


class ManualHTTPTests(unittest.TestCase):
    def test_token_origin_size_and_idempotent_real_http(self):
        with tempfile.TemporaryDirectory() as folder:
            market = Market();market.now = time.time()
            original = market.get
            def feed(kind, symbol='', interval='5'):
                value = original(kind, symbol, interval)
                if kind == 'screener':
                    value['rows'][0]['next_funding'] = market.now+3600
                return value
            market.get = feed
            engine = manual_paper.ManualPaper(market, folder, clock=lambda:market.now)
            spec = importlib.util.spec_from_file_location('manual_http_server', Path(__file__).resolve().parents[1]/'src/trading-panel/server.py')
            module = importlib.util.module_from_spec(spec)
            with patch.object(market_data, 'MarketData', return_value=market), patch.object(manual_paper, 'ManualPaper', return_value=engine):
                spec.loader.exec_module(module)
            try:
                server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
            except PermissionError:
                self.skipTest('Local sockets unavailable; runs in CI')
            thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            headers = {'Host':'127.0.0.1:8787', 'Content-Type':'application/json', 'X-Lab-Control':module.control_client.TOKEN, 'Sec-Fetch-Site':'same-origin'}
            p = plan();p['stamp'] = market.now
            command = dict(id='real-http-open-123', action='open', generation=0, plan=p)
            def request(value, h=None):
                return urlopen(Request(base+'/api/manual-paper', data=json.dumps(value).encode(), headers=h or headers), timeout=3)
            try:
                for change in ({'X-Lab-Control':'invalid'}, {'Sec-Fetch-Site':'cross-site'}, {'Origin':'null'}, {'Content-Type':'text/plain'}, {'Host':'attacker.invalid'}):
                    with self.assertRaises(HTTPError) as error:
                        request(command, dict(headers, **change))
                    self.assertEqual(error.exception.code, 403)
                self.assertIsNone(engine.snapshot()['position'])
                with request(command) as response:
                    self.assertEqual(response.status, 202)
                    first = json.load(response)
                with request(command) as response:
                    self.assertEqual(json.load(response), first)
                with self.assertRaises(HTTPError) as error:
                    request(dict(command, id='new-open-http-123', generation=1))
                self.assertEqual(error.exception.code, 409)
                with self.assertRaises(HTTPError):
                    request(dict(command, id='x'*5000))
                with urlopen(Request(base+'/api/manual-paper', headers={'Host':'127.0.0.1:8787'})) as response:
                    snapshot = json.load(response)
                    self.assertEqual(snapshot['position']['id'], command['id'])
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                    self.assertNotIn('unsafe-eval', response.headers['Content-Security-Policy'])
            finally:
                server.shutdown();server.server_close();thread.join()
