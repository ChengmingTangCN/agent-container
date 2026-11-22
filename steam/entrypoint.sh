#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: steam-entrypoint run [STEAM OPTIONS...]
       steam-entrypoint check
       steam-entrypoint shell
USAGE
}

check_runtime() {
  local FAILED=0

  if [[ -n "${DISPLAY:-}" ]] && xdpyinfo >/dev/null 2>&1; then
    echo "display:  ok (${DISPLAY})"
  else
    echo "display:  failed (${DISPLAY:-unset})" >&2
    FAILED=1
  fi

  if pactl info >/dev/null 2>&1; then
    echo "audio:    ok (${PULSE_SERVER:-default server})"
  else
    echo "audio:    failed (${PULSE_SERVER:-PULSE_SERVER unset})" >&2
    FAILED=1
  fi

  local VULKAN_SUMMARY
  local VULKAN_GPU=""
  if VULKAN_SUMMARY="$(vulkaninfo --summary 2>&1)"; then
    VULKAN_GPU="$(
      printf '%s\n' "${VULKAN_SUMMARY}" \
        | awk '
            /deviceType/ {
              software = ($0 ~ /PHYSICAL_DEVICE_TYPE_CPU/)
              next
            }
            /deviceName/ && !software {
              sub(/^[[:space:]]*deviceName[[:space:]]*=[[:space:]]*/, "")
              print
              exit
            }
          '
    )"
    if [[ "${STEAM_REQUIRE_HARDWARE_GPU:-0}" == "1" && -z "${VULKAN_GPU}" ]]; then
      echo "vulkan:   failed (only a software renderer is visible)" >&2
      FAILED=1
    elif [[ -n "${VULKAN_GPU}" ]]; then
      echo "vulkan:   ok (${VULKAN_GPU})"
    else
      echo "vulkan:   ok (software renderer)"
    fi
  else
    echo "vulkan:   failed" >&2
    FAILED=1
  fi

  if unshare -Ur true; then
    echo "userns:   ok"
  else
    echo "userns:   failed" >&2
    FAILED=1
  fi

  if command -v bwrap >/dev/null 2>&1 \
      && bwrap --ro-bind / / --dev /dev --proc /proc true; then
    echo "bwrap:    ok"
  else
    echo "bwrap:    failed" >&2
    FAILED=1
  fi

  if command -v steam >/dev/null 2>&1; then
    echo "steam:    ok"
  else
    echo "steam:    failed (steam executable is missing)" >&2
    FAILED=1
  fi

  return "${FAILED}"
}

run_steam() {
  local RUNTIME_DIR
  RUNTIME_DIR="$(mktemp -d /tmp/steam-runtime.XXXXXX)"
  chmod 700 "${RUNTIME_DIR}"
  export XDG_RUNTIME_DIR="${RUNTIME_DIR}"

  mkdir -p "${HOME}/.local/share" "${HOME}/.config"
  set +e
  dbus-run-session -- steam "$@"
  local STATUS=$?
  set -e
  rm -rf -- "${RUNTIME_DIR}"
  return "${STATUS}"
}

COMMAND="${1:-run}"
[[ $# -eq 0 ]] || shift

case "${COMMAND}" in
  run)
    run_steam "$@"
    ;;
  check)
    check_runtime
    ;;
  shell)
    exec bash
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    usage >&2
    exit 2
    ;;
esac
