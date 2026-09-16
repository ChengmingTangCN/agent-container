# Deployment and troubleshooting

## Deploy the VPS

The installer targets **x86_64, dnf-based Linux, and systemd**. Prepare a public
IPv4 address or a domain pointing to the VPS, allow ports 80/443, and copy this
repository to the VPS. Then run:

```bash
sudo ./deploy/vps-setup.sh hapi.example.com
```

The script installs Nginx, TLS certificates, the upstream HAPI Hub, and a
certificate renewal timer. The Hub listens on `127.0.0.1:3006` and restarts through
systemd. Local Runners have a separate lifecycle; see the [README](../README.md#launch-modes).
Native Android/iOS push relays are disabled.

| Content | VPS path |
| --- | --- |
| HAPI data and SQLite database | `/var/lib/codex-hapi/hapi/` |
| Login access token | `/etc/codex-hapi/hapi-access-token` (private file) |
| Hub environment | `/etc/codex-hapi/hub.env` |
| Hub/PWA runtime files | `/opt/codex-hapi/hapi-runtime/` |

The build pins HAPI `v0.30.7` at `0239edf38e2da653d662f31039e24ccea04c7837` and
uses Bun `1.4.0`. It verifies the tag's commit and runs upstream type checks and
PWA/Hub builds without patches. For a small VPS, prebuild on another machine
with Git and Bun `1.4.0` installed:

```bash
./deploy/build-hapi.sh /tmp/hapi-build
# Transfer hub/dist and web/dist to the VPS, keeping their directory structure.
sudo ./deploy/vps-setup.sh --hapi-dist /path/to/hapi-build hapi.example.com
```

The build script accepts a new directory or a checkout it created itself.
Rebuilding cleans all changes and artifacts in that checkout. Prebuilt releases
must include upstream `hub/dist` and `web/dist`; do not reuse an older patched PWA.

## Check, upgrade, and back up

```bash
systemctl status codex-hapi-hub nginx codex-hapi-cert-renew.timer
journalctl -u codex-hapi-hub -n 100 --no-pager
curl -fsS https://hapi.example.com/health
```

Update the repository and rerun the installer to preserve existing credentials
and data while restarting the Hub. Before deployment, back up the VPS data and
`/etc/codex-hapi/`. Use a consistent SQLite backup, or stop the Hub before copying
the complete data directory; copying only a live database's main file is not
sufficient. Back up local project state separately and protect backups as credentials.

Importing an existing Hub requires an empty target data directory. Use a copy
from a stopped Hub or a consistent backup:

```bash
sudo ./deploy/vps-setup.sh --import-hapi-home /path/to/backup hapi.example.com
```

Legacy container layouts are not adopted automatically. Finish active tasks,
stop and remove the old container locally, then launch the current version,
keeping project files and state. If you installed the old control layer, disable
its local management services. The VPS installer disables the old Coordinator
and retains its data; old `/api/control` routes return 404. Refresh the PWA after
upgrading and clear its old application cache if needed.

## Runner cannot connect

Start with `docker logs <container-name>`. Check credentials and the Hub URL in
the project's `hapi/settings.json`. `hapi auth login` does not save the
`HAPI_API_URL` environment variable: export it in each new terminal, or set
`apiUrl` in that configuration file. Existing containers retain their original
environment; stop, remove, and recreate them after changing the URL or proxy.

Uppercase and lowercase `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, and `NO_PROXY`
are supported, with lowercase values taking precedence. When connecting to an
HTTPS IP address through a proxy, HAPI may fail with a TLS `servername` error.
If the VPS is reachable directly, add its IP to both bypass lists before creating
the container:

```bash
export NO_PROXY=localhost,127.0.0.1,::1,203.0.113.10  # Replace with your VPS IP.
export no_proxy="$NO_PROXY"
```

If the agent fails to start, check model credentials, account balance, and any
auxiliary files referenced by its configuration. For example, a JSON file named
by `model_catalog_json` is not one of the three seed files and must be copied manually.

## Verification

```bash
python3 -m unittest discover -v
```

There are 24 tests: 12 launcher behavior tests use simulated Docker, nine check
deployment scripts, and three use real Nginx to verify routing, rate limits, and
logs. The Nginx tests are skipped when Nginx is unavailable.

Local Docker and VPS integration checks covered real Codex execution, permission
approval and denial, stored messages, history access while the container was
stopped, Hub restarts, and resuming the same Codex session after recreating its
container. Mobile/PWA UI interactions, installation, push notifications, and
DSH/ZCode remain unverified. Codex's inner sandbox failed to start during testing;
approved commands ran inside Docker. This does not verify the inner sandbox.
