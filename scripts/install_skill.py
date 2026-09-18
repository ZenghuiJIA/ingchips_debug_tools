#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
One-click installer for Embedded HIL Debugger AI Skill.
Deploys the skill into Antigravity (agy), Gemini CLI, Claude Code, and workspace directories.
"""

import os
import sys
import shutil
from pathlib import Path

SKILL_NAME = "embedded-hil-debugger"
CURRENT_DIR = Path(__file__).resolve().parent.parent
SOURCE_SKILL_DIR = CURRENT_DIR / "skills" / SKILL_NAME

# Target installation paths for various agent ecosystems
USER_HOME = Path.home()
TARGET_LOCATIONS = [
    # 1. Antigravity CLI global skills
    USER_HOME / ".gemini" / "antigravity-cli" / "skills" / SKILL_NAME,
    # 2. Antigravity / Gemini config skills
    USER_HOME / ".gemini" / "config" / "skills" / SKILL_NAME,
    # 3. Claude Code global skills
    USER_HOME / ".claude" / "skills" / SKILL_NAME,
    # 4. Local workspace .agents skills
    CURRENT_DIR / ".agents" / "skills" / SKILL_NAME,
]

def main():
    print("=" * 60)
    print("   AI-HIL Debugger - AI Agent Skill Installer")
    print("=" * 60)
    print(f"Source Skill Directory: {SOURCE_SKILL_DIR}")

    if not SOURCE_SKILL_DIR.exists() or not (SOURCE_SKILL_DIR / "SKILL.md").exists():
        print(f"[ERROR] Source SKILL.md not found at {SOURCE_SKILL_DIR}")
        sys.exit(1)

    installed_count = 0
    for target in TARGET_LOCATIONS:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(SOURCE_SKILL_DIR, target)
            print(f"  [SUCCESS] Installed to: {target}")
            installed_count += 1
        except Exception as e:
            print(f"  [WARNING] Could not install to {target}: {e}")

    print("=" * 60)
    print(f"Skill '{SKILL_NAME}' successfully deployed to {installed_count} locations!")
    print("\nHow to verify in AI Agent:")
    print("  1. In Antigravity (AGY): The skill is automatically loaded via progressive disclosure.")
    print("  2. In Claude Code: Skill is registered in ~/.claude/skills/")
    print("  3. Ask the agent: '如何排查单片机 HardFault？' or '帮我烧录固件'")
    print("=" * 60)

if __name__ == "__main__":
    main()
