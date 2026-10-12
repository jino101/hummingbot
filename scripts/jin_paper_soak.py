"""GET-only local PAPER observation; never start, stop or submit a trade."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ipaddress
import json
import math
import os
from pathlib import Path
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


INTERVAL_SECONDS = 5.0
REQUEST_TIMEOUT = 4.0
MAX_RESPONSE_BYTES = 2_000_000
REASONS = {'ready', 'worker_disabled', 'worker_failed', 'worker_starting',
           'worker_stopped', 'worker_stopping', 'processing_failed',
           'market_data_missing', 'market_data_stale', 'trading_halted',
           'account_not_ready', 'status_unavailable', 'route_incomplete', 'capacity_exhausted', 'clock_skew'}
ORDER_STATES = {'prepared', 'submitting', 'open', 'partial', 'closed', 'filled',
                'cancelled', 'canceled', 'rejected', 'failed', 'unknown'}


def utc(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='milliseconds')


def finite(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def money(value):
    try:
        number = Decimal(str(value))
        return str(number) if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def state_url(value):
    """Never send the token to a remote host, proxy, redirect or URL credential."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        local = host == 'localhost' or ipaddress.ip_address(host).is_loopback
        port = parsed.port
    except (ValueError, TypeError):
        local = False
        port = None
    if (not local or parsed.scheme not in ('http', 'https') or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/', '/api/state') or port == 0):
        raise ValueError('Use a loopback HTTP(S) URL without credentials, query or fragment')
    return parsed.scheme + '://' + parsed.netloc + '/api/state'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PollError(Exception):
    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind, self.status = kind, status


def fetch_state(url, token, timeout=REQUEST_TIMEOUT):
    request = Request(url, headers={'Authorization': 'Bearer ' + token,
                                   'Accept': 'application/json'}, method='GET')
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise PollError('response_too_large')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise PollError('invalid_response')
        return value
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise PollError('authentication_failed' if status in (401, 403) else 'http_error',
                        status) from None
    except (URLError, OSError, TimeoutError):
        raise PollError('connection_failed') from None
    except (ValueError, UnicodeError):
        raise PollError('invalid_response') from None


def private_output(path):
    """Create a new owner-only file; fail before writing data if protection fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            advapi = ctypes.WinDLL('advapi32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            security = ctypes.c_void_p()
            convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
            convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
            convert.restype = wintypes.BOOL
            apply = advapi.SetFileSecurityW
            apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
            apply.restype = wintypes.BOOL
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            # Protected DACL; only the file owner has full access (Owner Rights SID).
            if not convert('D:P(A;;FA;;;OW)', 1, ctypes.byref(security), None):
                raise OSError('Unable to protect output')
            try:
                if not apply(str(path.resolve()), 0x80000004, security):
                    raise OSError('Unable to protect output')
            finally:
                kernel.LocalFree(security)
        elif stat.S_IMODE(os.fstat(descriptor).st_mode) & 0o077:
            raise OSError('Output permissions are not private')
        return os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n')
    except BaseException:
        os.close(descriptor)
        path.unlink()
        raise


class Observation:
    def __init__(self):
        self.samples = self.failed_samples = self.readiness_outages = 0
        self.last_ready = None
        self.failures = Counter()
        self.max_market_age_seconds = None
        self.max_feed_errors = 0
        self.first_pnl = self.last_pnl = None
        self.first_orders = self.last_orders = None
        self.order_ids = set()
        self.trade_ids = set()
        self.order_states = Counter()
        self.active_bot_observed = False
        self.enabled_bot_samples = 0
        self.worker_error_samples = 0
        self.stale_samples = 0
        self.previous_elapsed = 0.0
        self.max_poll_gap_seconds = 0.0

    def add(self, state, elapsed, wall, error=None):
        self.samples += 1
        if self.previous_elapsed is not None:
            self.max_poll_gap_seconds = max(self.max_poll_gap_seconds, elapsed - self.previous_elapsed)
        self.previous_elapsed = elapsed
        record = {'type': 'sample', 'at_utc': utc(wall), 'elapsed_seconds': round(elapsed, 6)}
        problems = []
        if error:
            problems.append(error.kind)
            if error.status is not None:
                record['http_status'] = error.status
        else:
            if not isinstance(state, dict):
                state = {}
            runtime = state.get('runtime')
            runtime = runtime if isinstance(runtime, dict) else {}
            portfolio = state.get('portfolio')
            portfolio = portfolio if isinstance(portfolio, dict) else {}
            if state.get('mode') != 'paper' or portfolio.get('mode') != 'paper':
                problems.append('not_paper')
            if runtime.get('ready') is not True:
                reason = runtime.get('reason')
                problems.append(reason if isinstance(reason, str) and reason in REASONS else 'not_ready')
            if runtime.get('enabled') is not True or runtime.get('thread_alive') is not True:
                problems.append('worker_not_running')
            if runtime.get('state') != 'running':
                problems.append('worker_not_running')
            if runtime.get('last_error') is not None or runtime.get('state') == 'failed':
                problems.append('worker_error')
                self.worker_error_samples += 1
            if state.get('halt') is not False or portfolio.get('halt') is not False:
                problems.append('trading_halted')
            if portfolio.get('ready') is not True:
                problems.append('account_not_ready')
            limit = finite(runtime.get('max_market_age_seconds'))
            markets = runtime.get('markets')
            markets = markets if isinstance(markets, dict) else {}
            market_ages = []
            actual_ages = []
            if not markets or limit is None or limit <= 0:
                problems.append('market_data_missing')
            for market in markets.values():
                market = market if isinstance(market, dict) else {}
                age = finite(market.get('age_seconds'))
                stamp = finite(market.get('last_market_at'))
                actual_age = wall - stamp if stamp is not None else None
                if age is not None:
                    market_ages.append(age)
                if actual_age is not None:
                    actual_ages.append(actual_age)
                if (age is None or actual_age is None or limit is None
                        or not 0 <= age <= limit or not 0 <= actual_age <= limit
                        or market.get('fresh') is not True):
                    problems.append('market_data_stale')
            if market_ages or actual_ages:
                maximum = max(market_ages + actual_ages)
                self.max_market_age_seconds = maximum if self.max_market_age_seconds is None else max(self.max_market_age_seconds, maximum)
            record['market_age_seconds'] = {'min': min(market_ages) if market_ages else None,
                                           'max': max(market_ages) if market_ages else None,
                                           'observed_max': max(actual_ages) if actual_ages else None,
                                           'limit': limit, 'markets': len(markets)}
            feed_errors = finite(runtime.get('feed_errors'))
            if feed_errors is None or feed_errors < 0:
                problems.append('invalid_feed_status')
            elif feed_errors:
                problems.append('feed_errors')
                self.max_feed_errors = max(self.max_feed_errors, feed_errors)
            record['feed_errors'] = feed_errors
            capital, baseline = money(state.get('capital')), money(state.get('baseline'))
            pnl = str(Decimal(capital) - Decimal(baseline)) if capital is not None and baseline is not None else None
            if pnl is None:
                problems.append('invalid_pnl')
            elif self.first_pnl is None:
                self.first_pnl = pnl
            self.last_pnl = pnl
            record['paper_equity'] = capital
            record['paper_pnl'] = pnl
            orders = portfolio.get('orders')
            if not isinstance(orders, list):
                problems.append('invalid_orders')
                orders = []
            counts = Counter()
            for order in orders:
                if isinstance(order, dict):
                    identity = order.get('client_id')
                    if isinstance(identity, str):
                        self.order_ids.add(identity)
                    status = order.get('state')
                    counts[status if isinstance(status, str) and status in ORDER_STATES else 'other'] += 1
            self.order_states = counts
            self.last_orders = len(orders)
            if self.first_orders is None:
                self.first_orders = len(orders)
            record['orders'] = {'visible': len(orders), 'by_state': dict(counts)}
            trades = state.get('trades', [])
            for trade in trades if isinstance(trades, list) else []:
                if isinstance(trade, dict) and isinstance(trade.get('id'), (str, int)):
                    self.trade_ids.add(str(trade['id']))
            bots = state.get('bots', [])
            active = sum(1 for bot in bots if isinstance(bot, dict) and bot.get('enabled') in (True, 1)) if isinstance(bots, list) else 0
            self.active_bot_observed |= active > 0
            self.enabled_bot_samples += int(active > 0)
            record['active_bots'] = active
        problems = sorted(set(problems))
        self.stale_samples += int('market_data_stale' in problems)
        ready = not problems
        if not ready:
            self.failed_samples += 1
            self.failures.update(problems)
            if self.last_ready is not False:
                self.readiness_outages += 1
        self.last_ready = ready
        record.update(ready=ready, failures=problems)
        return record

    def finish(self, started_wall, ended_wall, elapsed, duration, interrupted=False, stop_reason=None):
        completed = not interrupted and stop_reason is None and elapsed >= duration
        gaps_ok = self.max_poll_gap_seconds <= INTERVAL_SECONDS + REQUEST_TIMEOUT + 1
        coverage = self.samples >= 2 and self.previous_elapsed >= duration and gaps_ok
        passed = completed and coverage and gaps_ok and self.failed_samples == 0
        delta = str(Decimal(self.last_pnl) - Decimal(self.first_pnl)) if self.first_pnl is not None and self.last_pnl is not None else None
        return {'type': 'summary', 'started_at_utc': utc(started_wall), 'ended_at_utc': utc(ended_wall),
                'elapsed_seconds': round(elapsed, 6), 'requested_duration_seconds': duration,
                'completed': completed, 'interrupted': interrupted, 'passed': passed,
                'stop_reason': stop_reason, 'samples': self.samples, 'failed_samples': self.failed_samples,
                'ready_samples': self.samples - self.failed_samples,
                'readiness_percent': round(100 * (self.samples - self.failed_samples) / self.samples, 3) if self.samples else 0.0,
                'stale_samples': self.stale_samples, 'worker_error_samples': self.worker_error_samples,
                'readiness_outages': self.readiness_outages, 'failure_counts': dict(self.failures),
                'coverage_complete': coverage, 'poll_gaps_ok': gaps_ok,
                'max_poll_gap_seconds': round(self.max_poll_gap_seconds, 6),
                'max_market_age_seconds': self.max_market_age_seconds,
                'max_feed_errors': self.max_feed_errors, 'paper_pnl_start': self.first_pnl,
                'paper_pnl_end': self.last_pnl, 'paper_pnl_change': delta,
                'orders_start': self.first_orders, 'orders_end': self.last_orders,
                'unique_orders_observed': len(self.order_ids), 'orders_end_by_state': dict(self.order_states),
                'unique_trades_observed_lower_bound': len(self.trade_ids),
                'active_bot_observed': self.active_bot_observed,
                'enabled_bot_samples': self.enabled_bot_samples,
                'observation_mode': 'paper_bots_observed' if self.active_bot_observed else 'scanner_only',
                'paper_execution_accepted': False,
                'scope': 'sampled_paper_health_only; no execution or profitability approval'}


def monitor(url, token, output, duration=86400.0, fetch=fetch_state,
            monotonic=time.monotonic, wall_clock=time.time, sleep=time.sleep):
    """Inject clocks/transport for offline tests; record each response immediately."""
    duration = finite(duration)
    if duration is None or duration <= 0:
        raise ValueError('Duration must be positive and finite')
    url = state_url(url)
    if not isinstance(token, str) or len(token) < 24 or '\r' in token or '\n' in token:
        raise ValueError('Set JIN_DASHBOARD_TOKEN locally (at least 24 characters)')
    stats = Observation()
    start_mono, start_wall = monotonic(), wall_clock()
    interrupted, stop_reason = False, None

    def redact(value):
        if isinstance(value, str):
            return value.replace(token, '[REDACTED]')
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    def write(record):
        output.write(json.dumps(redact(record), ensure_ascii=True, allow_nan=False) + '\n')
        output.flush()

    write({'type': 'start', 'started_at_utc': utc(start_wall), 'duration_seconds': duration,
           'interval_seconds': INTERVAL_SECONDS, 'request_timeout_seconds': REQUEST_TIMEOUT,
           'method': 'GET', 'endpoint': '/api/state', 'token_source': 'environment'})
    try:
        while True:
            poll_started = monotonic() - start_mono
            state, error = None, None
            try:
                state = fetch(url, token)
            except PollError as exc:
                error = exc
            except Exception:
                # Never serialize exception text: it can contain auth headers/URLs.
                error = PollError('request_failed')
            elapsed = monotonic() - start_mono
            sample = stats.add(state, elapsed, wall_clock(), error)
            write(sample)
            if 'authentication_failed' in sample['failures']:
                stop_reason = 'authentication_failed'
                break
            if 'not_paper' in sample['failures']:
                stop_reason = 'not_paper'
                break
            if elapsed >= duration:
                break
            delay = max(0.0, INTERVAL_SECONDS - (elapsed - poll_started))
            sleep(min(delay, duration - elapsed))
    except KeyboardInterrupt:
        interrupted = True
    summary = redact(stats.finish(start_wall, wall_clock(), monotonic() - start_mono,
                                 duration, interrupted, stop_reason))
    write(summary)
    return summary


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's usual error includes rejected values, potentially credentials.
        self.exit(2, 'Invalid arguments; use --help. Credentials belong only in the environment.\n')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8788')
    parser.add_argument('--duration-seconds', type=float, default=86400.0)
    parser.add_argument('--output', type=Path, required=True, help='New private JSONL file; never overwrite')
    args = parser.parse_args(argv)
    try:
        url = state_url(args.url)
        duration = finite(args.duration_seconds)
        if duration is None or duration <= 0:
            raise ValueError('Duration must be positive and finite')
        token = os.environ.get('JIN_DASHBOARD_TOKEN', '')
        if len(token) < 24 or '\r' in token or '\n' in token:
            raise ValueError('Set JIN_DASHBOARD_TOKEN locally (at least 24 characters)')
        with private_output(args.output) as output:
            summary = monitor(url, token, output, duration)
    except (OSError, ValueError):
        # Paths and exception text can contain credentials supplied by mistake.
        parser.exit(2, 'Unable to run: check loopback URL, duration, local token and a new private output path.\n')
    print(json.dumps(summary, allow_nan=False))
    return 0 if summary['passed'] else 130 if summary['interrupted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
