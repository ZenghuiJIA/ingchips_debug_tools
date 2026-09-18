#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-click installer for Embedded HIL Debugger AI Skill.
Deploys the skill into CC Switch (~/.agents/skills), DeepSeek Harness (~/.ohdsh/skills),
Antigravity (agy), Gemini CLI, Claude Code, and workspace directories without redundant re-installations.
"""

import os
import sys
import time
import shutil
import sqlite3
import hashlib
from pathlib import Path

SKILL_NAME = "embedded-hil-debugger"
CURRENT_DIR = Path(__file__).resolve().parent.parent

# Candidate locations for the source skill
candidate_sources = [
    CURRENT_DIR / "skills" / SKILL_NAME,
    CURRENT_DIR / ".agents" / "skills" / SKILL_NAME,
    Path.home() / ".agents" / "skills" / SKILL_NAME,
]
SOURCE_SKILL_DIR = next((p for p in candidate_sources if p.exists() and (p / "SKILL.md").exists()), candidate_sources[0])

# Target installation paths for various agent ecosystems
USER_HOME = Path.home()
TARGET_LOCATIONS = [
    # 1. CC Switch universal skills directory (~/.agents/skills)
    USER_HOME / ".agents" / "skills" / SKILL_NAME,
    # 2. DeepSeek Harness global skills directory (~/.ohdsh/skills)
    USER_HOME / ".ohdsh" / "skills" / SKILL_NAME,
    # 3. Antigravity CLI global skills
    USER_HOME / ".gemini" / "antigravity-cli" / "skills" / SKILL_NAME,
    # 4. Antigravity / Gemini config skills
    USER_HOME / ".gemini" / "config" / "skills" / SKILL_NAME,
    # 5. Claude Code global skills
    USER_HOME / ".claude" / "skills" / SKILL_NAME,
    # 6. Local workspace .agents skills
    CURRENT_DIR / ".agents" / "skills" / SKILL_NAME,
]

def is_skill_identical(src_dir: Path, dst_dir: Path) -> bool:
    """Check if skill is already installed with identical files and checksums."""
    if not dst_dir.exists() or not dst_dir.is_dir():
        return False
    if not (dst_dir / "SKILL.md").exists():
        return False

    src_files = {p.relative_to(src_dir): p for p in src_dir.rglob("*") if p.is_file()}
    dst_files = {p.relative_to(dst_dir): p for p in dst_dir.rglob("*") if p.is_file()}

    if set(src_files.keys()) != set(dst_files.keys()):
        return False

    for rel_path, s_file in src_files.items():
        d_file = dst_files[rel_path]
        if s_file.stat().st_size != d_file.stat().st_size:
            return False
        with open(s_file, "rb") as f1, open(d_file, "rb") as f2:
            if hashlib.sha256(f1.read()).hexdigest() != hashlib.sha256(f2.read()).hexdigest():
                return False
    return True

def sync_to_ccswitch_db(db_path: Path):
    """Ensure skill is registered in CC Switch SQLite database without duplication."""
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT id FROM skills WHERE id = 'local:embedded-hil-debugger'")
        row = cur.fetchone()
        if row:
            print(f"  [EXISTS] Skill 'embedded-hil-debugger' is already registered in CCSwitch database.")
        else:
            now = int(time.time())
            cur.execute("""
                INSERT INTO skills (
                    id, name, description, directory, repo_branch,
                    enabled_claude, enabled_codex, enabled_gemini, enabled_opencode, enabled_hermes, enabled_grokbuild,
                    installed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, 1, 1, 1, 1, ?, ?)
            """, (
                "local:embedded-hil-debugger",
                "embedded-hil-debugger",
                "AI 嵌入式硬件在环(HIL)测试与调试系统 (DAPLink串口/SWD烧录/寄存器分析/HardFault自动诊断)",
                "embedded-hil-debugger",
                "main",
                now,
                now
            ))
            conn.commit()
            print(f"  [OK] Successfully registered skill 'embedded-hil-debugger' in CCSwitch database!")
        conn.close()
    except Exception as e:
        print(f"  [WARNING] CCSwitch skill DB registration check failed: {e}")

def main():
    print("=" * 65)
    print("      AI-HIL Debugger - AI Agent Skill Installer")
    print("=" * 65)
    print(f"Source Skill Directory: {SOURCE_SKILL_DIR}\n")

    if not SOURCE_SKILL_DIR.exists() or not (SOURCE_SKILL_DIR / "SKILL.md").exists():
        print(f"[ERROR] Source SKILL.md not found at {SOURCE_SKILL_DIR}")
        sys.exit(1)

    installed_count = 0
    skipped_count = 0

    for target in TARGET_LOCATIONS:
        try:
            # Check if identical skill already exists to avoid redundant re-installation
            if is_skill_identical(SOURCE_SKILL_DIR, target):
                print(f"  [EXISTS] Skill already installed and up to date at:\n           {target} (Skipping)")
                skipped_count += 1
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(SOURCE_SKILL_DIR, target)
            print(f"  [OK] Installed to:\n       {target}")
            installed_count += 1
        except Exception as e:
            print(f"  [WARNING] Could not install to {target}: {e}")

    # Register to CC Switch DB
    cc_switch_db = USER_HOME / ".cc-switch" / "cc-switch.db"
    if cc_switch_db.exists():
        print("\n[CCSwitch Integration]")
        sync_to_ccswitch_db(cc_switch_db)

    print("\n" + "=" * 65)
    print(f"Skill deployment summary: {installed_count} newly installed/updated, {skipped_count} up to date (no repeat).")
    print("Supported environments:")
    print("  1. CC Switch: ~/.agents/skills/embedded-hil-debugger (universal directory)")
    print("  2. DeepSeek Harness: ~/.ohdsh/skills/embedded-hil-debugger")
    print("  3. Antigravity / Gemini CLI: ~/.gemini/antigravity-cli/skills/ & ~/.gemini/config/skills/")
    print("  4. Claude Code: ~/.claude/skills/")
    print("=" * 65)

if __name__ == "__main__":
    main()
