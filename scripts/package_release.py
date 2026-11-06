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
                ["node", str(ROOT_DIR / "node_modules" / "@tauri-apps" / "cli" / "tauri.js"), "build", "--no-bundle"],
                cwd=str(ROOT_DIR),
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
    print("=" * 60)
    print(f"[SUCCESS] Release packaged successfully!")
    print(f"  Directory: {target_dir}")
    print(f"  Archive:   {zip_path} ({zip_size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    package()
