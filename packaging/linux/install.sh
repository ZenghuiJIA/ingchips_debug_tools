#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="ai-hil-debugger"

if [[ "${EUID}" -eq 0 ]]; then
  PREFIX="/usr/local"
  UDEV_DIR="/usr/lib/udev/rules.d"
  DESKTOP_DIR="/usr/share/applications"
  ICON_DIR="/usr/share/icons/hicolor/128x128/apps"
else
  PREFIX="${HOME}/.local"
  UDEV_DIR=""
  DESKTOP_DIR="${HOME}/.local/share/applications"
  ICON_DIR="${HOME}/.local/share/icons/hicolor/128x128/apps"
fi

BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/${APP_NAME}"

echo "Installing AI-HIL Debugger to ${PREFIX}..."
install -d "${BIN_DIR}" "${LIB_DIR}" "${LIB_DIR}/packs" "${DESKTOP_DIR}" "${ICON_DIR}"

install -m 755 "${SCRIPT_DIR}/bin/ai-hil-debugger" "${BIN_DIR}/ai-hil-debugger"
install -m 755 "${SCRIPT_DIR}/bin/hil-daemon" "${BIN_DIR}/hil-daemon"
install -m 755 "${SCRIPT_DIR}/lib/hil-python-worker" "${LIB_DIR}/hil-python-worker"
install -m 755 "${SCRIPT_DIR}/lib/hil-protocol" "${LIB_DIR}/hil-protocol"
install -m 644 "${SCRIPT_DIR}/lib/mcp-tools.json" "${LIB_DIR}/mcp-tools.json"
install -m 644 "${SCRIPT_DIR}/lib/packs/"* "${LIB_DIR}/packs/"
install -m 644 "${SCRIPT_DIR}/LICENSE" "${LIB_DIR}/LICENSE"
install -m 644 "${SCRIPT_DIR}/share/ai-hil-debugger.desktop" "${DESKTOP_DIR}/${APP_NAME}.desktop"
install -m 644 "${SCRIPT_DIR}/share/ai-hil-debugger.png" "${ICON_DIR}/${APP_NAME}.png"

if [[ -n "${UDEV_DIR}" ]]; then
  install -d "${UDEV_DIR}"
  install -m 644 "${SCRIPT_DIR}/udev/99-ai-hil-debugger.rules" "${UDEV_DIR}/99-ai-hil-debugger.rules"
  if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
  fi
  echo "udev rules installed to ${UDEV_DIR}/99-ai-hil-debugger.rules"
else
  echo ""
  echo "[Note] Installed in user mode (~/.local). To grant non-root access to DAPLink/J-Link/USB-Serial:"
  echo "  sudo install -Dm644 \"${SCRIPT_DIR}/udev/99-ai-hil-debugger.rules\" /usr/lib/udev/rules.d/99-ai-hil-debugger.rules"
  echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi

echo "Done! Launch with: ${BIN_DIR}/ai-hil-debugger"
