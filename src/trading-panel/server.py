import json
import time
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from market_data import MarketData
import control_client
import selection
from manual_paper import ManualPaper

ROOT = Path("/opt/trading-panel")
STATE = Path("/var/lib/trading-bot/state.json")
# The public ticker cache is warmed on the server, so opening a dashboard section
# never has to wait for another browser tab to have visited the screener first.
MARKET = MarketData(background=True)
MANUAL = ManualPaper(MARKET, background=True)
FILES = {
    "/fresh-alerts.js": ("fresh-alerts.js", "text/javascript; charset=utf-8"),
    "/alerts.css": ("alerts.css", "text/css; charset=utf-8"),
    "/positions.js": ("positions.js", "text/javascript; charset=utf-8"),
    "/positions.css": ("positions.css", "text/css; charset=utf-8"),
    "/models.js": ("models.js", "text/javascript; charset=utf-8"),
    "/models.css": ("models.css", "text/css; charset=utf-8"),
    "/ui.js": ("ui.js", "text/javascript; charset=utf-8"),
    "/layout.js": ("layout.js", "text/javascript; charset=utf-8"),
    "/layout.css": ("layout.css", "text/css; charset=utf-8"),
    "/screener.js": ("screener.js", "text/javascript; charset=utf-8"),
    "/screener.css": ("screener.css", "text/css; charset=utf-8"),
    "/model-status.js": ("model-status.js", "text/javascript; charset=utf-8"),
    "/api/research": ("/var/lib/trading-research/report.json", "application/json"),
    "/journal-c.csv": ("/var/lib/trading-research/journal-c.csv", "text/csv; charset=utf-8"),
    "/journal-d.csv": ("/var/lib/trading-research/journal-d.csv", "text/csv; charset=utf-8"),
    "/research.js": ("research.js", "text/javascript; charset=utf-8"),
    "/workspace.js": ("workspace.js", "text/javascript; charset=utf-8"),
    "/chart.html": ("chart.html", "text/html; charset=utf-8"),
    "/chart.js": ("chart.js", "text/javascript; charset=utf-8"),
    "/chart.css": ("chart.css", "text/css; charset=utf-8"),
    "/data-client.js": ("data-client.js", "text/javascript; charset=utf-8"),
    "/alerts.js": ("alerts.js", "text/javascript; charset=utf-8"),
    "/model-journals.js": ("model-journals.js", "text/javascript; charset=utf-8"),
    "/api/journal-a": ("/var/lib/trading-report/journal-a.json", "application/json"),
    "/api/journal-b": ("/var/lib/trading-report/journal-b.json", "application/json"),
    "/journal-a.csv": ("/var/lib/trading-report/journal-a.csv", "text/csv; charset=utf-8"),
    "/journal-b.csv": ("/var/lib/trading-report/journal-b.csv", "text/csv; charset=utf-8"),
    "/lab-report.js": ("lab-report.js", "text/javascript; charset=utf-8"),
    "/api/lab-report": ("/var/lib/trading-report/report.json", "application/json"),
    "/model-b.js": ("model-b.js", "text/javascript; charset=utf-8"),
    "/api/model-b": ("/var/lib/scalp-model-b/state.json", "application/json"),
    "/signals.js": ("signals.js", "text/javascript; charset=utf-8"),
    "/api/signals": ("/var/lib/trading-signals/signals.json", "application/json"),
    "/api/journal": ("/var/lib/scalp-paper/journal-report.json", "application/json"),
    "/paper.js": ("paper.js", "text/javascript; charset=utf-8"),
    "/api/paper": ("/var/lib/scalp-paper/state.json", "application/json"),
    "/live.js": ("live.js", "text/javascript; charset=utf-8"),
    "/api/live": ("/var/lib/trading-live/live.json", "application/json"),
    "/scalp.js": ("scalp.js", "text/javascript; charset=utf-8"),
    "/api/scalp": ("/var/lib/trading-scalp/scalp.json", "application/json"),
    "/scanner.js": ("scanner.js", "text/javascript; charset=utf-8"),
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if urlsplit(self.path).path == "/chart.html" else "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # Isolate the external widget from the authenticated dashboard.
        chart = urlsplit(self.path).path == "/chart.html"
        policy = (
            "default-src 'none'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "frame-src https://www.tradingview-widget.com https://s.tradingview.com; "
            "img-src 'self' data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
            if chart else
            "default-src 'self'; frame-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'; object-src 'none'"
        )
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(body)

    def api_error(self, code, message):
        self.send(code, json.dumps(dict(status='error', error=message), ensure_ascii=False).encode(),
                  'application/json; charset=utf-8')

    def do_GET(self):
        if self.headers.get("Host") not in (
            "127.0.0.1:8787", "localhost:8787"
        ):
            self.send(403, b"Invalid Host", "text/plain")
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/manual-paper":
                data = MANUAL.snapshot()
                data['token'] = control_client.TOKEN
                self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), 'application/json')
            elif path == "/api/engine-journal":
                query = parse_qs(urlsplit(self.path).query)
                if set(query) != {"engine"} or len(query["engine"]) != 1 or query["engine"][0] not in ("freqtrade", "hummingbot", "jesse"):
                    self.api_error(400, 'Invalid engine')
                    return
                data = control_client.call(dict(op="journal", engine=query["engine"][0]))
                self.send(200, data["csv"].encode(), "text/csv; charset=utf-8")
            elif path == "/api/models-control":
                try:
                    data = control_client.call(dict(op="status"))
                    data["token"] = control_client.TOKEN
                    self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), "application/json")
                except (OSError, ValueError):
                    self.send(503, b'{"status":"unavailable","error":"Model controller unavailable"}', "application/json")
            elif path in ('/api/market-selection', '/api/market-alerts'):
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if any(len(v) != 1 for v in query.values()) or set(query) - (set(selection.DEFAULT_FILTERS) | {'search', 'watch'}):
                    self.api_error(400, 'Некорректные параметры отбора')
                    return
                try:
                    filters = selection.parse_filters({k: v[0] for k, v in query.items() if k not in ('search', 'watch')})
                    method = MARKET.alerts_snapshot if path == '/api/market-alerts' else MARKET.selection_snapshot
                    data = method(filters, query.get('search', [''])[0], watch=query.get('watch', [''])[0])
                except ValueError as exc:
                    self.api_error(400, str(exc))
                    return
                self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), 'application/json')
            elif path in ("/api/screener", "/api/market-chart", "/api/market-book"):
                query = parse_qs(urlsplit(self.path).query)
                if any(len(v) != 1 for v in query.values()) or set(query) - {"symbol", "interval"}:
                    self.api_error(400, 'Invalid query')
                    return
                kind = {"/api/screener": "screener", "/api/market-chart": "chart", "/api/market-book": "book"}[path]
                try:
                    data = MARKET.get(kind, query.get("symbol", [""])[0], query.get("interval", ["5"])[0])
                except ValueError:
                    self.api_error(400, 'Invalid symbol or timeframe')
                    return
                self.send(200, json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), "application/json")
            elif path in ("/api/state", "/api/scanner"):
                source = STATE if path == "/api/state" else Path("/var/lib/trading-scanner/market.json")
                state = json.loads(source.read_text())
                state["server_time"] = time.time()
                self.send(
                    200, json.dumps(state, allow_nan=False).encode(),
                    "application/json"
                )
            elif path in FILES:
                name, content_type = FILES[path]
                self.send(200, (ROOT / name).read_bytes(), content_type)
            else:
                self.send(404, b"Not found", "text/plain")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            print(type(exc).__name__, str(exc), flush=True)
            if urlsplit(self.path).path.startswith('/api/'):
                self.api_error(503, 'Data source unavailable')
            else:
                self.send(503, b"State unavailable", "text/plain")

    def log_message(self, *args):
        pass

    def do_POST(self):
        if self.headers.get("Host") not in ("127.0.0.1:8787", "localhost:8787"):
            self.send(403, b'{"error":"Invalid Host"}', "application/json")
            return
        if self.path == '/api/worker':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                key = self.headers.get('X-Lab-Worker', '')
                if (not 0 < length <= 32768 or self.headers.get('Transfer-Encoding') or
                        self.headers.get('Content-Type') != 'application/json' or
                        not 32 <= len(key) <= 128 or not key.isascii() or
                        self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site')):
                    raise ValueError('Invalid worker request')
                payload = json.loads(self.rfile.read(length))
                result = control_client.call(dict(op='worker', key=key, payload=payload))
                self.send(200 if result.get('status') == 'ok' else 409,
                          json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), 'application/json')
            except (ValueError, TypeError):
                self.send(400, b'{"error":"Invalid worker request"}', 'application/json')
            except OSError:
                self.send(503, b'{"error":"Controller unavailable"}', 'application/json')
            return
        if self.path not in ("/api/models-control", "/api/manual-paper"):
            self.send(404, b'{"error":"Not found"}', "application/json")
            return
        if not control_client.authorized(self.headers):
            self.send(403, b'{"error":"Invalid control token or origin"}', "application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096 or self.headers.get("Transfer-Encoding"):
                raise ValueError("Invalid request size")
            command = json.loads(self.rfile.read(length))
            result = (MANUAL.command(command) if self.path == '/api/manual-paper' else
                      control_client.call(dict(op="command", command=command)))
            self.send(202 if result.get("status") == "accepted" else 409,
                      json.dumps(result, ensure_ascii=False, allow_nan=False).encode(), "application/json")
        except (ValueError, TypeError, OverflowError) as exc:
            if self.path == '/api/manual-paper':
                self.api_error(409, str(exc))
            else:
                self.send(400, b'{"error":"Invalid command"}', "application/json")
        except (OSError, sqlite3.Error):
            self.api_error(503, 'Хранилище или контроллер недоступны; повторите после обновления')


if __name__ == "__main__":
    print("Panel: http://127.0.0.1:8787", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
