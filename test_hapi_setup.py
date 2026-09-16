"""Exercise setup and readiness against a real local HTTP server, never a provider."""

import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

spec = importlib.util.spec_from_file_location('hapi_setup', Path(__file__).with_name('hapi-setup.py'))
hapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hapi)


class SetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.calls.append((self.path, body))
                if self.server.redirect:
                    self.send_response(302)
                    self.send_header('Location', self.server.redirect)
                    self.end_headers()
                    return
                self.send_response(200 if body.get('accessToken') == 'test-secret' else 401)
                self.end_headers()
                self.wfile.write(b'{"token":"test-jwt"}')

            def do_GET(self):
                self.server.calls.append((self.path, self.headers.get('Authorization')))
                code = self.server.rpc_codes.pop(0) if self.server.rpc_codes else 200
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b'{"agents":[{"agent":"codex","available":true}]}')

        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'settings.json'
        self.server.calls = []
        self.server.rpc_codes = []
        self.server.redirect = None
        self.env = patch.dict(os.environ, {'NO_PROXY': '127.0.0.1'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.output = io.StringIO()
        for redirect in (contextlib.redirect_stdout, contextlib.redirect_stderr):
            self.enterContext(redirect(self.output))

    def save(self, **values):
        self.path.write_text(json.dumps({'apiUrl': self.url, 'cliApiToken': 'test-secret',
                                         'machineId': 'machine-a', **values}))

    def test_first_interactive_setup_verifies_token_and_saves_private_settings(self):
        with patch.object(hapi.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', return_value=self.url), \
                patch.object(hapi.getpass, 'getpass', return_value='test-secret') as hidden:
            hapi.setup(self.path)
        hidden.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text()), {'apiUrl': self.url, 'cliApiToken': 'test-secret'})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.server.calls[0][0], '/api/auth')
        self.assertNotIn('test-secret', self.output.getvalue())

    def test_noninteractive_setup_explains_env_file(self):
        with patch.object(hapi.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(hapi.SetupError, '--env-file'):
                hapi.setup(self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.server.calls, [])

    def test_environment_setup_saves_url_without_copying_token(self):
        with patch.dict(os.environ, HAPI_API_URL=self.url, CLI_API_TOKEN='test-secret'):
            hapi.setup(self.path)
        self.assertEqual(json.loads(self.path.read_text()), {'apiUrl': self.url})

    def test_rejected_saved_token_can_be_repaired_without_changing_identity(self):
        self.save(cliApiToken='old-token', otherSetting='keep')
        with patch.object(hapi.sys.stdin, 'isatty', return_value=True), \
                patch.object(hapi.getpass, 'getpass', return_value='test-secret'):
            hapi.setup(self.path)
        settings = json.loads(self.path.read_text())
        self.assertEqual(settings['machineId'], 'machine-a')
        self.assertEqual(settings['otherSetting'], 'keep')
        self.assertEqual(settings['cliApiToken'], 'test-secret')
        self.assertEqual(len(self.server.calls), 2)

    def test_rejected_token_does_not_replace_existing_settings(self):
        self.save(cliApiToken='bad-secret')
        original = self.path.read_bytes()
        with patch.object(hapi.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(urllib.error.HTTPError):
                hapi.setup(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertNotIn('bad-secret', self.output.getvalue())

    def test_changed_hub_requires_new_token_and_never_sends_old_one(self):
        self.save(apiUrl='https://previous.example.test')
        original = self.path.read_bytes()
        with patch.dict(os.environ, HAPI_API_URL=self.url), \
                patch.object(hapi.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(hapi.SetupError, '--env-file'):
                hapi.setup(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.server.calls, [])

    def test_changed_hub_environment_does_not_retain_previous_hub_token(self):
        self.save(apiUrl='https://previous.example.test', cliApiToken='old-secret')
        with patch.dict(os.environ, HAPI_API_URL=self.url, CLI_API_TOKEN='test-secret'):
            hapi.setup(self.path)
        self.assertNotIn('cliApiToken', json.loads(self.path.read_text()))
        self.assertNotIn('old-secret', str(self.server.calls))

    def test_readiness_retries_until_machine_rpc_works(self):
        self.save()
        self.server.rpc_codes = [404, 500, 200]
        with patch.object(hapi.time, 'sleep'):
            hapi.ready(self.path, wait_seconds=2)
        self.assertEqual([call[0] for call in self.server.calls],
                         ['/api/auth'] + ['/api/machines/machine-a/agent-availability'] * 3)
        self.assertIn('Runner ready', self.output.getvalue())
        self.assertNotIn('test-jwt', self.output.getvalue())

    def test_readiness_times_out_instead_of_accepting_offline_machine(self):
        self.save()
        self.server.rpc_codes = [404] * 10
        with self.assertRaisesRegex(hapi.SetupError, 'timed out'):
            hapi.ready(self.path, wait_seconds=0.05)
        self.assertNotIn('Runner ready', self.output.getvalue())

    def test_auth_rejection_does_not_attempt_machine_rpc(self):
        self.save(cliApiToken='bad-secret')
        with self.assertRaises(urllib.error.HTTPError):
            hapi.ready(self.path)
        self.assertEqual(len(self.server.calls), 1)

    def test_http_redirect_never_receives_credentials(self):
        self.server.redirect = self.url + '/unexpected'
        with self.assertRaises(urllib.error.HTTPError) as error:
            hapi.authenticate(self.url, 'test-secret')
        self.assertEqual(error.exception.code, 302)
        self.assertEqual(len(self.server.calls), 1)

    def test_main_reports_auth_failure_without_token_or_server_body(self):
        self.save(cliApiToken='bad-secret')
        with patch.dict(os.environ, HAPI_HOME=str(self.path.parent)), \
                patch.object(hapi.sys, 'argv', ['hapi-setup.py', 'ready']):
            self.assertEqual(hapi.main(), 1)
        self.assertIn('401', self.output.getvalue())
        self.assertNotIn('bad-secret', self.output.getvalue())
        self.assertNotIn('test-jwt', self.output.getvalue())

    def test_malformed_settings_are_preserved(self):
        for value in ('{broken', '[]', '{"cliApiToken":123}'):
            with self.subTest(value=value):
                self.path.write_text(value)
                with self.assertRaises(hapi.SetupError):
                    hapi.setup(self.path)
                self.assertEqual(self.path.read_text(), value)

    def test_unsafe_or_ambiguous_hub_urls_are_rejected(self):
        for url in ('http://public.example.test', 'https://user:secret@example.test',
                    'https://example.test/path', 'https://example.test?token=secret',
                    'https://example.test#fragment', 'https://example.test:invalid'):
            with self.subTest(url=url), self.assertRaises(hapi.SetupError):
                hapi.hub_url(url)


if __name__ == '__main__':
    unittest.main()
