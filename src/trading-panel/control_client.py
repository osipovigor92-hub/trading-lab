"""HTTP-to-local-broker transport. The dashboard receives no shell or root privileges."""
import hmac
import json
import secrets
import socket

SOCKET = '/run/trading-control/control.sock'
TOKEN = secrets.token_urlsafe(32)


def authorized(headers):
    token = headers.get('X-Lab-Control', '')
    return (headers.get('Content-Type', '').split(';')[0].strip().lower() == 'application/json'
            and headers.get('Sec-Fetch-Site', 'same-origin') in ('same-origin', 'none')
            and headers.get('Origin') != 'null'
            and isinstance(token, str) and token.isascii() and hmac.compare_digest(token, TOKEN))


def call(request):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(SOCKET)
        connection.sendall(json.dumps(request, allow_nan=False).encode() + b'\n')
        with connection.makefile('rb') as f:
            raw = f.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or not raw.endswith(b'\n'):
            raise ValueError('Invalid controller response')
        return json.loads(raw)
