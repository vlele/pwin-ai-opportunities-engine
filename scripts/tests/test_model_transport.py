"""Rate-limit diagnostics must preserve useful details without leaking secrets."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import httpx
from openai import APIConnectionError, RateLimitError, BadRequestError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import model_transport as t


def error(body=None, headers=None, status=429):
    request = httpx.Request('POST', 'https://example.invalid/v1')
    cls = RateLimitError if status == 429 else BadRequestError
    return cls('provider failure', response=httpx.Response(status, headers=headers or {}, request=request),
               body=body or {'code': 'rate_limit_exceeded', 'message': 'Wait before retrying.'})


class TransportTests(unittest.TestCase):
    def test_retry_after_seconds_is_a_minimum_and_payload_is_unchanged(self):
        call = Mock(side_effect=[error(headers={'Retry-After': '10'}), {'ok': True}])
        events, sleep = [], Mock()
        self.assertEqual(t.create_with_retries(call, sleep=sleep, emit=events.append,
                                             request={'messages': ['fixed']}), {'ok': True})
        self.assertGreaterEqual(sleep.call_args.args[0], 10)
        self.assertEqual(call.call_args_list[0], call.call_args_list[1])
        self.assertEqual(events[0]['error']['headers']['retry-after'], '10')
        self.assertEqual(events[0]['error']['body']['code'], 'rate_limit_exceeded')

    def test_http_date_milliseconds_and_invalid_headers(self):
        self.assertEqual(t.retry_after_seconds({'retry-after': 'Thu, 01 Jan 1970 00:01:00 GMT'}, now=30), 30)
        self.assertEqual(t.retry_after_seconds({'retry-after-ms': '15000', 'retry-after': '10'}, now=0), 15)
        self.assertIsNone(t.retry_after_seconds({'retry-after': 'nonsense'}, now=0))
        self.assertIsNone(t.retry_after_seconds({'retry-after': 'nan'}, now=0))
        self.assertIsNone(t.retry_after_seconds({'retry-after-ms': 'inf'}, now=0))

    def test_hour_long_retry_is_deferred_not_shortened(self):
        call, sleep, events = Mock(side_effect=error(headers={'Retry-After': '3600'})), Mock(), []
        with self.assertRaises(RateLimitError):
            t.create_with_retries(call, request={}, sleep=sleep, emit=events.append)
        sleep.assert_not_called()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(events[0]['decision'], 'defer')
        self.assertEqual(events[0]['retry_after_seconds'], 3600)

    def test_quota_auth_schema_and_unknown_429_are_not_retried(self):
        errors = [error({'code': c}, {'Retry-After': '1'}) for c in
                  ('insufficient_quota', 'credit_balance_exhausted', 'billing_hard_limit_reached')]
        errors += [error({'code': 'invalid_request_error'}, status=400),
                   error({'code': 'unknown_provider_error'})]
        for exc in errors:
            with self.subTest(exc=exc.body):
                call, sleep = Mock(side_effect=exc), Mock()
                with self.assertRaises(type(exc)):
                    t.create_with_retries(call, request={}, sleep=sleep, emit=lambda e: None)
                self.assertEqual(call.call_count, 1)
                sleep.assert_not_called()

    def test_retry_count_and_total_wait_are_bounded(self):
        call, sleep = Mock(side_effect=error()), Mock()
        with self.assertRaises(RateLimitError):
            t.create_with_retries(call, request={}, sleep=sleep, emit=lambda e: None)
        self.assertEqual(call.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        call = Mock(side_effect=error(headers={'Retry-After': '200'}))
        sleep.reset_mock()
        with self.assertRaises(RateLimitError):
            t.create_with_retries(call, request={}, sleep=sleep, emit=lambda e: None, max_wait_seconds=300)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(sleep.call_count, 1)

    def test_network_errors_retry_but_semantic_responses_do_not(self):
        exc = APIConnectionError(request=httpx.Request('POST', 'https://example.invalid'))
        call = Mock(side_effect=[exc, {'verdict': 'unsupported'}])
        self.assertEqual(t.create_with_retries(call, request={}, sleep=Mock(), emit=lambda e: None),
                         {'verdict': 'unsupported'})
        self.assertEqual(call.call_count, 2)

    def test_redact_environment_headers_nested_keys_and_key_patterns(self):
        secret = 'private-test-value-12345'
        body = {'error': {'code': 'rate_limit_exceeded', 'message': f'key {secret}; Bearer secret-token-value; sk-proj-abcdef1234567890',
                          'context': {'api_key': 'not-in-env', 'authorization': 'another-secret'}, 'tokens': 123}}
        with patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
            detail = t.error_details(error(body, {'Retry-After': '10', 'Authorization': secret}))
        encoded = json.dumps(detail)
        for value in (secret, 'secret-token-value', 'sk-proj-abcdef1234567890', 'not-in-env', 'another-secret'):
            self.assertNotIn(value, encoded)
        self.assertEqual(detail['body']['error']['tokens'], 123)
        self.assertEqual(detail['body']['error']['code'], 'rate_limit_exceeded')


if __name__ == '__main__':
    unittest.main()
