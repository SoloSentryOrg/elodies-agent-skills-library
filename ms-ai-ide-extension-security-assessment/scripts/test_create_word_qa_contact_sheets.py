#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from create_word_qa_contact_sheets import _open_page, main


class WordQaContactSheetTests(unittest.TestCase):
    def test_rejects_symlink_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.png"
            Image.new("RGB", (10, 10), "white").save(target)
            link = root / "report-word-page-001.png"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                _open_page(link)

    def test_rejects_unsafe_page_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report-word-page-001.png"
            Image.new("RGB", (10, 10), "white").save(path)
            with (
                patch("create_word_qa_contact_sheets.MAX_PAGE_PIXELS", 50),
                self.assertRaisesRegex(ValueError, "dimensions are unsafe"),
            ):
                _open_page(path)

    def test_rejects_existing_symlink_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            output_dir.mkdir()
            page = input_dir / "report-word-page-001.png"
            Image.new("RGB", (10, 10), "white").save(page)
            target = root / "target.png"
            target.write_bytes(b"keep")
            (output_dir / "report-pages-001-001.png").symlink_to(target)
            with (
                patch(
                    "sys.argv",
                    [
                        "create_word_qa_contact_sheets.py",
                        "--workspace-root",
                        str(root),
                        str(input_dir),
                        str(output_dir),
                    ],
                ),
                redirect_stdout(StringIO()),
                self.assertRaisesRegex(ValueError, "output already exists"),
            ):
                main()
            self.assertEqual(target.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
