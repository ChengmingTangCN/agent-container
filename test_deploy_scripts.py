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

    def test_hapi_build_is_pinned_and_uses_unmodified_source(self):
        script = (REPO / "deploy/build-hapi.sh").read_text()
        self.assertIn('HAPI_VERSION="v0.30.7"', script)
        self.assertIn('HAPI_COMMIT="0239edf38e2da653d662f31039e24ccea04c7837"', script)
        self.assertNotIn("PATCH_FILE", script)
        self.assertNotIn(" apply ", script)
        self.assertIn('reset --hard "$HAPI_COMMIT"', script)
        self.assertIn("typecheck", script)

    def test_vps_import_preserves_existing_hapi_identity(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("--import-hapi-home", script)
        self.assertIn('candidate = json.loads(settings_path.read_text()).get("cliApiToken")', script)
        self.assertIn("Refusing to import over a nonempty HAPI state directory", script)

    def test_vps_can_install_a_prebuilt_hapi_distribution(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn("--hapi-dist", script)
        self.assertIn('$HAPI_RELEASE/hub/dist/index.js', script)
        self.assertIn('$HAPI_RELEASE/web/dist/index.html', script)
        self.assertIn('cp -a "$HAPI_RELEASE/$COMPONENT/dist"', script)
        self.assertIn('HAPI_RUNTIME="$BASE/hapi-runtime"', script)

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

    def test_hapi_runs_from_the_bundled_asset_directory(self):
        script = (REPO / "deploy/vps-setup.sh").read_text()
        self.assertIn('WorkingDirectory=$HAPI_RUNTIME/hub', script)

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
