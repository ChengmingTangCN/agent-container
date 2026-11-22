"""Exercise the Steam launcher against a recording Docker CLI."""

import json
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent

DOCKER_STUB = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["STEAM_TEST_CALLS"], "a") as output:
    output.write(json.dumps(args) + "\n")

config = json.loads(Path(os.environ["STEAM_TEST_CONFIG"]).read_text())
if args[:2] == ["image", "inspect"]:
    sys.exit(0 if config.get("image_exists", True) else 1)
if args[:2] == ["container", "inspect"]:
    sys.exit(0 if config.get("exists") else 1)
if args[0] == "inspect":
    template = args[2]
    if "agent-steam.schema" in template:
        print(config.get("schema", "1"))
    elif ".Config.Image" in template:
        print(config.get("image", "current-image"))
    elif ".State.Running" in template:
        print("true" if config.get("running") else "false")
    else:
        sys.exit(9)
    sys.exit(0)
if args[0] == "build":
    sys.exit(config.get("build_exit", 0))
if args[0] == "run":
    if args[-1] == "check":
        sys.exit(config.get("check_exit", 0))
    sys.exit(config.get("run_exit", 0))
if args[0] in ("attach", "rm"):
    sys.exit(0)
sys.exit(9)
'''


def userns_restricted():
    enabled = Path("/sys/module/apparmor/parameters/enabled")
    restriction = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
    return (
        enabled.exists()
        and enabled.read_text().strip() == "Y"
        and restriction.exists()
        and restriction.read_text().strip() == "1"
    )


class SteamLauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="steam-launcher-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.data = self.base / "state"
        bindir = self.base / "bin"
        bindir.mkdir()
        docker = bindir / "docker"
        docker.write_text(DOCKER_STUB)
        docker.chmod(0o755)

        self.calls_path = self.base / "calls.jsonl"
        self.config_path = self.base / "docker.json"
        self.configure()
        self.env = os.environ.copy()
        self.env.update({
            "HOME": str(self.home),
            "AGENT_CONTAINER_DATA_DIR": str(self.data),
            "PATH": str(bindir) + os.pathsep + self.env["PATH"],
            "STEAM_TEST_CALLS": str(self.calls_path),
            "STEAM_TEST_CONFIG": str(self.config_path),
        })
        for name in (
            "ALL_PROXY",
            "DISPLAY",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "PULSE_COOKIE",
            "STEAM_CONTAINER_APPARMOR_PROFILE",
            "XAUTHORITY",
            "XDG_RUNTIME_DIR",
            "all_proxy",
            "http_proxy",
            "https_proxy",
            "no_proxy",
        ):
            self.env.pop(name, None)

        runtime = self.base / "runtime"
        pulse_dir = runtime / "pulse"
        pulse_dir.mkdir(parents=True)
        self.pulse_socket = pulse_dir / "native"
        self.bind_socket(self.pulse_socket)
        self.xauthority = self.home / ".Xauthority"
        self.xauthority.write_bytes(b"")
        self.pulse_cookie = self.home / "pulse-cookie"
        self.pulse_cookie.write_bytes(b"")
        self.env.update({
            "XDG_RUNTIME_DIR": str(runtime),
            "XAUTHORITY": str(self.xauthority),
            "PULSE_COOKIE": str(self.pulse_cookie),
        })

        x11_dir = Path("/tmp/.X11-unix")
        if x11_dir.is_dir() and os.access(x11_dir, os.W_OK):
            self.display = f":{10000 + os.getpid() % 50000}"
            self.x_socket = x11_dir / f"X{self.display[1:]}"
            try:
                self.bind_socket(self.x_socket)
            except OSError:
                self.x_socket = None
        else:
            self.display = ":14999"
            self.x_socket = None
        self.env["DISPLAY"] = self.display
        self.launcher = REPO / "steam-container"

    def bind_socket(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        listener.close()
        self.addCleanup(path.unlink, missing_ok=True)

    def configure(self, **values):
        self.config_path.write_text(json.dumps(values))

    def launch(self, *options):
        return subprocess.run(
            ["bash", str(self.launcher), *options],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def calls(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def run_calls(self):
        return [call for call in self.calls() if call[0] == "run"]

    def runtime_check_args(self):
        return next(call for call in self.run_calls() if call[-1] == "check")

    @staticmethod
    def mount_specs(args):
        return [args[index + 1] for index, arg in enumerate(args) if arg == "-v"]

    def test_preflight_uses_host_network_devices_and_narrow_socket_mounts(self):
        result = self.launch("--check", "--no-apparmor-profile")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.runtime_check_args()
        mounts = self.mount_specs(args)

        self.assertEqual(args[args.index("--network") + 1], "host")
        self.assertIn("seccomp=unconfined", args)
        self.assertNotIn("--privileged", args)
        self.assertIn(f"{self.data}/steam/home:/home/dev", mounts)
        self.assertIn(
            f"{self.pulse_socket}:/run/steam/pulse-native:ro", mounts
        )
        self.assertIn(
            f"{self.pulse_cookie}:/run/steam/pulse-cookie:ro", mounts
        )
        self.assertIn(
            f"{self.xauthority}:/run/steam/xauthority:ro", mounts
        )
        if self.x_socket is not None:
            self.assertIn(f"{self.x_socket}:{self.x_socket}:ro", mounts)
        self.assertFalse(any("docker.sock" in mount for mount in mounts))
        self.assertFalse(any("/run/user/" in mount for mount in mounts))

    def test_dri_group_ids_are_added_without_privileged_mode(self):
        dri = Path("/dev/dri")
        devices = list(dri.glob("*")) if dri.is_dir() else []
        devices = [path for path in devices if path.is_char_device()]
        if not devices:
            self.skipTest("host has no /dev/dri device")

        result = self.launch("--check", "--no-apparmor-profile")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.runtime_check_args()
        self.assertIn("--device", args)
        self.assertEqual(args[args.index("--device") + 1], "/dev/dri")
        added_groups = {
            args[index + 1] for index, arg in enumerate(args) if arg == "--group-add"
        }
        self.assertEqual(added_groups, {str(path.stat().st_gid) for path in devices})
        self.assertIn("STEAM_REQUIRE_HARDWARE_GPU=1", args)
        self.assertNotIn("--privileged", args)

    def test_bridge_mode_drops_an_unreachable_host_local_proxy(self):
        self.env["HTTP_PROXY"] = "http://user:secret@127.0.0.1:7890"
        result = self.launch(
            "--check", "--bridge-network", "--no-apparmor-profile"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.runtime_check_args()
        self.assertNotIn("--network", args)
        self.assertFalse(any(arg.startswith("HTTP_PROXY=") for arg in args))
        self.assertFalse(any(arg.startswith("http_proxy=") for arg in args))
        self.assertIn("Ignoring host-local HTTP_PROXY", result.stderr)
        self.assertNotIn("user:secret", result.stdout + result.stderr)

    def test_host_network_keeps_a_host_local_proxy(self):
        self.env["HTTPS_PROXY"] = "http://127.0.0.1:7890"
        result = self.launch("--check", "--no-apparmor-profile")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.runtime_check_args()
        self.assertEqual(args[args.index("--network") + 1], "host")
        self.assertIn("HTTPS_PROXY=http://127.0.0.1:7890", args)
        self.assertIn("https_proxy=http://127.0.0.1:7890", args)

    def test_library_paths_receive_stable_nonshared_mounts(self):
        first = self.base / "games one"
        second = self.base / "games-two"
        first.mkdir()
        second.mkdir()
        result = self.launch(
            "--check",
            "--no-apparmor-profile",
            "--library",
            str(first),
            "--library",
            str(second),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        mounts = self.mount_specs(self.runtime_check_args())
        library_mounts = [mount for mount in mounts if ":/home/dev/SteamLibrary-" in mount]
        self.assertEqual(len(library_mounts), 2)
        self.assertTrue(any(
            mount.startswith(f"{first}:/home/dev/SteamLibrary-games-one-")
            for mount in library_mounts
        ))
        self.assertTrue(any(
            mount.startswith(f"{second}:/home/dev/SteamLibrary-games-two-")
            for mount in library_mounts
        ))
        self.assertEqual(len(set(library_mounts)), 2)

    def test_failed_preflight_never_starts_the_named_container(self):
        self.configure(check_exit=1)
        result = self.launch("--check", "--no-apparmor-profile")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.run_calls()), 1)
        self.assertFalse(any(call[:2] == ["container", "inspect"] for call in self.calls()))

    def test_running_container_is_attached_and_stopped_container_is_recreated(self):
        self.configure(exists=True, running=True)
        result = self.launch("--skip-check", "--no-apparmor-profile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[0] == "attach" for call in self.calls()))
        self.assertFalse(any(call[0] == "rm" for call in self.calls()))

        self.calls_path.write_text("")
        self.configure(exists=True, running=False)
        result = self.launch("--skip-check", "--no-apparmor-profile")
        self.assertEqual(result.returncode, 0, result.stderr)
        operations = [call[0] for call in self.calls()]
        self.assertIn("rm", operations)
        self.assertEqual(operations[-1], "run")

    @unittest.skipUnless(
        userns_restricted(), "host does not restrict unprivileged user namespaces"
    )
    def test_missing_apparmor_profile_fails_before_docker(self):
        self.env["STEAM_CONTAINER_APPARMOR_PROFILE"] = "agent-steam-profile-missing"
        result = self.launch("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Required AppArmor profile is not installed", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_dockerfile_preserves_the_domestic_mirror_and_fallback(self):
        dockerfile = (REPO / "steam/Dockerfile").read_text()
        self.assertIn("APT_MIRROR=http://mirrors.ustc.edu.cn/ubuntu", dockerfile)
        self.assertIn("APT::Update::Error-Mode=any", dockerfile)
        self.assertIn("http://archive.ubuntu.com/ubuntu", dockerfile)
        self.assertIn("dpkg --add-architecture i386", dockerfile)
        self.assertIn("ENV PATH=/usr/games:", dockerfile)

    def test_apparmor_support_is_namespaced_and_does_not_change_host_default(self):
        profile = (REPO / "steam/apparmor/agent-container-steam").read_text()
        installer = (REPO / "steam/install-apparmor-profile.sh").read_text()
        self.assertIn("profile agent-container-steam", profile)
        self.assertIn("userns,", profile)
        self.assertIn('PROFILE_TARGET="/etc/apparmor.d/${PROFILE_NAME}"', installer)
        self.assertIn(
            "/proc/sys/kernel/apparmor_restrict_unprivileged_userns", installer
        )
        self.assertNotIn("sysctl", installer)
        self.assertNotIn(
            "kernel.apparmor_restrict_unprivileged_userns=0", installer
        )

    def test_launcher_never_grants_privileged_or_docker_control(self):
        launcher = (REPO / "steam-container").read_text()
        self.assertNotIn("--privileged", launcher)
        self.assertNotIn("docker.sock", launcher)
        self.assertIn("--security-opt seccomp=unconfined", launcher)
        self.assertIn("--security-opt", launcher)
        self.assertIn("bwrap --ro-bind / /", (REPO / "steam/entrypoint.sh").read_text())


if __name__ == "__main__":
    unittest.main()
