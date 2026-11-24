"""Atomically create/update a Draft GitHub Release, upload all assets, then publish --latest."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def release_notes_match_version(notes: str, version: str) -> bool:
    first_line = notes.lstrip("\ufeff").splitlines()[0] if notes.strip() else ""
    return bool(re.match(rf"^#\s+.*v?{re.escape(version)}\b", first_line))


def release_assets(tag: str) -> list[str]:
    clean_tag = tag if tag.startswith("v") else f"v{tag}"
    if not re.fullmatch(r"v\d+\.\d+\.\d+", clean_tag):
        raise ValueError(f"Invalid release tag: {tag!r}")
    return [
        f"release/AI-HIL-Debugger-{clean_tag}-windows-x64.zip",
        "release/AI-HIL-Debugger-setup.exe",
        "release/AI-HIL-Debugger-setup.exe.sig",
        "release/latest.json",
        "release/release-manifest.json",
    ]


def build_release_commands(
    *,
    tag: str,
    version: str,
    notes_file: str,
    existing_status: int,
    existing_stdout: str,
    existing_stderr: str,
    assets: list[str],
) -> list[list[str]]:
    if tag not in (version, f"v{version}"):
        raise ValueError(f"Release tag {tag!r} does not match app version {version!r}")
    if not notes_file:
        raise ValueError("Missing RELEASE_NOTES_FILE")

    if existing_status == 0:
        info = json.loads(existing_stdout)
        if not info.get("isDraft", False):
            raise RuntimeError("该版本已发布，禁止覆盖已发布的更新文件")
        prepare = [
            "release",
            "edit",
            tag,
            "--draft",
            "--title",
            f"AI-HIL Debugger {tag}",
            "--notes-file",
            notes_file,
        ]
    elif "release not found" in (existing_stderr or "").lower():
        prepare = [
            "release",
            "create",
            tag,
            "--verify-tag",
            "--draft",
            "--title",
            f"AI-HIL Debugger {tag}",
            "--notes-file",
            notes_file,
        ]
    else:
        raise RuntimeError(existing_stderr or "无法检查现有 GitHub Release，请确认权限与网络")

    return [
        prepare,
        ["release", "upload", tag, *assets, "--clobber"],
        ["release", "edit", tag, "--draft=false", "--latest"],
    ]


def _gh(args: list[str]) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"gh {' '.join(args)} failed")
    return res.stdout


def main() -> int:
    tag = os.environ.get("RELEASE_TAG", "").strip()
    notes_file = os.environ.get("RELEASE_NOTES_FILE", "").strip()
    if not tag or not notes_file:
        raise SystemExit("Missing RELEASE_TAG or RELEASE_NOTES_FILE")
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    notes = (root / notes_file).read_text(encoding="utf-8")
    if not release_notes_match_version(notes, version):
        raise SystemExit(f"Release notes {notes_file} do not match version {version}")

    assets = release_assets(tag)
    for asset in assets:
        if not (root / asset).is_file():
            raise SystemExit(f"Missing release asset: {asset}")

    existing = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(root),
    )
    for cmd in build_release_commands(
        tag=tag,
        version=version,
        notes_file=notes_file,
        existing_status=existing.returncode,
        existing_stdout=existing.stdout,
        existing_stderr=existing.stderr,
        assets=assets,
    ):
        _gh(cmd)
    print(f"已验证并原子发布 {tag} 的安装器、便携 ZIP 与签名更新清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
