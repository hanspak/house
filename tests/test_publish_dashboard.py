import contextlib
import http.client
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_dashboard as publisher


def http_error(code, headers=None):
    return urllib.error.HTTPError('https://example.invalid', code, 'error', headers or {}, io.BytesIO())


class PublicationReadTests(unittest.TestCase):
    page = 'https://hanspak.github.io/house/overview.html'

    def test_success_is_one_read_without_delay(self):
        response = io.BytesIO(b'{"ok":true}')
        with patch.object(publisher.urllib.request, 'urlopen', return_value=response) as request, patch.object(publisher.time, 'sleep') as sleep:
            self.assertEqual(publisher.get(self.page), '{"ok":true}')
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['timeout'], 40)
        sleep.assert_not_called()
        self.assertTrue(response.closed)

    def test_transient_http_retries_and_caps_server_delay(self):
        errors = [http_error(503), http_error(429, {'Retry-After': '999'})]
        with patch.object(publisher.urllib.request, 'urlopen', side_effect=errors + [io.BytesIO(b'ok')]), patch.object(publisher.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(publisher.get(self.page + '?private=hidden'), 'ok')
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 15])
        self.assertIn('HTTP 503', output.getvalue())
        self.assertNotIn('hidden', output.getvalue())
        self.assertTrue(all(error.fp.closed for error in errors))

    def test_transport_and_partial_response_retry_without_false_success(self):
        failures = [urllib.error.URLError('transport'), TimeoutError(), http.client.IncompleteRead(b'partial')]
        with patch.object(publisher.urllib.request, 'urlopen', side_effect=failures + [io.BytesIO(b'complete')]) as request, patch.object(publisher.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.get(self.page), 'complete')
        self.assertEqual(request.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 8])

    def test_permanent_errors_and_api_not_found_fail_immediately(self):
        for url, code in [(self.page, 403), (self.page, 400), ('https://api.github.com/repos/unknown', 404)]:
            with self.subTest(code=code), patch.object(publisher.urllib.request, 'urlopen', side_effect=http_error(code)) as request, patch.object(publisher.time, 'sleep') as sleep:
                with self.assertRaises(urllib.error.HTTPError):
                    publisher.get(url)
                self.assertEqual(request.call_count, 1)
                sleep.assert_not_called()

    def test_pages_not_found_has_only_bounded_retry(self):
        with patch.object(publisher.urllib.request, 'urlopen', side_effect=[http_error(404), io.BytesIO(b'published')]), patch.object(publisher.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publisher.get(self.page), 'published')
        sleep.assert_called_once_with(2)

    def test_exhaustion_raises_final_failure(self):
        failures = [http_error(503) for _ in range(4)]
        with patch.object(publisher.urllib.request, 'urlopen', side_effect=failures) as request, patch.object(publisher.time, 'sleep') as sleep, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                publisher.get(self.page)
        self.assertIs(raised.exception, failures[-1])
        self.assertEqual(request.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_deadline_limits_requests_and_waits(self):
        with patch.object(publisher.time, 'monotonic', return_value=100), patch.object(publisher.urllib.request, 'urlopen') as request:
            with self.assertRaises(TimeoutError):
                publisher.get(self.page, deadline=100)
            request.assert_not_called()
        with patch.object(publisher.time, 'monotonic', return_value=100), patch.object(publisher.urllib.request, 'urlopen', side_effect=http_error(503)) as request, patch.object(publisher.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                publisher.get(self.page, deadline=101)
            self.assertEqual(request.call_args.kwargs['timeout'], 1)
            sleep.assert_not_called()

    def test_bad_encoding_is_not_retried_as_network_error(self):
        with patch.object(publisher.urllib.request, 'urlopen', return_value=io.BytesIO(b'\xff')) as request, patch.object(publisher.time, 'sleep') as sleep:
            with self.assertRaises(UnicodeDecodeError):
                publisher.get(self.page)
        self.assertEqual(request.call_count, 1)
        sleep.assert_not_called()
