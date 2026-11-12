import shlex
import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent


class DeploymentScriptTests(unittest.TestCase):
    def test_shell_scripts_parse_and_obsolete_ingress_is_absent(self):
        scripts = [REPO / "agent-container", REPO / "hapi-release.env",
                   *sorted((REPO / "deploy").glob("*.sh"))]
        self.assertTrue(scripts)
        for script in scripts:
            with self.subTest(script=script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)
        deployment_text = "\n".join(
            path.read_text() for path in (REPO / "deploy").iterdir() if path.is_file()
        )
        self.assertNotIn("/manage", deployment_text)
        self.assertNotIn("frpc", deployment_text)
        self.assertNotIn("frps", deployment_text)

    def test_nginx_rejects_retired_control_api_and_keeps_safe_logs(self):
        config = (REPO / "deploy/nginx-hapi.conf").read_text()
        self.assertIn("location ^~ /api/control/ { return 404; }", config)
        self.assertNotIn("127.0.0.1:3010", config)
        self.assertIn("proxy_pass http://127.0.0.1:3006", config)
        self.assertIn("$request_method $uri $server_protocol", config)
        self.assertNotIn("$request_uri", config.split("limit_req_zone", 1)[0])
        self.assertEqual(config.count("server_tokens off;"), 2)
        self.assertNotIn("\nserver_tokens off;", config)

    def test_nginx_only_serves_the_configured_public_host(self):
        config = (REPO / "deploy/nginx-hapi.conf").read_text()
        self.assertIn("listen 80 default_server;", config)
        self.assertIn("listen [::]:80 default_server;", config)
        self.assertIn("listen 443 ssl default_server;", config)
        self.assertIn("listen [::]:443 ssl default_server;", config)
        self.assertIn("ssl_reject_handshake on;", config)
        self.assertIn("return 444;", config)
        self.assertEqual(config.count("default_server"), 4)

    def test_nginx_allows_attachment_sized_bodies_and_caps_auth(self):
        config = (REPO / "deploy/nginx-hapi.conf").read_text()
        self.assertIn("client_max_body_size 100m;", config)
        self.assertIn("client_max_body_size 4k;", config)

    def test_vps_removes_the_package_default_site(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("rm -f /etc/nginx/sites-enabled/default", script)

    def test_hapi_release_binary_is_pinned_and_verified(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn('source "$SCRIPT_DIR/../hapi-release.env"', script)
        self.assertIn('https://github.com/tiann/hapi/releases/download/v${HAPI_VERSION}/', script)
        self.assertIn('echo "$HAPI_ARCHIVE_SHA256  $HAPI_ARCHIVE" | sha256sum -c -', script)
        self.assertIn('tar -xOzf "$HAPI_ARCHIVE" hapi', script)
        self.assertIn('"$HAPI_BIN_TMP" --version', script)
        self.assertFalse((REPO / "deploy/build-hapi.sh").exists())

    def test_image_hapi_install_requires_a_version_and_checks_the_binary(self):
        dockerfile = (REPO / 'Dockerfile').read_text().replace('\\\n', '')
        install = next(line.removeprefix('RUN ') for line in dockerfile.splitlines()
                       if line.startswith('RUN npm i -g --registry=https://registry.npmjs.org '))
        commands = '''HAPI_VERSION="$1"
TEST_INSTALLED_VERSION="$2"
npm() { printf '%s\\n' "$@"; }
hapi() { printf 'hapi version: %s\\n' "$TEST_INSTALLED_VERSION"; }
''' + install
        for requested, installed, success in (
            ('0.0.1', '0.0.1', True),
            ('0.0.1', '0.0.2', False),
            ('', '0.0.1', False),
        ):
            with self.subTest(requested=requested, installed=installed):
                result = subprocess.run(['sh', '-ec', commands, 'test', requested, installed],
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                if requested:
                    self.assertIn(f'@twsxtd/hapi@{requested}', result.stdout.splitlines())
                else:
                    self.assertEqual(result.stdout, '')

    def test_vps_import_preserves_existing_hapi_identity(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("--import-hapi-home", script)
        self.assertIn('candidate = json.loads(settings_path.read_text()).get("cliApiToken")', script)
        self.assertIn("Refusing to import over a nonempty HAPI state directory", script)

    def test_vps_no_longer_builds_or_accepts_custom_hapi_assets(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertNotIn("--hapi-dist", script)
        self.assertNotIn("bun", script.lower())
        self.assertNotIn("git clone", script)
        self.assertNotIn("hapi-runtime", script)

    def test_vps_supports_apt_and_dnf_systems(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("command -v apt-get", script)
        self.assertIn("apt-get update", script)
        self.assertIn("apt-get install -y", script)
        self.assertIn("command -v dnf", script)
        self.assertIn("dnf install -y", script)
        self.assertIn('"$PYTHON_BIN" -m venv', script)
        self.assertNotIn("requires a dnf-based VPS", script)

    def test_vps_installs_only_missing_packages(self):
        script = (REPO / 'deploy/vps-setup.sh').read_text()
        dependencies = script[script.index('STEP=0'):script.index('# Package-provided default sites')]
        stubs = r'''
TEST_MANAGER="$1"
TEST_MISSING="$2"
TEST_DPKG_STATUS="$3"
TEST_INSTALL_EXIT="$4"
command() {
  case "$2" in
    apt-get|dnf) [[ "$2" == "$TEST_MANAGER" ]] ;;
    systemctl|python3|python3.11) printf '/test/%s\n' "$2" ;;
    *) return 1 ;;
  esac
}
dpkg-query() {
  if [[ " $TEST_MISSING " == *" ${!#} "* ]]; then
    printf '%s' "$TEST_DPKG_STATUS"
    [[ -n "$TEST_DPKG_STATUS" ]]
  else
    printf installed
  fi
}
rpm() { [[ " $TEST_MISSING " != *" ${!#} "* ]]; }
apt-get() {
  printf 'CALL apt-get %s\n' "$*"
  [[ "$1" != install ]] || return "$TEST_INSTALL_EXIT"
}
dnf() { printf 'CALL dnf %s\n' "$*"; return "$TEST_INSTALL_EXIT"; }
'''
        for manager, missing, status, install_exit, expected in (
            ('apt-get', '', '', 0, []),
            ('apt-get', 'curl nginx', '', 0,
             ['CALL apt-get update', 'CALL apt-get install -y curl nginx']),
            ('apt-get', 'nginx', 'config-files', 0,
             ['CALL apt-get update', 'CALL apt-get install -y nginx']),
            ('dnf', '', '', 0, []),
            ('dnf', 'curl python3.11-pip', '', 0,
             ['CALL dnf install -y curl python3.11-pip']),
            ('apt-get', 'curl', '', 23,
             ['CALL apt-get update', 'CALL apt-get install -y curl']),
            ('dnf', 'curl', '', 23, ['CALL dnf install -y curl']),
        ):
            with self.subTest(manager=manager, missing=missing, status=status, exit=install_exit):
                result = subprocess.run(
                    ['bash', '-Eeuc', stubs + dependencies, 'test', manager, missing,
                     status, str(install_exit)], text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, install_exit, result.stderr)
                calls = [line for line in result.stdout.splitlines() if line.startswith('CALL ')]
                self.assertEqual(calls, expected)
                self.assertIn('Check system dependencies', result.stdout)
                self.assertIn(f'Package manager: {manager}', result.stdout)
                if not missing:
                    self.assertIn('skipping', result.stdout)
                if install_exit:
                    self.assertIn('Failed during: Check system dependencies', result.stderr)
                    self.assertIn('exit 23', result.stderr)

    def test_vps_health_check_reports_waits_and_failure(self):
        script = (REPO / 'deploy/vps-setup.sh').read_text()
        progress = script[script.index('STEP=0'):script.index('step "Check system dependencies"')]
        health = script[script.index('step "Wait for HAPI health check"'):script.index('echo "HAPI is ready')]
        stubs = r'''
TEST_READY_AFTER="$1"
TEST_CALLS=0
curl() {
  TEST_CALLS=$((TEST_CALLS + 1))
  [[ "$TEST_CALLS" -ge "$TEST_READY_AFTER" ]]
}
sleep() { :; }
systemctl() { printf 'SERVICE %s\n' "$*"; }
'''
        for ready_after in (1, 3, 31):
            with self.subTest(ready_after=ready_after):
                result = subprocess.run(
                    ['bash', '-Eeuc', progress + stubs + health, 'test', str(ready_after)],
                    text=True, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, int(ready_after > 30), result.stderr)
                self.assertIn('Wait for HAPI health check', result.stdout)
                self.assertEqual(result.stdout.count('Waiting for HAPI to become ready'),
                                 min(ready_after - 1, 30))
                if ready_after > 30:
                    self.assertIn('journalctl -u agent-hapi-hub.service', result.stderr)
                    self.assertNotIn('SERVICE ', result.stdout)
                else:
                    self.assertIn('SERVICE is-active agent-hapi-hub.service', result.stdout)

    def test_vps_selects_verified_hapi_archive_for_each_architecture(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        release = REPO / "hapi-release.env"
        values = dict(entry.split('=', 1) for entry in shlex.split(release.read_text(), comments=True))
        self.assertRegex(values['HAPI_VERSION'], r'^\d+\.\d+\.\d+$')
        start = script.index('case "$(uname -m)" in')
        selection = script[start:script.index('esac', start) + len('esac')]
        for arch, target, key in (
            ('x86_64', 'x64-baseline', 'HAPI_SHA256_X64_BASELINE'),
            ('amd64', 'x64-baseline', 'HAPI_SHA256_X64_BASELINE'),
            ('aarch64', 'arm64', 'HAPI_SHA256_ARM64'),
            ('arm64', 'arm64', 'HAPI_SHA256_ARM64'),
        ):
            with self.subTest(arch=arch):
                self.assertRegex(values[key], r'^[0-9a-f]{64}$')
                result = subprocess.run([
                    'bash', '-euc',
                    'source "$1"\nTEST_ARCH="$2"\nuname() { printf "%s\\n" "$TEST_ARCH"; }\n'
                    + selection + '\nprintf "%s\\n" "$HAPI_ARCHIVE_NAME" "$HAPI_ARCHIVE_SHA256"',
                    'test', str(release), arch,
                ], check=True, text=True, capture_output=True)
                self.assertEqual(result.stdout.splitlines(),
                                 [f'hapi-linux-{target}.tar.gz', values[key]])

    def test_vps_reloads_an_already_running_nginx(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        enable = script.index("systemctl enable --now")
        reload = script.index("systemctl reload nginx", enable)
        health_check = script.index('step "Wait for HAPI health check"')
        self.assertLess(enable, reload)
        self.assertLess(reload, health_check)

    def test_vps_restarts_updated_application_services(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        enable = script.index("systemctl enable --now")
        restart = script.index("systemctl restart agent-hapi-hub.service", enable)
        health_check = script.index('step "Wait for HAPI health check"')
        self.assertLess(enable, restart)
        self.assertLess(restart, health_check)

    def test_token_rotation_updates_both_token_sources_and_checks_health(self):
        script = (REPO / "deploy/rotate-hapi-token.sh").read_text()
        self.assertIn('TOKEN_FILE="$CONFIG/hapi-access-token"', script)
        self.assertIn('ENV_FILE="$CONFIG/hub.env"', script)
        self.assertIn("secrets.token_urlsafe(48)", script)
        self.assertIn("printf 'CLI_API_TOKEN=%s\\n'", script)
        self.assertIn('chmod 600 "$TOKEN_TMP" "$ENV_TMP"', script)
        self.assertIn('systemctl restart "$SERVICE"', script)
        self.assertIn("http://127.0.0.1:3006/health", script)
        self.assertNotIn('echo "$TOKEN"', script)

    def test_hapi_runs_official_binary_without_public_relay(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn('WorkingDirectory=$STATE/hapi', script)
        self.assertIn('ExecStart=$HAPI_BIN hub --no-relay', script)

    def test_native_push_relays_are_disabled_by_default(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("Environment=HAPI_ANDROID_PUSH=off", script)
        self.assertIn("Environment=HAPI_IOS_PUSH=off", script)

    def test_renewal_uses_the_served_webroot_without_stopping_nginx(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        command = next(line.removeprefix("ExecStart=") for line in script.splitlines()
                       if line.startswith("ExecStart=$CERTBOT renew "))
        args = shlex.split(command)
        self.assertIn('--webroot', args)
        webroot = args[args.index('--webroot-path') + 1]
        self.assertIn(f'root {webroot};', (REPO / 'deploy/nginx-hapi.conf').read_text())
        self.assertEqual(args[args.index('--deploy-hook') + 1], '/usr/bin/systemctl reload nginx')
        self.assertNotIn('--standalone', args)


if __name__ == "__main__":
    unittest.main()
