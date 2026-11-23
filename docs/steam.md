# Steam desktop access

`agent-container --steam` adds host GPU, audio and X11 display access to a
normal project container. It does not install Steam. Install the Steam `.deb`
yourself inside the container; HAPI, Codex, Pi and OpenCode continue to run in
the same container.

This is headful: the Steam window opens on the desktop where the launcher runs.
It is intended for a local workstation. For browser or remote-streaming gaming,
the community projects [LinuxServer Steam](https://github.com/linuxserver/docker-steam),
[Steam Headless](https://github.com/Steam-Headless/docker-steam-headless), and
[Games on Whales](https://github.com/games-on-whales/gow) provide complete
virtual-display and streaming environments.

## Requirements

- An x86_64 Linux host with Docker and a working X11 or XWayland display.
- An audio server reachable through a PipeWire-Pulse or PulseAudio socket.
- AMD/Intel `/dev/dri` devices, or NVIDIA with the NVIDIA Container Toolkit.
- A Steam `.deb` and any package dependencies you choose to install.
- On Ubuntu systems that restrict unprivileged user namespaces with AppArmor,
  the named profile described below.

The base agent image uses Ubuntu 24.04. It does not ship Steam, Mesa/Vulkan
userspace drivers or Steam's 32-bit dependencies; install what your `.deb` and
GPU require with `apt`.

## Start

Install the host AppArmor profile once if Ubuntu restricts unprivileged user
namespaces. The installer only adds a named profile; it does not change the
kernel setting or other application profiles.

```bash
sudo ./steam/install-apparmor-profile.sh
```

Start a persistent project container with host access:

```bash
agent-container --hapi --steam ~/dev/myproj
docker exec -it <container> bash
```

Install Steam and start it from that shell:

```bash
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install ./steam.deb
steam
```

For interactive use, keep the container after exit:

```bash
agent-container --steam --persistent ~/dev/myproj
```

The first Steam launch normally downloads more than 1 GB. Steam and its data
live in the container's writable layer: stop/start preserves them, while
removing or rebuilding the container loses them. A container created without
`--steam` cannot gain the extra mounts in place; recreate it before installing
Steam.

## Host access

The launcher is deliberately narrower than `--privileged`:

| Host resource | Container access | Purpose |
| --- | --- | --- |
| `/dev/dri` | Device plus its numeric GIDs | AMD/Intel graphics and Vulkan |
| NVIDIA devices | `--gpus all` and NVIDIA runtime variables | NVIDIA graphics |
| X11 socket | Only the current `DISPLAY` socket, read-only | Steam window and input |
| `XAUTHORITY` | Read-only bind mount | Authenticate to the X server |
| Pulse socket | Read-only Unix socket mount | Desktop audio and microphone |
| Pulse cookie | Read-only bind mount | Pulse authentication |
| Network | Host network namespace by default | Steam login, LAN discovery, Remote Play, localhost proxies |

The container also receives `--init` and a 1 GiB shared-memory segment. The
Docker socket, full host runtime directory, host D-Bus, and `--privileged` are
not mounted or enabled.

The container shares the Linux kernel and therefore observes host CPU, memory,
kernel, and mapped GPU details. With no Docker CPU or memory limit, Steam's
System Information page normally reports the host's full resources. Driver
specific tools can still misreport some fields, such as dedicated VRAM.

## Ubuntu AppArmor

Ubuntu can set:

```text
kernel.apparmor_restrict_unprivileged_userns=1
```

This setting restricts ordinary processes from creating unprivileged user
namespaces. Docker containers are also subject to this control. Modern Steam
uses `bubblewrap` and user namespaces for its runtime sandbox, so a container
that otherwise has display and GPU access can still fail with:

```text
unshare: operation not permitted
bwrap: setting up uid map: Permission denied
```

Ubuntu's AppArmor policy language exposes a `userns` permission for this case.
`steam/apparmor/agent-container-steam` is a named unconfined Docker profile with
that permission and is selected explicitly with Docker's `apparmor=` security
option. The container therefore does not need a
`kernel.apparmor_restrict_unprivileged_userns=0` change that would affect the
whole host. The profile does not add filesystem or device confinement beyond
the container's mounts; treating it otherwise would overstate what AppArmor is
doing here.

Docker's default seccomp policy is relaxed for this container because the Steam
Runtime uses a nested sandbox. The launcher compensates by omitting
`--privileged` and Docker control sockets.

If AppArmor is disabled or this user-namespace restriction is not enabled, the
installer leaves the host unchanged and the launcher does not require the
profile.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Steam requires the host AppArmor profile` | Run `sudo ./steam/install-apparmor-profile.sh` |
| `userns` or `bwrap` fails | Confirm AppArmor is enabled, the profile is installed, and the container was recreated with `--steam` |
| Steam window does not appear | Start the container from the desktop session; confirm `DISPLAY`, `XAUTHORITY`, and `/tmp/.X11-unix/X<n>` |
| Audio fails | Confirm `pactl info` works on the host and `$XDG_RUNTIME_DIR/pulse/native` exists |
| Vulkan/GPU fails | Confirm `/dev/dri` or the NVIDIA Container Toolkit is available; install the matching Mesa/Vulkan userspace packages in the container |
| `steam` command not found | Install the `.deb` and use the path it installed; install `dbus-x11` and missing dependencies with `apt` |
| `steam.deb` dependency errors | Run `sudo dpkg --add-architecture i386`, `sudo apt update`, then retry `sudo apt install ./steam.deb` |
| Portal, accessibility, PipeWire, or FUSE warnings appear | These services are optional for the Steam login window unless the corresponding in-game feature needs them |
