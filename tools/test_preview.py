import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
import preview

class PreviewTests(unittest.TestCase):
    def test_routes_and_source_isolation(self):
        try:
            server=preview.ThreadingHTTPServer(('127.0.0.1',0),preview.Handler)
        except PermissionError:
            self.skipTest('Local sockets unavailable; this check runs in GitHub Actions')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/') as r:
                self.assertIn('СИНТЕТИЧЕСКИЕ ДАННЫЕ',r.read().decode())
            for route in preview.fixtures():
                with urlopen(base+route) as r:
                    self.assertIsInstance(json.load(r),dict)
            with urlopen(base+'/journal-a.csv') as r:
                self.assertIn('DEMOUSDT',r.read().decode('utf-8-sig'))
            for path in ('/server.py','/../requirements-dev.txt','/api/unknown'):
                with self.assertRaises(HTTPError) as caught:
                    urlopen(base+path)
                self.assertEqual(caught.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__': unittest.main()
