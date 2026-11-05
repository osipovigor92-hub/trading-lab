"""Local public-data assistant, without PAPER or real-order execution.

Kronos is optional and runs in its own process. This server imports only its
stdlib client; read-only forecast polling cannot start market or model jobs.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urlsplit

PANEL = Path(__file__).resolve().parents[1] / 'src/trading-panel'
sys.path.insert(0, str(PANEL))
from exchange_data import ExchangeData
from densities import DensityMonitor
from market_data import MarketData
from kronos_client import KronosClient, response

CSP = "default-src 'self'; frame-src 'self'; frame-ancestors 'none'; connect-src 'self' wss://stream.bybit.com wss://fstream.binance.com wss://ws.okx.com wss://fx-ws.gateio.ws wss://ws.bitget.com; base-uri 'none'; form-action 'none'; object-src 'none'"


class PublicHTTPServer(ThreadingHTTPServer):
    request_queue_size = 64


def build_handler(exchange, density, market, kronos, port):
    token = secrets.token_urlsafe(32)
    files = {p.name: p for p in PANEL.iterdir() if p.suffix in ('.html', '.js', '.css')}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def send(self, code, data, content_type='application/json; charset=utf-8'):
            body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(code)
            for key, value in [('Content-Type', content_type), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'), ('Content-Security-Policy', CSP), ('X-Content-Type-Options', 'nosniff')]:
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

        def do_GET(self):
            if not self.host():
                self.send(403, dict(status='error', error='Invalid Host'));return
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if len(parsed.query) > 3000 or any(len(v) != 1 for v in query.values()):
                self.send(400, dict(status='error', error='Invalid query'));return
            args = {k: v[0] for k, v in query.items()}
            try:
                if parsed.path == '/api/kronos/status':
                    if args: raise ValueError('Invalid Kronos query')
                    data = dict(kronos.status(), token=token)
                elif parsed.path == '/api/kronos/forecast':
                    if set(args) != {'exchange', 'symbol', 'interval'}: raise ValueError('Invalid Kronos source')
                    packet = exchange.peek_chart_snapshot(*(args[k] for k in ('exchange', 'symbol', 'interval')))
                    if packet.get('status') == 'ok':
                        data = kronos.snapshot(packet)
                    elif packet.get('status') == 'error':
                        data = response('error', enabled=True, error=packet.get('error') or 'Источник свечей недоступен')
                    else:
                        data = response('pending', enabled=True, error='Ожидаем проверенные свечи')
                elif parsed.path == '/api/exchange-screener':
                    if set(args) - {'exchange'}: raise ValueError('Invalid catalog query')
                    data = exchange.exchange_snapshot(args.get('exchange', 'bybit'))
                elif parsed.path == '/api/exchange-chart':
                    if set(args) != {'exchange', 'symbol', 'interval'}: raise ValueError('Invalid chart source')
                    data = exchange.chart_snapshot(*(args[k] for k in ('exchange', 'symbol', 'interval')))
                elif parsed.path == '/api/densities':
                    if set(args) - {'exchanges', 'symbols', 'watch'}: raise ValueError('Invalid density query')
                    data = density.request(**args)
                elif parsed.path in ('/api/screener', '/api/market-chart', '/api/market-book'):
                    if set(args) - {'symbol', 'interval'}: raise ValueError('Invalid market query')
                    data = market.get({'/api/screener':'screener', '/api/market-chart':'chart', '/api/market-book':'book'}[parsed.path], args.get('symbol', ''), args.get('interval', '5'))
                elif parsed.path in ('/api/market-selection', '/api/market-alerts'):
                    import selection
                    if set(args) - (set(selection.DEFAULT_FILTERS) | {'search', 'watch'}): raise ValueError('Invalid selection query')
                    filters = selection.parse_filters({k:v for k,v in args.items() if k not in ('search', 'watch')})
                    method = market.assistant_snapshot if parsed.path == '/api/market-selection' else market.assistant_alerts_snapshot
                    data = method(filters, args.get('search', ''), watch=args.get('watch', ''))
                elif parsed.path == '/api/manual-paper':
                    data = dict(status='unavailable', updated=time.time(), error='Ручной PAPER выключен в локальном публичном режиме', token=token)
                else:
                    name = 'index.html' if parsed.path == '/' else parsed.path[1:]
                    if name not in files:
                        self.send(404, dict(status='error', error='Not found'));return
                    self.send(200, files[name].read_bytes(), {'.html':'text/html', '.js':'text/javascript', '.css':'text/css'}[files[name].suffix]+'; charset=utf-8');return
                self.send(200, data)
            except (ValueError, TypeError):
                self.send(400, dict(status='error', error='Некорректные параметры публичных данных'))
            except (OSError, KeyError):
                self.send(503, dict(status='unavailable', error='Публичный источник недоступен'))

        def do_POST(self):
            if not self.host() or self.path != '/api/kronos/forecast':
                self.send(403, dict(status='error', error='Доступен только расчёт Kronos'));return
            given = self.headers.get('X-Lab-Control', '')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none') or self.headers.get('Origin') == 'null' or not given.isascii() or not hmac.compare_digest(given, token):
                self.send(403, dict(status='error', error='Invalid control token or origin'));return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'): raise ValueError('Invalid size')
                args = json.loads(self.rfile.read(length))
                if not isinstance(args, dict) or set(args) != {'exchange', 'symbol', 'interval'}: raise ValueError('Invalid source')
                state = kronos.status()
                if state.get('enabled'):
                    packet = exchange.chart_snapshot(*(args[k] for k in ('exchange', 'symbol', 'interval')))
                    if packet.get('status') == 'ok':
                        data = kronos.request(packet)
                    elif packet.get('queued') is True:
                        data = response('pending', enabled=True, error='Загружаем проверенные свечи')
                    else:
                        data = response('error', enabled=True, error=packet.get('error') or 'Очередь свечей занята. Повторите отбор.')
                else:
                    data = state
                self.send(202, data)
            except (ValueError, TypeError):
                self.send(400, dict(status='error', error='Invalid Kronos request'))

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8789)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535: parser.error('Use a local nonprivileged port')
    exchange, market = ExchangeData(), MarketData(background=True)
    density = DensityMonitor(exchange, background=True)
    server = PublicHTTPServer(('127.0.0.1', args.port), build_handler(exchange, density, market, KronosClient(), args.port))
    print(f'Public assistant: http://127.0.0.1:{args.port} · no order execution', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close();density.close();exchange.close();market.close()


if __name__ == '__main__':
    main()
