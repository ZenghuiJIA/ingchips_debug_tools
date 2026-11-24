"""Validate that a release tag, package metadata, and functional release notes agree."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_release_version.py vX.Y.Z")
    tag = sys.argv[1]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise SystemExit(f"Invalid release tag: {tag!r}; expected vX.Y.Z")
    version = tag[1:]
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    if package.get("version") != version:
        raise SystemExit(f"package.json version {package.get('version')} != tag {version}")
    for relative in ("src-tauri/Cargo.toml", "src-tauri/runtime/Cargo.toml"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if not re.search(rf'^version\s*=\s*"{re.escape(version)}"\s*$', text, re.MULTILINE):
            raise SystemExit(f"{relative} does not contain version {version}")
    config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    if config.get("version") != version:
        raise SystemExit(f"tauri.conf.json version {config.get('version')} != tag {version}")
    cargo_lock = (ROOT / "src-tauri/Cargo.lock").read_text(encoding="utf-8")
    for pkg_name in ("ai-hil-debugger", "hil-runtime"):
        m = re.search(rf'\[\[package\]\]\s+name = "{re.escape(pkg_name)}"\s+version = "([^"]+)"', cargo_lock)
        if not m or m.group(1) != version:
            raise SystemExit(f"Cargo.lock {pkg_name} version {m.group(1) if m else None} != {version}")
    daemon_text = (ROOT / "src-tauri/daemon/daemon_entry.py").read_text(encoding="utf-8")
    m_daemon = re.search(
        r'^MCP_SERVER_VERSION\s*=\s*(?:os\.environ\.get\(\s*"MCP_SERVER_VERSION"\s*,\s*"([^"]+)"\s*\)|"([^"]+)")',
        daemon_text,
        re.MULTILINE,
    )
    daemon_ver = (m_daemon.group(1) or m_daemon.group(2)) if m_daemon else None
    if daemon_ver != version:
        raise SystemExit(f"daemon_entry.py MCP_SERVER_VERSION {daemon_ver} != {version}")
    notes = ROOT / "docs" / f"RELEASE_NOTES_{tag}.md"
    if not notes.is_file():
        raise SystemExit(f"Missing functional release notes: {notes}")
    content = notes.read_text(encoding="utf-8")
    if not re.search(rf'^# .*{re.escape(tag)}', content, re.MULTILINE):
        raise SystemExit(f"Release notes title does not name {tag}")
    forbidden = ("## 验证边界", "## Validation boundary", "未上板", "未进行真实")
    if any(marker in content for marker in forbidden):
        raise SystemExit("Release notes must contain functional updates only; move validation limits to audit docs")
    print(f"PASS release metadata and functional notes: {tag}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
