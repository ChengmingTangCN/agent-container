# AGENTS.md

## Nginx entry points belong to the HAPI installer

`deploy/vps-setup.sh` and `deploy/nginx-hapi.conf` own the HTTP(S) entry points
of the host:

- The catch-all block owns `default_server` on 80 and 443, IPv4 and IPv6, and
  rejects every name except the configured public host (`ssl_reject_handshake`
  for TLS, `return 444` for HTTP).
- The installer removes `/etc/nginx/sites-enabled/default` on every run.

Additional services (home page, resume, mail web UI, ...) must therefore use
named vhosts with exact `server_name`s. They must not declare `default_server`,
enable a site named `default`, reuse the `hapi_`-prefixed map, limit zones or
log names, or edit `/etc/nginx/conf.d/agent-hapi.conf`. See "Add other services"
in [`docs/operations.md`](docs/operations.md) for the full constraint list.

Do not weaken this behaviour without updating that documentation, the
installer tests (`test_deploy_scripts.py`), and the Nginx runtime tests
(`test_nginx_rate_limits.py`).

## Keep private deployment details out of the repository

This repository is a generic tool. Never put a real domain, IP address, token,
or other private deployment value into code, docs, tests, comments, or commit
messages. Use placeholders such as `hapi.example.com` and `192.0.2.1` instead.
Keep live values in the shell or on the host, never in the tree.

## Commit messages

Write a `<subsystem>: <imperative intent>` subject under 75 characters. Keep
the body brief: one short paragraph per point, leading with the problem and
root cause, then the fix and its consequences. Do not recap the diff.
