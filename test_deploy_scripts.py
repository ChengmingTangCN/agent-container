import shlex
import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent


class DeploymentScriptTests(unittest.TestCase):
    def test_shell_scripts_parse_and_obsolete_ingress_is_absent(self):
        scripts = [REPO / "agent-container", *sorted((REPO / "deploy").glob("*.sh"))]
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

    def test_hapi_release_binary_is_pinned_and_verified(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn('HAPI_VERSION="v0.30.7"', script)
        self.assertIn("https://github.com/tiann/hapi/releases/download/", script)
        self.assertIn('echo "$HAPI_ARCHIVE_SHA256  $HAPI_ARCHIVE" | sha256sum -c -', script)
        self.assertIn('tar -xOzf "$HAPI_ARCHIVE" hapi', script)
        self.assertIn('"$HAPI_BIN_TMP" --version', script)
        self.assertFalse((REPO / "deploy/build-hapi.sh").exists())

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

    def test_vps_selects_verified_hapi_archive_for_each_architecture(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("x86_64|amd64)", script)
        self.assertIn("aarch64|arm64)", script)
        self.assertIn('HAPI_ARCHIVE_NAME="hapi-linux-x64-baseline.tar.gz"', script)
        self.assertIn('HAPI_ARCHIVE_NAME="hapi-linux-arm64.tar.gz"', script)
        self.assertIn("d405bd3e592d6444089884cf5b97640eecfdcd8ad37ab06a8e5611f1811c8a41", script)
        self.assertIn("4c11ed308412e4510289ed5e5875a43f60f7ee5cee9cbfdc0e2d97f55851a193", script)

    def test_vps_reloads_an_already_running_nginx(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        enable = script.index("systemctl enable --now")
        reload = script.index("systemctl reload nginx", enable)
        health_check = script.index("for _ in {1..30}")
        self.assertLess(enable, reload)
        self.assertLess(reload, health_check)

    def test_vps_restarts_updated_application_services(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        enable = script.index("systemctl enable --now")
        restart = script.index("systemctl restart agent-hapi-hub.service", enable)
        health_check = script.index("for _ in {1..30}")
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
