#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto-sync 'zh-TW' entries in src/utils/i18n.ts from 'zh' using OpenCC (s2twp).
Run whenever you add or update Simplified Chinese strings in 'zh'.
"""

import re
import sys
from pathlib import Path

try:
    import opencc
except ImportError:
    print("Error: 'opencc' Python package is required (pip install opencc or pacman -S python-opencc).", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
I18N_PATH = ROOT / "src" / "utils" / "i18n.ts"


def main():
    src = I18N_PATH.read_text(encoding="utf-8")
    m_zh = re.search(r"(  zh:\s*\{\n[\s\S]*?\n  \}),\n  'zh-TW':", src)
    m_tw = re.search(r"(  'zh-TW':\s*\{\n[\s\S]*?\n  \}),\n  en:", src)
    if not m_zh or not m_tw:
        raise RuntimeError("Could not locate zh and zh-TW blocks in src/utils/i18n.ts")

    converter = opencc.OpenCC("s2twp.json")

    def convert_line(line: str) -> str:
        m = re.match(r"^(\s*[a-zA-Z0-9_]+\s*:\s*')((?:\\'|[^'])*)('.*)$", line)
        if not m:
            return line
        prefix, val, suffix = m.groups()
        placeholders = []

        def save_ph(match):
            placeholders.append(match.group(0))
            return f"__PH_{len(placeholders)-1}__"

        protected = re.sub(r"\{[a-zA-Z0-9_]+\}", save_ph, val)
        converted = converter.convert(protected)
        for idx, ph in enumerate(placeholders):
            converted = converted.replace(f"__PH_{idx}__", ph)
        return f"{prefix}{converted}{suffix}"

    tw_lines = []
    for i, line in enumerate(m_zh.group(1).splitlines()):
        if i == 0:
            tw_lines.append("  'zh-TW': {")
        else:
            tw_lines.append(convert_line(line))

    new_tw_block = "\n".join(tw_lines)
    updated = src[:m_tw.start(1)] + new_tw_block + src[m_tw.end(1):]
    I18N_PATH.write_text(updated, encoding="utf-8")
    print("[sync_i18n_tw] Synced 'zh-TW' from 'zh' in src/utils/i18n.ts")


if __name__ == "__main__":
    main()
