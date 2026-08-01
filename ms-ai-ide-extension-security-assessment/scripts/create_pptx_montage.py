#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Create a deterministic labelled montage from rendered presentation slides."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from portable_fs import bounded_read, open_exclusive_write

THUMBNAIL = (400, 225)
MAX_SLIDES = 250


def _open_image(path: Path) -> Image.Image:
    import io
    data, _ = bounded_read(path, 64 * 1024 * 1024)
    with io.BytesIO(data) as stream:
        image = Image.open(stream)
        image.load()
        if image.width < 1 or image.height < 1 or image.width * image.height > 100_000_000:
            raise ValueError(f"unsafe slide dimensions: {path}")
        return image.convert("RGB")


def create_montage(inputs: list[Path], output: Path, columns: int) -> None:
    if not inputs or len(inputs) > MAX_SLIDES or columns < 1 or columns > 10:
        raise ValueError("slide count or montage column count is outside bounds")
    rows = (len(inputs) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * THUMBNAIL[0], rows * THUMBNAIL[1]), "white")
    draw = ImageDraw.Draw(canvas)
    for index, source in enumerate(inputs):
        image = _open_image(source)
        image.thumbnail((THUMBNAIL[0], THUMBNAIL[1]), Image.Resampling.LANCZOS)
        left = (index % columns) * THUMBNAIL[0] + (THUMBNAIL[0] - image.width) // 2
        top = (index // columns) * THUMBNAIL[1] + (THUMBNAIL[1] - image.height) // 2
        canvas.paste(image, (left, top))
        draw.rectangle((left + 6, top + 6, left + 46, top + 30), fill="white", outline="black")
        draw.text((left + 12, top + 10), str(index + 1), fill="black")
    with open_exclusive_write(output) as stream:
        canvas.save(stream, format="PNG", optimize=True)
        stream.flush()
        os.fsync(stream.fileno())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input_files", nargs="+", required=True, type=Path)
    parser.add_argument("--output_file", required=True, type=Path)
    parser.add_argument("--num_col", default="5", type=int)
    parser.add_argument("--label_mode", choices=("number",), default="number")
    parser.add_argument("--fail_on_image_error", action="store_true")
    args = parser.parse_args(argv)
    try:
        create_montage(args.input_files, args.output_file, args.num_col)
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
