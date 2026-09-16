# Operations

## Deploy

The VPS installer requires x86_64, dnf, systemd, a public IPv4 address or domain,
and inbound ports 80/443. From this repository on the VPS:

```bash
sudo ./deploy/vps-setup.sh hapi.example.com
```

It installs Nginx, TLS, and the unmodified HAPI Hub listening on `127.0.0.1:3006`.
Systemd restarts the Hub; native Android/iOS push relays are disabled. A timer
handles certificate renewal.

| Content | Path |
| --- | --- |
| Hub data / SQLite | `/var/lib/agent-hapi/hapi/` |
| Access token | `/etc/agent-hapi/hapi-access-token` |
| Hub environment | `/etc/agent-hapi/hub.env` |
| Hub / PWA runtime | `/opt/agent-hapi/hapi-runtime/` |

HAPI is pinned to `v0.30.7`, commit `0239edf38e2da653d662f31039e24ccea04c7837`;
Bun is pinned to `1.4.0`. The build verifies the tag, checks PWA types, and builds
upstream assets. To avoid building on a small VPS, use a machine with Git and Bun:

```bash
./deploy/build-hapi.sh /tmp/hapi-build
# Transfer hub/dist and web/dist to the VPS, preserving their directory structure.
sudo ./deploy/vps-setup.sh --hapi-dist /path/to/hapi-build hapi.example.com
```

The build directory must be new or created by this script. Rebuilding discards
changes and artifacts in that directory. Do not supply older patched PWA assets.

## Maintain

```bash
systemctl status agent-hapi-hub nginx agent-hapi-cert-renew.timer
journalctl -u agent-hapi-hub -n 100 --no-pager
curl -fsS https://hapi.example.com/health
```

Back up `/etc/agent-hapi/` and the Hub data before updating this repository and
rerunning the installer. Use a consistent SQLite backup or stop the Hub before
copying the complete data directory; copying a live database's main file alone
is insufficient. Back up local agent state separately and protect it as credentials.

To import a stopped Hub's data or consistent backup into an empty data directory:

```bash
sudo ./deploy/vps-setup.sh --import-hapi-home /path/to/backup hapi.example.com
```

## Migrate from codex-container

Finish active tasks, then stop and remove the old `codex-*` containers. Keep their
mounted project files and state. With all old containers stopped, rename
`~/.codex-container` to `~/.agent-container` if the destination does not exist;
do not merge two existing state roots. Alternatively, set
`AGENT_CONTAINER_DATA_DIR` to the existing state directory. Replace
`CODEX_CONTAINER_DATA_DIR` in your shell configuration, reinstall the launcher
as `~/.local/bin/agent-container`, and remove the old launcher symlink.
Project hashes are unchanged, so per-project credentials and native resume state
are reused. Legacy containers with globally shared state must be recreated;
only the documented seed files are copied into new project state.

On an existing VPS, back up state and configuration, disable and stop
`codex-hapi-hub.service` and `codex-hapi-cert-renew.timer`, and wait for any active
`codex-hapi-cert-renew.service` to finish. Move `/var/lib/codex-hapi` to
`/var/lib/agent-hapi` and `/etc/codex-hapi` to `/etc/agent-hapi`, only when the new
paths do not exist. The installer updates state ownership and preserves the token.
Remove `/etc/nginx/conf.d/codex-hapi.conf` and rerun the installer. It creates fresh
runtime files and certificates under `/opt/agent-hapi`; keep the old runtime and
certificate tree as a backup until the new deployment works. Disable any legacy
host-control services too; retired `/api/control` routes return 404.

The installer does not migrate live deployments automatically. Local Runner
containers keep their credentials and Hub URL; recreate them with the new launcher.

## Troubleshoot

Start with `docker logs <container-name>`. Check the Hub URL and credentials in
that project's `hapi/settings.json`. `hapi auth login` does not save `HAPI_API_URL`;
export it each time or set `apiUrl` in that file. Recreate containers after changing
the URL or proxy, because existing containers keep their original environment.

Both cases of `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY` are supported;
nonempty lowercase values take precedence. For a directly reachable HTTPS IP,
bypass the proxy if HAPI reports a TLS `servername` error:

```bash
export NO_PROXY=localhost,127.0.0.1,::1,203.0.113.10  # Use your VPS IP.
export no_proxy="$NO_PROXY"
```

If an agent fails to start, check its credentials, account balance, and referenced
configuration files. For example, a file named by `model_catalog_json` is not one
of the seed files and must be copied separately.

## Verify

```bash
python3 -m unittest discover -v
```

Launcher tests use simulated Docker; deployment tests check scripts and real
Nginx routing, rate limits, and logs. Nginx tests skip when Nginx is unavailable.
Real integration checks should cover Runner readiness, permission approval and
denial, message sync, Hub restarts, and native session resume after container
recreation. Mobile UI, installation, and each additional agent need separate
verification. Earlier Codex checks required approving commands outside its inner
sandbox; they did not verify that inner sandbox.
