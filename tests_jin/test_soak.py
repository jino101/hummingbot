import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.jin_paper_soak import (
    NoRedirect, Observation, PollError, fetch_state, main, monitor, private_output, state_url,
)


TOKEN = 'test-secret-that-must-never-appear'


class Clock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def wall(self):
        return 1700000000.0 + self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


def healthy(now, *, pnl='0', orders=None, enabled=True):
    return {
        'mode': 'paper', 'capital': str(5 + float(pnl)), 'baseline': '5', 'halt': False,
        'bots': [{'enabled': enabled}], 'trades': [{'id': 1}],
        'portfolio': {'mode': 'paper', 'ready': True, 'halt': False,
                      'orders': orders if orders is not None else []},
        'runtime': {'enabled': True, 'state': 'running', 'thread_alive': True,
                    'ready': True, 'reason': 'ready', 'last_error': None, 'feed_errors': 0,
                    'max_market_age_seconds': 3,
                    'markets': {'kucoin': {'age_seconds': 0.5, 'last_market_at': now - 0.5,
                                           'fresh': True}}},
    }


class SoakTests(unittest.TestCase):
    def run_monitor(self, fetch=None, duration=10, clock=None, sleep=None):
        clock = clock or Clock()
        output = io.StringIO()
        result = monitor('http://127.0.0.1:8788/', TOKEN, output, duration,
                         fetch=fetch or (lambda url, token: healthy(clock.wall())),
                         monotonic=clock.monotonic, wall_clock=clock.wall,
                         sleep=sleep or clock.sleep)
        return result, [json.loads(line) for line in output.getvalue().splitlines()], output.getvalue()

    def test_full_duration_aggregates_orders_pnl_and_activity_without_double_counting(self):
        clock = Clock()

        def fetch(url, token):
            self.assertEqual(url, 'http://127.0.0.1:8788/api/state')
            self.assertEqual(token, TOKEN)
            orders = [{'client_id': 'first', 'state': 'filled'}]
            if clock.elapsed >= 5:
                orders.append({'client_id': 'second', 'state': 'closed'})
            return healthy(clock.wall(), pnl=str(clock.elapsed / 100), orders=orders)

        result, records, _ = self.run_monitor(fetch, clock=clock)
        self.assertTrue(result['completed'])
        self.assertTrue(result['passed'])
        self.assertEqual(result['elapsed_seconds'], 10)
        self.assertEqual(result['samples'], 3)
        self.assertEqual(result['readiness_percent'], 100)
        self.assertEqual(result['unique_orders_observed'], 2)
        self.assertEqual(result['orders_start'], 1)
        self.assertEqual(result['orders_end'], 2)
        self.assertEqual(result['unique_trades_observed_lower_bound'], 1)
        self.assertEqual(result['paper_pnl_change'], '0.1')
        self.assertEqual(result['enabled_bot_samples'], 3)
        self.assertFalse(result['paper_execution_accepted'])
        self.assertEqual(records[0]['type'], 'start')
        self.assertEqual(records[-1]['type'], 'summary')

    def test_expired_quotes_override_claimed_ready_and_recover_as_one_outage(self):
        stats = Observation()
        for elapsed in (0, 5, 10, 15):
            state = healthy(1700000000 + elapsed)
            if elapsed in (5, 10):
                market = state['runtime']['markets']['kucoin']
                market.update(age_seconds=8, last_market_at=1700000000 + elapsed - 8)
            stats.add(state, elapsed, 1700000000 + elapsed)
        result = stats.finish(1700000000, 1700000015, 15, 15)
        self.assertTrue(result['completed'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['readiness_outages'], 1)
        self.assertEqual(result['stale_samples'], 2)
        self.assertEqual(result['readiness_percent'], 50)
        self.assertEqual(result['max_market_age_seconds'], 8)

    def test_expired_timestamp_is_not_hidden_by_small_reported_age(self):
        state = healthy(1700000000)
        state['runtime']['markets']['kucoin']['last_market_at'] -= 30
        record = Observation().add(state, 0, 1700000000)
        self.assertFalse(record['ready'])
        self.assertIn('market_data_stale', record['failures'])

    def test_interrupted_and_incomplete_run_never_pass(self):
        def interrupt(seconds):
            raise KeyboardInterrupt

        result, records, _ = self.run_monitor(sleep=interrupt)
        self.assertTrue(result['interrupted'])
        self.assertFalse(result['completed'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(records[-1], result)
        stats = Observation()
        stats.add(healthy(1700000000), 0, 1700000000)
        result = stats.finish(1700000000, 1700000005, 5, 86400)
        self.assertFalse(result['completed'])
        self.assertFalse(result['passed'])

    def test_sampling_gap_fails_even_when_clock_duration_and_readiness_pass(self):
        clock = Clock()

        def long_sleep(seconds):
            clock.elapsed += 20

        result, _, _ = self.run_monitor(clock=clock, sleep=long_sleep)
        self.assertTrue(result['completed'])
        self.assertFalse(result['poll_gaps_ok'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['max_poll_gap_seconds'], 20)

    def test_late_first_sample_cannot_claim_twenty_four_hours_of_coverage(self):
        stats = Observation()
        for elapsed in (86395, 86400):
            stats.add(healthy(1700000000 + elapsed), elapsed, 1700000000 + elapsed)
        result = stats.finish(1700000000, 1700086400, 86400, 86400)
        self.assertTrue(result['completed'])
        self.assertFalse(result['poll_gaps_ok'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['max_poll_gap_seconds'], 86395)
        self.assertFalse(result['coverage_complete'])

    def test_no_opportunities_and_stopped_bots_are_valid_scanner_observations(self):
        clock = Clock()
        result, _, _ = self.run_monitor(lambda url, token: healthy(clock.wall(), enabled=False), clock=clock)
        self.assertTrue(result['passed'])
        self.assertEqual(result['observation_mode'], 'scanner_only')
        self.assertEqual(result['orders_end'], 0)
        self.assertEqual(result['enabled_bot_samples'], 0)
        self.assertFalse(result['paper_execution_accepted'])

    def test_auth_failure_aborts_and_error_details_are_redacted(self):
        def unauthorized(url, token):
            raise PollError('authentication_failed', 401)

        result, records, raw = self.run_monitor(unauthorized)
        self.assertFalse(result['completed'])
        self.assertEqual(result['stop_reason'], 'authentication_failed')
        self.assertEqual(records[1]['http_status'], 401)
        self.assertNotIn(TOKEN, raw)

        clock = Clock()

        def leaking_adapter(url, token):
            raise RuntimeError('Authorization: Bearer ' + token)

        result, _, raw = self.run_monitor(leaking_adapter, clock=clock)
        self.assertTrue(result['completed'])
        self.assertFalse(result['passed'])
        self.assertNotIn(TOKEN, raw)
        self.assertNotIn('Authorization', raw)

    def test_raw_response_reasons_ids_and_unknown_order_states_are_not_logged(self):
        clock = Clock()

        def fetch(url, token):
            state = healthy(clock.wall(), orders=[{'client_id': TOKEN, 'state': TOKEN}])
            state['runtime'].update(ready=False, reason=TOKEN, last_error=TOKEN)
            state['token'] = TOKEN
            return state

        result, _, raw = self.run_monitor(fetch, clock=clock)
        self.assertNotIn(TOKEN, raw)
        self.assertEqual(result['worker_error_samples'], 3)
        self.assertEqual(result['orders_end_by_state'], {'other': 1})

    def test_live_mode_is_only_read_once_and_never_accepted(self):
        state = healthy(1700000000)
        state['mode'] = state['portfolio']['mode'] = 'live'
        fetch = Mock(return_value=state)
        result, _, _ = self.run_monitor(fetch)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['stop_reason'], 'not_paper')
        self.assertFalse(result['completed'])

    def test_http_transport_uses_only_get_and_does_not_log_auth_body(self):
        response = Mock()
        response.read.return_value = json.dumps(healthy(1700000000)).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch('scripts.jin_paper_soak.build_opener', return_value=opener):
            fetch_state('http://127.0.0.1:8788/api/state', TOKEN)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + TOKEN)
        opener.open.side_effect = HTTPError('http://127.0.0.1', 401, TOKEN, {}, io.BytesIO(TOKEN.encode()))
        with patch('scripts.jin_paper_soak.build_opener', return_value=opener):
            with self.assertRaises(PollError) as caught:
                fetch_state('http://127.0.0.1:8788/api/state', TOKEN)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertEqual(caught.exception.status, 401)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.org'))

    def test_remote_credentials_queries_and_control_urls_are_rejected(self):
        for url in ('https://example.org', 'http://127.0.0.1/api/halt',
                    'http://user:secret@127.0.0.1', 'http://127.0.0.1/?token=secret',
                    'http://127.0.0.1/#secret', 'file:///tmp/state', 'http://127.0.0.1:bad'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                state_url(url)
        self.assertEqual(state_url('http://[::1]:8788'), 'http://[::1]:8788/api/state')

    def test_private_file_is_exclusive_and_not_world_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'run.jsonl'
            with private_output(path) as output:
                output.write('{"type":"start"}\n')
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
            with self.assertRaises(FileExistsError):
                private_output(path)
            self.assertEqual(path.read_text(), '{"type":"start"}\n')

    def test_accidental_token_argument_is_not_echoed_by_argument_parser(self):
        output = io.StringIO()
        with patch('sys.stderr', output), self.assertRaises(SystemExit) as caught:
            main(['--output', 'unused.jsonl', '--token', TOKEN])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(TOKEN, output.getvalue())


if __name__ == '__main__':
    unittest.main()
