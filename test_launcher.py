"""Run the real launcher against a recording Docker CLI, without touching user data."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent

DOCKER_STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['LAUNCHER_TEST_CALLS'], 'a') as log:
    log.write(json.dumps(args) + '\n')
config = json.loads(Path(os.environ['LAUNCHER_TEST_CONFIG']).read_text())
if args[:2] == ['container', 'inspect']:
    sys.exit(0 if config.get('exists') else 1)
if args[:2] == ['image', 'inspect']:
    sys.exit(0 if config.get('image_exists', True) else 1)
if args[0] == 'inspect':
    template = args[2]
    if 'schema' in template: print(config.get('schema', '3'))
    elif 'project' in template: print(config['project'])
    elif 'mode' in template: print(config.get('mode', 'shell'))
    elif '.Config.Image' in template: print(config.get('image', 'old-image'))
    elif '.State.Running' in template: print('true' if config.get('running') else 'false')
    else: sys.exit(9)
    sys.exit(0)
if args[0] == 'build': sys.exit(config.get('build_exit', 0))
if args[0] == 'exec': sys.exit(config.get('ready_exit', 0))
if args[0] == 'run' and args[-1] == 'setup': sys.exit(config.get('setup_exit', 0))
if args[0] in ('run', 'start', 'attach', 'rm'): sys.exit(0)
sys.exit(9)
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='agent-launcher-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.project = self.base / 'projects' / 'a project'
        self.project.mkdir(parents=True)
        self.data = self.home / '.agent-container'
        digest = hashlib.sha1(os.fsencode(str(self.project))).hexdigest()[:8]
        self.state = self.data / 'projects' / digest
        bindir = self.base / 'bin'
        bindir.mkdir()
        docker = bindir / 'docker'
        docker.write_text(DOCKER_STUB)
        docker.chmod(0o755)
        self.calls_path = self.base / 'calls.jsonl'
        self.config_path = self.base / 'docker.json'
        self.configure()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), AGENT_CONTAINER_DATA_DIR=str(self.data),
                        PATH=str(bindir) + os.pathsep + self.env['PATH'],
                        LAUNCHER_TEST_CALLS=str(self.calls_path),
                        LAUNCHER_TEST_CONFIG=str(self.config_path))
        self.env.pop('HAPI_API_URL', None)

    def configure(self, **values):
        self.config_path.write_text(json.dumps({'project': str(self.project), **values}))

    def launch(self, *options, project=None):
        return subprocess.run(['bash', str(REPO / 'agent-container'), *options,
                               str(project or self.project)], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def calls(self):
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def run_args(self):
        return next(call for call in reversed(self.calls()) if call[0] == 'run')

    def login_fixture(self):
        directory = self.state / 'hapi'
        directory.mkdir(parents=True, exist_ok=True)
        settings = directory / 'settings.json'
        settings.write_text('{"cliApiToken":"dummy-token","machineId":"project-a"}')
        return settings

    def test_interactive_mounts_only_current_project_and_its_state(self):
        (self.home / '.gitconfig').write_text('[user]\nname = Test\n')
        unrelated = self.data / 'projects' / 'another-project' / 'hapi'
        unrelated.mkdir(parents=True)
        (unrelated / 'settings.json').write_text('private-other-project')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.run_args()
        self.assertIn('--rm', args)
        mounts = [args[i + 1] for i, arg in enumerate(args) if arg == '-v']
        expected = {
            f'{self.project}:/work/a project',
            f'{self.state}/codex:/home/dev/.codex',
            f'{self.state}/hapi:/home/dev/.hapi',
            f'{self.state}/opencode/config:/home/dev/.config/opencode',
            f'{self.state}/opencode/data:/home/dev/.local/share/opencode',
            f'{self.state}/opencode/state:/home/dev/.local/state/opencode',
            f'{self.state}/pi:/home/dev/.pi',
            f'{self.home}/.gitconfig:/home/dev/.gitconfig:ro',
        }
        self.assertEqual(set(mounts), expected)
        self.assertEqual((unrelated / 'settings.json').read_text(), 'private-other-project')
        self.assertEqual((self.state / 'codex').stat().st_mode & 0o777, 0o700)

    def test_host_network_container_resolves_its_configured_hostname(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.run_args()
        hostname = args[args.index('--hostname') + 1]
        self.assertIn('--network', args)
        self.assertEqual(args[args.index('--network') + 1], 'host')
        self.assertEqual(args[args.index('--add-host') + 1],
                         f'{hostname}:127.0.1.1')

    def test_seeds_only_selected_config_once_without_copying_history(self):
        seed = self.data / 'seed' / 'codex'
        seed.mkdir(parents=True)
        (seed / 'auth.json').write_text('reusable-credential')
        (seed / 'config.toml').write_text('model_provider = "openai"\n')
        (seed / 'AGENTS.md').write_text('project instructions')
        (seed / 'sessions').mkdir()
        (seed / 'sessions' / 'other.jsonl').write_text('other-history')
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual((self.state / 'codex/auth.json').read_text(), 'reusable-credential')
        self.assertEqual((self.state / 'codex/config.toml').read_text(),
                         'model_provider = "openai"\n')
        self.assertFalse((self.state / 'codex/sessions').exists())
        self.assertEqual(os.readlink(self.state / 'pi/agent/AGENTS.md'), '/home/dev/.codex/AGENTS.md')
        (self.state / 'codex/auth.json').write_text('refreshed-project-credential')
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual((self.state / 'codex/auth.json').read_text(), 'refreshed-project-credential')

    def test_host_codex_login_is_not_imported_without_an_explicit_seed(self):
        host_codex = self.home / '.codex'
        host_codex.mkdir()
        (host_codex / 'auth.json').write_text('host-login')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.state / 'codex/auth.json').exists())

    def test_hapi_runs_upstream_runner_with_same_project_mounts_and_url(self):
        settings = self.login_fixture()
        original = settings.read_text()
        self.env['HAPI_API_URL'] = 'https://hub.example.test'
        result = self.launch('--hapi')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.run_args()
        self.assertIn('-d', args)
        self.assertNotIn('--rm', args)
        self.assertIn('HAPI_API_URL=https://hub.example.test', args)
        self.assertEqual(args[-5:], ['hapi', 'runner', 'start-sync', '--workspace-root', '/work/a project'])
        self.assertIn(f'{self.state}/opencode/config:/home/dev/.config/opencode', args)
        self.assertEqual(settings.read_text(), original)
        self.assertNotIn('dummy-token', result.stdout + result.stderr)

    def test_first_hapi_launch_configures_hub_before_starting_and_checks_rpc(self):
        result = self.launch('--hapi')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        setup = next(i for i, call in enumerate(calls) if call[-1] == 'setup')
        runner = next(i for i, call in enumerate(calls) if '-d' in call)
        ready = next(i for i, call in enumerate(calls) if call[0] == 'exec')
        self.assertLess(setup, runner)
        self.assertLess(runner, ready)
        self.assertIn('--rm', calls[setup])
        self.assertIn('codex login --device-auth', result.stdout)
        self.assertIn('Pi: pi, then /login', result.stdout)

    def test_failed_setup_never_starts_background_runner(self):
        self.configure(setup_exit=1)
        self.assertNotEqual(self.launch('--hapi').returncode, 0)
        self.assertFalse(any('-d' in call or call[0] == 'exec' for call in self.calls()))

    def test_rpc_failure_does_not_report_success_even_for_running_container(self):
        self.login_fixture()
        self.configure(exists=True, mode='hapi', running=True, ready_exit=1)
        result = self.launch('--hapi')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Runner is not ready', result.stderr)
        self.assertIn('docker logs', result.stderr)

    def test_env_file_is_shared_by_setup_and_runner_but_never_build(self):
        envfile = self.home / 'provider.env'
        envfile.write_text('ANTHROPIC_API_KEY=private-key\n')
        result = self.launch('--hapi', '--rebuild', '--env-file', str(envfile))
        self.assertEqual(result.returncode, 0, result.stderr)
        for call in self.calls():
            if call[0] == 'run':
                self.assertIn('--env-file', call)
                self.assertIn(str(envfile), call)
            elif call[0] == 'build':
                self.assertNotIn('--env-file', call)
            self.assertNotIn('private-key', ' '.join(call))
        self.assertNotIn('private-key', result.stdout + result.stderr)

    def test_env_file_cannot_be_silently_ignored_for_existing_container(self):
        self.configure(exists=True, mode='hapi', running=True)
        envfile = self.home / 'provider.env'
        envfile.touch()
        result = self.launch('--hapi', '--env-file', str(envfile))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('original environment', result.stderr)
        self.assertFalse(any(call[0] in ('start', 'run', 'exec') for call in self.calls()))

    def test_stopped_runner_restarts_without_losing_identity(self):
        settings = self.login_fixture()
        original = settings.read_text()
        for name in ('runner.state.json', 'runner.state.json.lock'):
            (settings.parent / name).write_text('stale-pid')
        self.configure(exists=True, mode='hapi', running=False)
        result = self.launch('--hapi')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[0] == 'start' for call in self.calls()))
        self.assertFalse(any(call[0] == 'run' for call in self.calls()))
        self.assertEqual(settings.read_text(), original)
        self.assertFalse((settings.parent / 'runner.state.json.lock').exists())

    def test_online_runner_keeps_its_live_lock(self):
        settings = self.login_fixture()
        lock = settings.parent / 'runner.state.json.lock'
        lock.write_text('live-pid')
        self.configure(exists=True, mode='hapi', running=True, image_exists=False)
        self.assertEqual(self.launch('--hapi').returncode, 0)
        self.assertEqual(lock.read_text(), 'live-pid')
        self.assertFalse(any(call[0] in ('start', 'run', 'build') for call in self.calls()))

    def test_interactive_restart_also_discards_old_runner_pids(self):
        settings = self.login_fixture()
        lock = settings.parent / 'runner.state.json.lock'
        lock.write_text('old-container-pid')
        self.configure(exists=True, mode='shell', running=False)
        result = self.launch('--persistent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(lock.exists())
        self.assertIn('project-a', settings.read_text())
        self.assertTrue(any(call[:2] == ['start', '-ai'] for call in self.calls()))

    def test_rebuild_replaces_owned_old_image_only_after_build_succeeds(self):
        self.configure(exists=True, running=False, image='old-dockerfile-image')
        result = self.launch('--rebuild')
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [call[0] for call in self.calls()]
        self.assertLess(operations.index('build'), operations.index('rm'))
        self.assertLess(operations.index('rm'), operations.index('run'))

    def test_failed_build_keeps_existing_container(self):
        self.configure(exists=True, build_exit=1)
        self.assertNotEqual(self.launch('--rebuild').returncode, 0)
        self.assertFalse(any(call[0] in ('rm', 'run') for call in self.calls()))

    def test_legacy_container_is_not_automatically_reused_or_removed(self):
        self.configure(exists=True, schema='2')
        result = self.launch('--rebuild')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('old or unrelated layout', result.stderr)
        self.assertFalse(any(call[0] in ('rm', 'run', 'build', 'start') for call in self.calls()))

    def test_refuses_mounting_all_state_or_root(self):
        for project in (self.home, Path('/')):
            with self.subTest(project=project):
                self.assertNotEqual(self.launch(project=project).returncode, 0)
        self.assertFalse(self.calls_path.exists())

    def test_rejects_home_and_credential_paths_with_external_state(self):
        self.env['AGENT_CONTAINER_DATA_DIR'] = str(self.base / 'external-state')
        private = self.home / '.ssh' / 'keys'
        private.mkdir(parents=True)
        alias = self.base / 'project-alias'
        alias.symlink_to(private, target_is_directory=True)
        gnupg = self.home / '.gnupg'
        gnupg.mkdir()
        for project in (self.home, self.base, private.parent, private, alias, gnupg):
            with self.subTest(project=project):
                self.assertNotEqual(self.launch(project=project).returncode, 0)
        self.assertFalse(self.calls_path.exists())

    def test_rejects_projects_inside_the_shared_state(self):
        nested = self.data / 'projects' / 'other-project'
        nested.mkdir(parents=True)
        self.assertNotEqual(self.launch(project=nested).returncode, 0)
        self.assertFalse(self.calls_path.exists())

    def test_default_state_root_and_container_use_agent_names(self):
        self.env.pop('AGENT_CONTAINER_DATA_DIR')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.run_args()
        self.assertEqual(args[args.index('--name') + 1], f'agent-a-project-{self.state.name}')
        self.assertIn(f'{self.state}/codex:/home/dev/.codex', args)
        self.assertIn(f'agent-container.project={self.project}', args)

    def test_proxy_values_are_forwarded_without_printing_them(self):
        self.env['HTTP_PROXY'] = 'http://username:secret@127.0.0.1:7890'
        self.env.pop('http_proxy', None)
        result = self.launch('--rebuild')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http_proxy=' + self.env['HTTP_PROXY'], self.run_args())
        build = next(call for call in self.calls() if call[0] == 'build')
        self.assertIn('HTTP_PROXY=' + self.env['HTTP_PROXY'], build)
        self.assertNotIn('username:secret', result.stdout + result.stderr)

    def test_unset_proxies_are_omitted_for_docker_client_defaults(self):
        proxy_names = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')
        for name in proxy_names:
            self.env.pop(name, None)
            self.env.pop(name.lower(), None)
        result = self.launch('--rebuild')
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(call for call in self.calls() if call[0] == 'build')
        run = self.run_args()
        for name in proxy_names:
            self.assertFalse(any(arg.startswith(f'{name}=') for arg in build))
            self.assertFalse(any(arg.startswith(f'{name}=') for arg in run))
            self.assertFalse(any(arg.startswith(f'{name.lower()}=') for arg in run))

    def test_lowercase_proxies_take_precedence_at_build_and_runtime(self):
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'):
            self.env[name] = 'uppercase-value'
            self.env[name.lower()] = 'lowercase-value'
        result = self.launch('--rebuild')
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(call for call in self.calls() if call[0] == 'build')
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY'):
            self.assertIn(f'{name}=lowercase-value', build)
            self.assertIn(f'{name}=lowercase-value', self.run_args())
            self.assertIn(f'{name.lower()}=lowercase-value', self.run_args())


if __name__ == '__main__':
    unittest.main()
