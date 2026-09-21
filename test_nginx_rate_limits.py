"""Exercise the shipped Nginx routes against a harmless local HTTP backend."""

import http.client
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("nginx"), "requires nginx; also run on the VPS before deployment")
class NginxRateLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agent-nginx-test-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)

        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_POST = do_GET
            do_DELETE = do_GET

        backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]

        template = (REPO / "deploy/nginx-hapi.conf").read_text()
        preamble = template.split("server {", 1)[0]
        blocks = re.findall(r"(?ms)^server \{.*?^\}", template)
        server = next(block for block in blocks if "listen 443 ssl;" in block)
        server = re.sub(r"(?m)^\s*listen .*;\n", "", server)
        server = server.replace("server {", f"server {{\n    listen 127.0.0.1:{self.port};", 1)
        server = re.sub(r"^\s*ssl_certificate(?:_key)? .*;", "", server, flags=re.MULTILINE)
        server = server.replace("__PUBLIC_HOST__", "localhost")
        server = server.replace("/var/log/nginx/hapi-access.log", str(base / "access.log"))
        for port in (3006,):
            server = server.replace(f"127.0.0.1:{port}", f"127.0.0.1:{backend.server_port}")
        catch_all = next(block for block in blocks if "ssl_reject_handshake on;" in block)
        catch_all = re.sub(r"(?m)^\s*listen .*;\n", "", catch_all)
        catch_all = catch_all.replace(
            "server {", f"server {{\n    listen 127.0.0.1:{self.port} default_server;", 1
        )
        catch_all = catch_all.replace("ssl_reject_handshake on;", "")
        self.access_log = base / "access.log"
        config = base / "nginx.conf"
        config.write_text(
            f"daemon off; master_process off; pid {base}/nginx.pid;\n"
            f"error_log {base}/error.log; events {{ worker_connections 128; }}\n"
            f"http {{ client_body_temp_path {base}/body; proxy_temp_path {base}/proxy;\n"
            f"fastcgi_temp_path {base}/fastcgi; uwsgi_temp_path {base}/uwsgi;\n"
            f"scgi_temp_path {base}/scgi;\n"
            + preamble + server + catch_all + "\n}\n"
        )
        validation = subprocess.run(["nginx", "-t", "-p", str(base), "-c", str(config)],
                                    text=True, capture_output=True)
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        process = subprocess.Popen(["nginx", "-p", str(base), "-c", str(config)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.wait(timeout=5))
        self.addCleanup(process.terminate)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                if self.request("GET", "/health") == 200:
                    return
            except OSError:
                time.sleep(.05)
        self.fail("Nginx did not start")

    def request(self, method, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body="{}" if method == "POST" else None,
                               headers={"Host": "localhost"})
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_retired_control_routes_never_reach_backend(self):
        for method in ("GET", "POST", "DELETE"):
            for path in ("/api/control", "/api/control/hosts", "/api/control/operations"):
                with self.subTest(method=method, path=path):
                    self.assertEqual(self.request(method, path), 404)
        self.assertEqual(self.request("GET", "/api/sessions"), 200)

    def test_auth_rate_limit_does_not_block_session_reads(self):
        statuses = [self.request("POST", "/api/auth") for _ in range(15)]
        self.assertIn(429, statuses)
        for _ in range(20):
            self.assertEqual(self.request("GET", "/api/sessions"), 200)

    def test_unknown_hosts_are_closed_without_a_response(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            with self.assertRaises(http.client.RemoteDisconnected):
                connection.request("GET", "/", headers={"Host": "unknown.test"})
                connection.getresponse()
        finally:
            connection.close()

    def test_access_log_omits_query_credentials(self):
        self.assertEqual(self.request("GET", "/api/events?token=private-test-token"), 200)
        log = self.access_log.read_text()
        self.assertIn("/api/events", log)
        self.assertNotIn("private-test-token", log)


if __name__ == "__main__":
    unittest.main()
