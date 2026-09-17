#!/usr/bin/env bash
# Rotate the access token for an installed HAPI Hub.
set -euo pipefail

if [[ "$(id -u)" != 0 ]] || [[ $# != 0 ]]; then
  echo "Usage: sudo bash rotate-hapi-token.sh" >&2
  exit 2
fi

CONFIG="/etc/agent-hapi"
TOKEN_FILE="$CONFIG/hapi-access-token"
ENV_FILE="$CONFIG/hub.env"
SERVICE_USER="agent-hapi"
SERVICE="agent-hapi-hub.service"

command -v python3.11 >/dev/null || { echo "python3.11 is required" >&2; exit 2; }
command -v systemctl >/dev/null || { echo "systemctl is required" >&2; exit 2; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 2; }
[[ -d "$CONFIG" && -f "$TOKEN_FILE" && -f "$ENV_FILE" ]] || {
  echo "HAPI is not installed: expected $TOKEN_FILE and $ENV_FILE" >&2
  exit 2
}
id "$SERVICE_USER" >/dev/null 2>&1 || {
  echo "HAPI service user does not exist: $SERVICE_USER" >&2
  exit 2
}

umask 077
TOKEN_TMP="$(mktemp -p "$CONFIG" .hapi-access-token.XXXXXX)"
ENV_TMP="$(mktemp -p "$CONFIG" .hub.env.XXXXXX)"
cleanup() {
  rm -f -- "$TOKEN_TMP" "$ENV_TMP"
}
trap cleanup EXIT

TOKEN="$(python3.11 -c 'import secrets; print(secrets.token_urlsafe(48))')"
printf '%s\n' "$TOKEN" > "$TOKEN_TMP"
printf 'CLI_API_TOKEN=%s\n' "$TOKEN" > "$ENV_TMP"
chown "$SERVICE_USER:$SERVICE_USER" "$TOKEN_TMP" "$ENV_TMP"
chmod 600 "$TOKEN_TMP" "$ENV_TMP"
mv -f -- "$TOKEN_TMP" "$TOKEN_FILE"
mv -f -- "$ENV_TMP" "$ENV_FILE"

systemctl restart "$SERVICE"
for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:3006/health >/dev/null; then
    echo "HAPI access token rotated successfully."
    echo "New token: $TOKEN_FILE"
    echo "Runners and clients using the previous token must authenticate again."
    exit 0
  fi
  sleep 1
done

echo "HAPI failed its health check after token rotation." >&2
echo "Inspect it with: journalctl -u $SERVICE -n 100 --no-pager" >&2
exit 1
