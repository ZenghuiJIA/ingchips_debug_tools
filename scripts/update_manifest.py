"""Generate Tauri v2 latest.json and SHA-256 release-manifest.json."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

DEFAULT_REPOSITORY = "ZenghuiJIA/ingchips_debug_tools"
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def build_latest_manifest(
    *,
    version: str,
    signature: str,
    tag: str | None = None,
    notes: str = "",
    pub_date: str | None = None,
    repository: str = DEFAULT_REPOSITORY,
) -> dict:
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"Invalid release version: {version!r}")
    resolved_tag = tag or f"v{version}"
    if resolved_tag not in (version, f"v{version}"):
        raise ValueError(f"Release tag {resolved_tag!r} does not match app version {version!r}")
    sig = signature.strip()
    if not sig:
        raise ValueError("Missing updater signature")
    resolved_date = pub_date or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        datetime.fromisoformat(resolved_date.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid publication date: {resolved_date!r}") from exc

    return {
        "version": version,
        "notes": notes,
        "pub_date": resolved_date,
        "platforms": {
            "windows-x86_64": {
                "signature": sig,
                "url": f"https://github.com/{repository}/releases/download/{quote(resolved_tag, safe='')}/AI-HIL-Debugger-setup.exe",
            }
        },
    }


def build_release_manifest(*, version: str, release_dir: Path, filenames: Iterable[str]) -> dict:
    files = []
    for name in filenames:
        data = (release_dir / name).read_bytes()
        files.append(
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {
        "version": version,
        "builtAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": files,
    }
