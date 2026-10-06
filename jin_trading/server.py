"""Authenticated, mobile control surface for the shared PAPER ledger."""
import argparse
import csv
import hmac
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jin_trading.store import Store
from jin_trading.worker import Worker, load_config


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Avoid recording tokens and query strings.
        pass

    def send(self, status, value, content_type='application/json'):
        data = value if isinstance(value, bytes) else json.dumps(value, default=str, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        supplied = self.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied, 'Bearer ' + self.server.token):
            self.send(401, {'error': 'Anmeldung erforderlich'})
            return False
        return True

    def do_GET(self):
        assets = {'/': ('dashboard.html', 'text/html; charset=utf-8'),
                  '/dashboard.js': ('dashboard.js', 'application/javascript'),
                  '/dashboard.css': ('dashboard.css', 'text/css')}
        if self.path in assets:
            name, mime = assets[self.path]
            self.send(200, Path(__file__).with_name(name).read_bytes(), mime)
            return
        if not self.authorized():
            return
        if self.path == '/api/state':
            self.send(200, self.server.store.snapshot())
        elif self.path == '/api/trades.csv':
            out = io.StringIO()
            fields = ['id', 'bot', 'timestamp', 'input', 'output', 'route']
            writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in self.server.store.snapshot()['trades']:
                # IDs are controlled by config, nevertheless prevent spreadsheet formula injection.
                writer.writerow({k: "'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v
                                 for k, v in row.items()})
            self.send(200, out.getvalue().encode(), 'text/csv; charset=utf-8')
        else:
            self.send(404, {'error': 'Unbekannter Pfad'})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length != 0:
                raise ValueError('This API accepts no request body')
            if self.path == '/api/halt':
                self.server.store.emergency()
            elif self.path == '/api/reset':
                self.server.store.reset()
            else:
                parts = self.path.split('/')
                if len(parts) != 5 or parts[1:3] != ['api', 'bots'] or parts[4] not in ('start', 'stop'):
                    self.send(404, {'error': 'Unbekannte Aktion'})
                    return
                self.server.store.control(parts[3], parts[4] == 'start')
            self.send(200, self.server.store.snapshot())
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})


def make_server(store, token, host='127.0.0.1', port=8787):
    if len(token) < 24:
        raise ValueError('JIN_DASHBOARD_TOKEN must contain at least 24 characters')
    server = ThreadingHTTPServer((host, port), Handler)
    server.store, server.token = store, token
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='jin_trading/config.example.json')
    parser.add_argument('--db', default='data/jin-paper.sqlite')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-worker', action='store_true', help='Serve existing ledger only')
    args = parser.parse_args()
    config = load_config(args.config)
    token = os.environ.get('JIN_DASHBOARD_TOKEN', '')
    if len(token) < 24:
        parser.error('Set a random JIN_DASHBOARD_TOKEN of at least 24 characters')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    store.configure({bot: spec['budget'] for bot, spec in config['bots'].items()})
    server = make_server(store, token, args.host, args.port)
    worker = Worker(store, config)
    if not args.no_worker:
        threading.Thread(target=worker.run, daemon=True).start()
    print(f'JIN paper dashboard: http://{args.host}:{args.port} — bots start stopped')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
