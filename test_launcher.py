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
if args[0] in ('run', 'start', 'attach', 'rm'): sys.exit(0)
sys.exit(9)
'''


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='codex-launcher-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.project = self.base / 'projects' / 'a project'
        self.project.mkdir(parents=True)
        self.data = self.home / '.codex-container'
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
        self.env.update(HOME=str(self.home), CODEX_CONTAINER_DATA_DIR=str(self.data),
                        PATH=str(bindir) + os.pathsep + self.env['PATH'],
                        LAUNCHER_TEST_CALLS=str(self.calls_path),
                        LAUNCHER_TEST_CONFIG=str(self.config_path))
        self.env.pop('HAPI_API_URL', None)

    def configure(self, **values):
        self.config_path.write_text(json.dumps({'project': str(self.project), **values}))

    def launch(self, *options, project=None):
        return subprocess.run(['bash', str(REPO / 'codex-container'), *options,
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

    def test_seeds_only_selected_config_once_without_copying_history(self):
        seed = self.data / 'seed' / 'codex'
        seed.mkdir(parents=True)
        (seed / 'auth.json').write_text('reusable-credential')
        (seed / 'AGENTS.md').write_text('project instructions')
        (seed / 'sessions').mkdir()
        (seed / 'sessions' / 'other.jsonl').write_text('other-history')
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual((self.state / 'codex/auth.json').read_text(), 'reusable-credential')
        self.assertFalse((self.state / 'codex/sessions').exists())
        self.assertEqual(os.readlink(self.state / 'pi/agent/AGENTS.md'), '/home/dev/.codex/AGENTS.md')
        (self.state / 'codex/auth.json').write_text('refreshed-project-credential')
        self.assertEqual(self.launch().returncode, 0)
        self.assertEqual((self.state / 'codex/auth.json').read_text(), 'refreshed-project-credential')

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

    def test_unconfigured_runner_explains_local_login_without_starting_container(self):
        result = self.launch('--hapi')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('hapi auth login', result.stderr)
        self.assertFalse(any(call[0] == 'run' for call in self.calls()))

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

    def test_proxy_values_are_forwarded_without_printing_them(self):
        self.env['HTTP_PROXY'] = 'http://username:secret@127.0.0.1:7890'
        self.env.pop('http_proxy', None)
        result = self.launch('--rebuild')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('http_proxy=' + self.env['HTTP_PROXY'], self.run_args())
        build = next(call for call in self.calls() if call[0] == 'build')
        self.assertIn('HTTP_PROXY=' + self.env['HTTP_PROXY'], build)
        self.assertNotIn('username:secret', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
