#!/usr/bin/env python3
"""Create deterministic four-page contact sheets from Word-native page PNGs."""

from __future__ import annotations

import argparse
import io
import os
import re
import stat
import warnings
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from portable_fs import bounded_read, is_link_or_reparse, open_exclusive_write, require_real_directory


PAGE_PATTERN = re.compile(r"^(?P<report>.+)-word-page-(?P<page>[0-9]{3})\.png$")
MAX_PAGE_FILES = 1_000
MAX_PAGE_FILE_BYTES = 25 * 1024 * 1024
MAX_PAGE_DIMENSION = 10_000
MAX_PAGE_PIXELS = 50_000_000
MAX_SHEET_PIXELS = 100_000_000


def _real_directory(path: Path, label: str) -> None:
    metadata = path.lstat()
    if is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a real directory: {path}")


def _workspace_root(value: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(value)))
    _real_directory(absolute, "workspace root")
    return absolute.resolve(strict=True)


def _within_workspace(
    value: Path, workspace_root: Path, label: str, *, must_exist: bool
) -> Path:
    absolute = Path(os.path.abspath(os.fspath(value)))
    if must_exist:
        metadata = absolute.lstat()
        if is_link_or_reparse(metadata):
            raise ValueError(f"{label} must be a non-symlink path")
        resolved = absolute.resolve(strict=True)
    else:
        resolved = absolute.parent.resolve(strict=True) / absolute.name
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the workspace root") from exc
    return resolved


def _open_page(path: Path) -> Image.Image:
    data, _ = bounded_read(path, MAX_PAGE_FILE_BYTES)
    with io.BytesIO(data) as stream, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        candidate = Image.open(stream)
        try:
            candidate.load()
            width, height = candidate.size
            if width < 1 or height < 1 or width > MAX_PAGE_DIMENSION or height > MAX_PAGE_DIMENSION or width * height > MAX_PAGE_PIXELS:
                raise ValueError(f"Word page dimensions are unsafe: {path}")
            return candidate.convert("RGB")
        finally:
            candidate.close()


def _save_sheet_exclusive(directory: Path, output: Path, sheet: Image.Image) -> None:
    try:
        require_real_directory(directory)
        with open_exclusive_write(output) as stream:
            sheet.save(stream, format="PNG", optimize=True)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError(f"contact-sheet output already exists: {output}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--pages-per-sheet", type=int, default=4)
    args = parser.parse_args()
    workspace_root = _workspace_root(args.workspace_root)
    args.input_dir = _within_workspace(
        args.input_dir, workspace_root, "input directory", must_exist=True
    )
    args.output_dir = _within_workspace(
        args.output_dir, workspace_root, "output directory", must_exist=False
    )
    if args.pages_per_sheet != 4:
        raise ValueError("only four-page sheets are supported")
    _real_directory(args.input_dir, "input directory")
    if args.output_dir.exists() or args.output_dir.is_symlink():
        _real_directory(args.output_dir, "output directory")
    else:
        _real_directory(args.output_dir.parent, "output parent")
        args.output_dir.mkdir()
        _real_directory(args.output_dir, "output directory")

    reports: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    page_paths = sorted(args.input_dir.glob("*-word-page-*.png"))
    if len(page_paths) > MAX_PAGE_FILES:
        raise ValueError(f"more than {MAX_PAGE_FILES} Word page files")
    for path in page_paths:
        match = PAGE_PATTERN.fullmatch(path.name)
        if not match:
            raise ValueError(f"unexpected Word page filename: {path}")
        reports[match.group("report")].append((int(match.group("page")), path))

    font = ImageFont.load_default()
    sheet_count = 0
    for report, pages in sorted(reports.items()):
        page_numbers = [number for number, _ in pages]
        if page_numbers != list(range(1, len(pages) + 1)):
            raise ValueError(f"non-contiguous Word pages for {report}: {page_numbers}")
        for offset in range(0, len(pages), 4):
            group = pages[offset : offset + 4]
            opened = [_open_page(path) for _, path in group]
            width = max(image.width for image in opened)
            height = max(image.height for image in opened)
            label_height = 34
            sheet_width = width * 2
            sheet_height = (height + label_height) * 2
            if sheet_width * sheet_height > MAX_SHEET_PIXELS:
                for image in opened:
                    image.close()
                raise ValueError(f"contact sheet dimensions are unsafe for {report}")
            sheet = Image.new(
                "RGB",
                (sheet_width, sheet_height),
                "white",
            )
            draw = ImageDraw.Draw(sheet)
            for index, ((page_number, _), image) in enumerate(zip(group, opened)):
                column = index % 2
                row = index // 2
                x = column * width
                y = row * (height + label_height)
                sheet.paste(image, (x, y + label_height))
                draw.text(
                    (x + 8, y + 8),
                    f"{report} | Word page {page_number}",
                    fill="black",
                    font=font,
                )
            first_page = group[0][0]
            last_page = group[-1][0]
            output = (
                args.output_dir
                / f"{report}-pages-{first_page:03d}-{last_page:03d}.png"
            )
            try:
                _save_sheet_exclusive(args.output_dir, output, sheet)
            except ValueError:
                sheet.close()
                for image in opened:
                    image.close()
                raise
            sheet.close()
            sheet_count += 1
            for image in opened:
                image.close()
    print(f"Created {sheet_count} contact sheets for {len(reports)} reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
