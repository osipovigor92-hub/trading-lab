import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from test_candidate_journal import journal,Market,ManualPaper
from test_market_alerts import evidence
import market_data
import manual_paper
import selection


class JournalHTTPTests(unittest.TestCase):
    def test_real_read_only_pages_csv_validation_unavailable_and_host_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            now=time.time();store=journal.CandidateJournal(folder)
            store.cycle(**evidence(now),scopes=[(selection.DEFAULT_FILTERS,'')],now=now)
            paper=ManualPaper(Market(),folder)
            spec=importlib.util.spec_from_file_location('journal_http_server',Path(__file__).resolve().parents[1]/'src/trading-panel/server.py')
            module=importlib.util.module_from_spec(spec)
            with patch.object(journal,'CandidateJournal',return_value=store),patch.object(market_data,'MarketData',return_value=Market()),patch.object(manual_paper,'ManualPaper',return_value=paper):spec.loader.exec_module(module)
            try:server=module.ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
            except PermissionError:self.skipTest('Local sockets unavailable; runs in CI')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}';headers={'Host':'127.0.0.1:8787'}
            def get(path):return urlopen(Request(base+path,headers=headers),timeout=3)
            original_store=store.path.read_bytes();original_paper=paper.path.read_bytes()
            try:
                with get('/api/candidate-journal?period=all&limit=1') as response:
                    packet=json.load(response);self.assertEqual(packet['total'],1)
                    self.assertEqual(response.headers['Cache-Control'],'no-store');self.assertNotIn('unsafe-eval',response.headers['Content-Security-Policy'])
                with get('/candidate-journal.csv?limit=1') as response:self.assertIn('evidence_json',response.read().decode('utf-8-sig'))
                with get('/api/manual-journal?limit=1') as response:self.assertEqual(json.load(response)['total'],0)
                with get('/manual-journal.csv') as response:self.assertIn('exit_reason',response.read().decode('utf-8-sig'))
                for path in ('/api/candidate-journal?limit=100','/api/candidate-journal?search=BTC%25','/api/candidate-journal?status=all&status=passed','/api/manual-journal?search=BTC','/candidate-journal.csv?bad=1'):
                    with self.assertRaises(HTTPError) as err:get(path)
                    self.assertEqual(err.exception.code,400)
                with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/candidate-journal',headers={'Host':'bad.invalid'}))
                self.assertEqual(err.exception.code,403)
                with self.assertRaises(HTTPError) as err:urlopen(Request(base+'/api/candidate-journal',data=b'{}',headers=headers))
                self.assertEqual(err.exception.code,404)
                store.installed=False
                with get('/api/candidate-journal') as response:self.assertEqual(json.load(response)['status'],'unavailable')
                with self.assertRaises(HTTPError) as err:get('/candidate-journal.csv')
                self.assertEqual(err.exception.code,503)
                self.assertEqual(store.path.read_bytes(),original_store);self.assertEqual(paper.path.read_bytes(),original_paper)
            finally:server.shutdown();server.server_close();thread.join()
