"""Authenticated, mobile control surface for the shared PAPER ledger."""
import argparse
import csv
import hmac
import io
import json
import os
import threading
from urllib.parse import unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from jin_trading.store import Store
from jin_trading.worker import Worker, load_config
from jin_trading.strategies import growth


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
        origin=self.headers.get('Origin')
        if origin in self.server.allowed_origins:
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        origin=self.headers.get('Origin')
        if origin and origin not in self.server.allowed_origins:
            self.send(403,{'error':'Origin not allowed'})
            return False
        supplied = self.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied, 'Bearer ' + self.server.token):
            self.send(401, {'error': 'Anmeldung erforderlich'})
            return False
        return True

    def do_OPTIONS(self):
        if self.headers.get('Origin') not in self.server.allowed_origins:
            self.send(403,{'error':'Origin not allowed'});return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
        self.send_header('Vary','Origin')
        self.send_header('Content-Length','0')
        self.end_headers()

    def state(self):
        state=self.server.store.snapshot()
        if self.server.worker:
            portfolio=self.server.worker.portfolio.snapshot()
            state['portfolio']=portfolio
            state['mode']=portfolio['mode']
            state['live_available']=portfolio['mode']=='live'
            state['capital']=portfolio['equity']
            state['baseline']=portfolio['baseline']
            state['halt']=state['halt'] or portfolio['halt']
            if portfolio['reason']:state['reason']=portfolio['reason']
            state['universe']=self.server.worker.universe_status
        state['growth']=growth(state['capital'])
        return state

    def do_GET(self):
        if self.path=='/healthz':
            mode=self.server.worker.portfolio.mode if self.server.worker else 'paper'
            self.send(200,{'service':'jin','mode':mode});return
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
            self.send(200, self.state())
        elif self.path=='/api/orders':
            self.send(200,self.server.worker.portfolio.orders() if self.server.worker else [])
        elif self.path == '/api/existing/status':
            path = self.server.observation_path
            if not path or not path.is_file():
                self.send(200, {'available': False})
                return
            try:
                import time
                if path.stat().st_size > 1_000_000:
                    raise ValueError('Observation snapshot too large')
                observation = json.loads(path.read_text())
                if not isinstance(observation, dict):
                    raise ValueError('Observation snapshot must be an object')
                age = time.time() - float(observation.get('timestamp', 0))
                self.send(200, {'available': True, 'stale': not 0 <= age <= 60, 'observation': observation})
            except (ValueError, OSError, TypeError) as exc:
                self.send(200, {'available': False, 'error': str(exc)})
        elif self.path == '/api/trades.csv':
            out = io.StringIO()
            fields = ['id', 'bot', 'timestamp', 'input', 'output', 'route']
            writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in self.server.store.trades():
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
                if self.server.worker:self.server.worker.engine.stop_all()
                if self.server.kill_switch_path:
                    self.server.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
                    self.server.kill_switch_path.touch()
            elif self.path == '/api/reset':
                if self.server.worker:self.server.worker.portfolio.reset()
                self.server.store.reset()
            elif self.path=='/api/reconcile':
                if not self.server.worker:raise ValueError('Worker unavailable')
                self.send(200,self.server.worker.engine.reconcile());return
            elif self.path.startswith('/api/runs/') and self.path.endswith('/accept-reconciled-inventory'):
                parts=self.path.split('/')
                if len(parts)!=5 or not self.server.worker:raise ValueError('Unknown execution')
                self.server.worker.portfolio.settle_held(unquote(parts[3],errors='strict'),
                    'ACCEPT_RECONCILED_INVENTORY')
            else:
                parts = self.path.split('/')
                if len(parts) != 5 or parts[1:3] != ['api', 'bots'] or parts[4] not in ('start', 'stop'):
                    self.send(404, {'error': 'Unbekannte Aktion'})
                    return
                bot=unquote(parts[3], errors='strict')
                if self.server.worker:
                    if parts[4]=='start' and not self.server.worker.portfolio.snapshot()['ready']:
                        raise ValueError('Portfolio not ready; refresh snapshots and reconcile')
                    if parts[4]=='stop':self.server.worker.engine.stop_bot(bot)
                self.server.store.control(bot, parts[4] == 'start')
            self.send(200, self.state())
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})


def make_server(store, token, host='127.0.0.1', port=8788, observation_path=None, kill_switch_path=None,
                worker=None, allowed_origins=()):
    if len(token) < 24:
        raise ValueError('JIN_DASHBOARD_TOKEN must contain at least 24 characters')
    server = ThreadingHTTPServer((host, port), Handler)
    server.store, server.token = store, token
    origins=set(allowed_origins)
    for origin in origins:
        parsed=urlsplit(origin)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            server.server_close();raise ValueError('CORS requires exact HTTP origins without a path')
    server.allowed_origins=origins | {f'http://{host}:{server.server_port}',f'http://127.0.0.1:{server.server_port}'}
    server.worker=worker
    server.observation_path = Path(observation_path) if observation_path else None
    server.kill_switch_path = Path(kill_switch_path) if kill_switch_path else None
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='jin_trading/config.example.json')
    parser.add_argument('--db', default='data/jin-paper.sqlite')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--no-worker', action='store_true', help='Serve existing ledger only')
    parser.add_argument('--feed',choices=['rest','websocket'],default='rest')
    parser.add_argument('--reset-paper-budgets', action='store_true',
                        help='Reset ONLY virtual paper balances/trades to config budgets; bots remain stopped')
    args = parser.parse_args()
    config = load_config(args.config)
    token = os.environ.get('JIN_DASHBOARD_TOKEN', '')
    if len(token) < 24:
        parser.error('Set a random JIN_DASHBOARD_TOKEN of at least 24 characters')
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    store = Store(args.db)
    budgets = {bot: spec['budget'] for bot, spec in config['bots'].items()}
    if args.reset_paper_budgets:
        store.reset_budgets(budgets)
    else:
        store.configure(budgets)
    worker = Worker(store, config)
    server = make_server(store, token, args.host, args.port,
                         config.get("existing_observation_path"), config.get("existing_kill_switch_path"),worker,
                         config.get('allowed_origins',()))
    if not args.no_worker:
        target=worker.run
        if args.feed=='websocket':
            try:import ccxt.pro
            except ImportError:parser.error('WebSocket feed needs the optional CCXT dependency')
            from jin_trading.websocket import run_public
            target=lambda:run_public(worker)
        threading.Thread(target=target, daemon=True).start()
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
