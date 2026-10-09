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

        def make_bmp_data_uri(raw_bytes: bytes, w: int, h: int, pixel_fmt: str) -> str:
            """Pure Python 24-bit BMP generator (no PIL required) as universal fallback."""
            # Convert any format to 24-bit BGR rows
            row_bytes_unpadded = w * 3
            padding = (4 - (row_bytes_unpadded % 4)) % 4
            row_size = row_bytes_unpadded + padding
            image_size = row_size * h
            file_size = 54 + image_size

            header = bytearray(54)
            # BMP Header
            header[0:2] = b'BM'
            header[2:6] = file_size.to_bytes(4, 'little')
            header[10:14] = (54).to_bytes(4, 'little')
            # DIB Header (BITMAPINFOHEADER)
            header[14:18] = (40).to_bytes(4, 'little')
            header[18:22] = w.to_bytes(4, 'little')
            header[22:26] = (-h).to_bytes(4, 'little', signed=True)  # Top-down bitmap
            header[26:28] = (1).to_bytes(2, 'little')
            header[28:30] = (24).to_bytes(2, 'little')
            header[34:38] = image_size.to_bytes(4, 'little')

            pixels = bytearray(image_size)
            p_idx = 0

            if pixel_fmt == "rgb565":
                src_idx = 0
                for _ in range(h):
                    for _ in range(w):
                        if src_idx + 1 < len(raw_bytes):
                            val = raw_bytes[src_idx] | (raw_bytes[src_idx + 1] << 8)
                            r = ((val >> 11) & 0x1F) * 255 // 31
                            g = ((val >> 5) & 0x3F) * 255 // 63
                            b = (val & 0x1F) * 255 // 31
                            pixels[p_idx] = b
                            pixels[p_idx + 1] = g
                            pixels[p_idx + 2] = r
                        src_idx += 2
                        p_idx += 3
                    p_idx += padding
            elif pixel_fmt == "rgb888":
                src_idx = 0
                for _ in range(h):
                    for _ in range(w):
                        if src_idx + 2 < len(raw_bytes):
                            pixels[p_idx] = raw_bytes[src_idx + 2]     # B
                            pixels[p_idx + 1] = raw_bytes[src_idx + 1] # G
                            pixels[p_idx + 2] = raw_bytes[src_idx]     # R
                        src_idx += 3
                        p_idx += 3
                    p_idx += padding
            elif pixel_fmt == "argb8888":
                src_idx = 0
                for _ in range(h):
                    for _ in range(w):
                        if src_idx + 3 < len(raw_bytes):
                            pixels[p_idx] = raw_bytes[src_idx]     # B
                            pixels[p_idx + 1] = raw_bytes[src_idx + 1] # G
                            pixels[p_idx + 2] = raw_bytes[src_idx + 2] # R
                        src_idx += 4
                        p_idx += 3
                    p_idx += padding
            else: # mono
                bit_idx = 0
                for _ in range(h):
                    for _ in range(w):
                        byte_pos = bit_idx // 8
                        bit_pos = 7 - (bit_idx % 8)
                        val = 255 if (byte_pos < len(raw_bytes) and (raw_bytes[byte_pos] & (1 << bit_pos))) else 0
                        pixels[p_idx] = val
                        pixels[p_idx + 1] = val
                        pixels[p_idx + 2] = val
                        bit_idx += 1
                        p_idx += 3
                    p_idx += padding

            bmp_content = bytes(header) + bytes(pixels)
            b64_bmp = base64.b64encode(bmp_content).decode("utf-8")
            return f"data:image/bmp;base64,{b64_bmp}"

        if not PIL_AVAILABLE:
            bmp_uri = make_bmp_data_uri(raw_data, width, height, fmt)
            return {
                "status": "success",
                "address": f"0x{address:08X}",
                "width": width,
                "height": height,
                "format": fmt,
                "byte_count": len(raw_data),
                "image_base64": bmp_uri
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
