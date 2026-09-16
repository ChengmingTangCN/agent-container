#!/usr/bin/env bash
# Install the unmodified upstream HAPI Hub on the VPS.
set -euo pipefail

IMPORT_HAPI_HOME=""
HAPI_DIST=""
while [[ $# -gt 1 ]]; do
  case "$1" in
    --import-hapi-home)
      [[ $# -ge 3 ]] || break
      IMPORT_HAPI_HOME="$2"
      shift 2
      ;;
    --hapi-dist)
      [[ $# -ge 3 ]] || break
      HAPI_DIST="$2"
      shift 2
      ;;
    *) break ;;
  esac
done
if [[ "$(id -u)" != 0 ]] || [[ $# != 1 ]]; then
  echo "Usage: sudo bash vps-setup.sh [--import-hapi-home <directory>] [--hapi-dist <directory>] <public-ip-or-domain>" >&2
  exit 2
fi

PUBLIC_HOST="$1"
if [[ ! "$PUBLIC_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]] || [[ "$PUBLIC_HOST" == *..* ]]; then
  echo "public host must be an IPv4 address or DNS name without a port or path" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="/opt/codex-hapi"
HAPI_BUILD="$BASE/hapi-build"
HAPI_RUNTIME="$BASE/hapi-runtime"
STATE="/var/lib/codex-hapi"
CONFIG="/etc/codex-hapi"
SERVICE_USER="codex-hapi"
PUBLIC_URL="https://$PUBLIC_HOST"
BUN_ARCHIVE_SHA256="2d03fb5fb83ac8b567aca0a281b2ce1a1a19d488f56c2968d88c3f25e92fe452"

command -v dnf >/dev/null || { echo "This installer requires a dnf-based VPS" >&2; exit 2; }
[[ "$(uname -m)" == "x86_64" ]] || { echo "This VPS installer currently requires x86_64" >&2; exit 2; }
dnf install -y git nginx python3.11 python3.11-pip unzip curl

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE" --create-home --shell /sbin/nologin "$SERVICE_USER"
fi
install -d -m 755 "$BASE/bin" /var/www/hapi-acme
install -d -m 755 "$CONFIG"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 700 \
  "$STATE" "$STATE/hapi"

if [[ -n "$IMPORT_HAPI_HOME" ]]; then
  if [[ ! -d "$IMPORT_HAPI_HOME" ]]; then
    echo "Imported HAPI home must be an existing directory" >&2
    exit 2
  fi
  if [[ -n "$(find "$STATE/hapi" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "Refusing to import over a nonempty HAPI state directory: $STATE/hapi" >&2
    exit 2
  fi
  cp -a "$IMPORT_HAPI_HOME/." "$STATE/hapi/"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE/hapi"
  chmod 700 "$STATE/hapi"
fi

if [[ ! -x "$BASE/bin/bun" ]] || [[ "$($BASE/bin/bun --version)" != "1.4.0" ]]; then
  BUN_ARCHIVE="$(mktemp)"
  trap 'rm -f "$BUN_ARCHIVE"' EXIT
  curl -fsSL --retry 3 -o "$BUN_ARCHIVE" \
    https://github.com/oven-sh/bun/releases/download/bun-v1.4.0/bun-linux-x64.zip
  echo "$BUN_ARCHIVE_SHA256  $BUN_ARCHIVE" | sha256sum -c -
  unzip -p "$BUN_ARCHIVE" bun-linux-x64/bun > "$BASE/bin/bun"
  chmod 755 "$BASE/bin/bun"
fi

if [[ -n "$HAPI_DIST" ]]; then
  HAPI_RELEASE="$HAPI_DIST"
else
  PATH="$BASE/bin:$PATH" "$SCRIPT_DIR/build-hapi.sh" "$HAPI_BUILD"
  HAPI_RELEASE="$HAPI_BUILD"
fi
[[ -s "$HAPI_RELEASE/hub/dist/index.js" && -s "$HAPI_RELEASE/web/dist/index.html" ]] || {
  echo "HAPI release must contain hub/dist/index.js and web/dist/index.html" >&2
  exit 2
}
for COMPONENT in hub web; do
  install -d -m 755 "$HAPI_RUNTIME/$COMPONENT"
  rm -rf "$HAPI_RUNTIME/$COMPONENT/dist.new"
  cp -a "$HAPI_RELEASE/$COMPONENT/dist" "$HAPI_RUNTIME/$COMPONENT/dist.new"
  rm -rf "$HAPI_RUNTIME/$COMPONENT/dist"
  mv "$HAPI_RUNTIME/$COMPONENT/dist.new" "$HAPI_RUNTIME/$COMPONENT/dist"
done
if [[ -z "$HAPI_DIST" ]]; then
  git -C "$HAPI_BUILD" clean -fdx
fi

HAPI_TOKEN_FILE="$CONFIG/hapi-access-token"
if [[ ! -s "$HAPI_TOKEN_FILE" ]]; then
  python3.11 - "$HAPI_TOKEN_FILE" "$STATE/hapi/settings.json" <<'PY'
import json, secrets, sys
from pathlib import Path
path, settings_path = map(Path, sys.argv[1:])
token = None
if settings_path.is_file():
    try:
        candidate = json.loads(settings_path.read_text()).get("cliApiToken")
        if isinstance(candidate, str) and candidate.strip():
            token = candidate.strip()
    except (OSError, ValueError, AttributeError):
        pass
path.write_text((token or secrets.token_urlsafe(48)) + "\n")
path.chmod(0o600)
PY
fi
chown "$SERVICE_USER:$SERVICE_USER" "$HAPI_TOKEN_FILE"

python3.11 - "$CONFIG/hub.env" "$HAPI_TOKEN_FILE" <<'PY'
import sys
from pathlib import Path
target, token_file = map(Path, sys.argv[1:])
token = token_file.read_text().strip()
target.write_text(f"CLI_API_TOKEN={token}\n")
target.chmod(0o600)
PY
chown "$SERVICE_USER:$SERVICE_USER" "$CONFIG/hub.env"

cat > /etc/systemd/system/codex-hapi-hub.service <<EOF_SERVICE
[Unit]
Description=Central HAPI Hub for container Runners
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$HAPI_RUNTIME/hub
ExecStart=$BASE/bin/bun $HAPI_RUNTIME/hub/dist/index.js
EnvironmentFile=$CONFIG/hub.env
Environment=HAPI_HOME=$STATE/hapi
Environment=DB_PATH=$STATE/hapi/hapi.db
Environment=HAPI_LISTEN_HOST=127.0.0.1
Environment=HAPI_LISTEN_PORT=3006
Environment=HAPI_PUBLIC_URL=$PUBLIC_URL
Environment=HAPI_ANDROID_PUSH=off
Environment=HAPI_IOS_PUSH=off
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$STATE/hapi

[Install]
WantedBy=multi-user.target
EOF_SERVICE

# Retire a previously installed control service without deleting its data.
if [[ -f /etc/systemd/system/codex-control-coordinator.service ]]; then
  systemctl disable --now codex-control-coordinator.service
  rm /etc/systemd/system/codex-control-coordinator.service
fi

CERTBOT="$BASE/certbot/bin/certbot"
if [[ ! -x "$CERTBOT" ]]; then
  python3.11 -m venv "$BASE/certbot"
  "$BASE/certbot/bin/pip" install 'certbot==5.8.0'
fi
CERT_ARGS=(--config-dir "$BASE/letsencrypt" --work-dir "$BASE/letsencrypt-work" --logs-dir "$BASE/letsencrypt-logs")
CERT_DIR="$BASE/letsencrypt/live/$PUBLIC_HOST"
if [[ ! -f "$CERT_DIR/fullchain.pem" ]]; then
  systemctl stop nginx 2>/dev/null || true
  if python3.11 - "$PUBLIC_HOST" <<'PY'
import ipaddress, sys
ipaddress.ip_address(sys.argv[1])
PY
  then
    "$CERTBOT" certonly --non-interactive --agree-tos --register-unsafely-without-email \
      --preferred-profile shortlived --standalone --ip-address "$PUBLIC_HOST" \
      --cert-name "$PUBLIC_HOST" "${CERT_ARGS[@]}"
  else
    "$CERTBOT" certonly --non-interactive --agree-tos --register-unsafely-without-email \
      --standalone -d "$PUBLIC_HOST" --cert-name "$PUBLIC_HOST" "${CERT_ARGS[@]}"
  fi
fi

python3.11 - "$SCRIPT_DIR/nginx-hapi.conf" /etc/nginx/conf.d/codex-hapi.conf \
  "$PUBLIC_HOST" "$CERT_DIR" <<'PY'
import sys
from pathlib import Path
source, target, host, cert = sys.argv[1:]
text = Path(source).read_text().replace("__PUBLIC_HOST__", host).replace("__CERT_DIR__", cert)
Path(target).write_text(text)
PY

cat > /etc/systemd/system/codex-hapi-cert-renew.service <<EOF_SERVICE
[Unit]
Description=Renew the HAPI TLS certificate

[Service]
Type=oneshot
ExecStart=$CERTBOT renew --quiet --cert-name $PUBLIC_HOST --config-dir $BASE/letsencrypt --work-dir $BASE/letsencrypt-work --logs-dir $BASE/letsencrypt-logs
ExecStartPost=/usr/bin/systemctl reload nginx
EOF_SERVICE
cat > /etc/systemd/system/codex-hapi-cert-renew.timer <<'EOF_TIMER'
[Unit]
Description=Daily HAPI TLS certificate renewal

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF_TIMER

nginx -t
systemctl daemon-reload
systemctl enable --now codex-hapi-hub.service nginx \
  codex-hapi-cert-renew.timer
systemctl restart codex-hapi-hub.service
systemctl reload nginx

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:3006/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:3006/health >/dev/null
systemctl is-active codex-hapi-hub.service nginx \
  codex-hapi-cert-renew.timer

echo "HAPI is ready at $PUBLIC_URL"
echo "Runner access token: $HAPI_TOKEN_FILE"
