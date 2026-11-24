#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Packages the AI-HIL Debugger into a standalone Windows release archive (ZIP).
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT_DIR / "release"

def get_release_version() -> str:
    """动态获取版本号：
    1. 优先使用命令行传入的参数 (如 python package_release.py v1.1.1)
    2. 优先尝试获取当前 commit 对应的精确 Git Tag (git describe --tags --exact-match)
    3. 尝试获取最近的 Git Tag (git describe --tags --abbrev=0)
    4. 回退读取 package.json 中的 version
    5. 保底使用 v1.0.0
    """
    # 1. 命令行参数重写
    if len(sys.argv) > 1 and sys.argv[1].strip():
        arg_ver = sys.argv[1].strip()
        if not arg_ver.startswith("v") and arg_ver[0].isdigit():
            arg_ver = f"v{arg_ver}"
        return arg_ver

    # 2. package.json 版本优先（便于发布管理）
    pkg_json = ROOT_DIR / "package.json"
    if pkg_json.exists():
        try:
            import json
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                v = data.get("version")
                if v:
                    return f"v{v}" if not v.startswith("v") else v
        except Exception:
            pass

    # 3. Git Tag (精确匹配)
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    # 4. Git Tag (最近 tag)
    try:
        res = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return "v1.2.1"

def get_release_paths(ver: str):
    pkg_name = f"AI-HIL-Debugger-{ver}-windows-x64"
    target_dir = RELEASE_DIR / pkg_name
    zip_path = RELEASE_DIR / f"{pkg_name}.zip"
    return pkg_name, target_dir, zip_path

def prepare_signing_env(env: dict) -> dict:
    """Load local updater signing key if TAURI_SIGNING_PRIVATE_KEY is not already set."""
    if env.get("TAURI_SIGNING_PRIVATE_KEY"):
        return env
    local_key = Path(
        env.get("AI_HIL_SIGNING_KEY_PATH")
        or (Path.home() / ".tauri" / "AI-HIL-Debugger" / "updater.key")
    )
    if not local_key.is_file():
        return env
    pub_file = Path(f"{local_key}.pub")
    if pub_file.is_file():
        import json
        conf = json.loads((ROOT_DIR / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
        expected_pub = conf.get("plugins", {}).get("updater", {}).get("pubkey", "").strip()
        actual_pub = pub_file.read_text(encoding="utf-8").strip()
        if expected_pub and actual_pub != expected_pub:
            raise RuntimeError("本地签名公钥与应用 tauri.conf.json 中的 pubkey 不一致")
    updated = dict(env)
    updated["TAURI_SIGNING_PRIVATE_KEY"] = local_key.read_text(encoding="utf-8")
    updated.setdefault("TAURI_SIGNING_PRIVATE_KEY_PASSWORD", "")
    return updated


def package(custom_version: str = None, daemon_source=None):
    version = custom_version or get_release_version()
    pkg_name, target_dir, zip_path = get_release_paths(version)

    print("=" * 60)
    print(f" Packaging Release: {pkg_name} (Version: {version})")
    print("=" * 60)

    # Optional build check: Ensure release exe is built with latest frontend
    auto_build = os.environ.get("SKIP_BUILD") != "1"
    if auto_build:
        from build_daemon_windows import build_native_codec, build_executable, build_native_runtime
        build_native_codec()
        if not (ROOT_DIR / 'build_dist/hil-python-worker.exe').is_file():
            build_executable()
        build_native_runtime()
        print("[0/5] Building latest frontend and Tauri release executable...")
        try:
            subprocess.run(
                ["node", str(ROOT_DIR / "node_modules" / "@tauri-apps" / "cli" / "tauri.js"), "build"],
                cwd=str(ROOT_DIR),
                env=prepare_signing_env(os.environ),
                check=True,
                shell=False
            )
            print("  [OK] Build completed successfully.")
        except Exception as e:
            raise RuntimeError(f"Tauri build failed; refusing to package stale binaries: {e}") from e

    # Resolve and verify all cleanup paths before replacing this release only.
    if target_dir.resolve().parent != RELEASE_DIR.resolve() or zip_path.resolve().parent != RELEASE_DIR.resolve():
        raise ValueError("Invalid release path")

    # Clean previous output
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    if zip_path.exists():
        try:
            zip_path.unlink()
        except Exception:
            pass

    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "bin").mkdir(exist_ok=True)
    (target_dir / "scripts").mkdir(exist_ok=True)
    (target_dir / "skills").mkdir(exist_ok=True)
    (target_dir / "mcp").mkdir(exist_ok=True)
    (target_dir / "packs").mkdir(exist_ok=True)

    # Copy primary executables
    print("[1/5] Copying application executables...")
    main_exe_candidates = [
        ROOT_DIR / "src-tauri" / "target" / "release" / "ai-hil-debugger.exe",
        ROOT_DIR / "src-tauri" / "target" / "release" / "AI-HIL-Debugger.exe",

    ]
    main_exe = next((p for p in main_exe_candidates if p.exists()), None)
    if main_exe is None:
        raise FileNotFoundError("Build the desktop release executable before packaging")
    if main_exe:
        shutil.copy2(main_exe, target_dir / "AI-HIL-Debugger.exe")
        print(f"  [OK] Copied {main_exe.name} -> AI-HIL-Debugger.exe ({main_exe.stat().st_size / 1024 / 1024:.1f} MB)")

    # Copy standalone NSIS installer & signature to release/ (not inside portable ZIP)
    bundle_dir = ROOT_DIR / "src-tauri" / "target" / "release" / "bundle"
    installer_version = version.lstrip("v")
    nsis_exe = next(
        (p for p in (bundle_dir / "nsis").glob("*.exe") if installer_version in p.name and not p.name.endswith(".sig")),
        None,
    )
    if nsis_exe is None:
        raise FileNotFoundError("Tauri NSIS installer missing; run a bundled tauri build first")
    shutil.copy2(nsis_exe, RELEASE_DIR / "AI-HIL-Debugger-setup.exe")
    print(f"  [OK] Copied NSIS installer -> release/AI-HIL-Debugger-setup.exe")

    nsis_sig = Path(f"{nsis_exe}.sig")
    if nsis_sig.is_file():
        shutil.copy2(nsis_sig, RELEASE_DIR / "AI-HIL-Debugger-setup.exe.sig")
        print(f"  [OK] Copied updater signature -> release/AI-HIL-Debugger-setup.exe.sig")

    daemon_exe = Path(daemon_source) if daemon_source else ROOT_DIR / 'build_dist/hil-native.exe'
    if not daemon_exe.is_file():
        raise FileNotFoundError("Build the daemon before packaging")
    if daemon_exe.exists():
        shutil.copy2(daemon_exe, target_dir / "bin" / "hil-daemon-x86_64-pc-windows-msvc.exe")
        print(f"  [OK] Copied {daemon_exe.name} ({daemon_exe.stat().st_size / 1024 / 1024:.1f} MB)")
    codec = ROOT_DIR / 'src-tauri/target/release/hil-protocol.exe'
    if not codec.is_file():
        raise FileNotFoundError('Build hil-protocol before packaging')
    shutil.copy2(codec, target_dir / 'bin' / codec.name)
    for filename in ['hil-python-worker.exe', 'hil-native.exe', 'mcp-tools.json']:
        source = ROOT_DIR / 'build_dist' / filename
        if not source.is_file(): raise FileNotFoundError(f'Missing native runtime dependency: {filename}')
        shutil.copy2(source, target_dir / 'bin' / filename)

    # Copy batch scripts
    print("[2/5] Copying batch launchers and installers...")
    for bat_file in ["start.bat", "install_mcp.bat", "install_skill.bat", "diagnose.bat"]:
        src = ROOT_DIR / "scripts" / bat_file
        if not src.exists():
            src = ROOT_DIR / bat_file
        if src.exists():
            shutil.copy2(src, target_dir / bat_file)
            print(f"  [OK] Copied {bat_file}")

    # Copy scripts
    print("[3/5] Copying Python helper scripts...")
    for script_name in ["deploy_mcp_to_agents.py", "install_skill.py"]:
        src = ROOT_DIR / "scripts" / script_name
        if src.exists():
            shutil.copy2(src, target_dir / "scripts" / script_name)
            print(f"  [OK] Copied scripts/{script_name}")

    # Copy skills and documentation
    print("[4/5] Copying skills and documentation...")
    skill_src = ROOT_DIR / "skills" / "embedded-hil-debugger"
    if skill_src.exists():
        shutil.copytree(skill_src, target_dir / "skills" / "embedded-hil-debugger")
        print(f"  [OK] Copied skills/embedded-hil-debugger")

    mcp_readme = ROOT_DIR / "mcp" / "README.md"
    if mcp_readme.exists():
        shutil.copy2(mcp_readme, target_dir / "mcp" / "README.md")
        print(f"  [OK] Copied mcp/README.md")

    root_readme = ROOT_DIR / "README.md"
    hil_examples = ROOT_DIR / "examples" / "hil"
    instrumentation_examples = ROOT_DIR / 'examples' / 'instrumentation'
    if instrumentation_examples.exists():
        shutil.copytree(instrumentation_examples, target_dir / 'examples' / 'instrumentation')
    sdk = ROOT_DIR / 'firmware' / 'hil-instrumentation'
    if sdk.exists():
        shutil.copytree(sdk, target_dir / 'firmware' / 'hil-instrumentation')
    for guide in ('EMBEDDED_DEBUG_STATUS.md', 'EMBEDDED_DEBUG_IMPLEMENTATION_PLAN.md', 'HIL_RESET_CANCEL.md'):
        (target_dir / 'docs').mkdir(exist_ok=True)
        shutil.copy2(ROOT_DIR / 'docs' / guide, target_dir / 'docs' / guide)
    if hil_examples.exists():
        shutil.copytree(hil_examples, target_dir / "examples" / "hil")
    hil_guide = ROOT_DIR / "docs" / "HIL_RUNNER.md"
    abc_guide = ROOT_DIR / 'docs/ABC_DEBUGGING.md'
    migration_guide = ROOT_DIR / 'docs/RUST_MIGRATION.md'
    if migration_guide.exists():
        (target_dir / 'docs').mkdir(exist_ok=True)
        shutil.copy2(migration_guide, target_dir / 'docs' / migration_guide.name)
    if abc_guide.exists():
        (target_dir / 'docs').mkdir(exist_ok=True)
        shutil.copy2(abc_guide, target_dir / 'docs' / abc_guide.name)
    if hil_guide.exists():
        (target_dir / "docs").mkdir(exist_ok=True)
        shutil.copy2(hil_guide, target_dir / "docs" / hil_guide.name)
    if root_readme.exists():
        shutil.copy2(root_readme, target_dir / "README.md")
        print(f"  [OK] Copied README.md")

    license_file = ROOT_DIR / "LICENSE"
    if license_file.exists():
        shutil.copy2(license_file, target_dir / "LICENSE")
        print(f"  [OK] Copied LICENSE")

    notes = ROOT_DIR / "docs" / f"RELEASE_NOTES_{version}.md"
    if notes.exists():
        shutil.copy2(notes, target_dir / "RELEASE_NOTES.md")
        (target_dir / "docs").mkdir(exist_ok=True)
        shutil.copy2(notes, target_dir / "docs" / notes.name)

    review = ROOT_DIR / "docs" / f"REVIEW_{version}.md"
    if review.is_file():
        (target_dir / "docs").mkdir(exist_ok=True)
        shutil.copy2(review, target_dir / "docs" / review.name)
    serial_audit = ROOT_DIR / "docs" / "SERIAL_ASSISTANT_AUDIT_2026-11.md"
    if serial_audit.is_file():
        (target_dir / "docs").mkdir(exist_ok=True)
        shutil.copy2(serial_audit, target_dir / "docs" / serial_audit.name)

    # Copy packs: only include the official default pack to keep release clean and free of testing debris
    default_pack_name = "INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack"
    packs_src = ROOT_DIR / "packs"
    if (packs_src / default_pack_name).exists():
        shutil.copy2(packs_src / default_pack_name, target_dir / "packs" / default_pack_name)
        print(f"  [OK] Copied default pack: {default_pack_name}")
    else:
        # Fallback to any INGChips pack if version differs
        ing_packs = list(packs_src.glob("INGChips*.pack"))
        if ing_packs:
            shutil.copy2(ing_packs[0], target_dir / "packs" / ing_packs[0].name)
            print(f"  [OK] Copied pack: {ing_packs[0].name}")

    import hashlib
    import json
    hashes = {str(p.relative_to(target_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in target_dir.rglob("*") if p.is_file()}
    (target_dir / "SHA256SUMS.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")

    # Compress into zip
    print(f"[5/5] Compressing package into {zip_path.name}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(target_dir):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(RELEASE_DIR)
                zf.write(full_path, rel_path)

    zip_size_mb = zip_path.stat().st_size / 1024 / 1024

    # Generate signed updater latest.json & release-manifest.json if .sig exists
    sig_file = RELEASE_DIR / "AI-HIL-Debugger-setup.exe.sig"
    if sig_file.is_file():
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        from update_manifest import build_latest_manifest, build_release_manifest

        notes_text = notes.read_text(encoding="utf-8") if notes.is_file() else ""
        latest_data = build_latest_manifest(
            version=installer_version,
            signature=sig_file.read_text(encoding="utf-8"),
            tag=version if version.startswith("v") else f"v{version}",
            notes=notes_text,
        )
        (RELEASE_DIR / "latest.json").write_text(
            json.dumps(latest_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rel_manifest = build_release_manifest(
            version=installer_version,
            release_dir=RELEASE_DIR,
            filenames=[
                "AI-HIL-Debugger-setup.exe",
                "AI-HIL-Debugger-setup.exe.sig",
                zip_path.name,
                "latest.json",
            ],
        )
        (RELEASE_DIR / "release-manifest.json").write_text(
            json.dumps(rel_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("  [OK] Generated release/latest.json & release/release-manifest.json")

    print("=" * 60)
    print(f"[SUCCESS] Release packaged successfully!")
    print(f"  Directory: {target_dir}")
    print(f"  Archive:   {zip_path} ({zip_size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    package()
