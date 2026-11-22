#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PROFILE_NAME="agent-container-steam"
PROFILE_SOURCE="${SCRIPT_DIR}/apparmor/${PROFILE_NAME}"
PROFILE_TARGET="/etc/apparmor.d/${PROFILE_NAME}"

[[ "${EUID}" -eq 0 ]] || {
  echo "Run this script with sudo to install the AppArmor profile." >&2
  exit 1
}
[[ -f "${PROFILE_SOURCE}" ]] || {
  echo "AppArmor profile not found: ${PROFILE_SOURCE}" >&2
  exit 1
}
[[ -d /sys/module/apparmor/parameters ]] || {
  echo "AppArmor is not enabled on this host; no profile was installed."
  exit 0
}
USERNS_RESTRICTED="$(
  cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || true
)"
[[ "${USERNS_RESTRICTED}" == "1" ]] || {
  echo "Unprivileged user namespaces are not restricted; no profile was installed."
  exit 0
}
command -v apparmor_parser >/dev/null 2>&1 || {
  echo "apparmor_parser is required to install the profile." >&2
  exit 1
}

install -m 0644 "${PROFILE_SOURCE}" "${PROFILE_TARGET}"
apparmor_parser -r "${PROFILE_TARGET}"
echo "Installed AppArmor profile: ${PROFILE_NAME}"
