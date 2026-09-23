#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression test for LCD Screen Mirror and RGB565 / RGB888 pixel decoding.
"""

import sys
from pathlib import Path

DAEMON_DIR = Path(__file__).resolve().parent.parent / "src-tauri" / "daemon"
sys.path.insert(0, str(DAEMON_DIR))

from lcd_mirror import LcdMirror

class DummyTarget:
    def __init__(self, data: bytes):
        self.data = data

    def read_memory_block8(self, addr: int, size: int):
        return list(self.data[:size])

def run_tests():
    print("=" * 60)
    print(" Running LCD Mirror FrameBuffer Decoding Regression Tests")
    print("=" * 60)

    # Test 1: 4x4 RGB565 Red image (RGB565 Red = 0xF800, Little-Endian = [0x00, 0xF8])
    red_pixel = bytes([0x00, 0xF8])
    dummy_fb = red_pixel * (4 * 4)
    target = DummyTarget(dummy_fb)

    res = LcdMirror.capture_framebuffer(target, 0x20000000, 4, 4, "rgb565")
    assert res["status"] == "success", f"RGB565 capture failed: {res}"
    assert res["width"] == 4 and res["height"] == 4
    assert res["byte_count"] == 32
    assert res["image_base64"].startswith("data:image/png;base64,")
    print("[PASS] RGB565 4x4 FrameBuffer decoded to PNG successfully.")

    # Test 2: 2x2 RGB888 Blue image (RGB888 Blue = [0x00, 0x00, 0xFF])
    blue_pixel = bytes([0x00, 0x00, 0xFF])
    dummy_fb2 = blue_pixel * (2 * 2)
    target2 = DummyTarget(dummy_fb2)

    res2 = LcdMirror.capture_framebuffer(target2, 0xC0000000, 2, 2, "rgb888")
    assert res2["status"] == "success", f"RGB888 capture failed: {res2}"
    assert res2["byte_count"] == 12
    assert res2["image_base64"].startswith("data:image/png;base64,")
    print("[PASS] RGB888 2x2 FrameBuffer decoded to PNG successfully.")

    print("=" * 60)
    print("[SUCCESS] All LCD Mirror tests PASSED!")

if __name__ == "__main__":
    run_tests()
