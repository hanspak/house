import contextlib
import http.client
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
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


class PublicationVerificationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / '.git').mkdir()
        (self.root / 'scripts').mkdir()
        self.sha = 'expected-commit'
        self.body = json.dumps({'schema_version': 1, 'sources': {}})
        self.digest = hashlib.sha256(self.body.encode()).hexdigest()[:12]
        self.pages = {}
        for name, module in [('trades.html', 'profile_loader.js'), ('index.html', 'market_analysis.js'), ('monthly.html', 'market_analysis.js'), ('overview.html', 'overview_comparison.js')]:
            (self.root / 'scripts' / module).write_text(module, encoding='utf-8')
            self.pages[name] = f'<meta name="build-commit" content="{self.sha}">' + module
        self.pages['overview.html'] += json.dumps({'revision_file': f'overview-data/revisions.{self.digest}.json'}, separators=(',', ':'))

    def read_public(self, url, deadline=None):
        name = url.split('/')[-1].split('?')[0]
        return self.pages.get(name, self.body)

    def fake_git(self, root, *args):
        return {'rev-parse': str(self.root / '.git') if args[-1] == '--git-common-dir' else self.sha,
                'status': '', 'branch': 'main', 'remote': 'https://github.com/hanspak/house.git'}.get(args[0], '')

    def test_rate_limit_is_distinct_from_permission_failure(self):
        for code, headers, expected in [(403, {}, False), (403, {'X-RateLimit-Remaining': '1'}, False), (403, {'X-RateLimit-Remaining': '0'}, True), (429, {}, True)]:
            error = http_error(code, headers)
            self.addCleanup(error.close)
            self.assertEqual(publisher.rate_limited(error), expected)

    def test_all_public_commits_modules_and_revision_hash_must_match(self):
        with patch.object(publisher, 'get', side_effect=self.read_public) as get, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(publisher.verify_public(self.root, 'hanspak/house', self.sha, 100))
        self.assertEqual(get.call_count, 5)
        self.assertTrue(all(call.kwargs['deadline'] == 100 for call in get.call_args_list))

    def test_old_page_is_pending_not_success(self):
        self.pages['monthly.html'] = self.pages['monthly.html'].replace(self.sha, 'old-commit')
        with patch.object(publisher, 'get', side_effect=self.read_public):
            self.assertFalse(publisher.verify_public(self.root, 'hanspak/house', self.sha, 100))

    def test_correct_commit_with_wrong_module_fails(self):
        self.pages['trades.html'] = self.pages['trades.html'].replace('profile_loader.js', 'unexpected')
        with patch.object(publisher, 'get', side_effect=self.read_public), self.assertRaises(SystemExit):
            publisher.verify_public(self.root, 'hanspak/house', self.sha, 100)

    def test_revision_link_hash_and_schema_are_required(self):
        original = self.pages['overview.html']
        for fault in ('missing', 'hash', 'schema'):
            with self.subTest(fault=fault):
                self.pages['overview.html'] = original
                self.body = json.dumps({'schema_version': 2 if fault == 'schema' else 1})
                if fault == 'missing':
                    self.pages['overview.html'] = original.split('{')[0]
                if fault == 'schema':
                    digest = hashlib.sha256(self.body.encode()).hexdigest()[:12]
                    self.pages['overview.html'] = original.replace(self.digest, digest)
                with patch.object(publisher, 'get', side_effect=self.read_public), self.assertRaises(SystemExit):
                    publisher.verify_public(self.root, 'hanspak/house', self.sha, 100)

    def test_quota_falls_back_once_and_waits_for_complete_publication(self):
        error = http_error(403, {'X-RateLimit-Remaining': '0'})
        with patch.object(publisher, 'git', side_effect=self.fake_git), patch.object(publisher, 'run'), patch.object(publisher.time, 'monotonic', return_value=0), patch.object(publisher.time, 'sleep') as sleep, patch.object(publisher, 'get', side_effect=error) as get, patch.object(publisher, 'verify_public', side_effect=[False, True]) as verify, contextlib.redirect_stdout(io.StringIO()) as output:
            publisher.publish(self.root, timeout=100)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(verify.call_count, 2)
        sleep.assert_called_once_with(20)
        self.assertIn('Actions status unavailable', output.getvalue())

    def test_permission_failure_does_not_use_fallback(self):
        with patch.object(publisher, 'git', side_effect=self.fake_git), patch.object(publisher, 'run'), patch.object(publisher.time, 'monotonic', return_value=0), patch.object(publisher, 'get', side_effect=http_error(403)), patch.object(publisher, 'verify_public') as verify, self.assertRaises(urllib.error.HTTPError):
            publisher.publish(self.root, timeout=100)
        verify.assert_not_called()

    def test_jobs_endpoint_quota_also_uses_public_verification(self):
        run = {'path': '.github/workflows/dashboard.yml', 'jobs_url': 'https://api.github.com/jobs', 'status': 'in_progress'}
        responses = [json.dumps({'workflow_runs': [run]}), http_error(429)]
        with patch.object(publisher, 'git', side_effect=self.fake_git), patch.object(publisher, 'run'), patch.object(publisher.time, 'monotonic', return_value=0), patch.object(publisher, 'get', side_effect=responses) as get, patch.object(publisher, 'verify_public', return_value=True) as verify, contextlib.redirect_stdout(io.StringIO()):
            publisher.publish(self.root, timeout=100)
        self.assertEqual(get.call_count, 2)
        verify.assert_called_once()
