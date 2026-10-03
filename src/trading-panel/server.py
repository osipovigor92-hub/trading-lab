import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from market_data import MarketData

ROOT = Path("/opt/trading-panel")
STATE = Path("/var/lib/trading-bot/state.json")
MARKET = MarketData()
FILES = {
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

    def do_GET(self):
        if self.headers.get("Host") not in (
            "127.0.0.1:8787", "localhost:8787"
        ):
            self.send(403, b"Invalid Host", "text/plain")
            return
        path = urlsplit(self.path).path
        try:
            if path in ("/api/screener", "/api/market-chart", "/api/market-book"):
                query = parse_qs(urlsplit(self.path).query)
                if any(len(v) != 1 for v in query.values()) or set(query) - {"symbol", "interval"}:
                    self.send(400, b"Invalid query", "text/plain")
                    return
                kind = {"/api/screener": "screener", "/api/market-chart": "chart", "/api/market-book": "book"}[path]
                try:
                    data = MARKET.get(kind, query.get("symbol", [""])[0], query.get("interval", ["5"])[0])
                except ValueError:
                    self.send(400, b"Invalid symbol or timeframe", "text/plain")
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
            self.send(503, b"State unavailable", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Panel: http://127.0.0.1:8787", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
