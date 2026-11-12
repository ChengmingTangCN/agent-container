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
Only the configured public host is served: the installer removes the distribution's
default Nginx site, TLS handshakes for any other name (including the bare IP) are
rejected, and other Host headers receive no response. Nginx 1.19.4 or newer is
required for that. Systemd restarts the Hub; native Android/iOS push relays are
disabled. Certificate renewal uses Nginx's ACME webroot and reloads Nginx after
successful renewal.

| Content | Path |
| --- | --- |
| Hub data / SQLite | `/var/lib/agent-hapi/hapi/` |
| Access token | `/etc/agent-hapi/hapi-access-token` |
| Hub environment | `/etc/agent-hapi/hub.env` |
| HAPI executable | `/opt/agent-hapi/bin/hapi` |

HAPI's version and official release archive checksums are pinned in
[hapi-release.env](../hapi-release.env). The installer selects the x86_64 baseline
or arm64 archive, verifies its pinned SHA-256 checksum, and installs the upstream
standalone executable. It does not clone or build HAPI and does not install Bun
on the VPS. Keep the version file with the repository when running the installer.

If the VPS cannot reach GitHub, download the official archive on another machine
and copy it to the VPS. Pass its local path before the public host:

```bash
sudo ./deploy/vps-setup.sh \
  --hapi-archive /path/to/hapi-linux-x64-baseline.tar.gz hapi.example.com
```

Use `hapi-linux-arm64.tar.gz` for an arm64 VPS. The archive must match the version
and architecture checksum pinned in `hapi-release.env`; version verification
still runs before replacing the binary. The supplied file is preserved. If the
pinned HAPI version is already installed, installation is skipped as usual.
This option can be combined with `--import-hapi-home`. It bypasses only the HAPI
download; missing system packages, Certbot, and certificate issuance still need
their normal network access.

The installer checks package installation state with `dpkg-query` or `rpm` and
installs only missing dependencies. When all dependencies are present, it skips
package-manager commands, including `apt-get update`.

Each installation stage prints a numbered status line, including skipped HAPI
downloads and certificate setup. HAPI downloads show a progress bar, allow 15
seconds to connect, and abort a transfer that stays below 1 KiB/s for 60 seconds;
eligible failures are retried up to three times. The final health check reports
its attempts and prints a `journalctl` command on failure. For a silent wait,
use the last stage line to identify the operation still in progress.

## Add other services

The installer owns the HTTP(S) entry points: it deletes
`/etc/nginx/sites-enabled/default` on every run, and its catch-all owns
`default_server` on 80 and 443, for IPv4 and IPv6. Additional services must not
take either resource:

- Serve every other service (home page, resume, mail web UI, ...) from a named
  vhost with an exact `server_name`. Name matches beat the catch-all, so config
  order does not matter.
- Never declare `default_server` on 80 or 443, and never enable a site named
  `default`; one breaks the next deployment with `duplicate default server`, the
  other gets its link deleted by the installer.
- Do not edit `/etc/nginx/conf.d/agent-hapi.conf`; the installer rewrites it. Do
  not reuse its `hapi_`-prefixed map, limit zones, or log names.
- Unknown names and the bare IP deliberately stay rejected. An exact
  `server_name <ip>;` vhost can still serve plain HTTP for that IP, but HTTPS by
  IP cannot work while handshakes for unknown names are rejected.
- Non-HTTP ports (mail, SSH, ...) are untouched. HAPI's certbot data lives in
  `/opt/agent-hapi/letsencrypt`; keep other certificates elsewhere.

Redeploying is safe for existing sites: the installer only runs `nginx -t` and a
graceful `reload`, and it stops Nginx solely to issue its own certificate the
first time. A broken third-party vhost fails that `nginx -t`, so fix it first;
the running configuration is left in place.

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

## Upgrade HAPI

To select a new release, check the official npm registry's `latest` version and
confirm that the matching GitHub release archives are available. Update
`HAPI_VERSION`, `HAPI_SHA256_X64_BASELINE`, and `HAPI_SHA256_ARM64` in
`hapi-release.env`, using the official archive checksums, then commit the change.
Store the version without a `v` prefix: npm uses it directly, while the Hub
installer adds `v` for the GitHub release tag. Deployments use this committed
version; pulling the commit does not update running processes.

After backing up the Hub as described above, update its checkout and rerun
`sudo ./deploy/vps-setup.sh hapi.example.com`. The installer compares versions,
installs the pinned release when needed, and restarts the Hub. Update the Runner
hosts to the same commit and finish active agent tasks before changing them.

New containers use the pinned version when their image is built. The launcher
passes `HAPI_VERSION` to Docker; direct Dockerfile builds must supply
`--build-arg HAPI_VERSION=<version>` too.

To update an existing Runner container while keeping its installed software and
files, run these commands from the repository on the **Docker host**:

```bash
source ./hapi-release.env
CONTAINER_NAME="<container>"
PROJECT_DIR="/path/to/project"
docker exec --user dev "$CONTAINER_NAME" npm install -g \
  --registry=https://registry.npmjs.org "@twsxtd/hapi@$HAPI_VERSION"
docker stop --time 60 "$CONTAINER_NAME"
agent-container --hapi "$PROJECT_DIR"
docker exec --user dev "$CONTAINER_NAME" hapi --version
```

The container must be running for `docker exec`; start a stopped Runner with
`agent-container --hapi "$PROJECT_DIR"` first. The final version must match
`HAPI_VERSION`, and the launcher must report Runner readiness. HAPI can also
attempt an automatic version handoff that exits the foreground Runner and stops
the container. If this interrupts installation, start the same container and
retry the npm command before checking the version.

Stopping and starting the same container preserves its writable layer and
mounted state, but interrupts running processes. An in-place HAPI update does
not change the container's original image tag or update other project containers.
`--rebuild` instead replaces the container and discards software and files in its
writable layer; reserve it for an intentional replacement.

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
