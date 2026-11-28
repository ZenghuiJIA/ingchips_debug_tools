#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ai-hil-debugger"

if [[ "${EUID}" -eq 0 ]]; then
  PREFIX="/usr/local"
  UDEV_FILE="/usr/lib/udev/rules.d/99-ai-hil-debugger.rules"
  DESKTOP_DIR="/usr/share/applications"
  ICON_DIR="/usr/share/icons/hicolor/128x128/apps"
else
  PREFIX="${HOME}/.local"
  UDEV_FILE=""
  DESKTOP_DIR="${HOME}/.local/share/applications"
  ICON_DIR="${HOME}/.local/share/icons/hicolor/128x128/apps"
fi

rm -f "${PREFIX}/bin/ai-hil-debugger" "${PREFIX}/bin/hil-daemon"
rm -rf "${PREFIX}/lib/${APP_NAME}"
rm -f "${DESKTOP_DIR}/${APP_NAME}.desktop" "${ICON_DIR}/${APP_NAME}.png"

if [[ -n "${UDEV_FILE}" && -f "${UDEV_FILE}" ]]; then
  rm -f "${UDEV_FILE}"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
  fi
fi

echo "Uninstalled AI-HIL Debugger from ${PREFIX}."
