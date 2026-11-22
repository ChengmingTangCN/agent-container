# Steam container

`steam-container` runs the desktop Steam client in its own container while
using the current X11 desktop, audio server, GPU, and host network. It does not
mix Steam state with a project's agent home or mount the Docker socket.

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
- On Ubuntu systems that restrict unprivileged user namespaces with AppArmor,
  the named profile described below.

The image uses Ubuntu 24.04 and preserves the USTC APT mirror for fast package
installation in mainland China. If that mirror is unavailable, the build falls
back to the official Ubuntu archive.

## Start

Install the host AppArmor profile once. The installer only adds a named profile;
it does not change the kernel setting or other application profiles.

```bash
sudo ./steam/install-apparmor-profile.sh
```

Verify host display, audio, Vulkan, user namespaces, and Steam's nested
bubblewrap sandbox:

```bash
./steam-container --check
```

When the launcher detects a host GPU device, the preflight also requires Vulkan
to expose a hardware device rather than accepting `llvmpipe` software rendering
alone.

Start Steam and sign in:

```bash
./steam-container
```

The first launch accepts the distribution's proprietary-software prompt and
downloads the current Steam client and runtime. This is normally more than
1 GB and is kept in the persistent state directory, so later starts reuse it.

The default container name is `agent-steam-<uid>`. Pressing Ctrl-C stops Steam
and the container; the next command reuses the downloaded state. A stopped or
older container is recreated with the current runtime arguments, while the
persistent home remains mounted.

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

Steam receives a private D-Bus session, a 1 GiB shared-memory segment, and a
read-only X socket. The Docker socket, full host runtime directory, host D-Bus,
and `--privileged` are not mounted or enabled.

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
option. The Steam container therefore does not need a
`kernel.apparmor_restrict_unprivileged_userns=0` change that would affect the
whole host. The profile does not add filesystem or device confinement beyond
the container's mounts; treating it otherwise would overstate what AppArmor is
doing here.

Docker's default seccomp policy is also relaxed for this container because the
Steam Runtime uses a nested sandbox. The launcher compensates by omitting
`--privileged` and Docker control sockets.

If AppArmor is disabled or this user-namespace restriction is not enabled, the
installer leaves the host unchanged and the launcher does not require the
profile.

## Options

```text
--check                  Run display/audio/GPU/sandbox checks only.
--skip-check             Skip the runtime preflight.
--rebuild                Rebuild without cache and replace the container.
--library DIR            Mount another Steam library; may be repeated.
--host-network           Use host networking (default).
--bridge-network         Use Docker bridge networking.
--apparmor-profile NAME  Select another installed Docker profile.
--no-apparmor-profile    Use Docker's default AppArmor profile.
```

Host-local proxies such as `http://127.0.0.1:7890` work with host networking.
In bridge mode they are omitted because that address denotes the container
itself. Remote proxies remain available in bridge mode.

To put a Steam library on a specific host disk:

```bash
./steam-container --library /path/to/SteamLibrary
```

Inside Steam, add `/home/dev/SteamLibrary-<name>-<hash>` as a library folder.

## State and removal

Steam credentials, client updates, Proton prefixes, and the default library
live under:

```text
${AGENT_CONTAINER_DATA_DIR:-$HOME/.agent-container}/steam/home
```

Stop and remove the container without deleting this state:

```bash
docker stop agent-steam-"$(id -u)"
docker rm agent-steam-"$(id -u)"
```

Delete the state directory only when a full Steam reset is intended.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Required AppArmor profile is not installed` | Run `sudo ./steam/install-apparmor-profile.sh` |
| `userns` or `bwrap` fails in `--check` | Confirm AppArmor's enabled state, the selected profile, and `apparmor_parser -Q -K` syntax |
| `display` fails | Run the launcher from the desktop session; confirm `DISPLAY`, `XAUTHORITY`, and `/tmp/.X11-unix/X<n>` |
| `audio` fails | Confirm `pactl info` works on the host and `$XDG_RUNTIME_DIR/pulse/native` exists |
| `vulkan` fails | Confirm the host uses the same GPU driver stack and the render/video GIDs are accessible |
| NVIDIA reports no GPU | Install and test the NVIDIA Container Toolkit with `docker run --rm --gpus all ... nvidia-smi` |
| Steam cannot connect through a localhost proxy | Keep host networking, or expose an HTTP proxy on an address reachable from a bridge container |
| Portal, accessibility, PipeWire, or FUSE warnings appear | These services are optional for the Steam login window unless the corresponding in-game feature needs them |

The `xdg-desktop-portal` FUSE warning observed in a minimal container does not
prevent Steam login. A game that explicitly needs desktop portals or FUSE
document access needs additional, narrowly scoped mounts or a purpose-built
remote-gaming image.
