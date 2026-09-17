# Operations

## Deploy

The VPS installer supports current Debian/Ubuntu (`apt-get`) and Fedora/RHEL-family
(`dnf`) systems on x86_64 or arm64. It requires systemd, Python 3.10 or newer, a
public IPv4 address or domain, and inbound ports 80/443. From this repository on
the VPS:

```bash
sudo ./deploy/vps-setup.sh hapi.example.com
```

It installs Nginx, TLS, and the unmodified HAPI Hub listening on `127.0.0.1:3006`.
Systemd restarts the Hub; native Android/iOS push relays are disabled. Certificate
renewal uses Nginx's ACME webroot and reloads Nginx after successful renewal.

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
changes and artifacts in that directory.

## Maintain

```bash
systemctl status agent-hapi-hub nginx agent-hapi-cert-renew.timer
journalctl -u agent-hapi-hub -n 100 --no-pager
curl -fsS https://hapi.example.com/health
sudo /opt/agent-hapi/certbot/bin/certbot renew --dry-run --webroot \
  --webroot-path /var/www/hapi-acme --config-dir /opt/agent-hapi/letsencrypt \
  --work-dir /opt/agent-hapi/letsencrypt-work \
  --logs-dir /opt/agent-hapi/letsencrypt-logs
```

To generate and activate a new Hub access token:

```bash
sudo ./deploy/rotate-hapi-token.sh
sudo cat /etc/agent-hapi/hapi-access-token
```

The script updates both `/etc/agent-hapi/hapi-access-token` and the Hub's native
`CLI_API_TOKEN` in `/etc/agent-hapi/hub.env`, restarts the Hub, and waits for its
local health check. There is no grace period: the old token stops working when
the Hub restarts. Sign in again from the PWA/mobile client and update each Runner.

For a Runner using its project-local `.hapi/settings.json`, authenticate inside
the container and rerun the launcher to verify the connection:

```bash
docker exec -it <container> hapi auth login
agent-container --hapi /path/to/project
```

If a Runner gets `CLI_API_TOKEN` from `--env-file`, update that file, then stop
and remove the existing container and rerun the same launch command. Docker does
not change an existing container's environment in place.

Back up `/etc/agent-hapi/` and the Hub data before updating this repository and
rerunning the installer. Use a consistent SQLite backup or stop the Hub before
copying the complete data directory; copying a live database's main file alone
is insufficient. Back up local agent state separately and protect it as credentials.

To import a stopped Hub's data or consistent backup into an empty data directory:

```bash
sudo ./deploy/vps-setup.sh --import-hapi-home /path/to/backup hapi.example.com
```

## Troubleshoot

`--hapi` verifies the Hub token and waits up to 45 seconds for a Runner RPC.
Failure returns a nonzero exit code with repair commands. A Runner already started
is left available for inspection; setup failures do not start a new Runner.

| Symptom | Action |
| --- | --- |
| Missing URL/token without a terminal | Run `--hapi` in a terminal, or supply both in `--env-file` |
| HTTP 401/403 | Check the Hub token/access policy; use the setup prompt or `docker exec -it <container> hapi auth login` |
| HTTP 409 / RPC version error | Use the same pinned HAPI release on Hub and Runner |
| HTTP 429 | Wait for the Hub rate limit before retrying |
| TLS/network error or readiness timeout | Check `docker logs <container>`, Hub URL, certificates, proxy and Hub service |
| Agent appears available but cannot answer | Follow [agent authentication](agents.md); availability does not verify provider access |

`hapi auth login` only saves a token; rerun `agent-container --hapi <project>` to
verify the connection. The launcher's first-run setup also saves `apiUrl`. An
explicit `HAPI_API_URL` overrides it. `CLI_API_TOKEN` in an env file overrides the
saved token and remains in Docker's environment, rather than being copied to disk.
Do not clone a project's HAPI state into another project: it includes machine identity.

Existing containers retain their original environment. To change keys, Hub URL,
or proxy, finish active sessions, remove the container and rerun the launch command:

```bash
docker stop <container>
docker rm <container>
agent-container --hapi --env-file ~/.config/agent-container/myproj.env ~/dev/myproj
```

State is retained. Repeat `--env-file` when recreating; an ordinary stop/start
retains the container's environment. Passing `--env-file` to an existing container
fails with guidance instead of silently ignoring changes. Files referenced by
environment variables must also exist inside the container.

Nonempty host values for `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY`
are forwarded in both cases; lowercase values take precedence. Unset values are
not passed as empty variables, so Docker can apply the current user's
`~/.docker/config.json` `proxies` settings to new containers and builds. Explicit
host values take precedence over Docker client defaults and an env file. Existing
containers keep the environment captured when they were created.

The Python readiness check uses HTTP(S) proxies; for a SOCKS-only setup, expose
an HTTP proxy as well. For a directly reachable HTTPS IP with HAPI's TLS
`servername` error, include the Hub IP in `NO_PROXY`/`no_proxy`. With this
launcher's Linux host networking, a proxy listening on host `127.0.0.1` is
reachable from the container; a remote Docker daemon resolves that address on
the daemon host instead.

## Verify

```bash
python3 -m unittest discover -v
```

Tests cover launcher lifecycle, setup/auth failures, Hub RPC readiness, deployment
scripts, and Nginx routing/rate limits/logs. Nginx tests skip if it is unavailable.
For integration changes, also check first setup, a real agent reply, and native
resume after container recreation. Each agent, mobile UI, and VPS certificate
renewal require their own integration checks.
