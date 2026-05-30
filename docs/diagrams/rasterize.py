#!/usr/bin/env python3
"""Rasterize diagram SVG(s) to PNG.

cairosvg resolves font-family per text run (no per-glyph CJK fallback), so for
PNG output we swap the SVG's Latin-first font stack for a CJK-capable font that
also covers Latin (Noto Sans CJK JP). The committed .svg files keep their
browser-facing Inter stack untouched.

Usage:  python3 rasterize.py <file.svg> [<file.svg> ...]
"""
import re
import sys

import cairosvg

PNG_FONT = "Noto Sans CJK JP, IPAGothic, sans-serif"


def rasterize(svg_path: str) -> str:
    with open(svg_path, encoding="utf-8") as fh:
        svg = fh.read()
    svg = re.sub(r'font-family="[^"]*"', f'font-family="{PNG_FONT}"', svg)
    png_path = re.sub(r"\.svg$", ".png", svg_path)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=png_path)
    return png_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python3 rasterize.py <file.svg> ...")
    for path in sys.argv[1:]:
        print("wrote", rasterize(path))
