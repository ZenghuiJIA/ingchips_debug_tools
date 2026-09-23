#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCD Screen Mirror & FrameBuffer Capture Engine:
Non-intrusively extracts MCU LCD display memory (FrameBuffer / SDRAM / SRAM) via SWD probe
and converts raw pixel data (RGB565, RGB888, ARGB8888, 1-bit Mono) into PNG/Base64 images.
"""

import io
import base64
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("hil_daemon.lcd")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception as e:
    logger.warning(f"PIL/Pillow import warning: {e}")
    PIL_AVAILABLE = False


class LcdMirror:
    """FrameBuffer extractor and image renderer."""

    @classmethod
    def capture_framebuffer(
        cls,
        target,
        address: int,
        width: int,
        height: int,
        pixel_format: str = "rgb565"
    ) -> Dict[str, Any]:
        """
        Reads raw display framebuffer bytes from target RAM and converts to Base64 PNG.
        Supported formats:
        - 'rgb565': 16-bit 5-6-5 (2 bytes/pixel, Little Endian)
        - 'rgb888': 24-bit 8-8-8 (3 bytes/pixel)
        - 'argb8888': 32-bit (4 bytes/pixel)
        - 'mono': 1-bit monochrome bitmap (OLED 128x64 SSD1306)
        """
        fmt = (pixel_format or "rgb565").lower()
        if fmt == "rgb565":
            bytes_per_pixel = 2
            total_bytes = width * height * 2
        elif fmt == "rgb888":
            bytes_per_pixel = 3
            total_bytes = width * height * 3
        elif fmt == "argb8888":
            bytes_per_pixel = 4
            total_bytes = width * height * 4
        elif fmt in ("mono", "1bit"):
            bytes_per_pixel = 0
            total_bytes = (width * height) // 8
        else:
            return {"status": "error", "message": f"Unsupported pixel format: {pixel_format}"}

        # Read memory block via SWD
        try:
            raw_data = bytes(target.read_memory_block8(address, total_bytes))
        except Exception as e:
            return {"status": "error", "message": f"Failed to read framebuffer memory at 0x{address:08X}: {e}"}

        if not PIL_AVAILABLE:
            # Return raw hex or length
            return {
                "status": "success",
                "address": f"0x{address:08X}",
                "width": width,
                "height": height,
                "format": fmt,
                "byte_count": len(raw_data),
                "image_base64": None,
                "message": "PIL library not installed, raw memory fetched."
            }

        try:
            if fmt == "rgb565":
                # Convert 16-bit RGB565 to 24-bit RGB
                rgb_bytes = bytearray(width * height * 3)
                idx = 0
                for i in range(0, len(raw_data) - 1, 2):
                    val = raw_data[i] | (raw_data[i + 1] << 8)
                    r = ((val >> 11) & 0x1F) * 255 // 31
                    g = ((val >> 5) & 0x3F) * 255 // 63
                    b = (val & 0x1F) * 255 // 31
                    rgb_bytes[idx] = r
                    rgb_bytes[idx + 1] = g
                    rgb_bytes[idx + 2] = b
                    idx += 3
                img = Image.frombytes("RGB", (width, height), bytes(rgb_bytes))
            elif fmt == "rgb888":
                img = Image.frombytes("RGB", (width, height), raw_data)
            elif fmt == "argb8888":
                img = Image.frombytes("RGBA", (width, height), raw_data)
            elif fmt in ("mono", "1bit"):
                img = Image.frombytes("1", (width, height), raw_data)
            else:
                img = Image.new("RGB", (width, height), (0, 0, 0))

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

            return {
                "status": "success",
                "address": f"0x{address:08X}",
                "width": width,
                "height": height,
                "format": fmt,
                "byte_count": len(raw_data),
                "image_base64": f"data:image/png;base64,{b64_data}"
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to decode image from framebuffer: {e}"}
