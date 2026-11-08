#!/usr/bin/env python3
"""Tests for image-dimension-checker-cli. Standard library unittest only.

Run from the repo root: python3 tests/test_image_dimension_checker.py
"""

import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import image_dimension_checker as idc  # noqa: E402

ALLOWED_STDLIB = {
    "argparse",
    "fnmatch",
    "json",
    "os",
    "struct",
    "sys",
    "pathlib",
}


def run_cli(argv, stdin_bytes=None):
    """Run main() in-process and capture (exit code, stdout, stderr)."""
    out = io.StringIO()
    err = io.StringIO()
    old_stdin = sys.stdin
    if stdin_bytes is not None:
        sys.stdin = _FakeStdin(stdin_bytes)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = idc.main(argv)
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


class _FakeStdin:
    """Minimal stdin with a .buffer, for --stdin tests."""

    def __init__(self, data):
        self.buffer = io.BytesIO(data)


def png_bytes(width, height):
    """A minimal PNG header: signature + IHDR with the size."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x00\x00\x00\x00"
    )


def jpeg_bytes(width, height, sof=0xC0):
    """A minimal JPEG header: SOI, one APP0 segment, one SOF segment."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof_segment = (
        bytes([0xFF, sof])
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x01\x01\x11\x00"
    )
    return b"\xff\xd8" + app0 + sof_segment


def gif_bytes(width, height):
    return b"GIF89a" + struct.pack("<HH", width, height)


def bmp_bytes(width, height, core_header=False):
    """A minimal BMP header, info header or 12-byte core header."""
    if core_header:
        return (
            b"BM"
            + b"\x00" * 12
            + struct.pack("<I", 12)
            + struct.pack("<HH", width, height)
        )
    return (
        b"BM"
        + b"\x00" * 12
        + struct.pack("<I", 40)
        + struct.pack("<ii", width, height)
    )


def webp_vp8x_bytes(width, height):
    chunk = (
        b"\x00\x00\x00\x00"
        + (width - 1).to_bytes(3, "little")
        + (height - 1).to_bytes(3, "little")
    )
    return (
        b"RIFF"
        + struct.pack("<I", 22)
        + b"WEBP"
        + b"VP8X"
        + struct.pack("<I", 10)
        + chunk
    )


def webp_vp8l_bytes(width, height):
    packed = (width - 1) | ((height - 1) << 14)
    chunk = b"\x2f" + struct.pack("<I", packed)
    return (
        b"RIFF"
        + struct.pack("<I", 17)
        + b"WEBP"
        + b"VP8L"
        + struct.pack("<I", 5)
        + chunk
    )


def webp_vp8_bytes(width, height):
    chunk = (
        b"\x00\x00\x00"
        + b"\x9d\x01\x2a"
        + struct.pack("<HH", width & 0x3FFF, height & 0x3FFF)
    )
    return (
        b"RIFF"
        + struct.pack("<I", 22)
        + b"WEBP"
        + b"VP8 "
        + struct.pack("<I", 10)
        + chunk
    )


class ReadDimensionsTests(unittest.TestCase):
    def test_png_header(self):
        self.assertEqual(
            idc.read_dimensions(png_bytes(800, 600)), ("PNG", 800, 600)
        )

    def test_jpeg_baseline_sof0(self):
        self.assertEqual(
            idc.read_dimensions(jpeg_bytes(800, 600, 0xC0)),
            ("JPEG", 800, 600),
        )

    def test_jpeg_progressive_sof2(self):
        self.assertEqual(
            idc.read_dimensions(jpeg_bytes(800, 600, 0xC2)),
            ("JPEG", 800, 600),
        )

    def test_jpeg_extended_sof1(self):
        self.assertEqual(
            idc.read_dimensions(jpeg_bytes(800, 600, 0xC1)),
            ("JPEG", 800, 600),
        )

    def test_jpeg_skips_app_segments_and_padding(self):
        data = (
            b"\xff\xd8"
            + b"\xff\xff\xff\xe1"
            + struct.pack(">H", 10)
            + b"Exif\x00\x00\x00\x00"
            + b"\xff\xc0"
            + struct.pack(">H", 11)
            + b"\x08"
            + struct.pack(">HH", 400, 300)
            + b"\x01\x01\x11\x00"
        )
        self.assertEqual(idc.read_dimensions(data), ("JPEG", 300, 400))

    def test_jpeg_sos_before_sof_cannot_be_read(self):
        data = b"\xff\xd8" + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x02\x03"
        with self.assertRaises(ValueError) as caught:
            idc.read_dimensions(data)
        self.assertIn("truncated or corrupt", str(caught.exception))

    def test_jpeg_truncated_segment_cannot_be_read(self):
        data = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 100)
        with self.assertRaises(ValueError):
            idc.read_dimensions(data)

    def test_jpeg_just_soi_cannot_be_read(self):
        with self.assertRaises(ValueError):
            idc.read_dimensions(b"\xff\xd8")

    def test_gif89a_header(self):
        self.assertEqual(
            idc.read_dimensions(gif_bytes(320, 240)), ("GIF", 320, 240)
        )

    def test_gif87a_header(self):
        data = b"GIF87a" + struct.pack("<HH", 100, 50)
        self.assertEqual(idc.read_dimensions(data), ("GIF", 100, 50))

    def test_bmp_info_header(self):
        self.assertEqual(
            idc.read_dimensions(bmp_bytes(640, 480)), ("BMP", 640, 480)
        )

    def test_bmp_top_down_negative_height(self):
        self.assertEqual(
            idc.read_dimensions(bmp_bytes(640, -480)), ("BMP", 640, 480)
        )

    def test_bmp_core_header(self):
        self.assertEqual(
            idc.read_dimensions(bmp_bytes(100, 50, core_header=True)),
            ("BMP", 100, 50),
        )

    def test_webp_vp8x(self):
        self.assertEqual(
            idc.read_dimensions(webp_vp8x_bytes(800, 600)),
            ("WebP", 800, 600),
        )

    def test_webp_vp8l(self):
        self.assertEqual(
            idc.read_dimensions(webp_vp8l_bytes(320, 240)),
            ("WebP", 320, 240),
        )

    def test_webp_vp8_lossy(self):
        self.assertEqual(
            idc.read_dimensions(webp_vp8_bytes(1600, 900)),
            ("WebP", 1600, 900),
        )

    def test_webp_unknown_first_chunk_cannot_be_read(self):
        data = (
            b"RIFF"
            + struct.pack("<I", 12)
            + b"WEBP"
            + b"EXIF"
            + struct.pack("<I", 4)
            + b"\x00\x00\x00\x00"
        )
        with self.assertRaises(ValueError):
            idc.read_dimensions(data)

    def test_webp_truncated_chunk_cannot_be_read(self):
        data = (
            b"RIFF"
            + struct.pack("<I", 22)
            + b"WEBP"
            + b"VP8X"
            + struct.pack("<I", 10)
            + b"\x00\x00"
        )
        with self.assertRaises(ValueError):
            idc.read_dimensions(data)

    def test_png_truncated_ihdr_cannot_be_read(self):
        with self.assertRaises(ValueError):
            idc.read_dimensions(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    def test_png_wrong_chunk_after_signature_cannot_be_read(self):
        data = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IDAT"
            + struct.pack(">II", 800, 600)
        )
        with self.assertRaises(ValueError):
            idc.read_dimensions(data)

    def test_zero_width_is_corrupt(self):
        with self.assertRaises(ValueError):
            idc.read_dimensions(png_bytes(0, 600))

    def test_text_is_not_a_supported_image(self):
        with self.assertRaises(ValueError) as caught:
            idc.read_dimensions(b"this is not an image\n")
        self.assertIn("not a supported image", str(caught.exception))

    def test_empty_bytes_cannot_be_read(self):
        with self.assertRaises(ValueError) as caught:
            idc.read_dimensions(b"")
        self.assertIn("empty file", str(caught.exception))

    def test_real_fixture_files(self):
        cases = [
            ("examples/small.png", ("PNG", 640, 480)),
            ("examples/wide.png", ("PNG", 1920, 1080)),
            ("examples/tall.png", ("PNG", 800, 1200)),
            ("examples/big.jpg", ("JPEG", 2000, 1500)),
            ("examples/icon.gif", ("GIF", 64, 64)),
            ("examples/photo.bmp", ("BMP", 300, 200)),
            ("examples/wide.webp", ("WebP", 1600, 900)),
            ("examples/small.webp", ("WebP", 320, 240)),
        ]
        for name, expected in cases:
            data = (REPO_ROOT / name).read_bytes()
            self.assertEqual(idc.read_dimensions(data), expected, name)


class CheckLimitsTests(unittest.TestCase):
    def test_no_limits_passes(self):
        self.assertEqual(
            idc.check_limits("PNG", 2000, 1500, (None, None, None)), []
        )

    def test_exact_limit_passes(self):
        self.assertEqual(
            idc.check_limits("PNG", 1600, 800, (1600, 800, 1280000)), []
        )

    def test_one_pixel_over_width_fails(self):
        problems = idc.check_limits("PNG", 1601, 800, (1600, None, None))
        self.assertEqual(len(problems), 1)
        self.assertIn(
            "too wide (1601 pixels, maximum 1600)", problems[0]["reason"]
        )

    def test_one_pixel_over_height_fails(self):
        problems = idc.check_limits("PNG", 800, 801, (None, 800, None))
        self.assertEqual(len(problems), 1)
        self.assertIn(
            "too tall (801 pixels, maximum 800)", problems[0]["reason"]
        )

    def test_one_pixel_over_total_fails(self):
        problems = idc.check_limits(
            "PNG", 1000, 1001, (None, None, 1000000)
        )
        self.assertEqual(len(problems), 1)
        self.assertIn(
            "too many pixels (1001000 pixels, maximum 1000000)",
            problems[0]["reason"],
        )

    def test_all_three_limits_reported(self):
        problems = idc.check_limits(
            "JPEG", 2000, 1500, (1600, 800, 1000000)
        )
        self.assertEqual(len(problems), 3)
        reasons = [p["reason"] for p in problems]
        self.assertIn("too wide (2000 pixels, maximum 1600)", reasons)
        self.assertIn("too tall (1500 pixels, maximum 800)", reasons)
        self.assertIn(
            "too many pixels (3000000 pixels, maximum 1000000)", reasons
        )


class CollectFromFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_good_file_passes(self):
        path = self.write("good.png", png_bytes(640, 480))
        problems, skipped, info = idc.collect_from_file(
            path, (1600, 800, None)
        )
        self.assertEqual((problems, skipped, info), ([], False, ("PNG", 640, 480)))

    def test_oversized_file_reports_each_limit(self):
        path = self.write("big.png", png_bytes(2000, 1500))
        problems, skipped, info = idc.collect_from_file(
            path, (1600, 800, 1000000)
        )
        self.assertEqual(len(problems), 3)
        self.assertFalse(skipped)
        self.assertEqual(info, ("PNG", 2000, 1500))

    def test_missing_file_reports_read_error(self):
        problems, skipped, info = idc.collect_from_file(
            self.root / "nope.png", (None, None, None)
        )
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["line"], 0)
        self.assertTrue(problems[0]["reason"].startswith("cannot read file:"))
        self.assertFalse(skipped)
        self.assertIsNone(info)

    def test_corrupt_file_is_a_problem_not_a_skip(self):
        path = self.write("bad.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00")
        problems, skipped, info = idc.collect_from_file(
            path, (None, None, None)
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("truncated or corrupt", problems[0]["reason"])
        self.assertFalse(skipped)
        self.assertIsNone(info)

    def test_text_file_is_not_a_supported_image(self):
        path = self.write("note.txt", b"this is not an image\n")
        problems, skipped, info = idc.collect_from_file(
            path, (None, None, None)
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("not a supported image", problems[0]["reason"])
        self.assertFalse(skipped)


class GatherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_folder_walk_only_checks_image_files(self):
        self.write("good.png", png_bytes(640, 480))
        self.write("notes.txt", b"no image here at all")
        self.write("sub/big.png", png_bytes(2000, 1500))
        entries, checked, skipped = idc.gather(
            [str(self.root)], [], True, (1600, None, None)
        )
        self.assertEqual(len(checked), 2)
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0][0].endswith("sub/big.png"))
        self.assertEqual(skipped, [])

    def test_no_recursive_stays_at_top_level(self):
        self.write("good.png", png_bytes(640, 480))
        self.write("sub/big.png", png_bytes(2000, 1500))
        entries, checked, skipped = idc.gather(
            [str(self.root)], [], False, (1600, None, None)
        )
        self.assertEqual(len(checked), 1)
        self.assertEqual(entries, [])

    def test_git_folder_is_never_walked(self):
        git = self.root / ".git"
        git.mkdir()
        (git / "big.png").write_bytes(png_bytes(2000, 1500))
        self.write("good.png", png_bytes(640, 480))
        entries, checked, skipped = idc.gather(
            [str(self.root)], [], True, (1600, None, None)
        )
        self.assertEqual(len(checked), 1)
        self.assertEqual(entries, [])

    def test_exclude_skips_matching_files(self):
        self.write("good.png", png_bytes(640, 480))
        self.write("draft.png", png_bytes(2000, 1500))
        entries, checked, skipped = idc.gather(
            [str(self.root)], ["draft*"], True, (1600, None, None)
        )
        self.assertEqual(len(checked), 1)
        self.assertEqual(entries, [])

    def test_direct_file_is_checked_even_without_image_extension(self):
        path = self.write("photo.txt", png_bytes(640, 480))
        entries, checked, skipped = idc.gather(
            [str(path)], [], True, (None, None, None)
        )
        self.assertEqual(len(checked), 1)
        self.assertEqual(checked[0]["format"], "PNG")
        self.assertEqual(entries, [])

    def test_direct_file_is_checked_even_if_excluded(self):
        path = self.write("draft.png", png_bytes(2000, 1500))
        entries, checked, skipped = idc.gather(
            [str(path)], ["draft*"], True, (1600, None, None)
        )
        self.assertEqual(len(entries), 1)

    def test_uppercase_extension_is_checked(self):
        path = self.write("UPPER.PNG", png_bytes(640, 480))
        entries, checked, skipped = idc.gather(
            [str(self.root)], [], True, (None, None, None)
        )
        self.assertEqual(len(checked), 1)

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            idc.gather(
                [str(self.root / "nope")], [], True, (None, None, None)
            )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_listing_mode_lists_size_and_exits_zero(self):
        path = self.write("good.png", png_bytes(640, 480))
        code, out, err = run_cli([str(path)])
        self.assertEqual(code, 0)
        self.assertIn(f"{path}: 640x480 (PNG)", out)
        self.assertIn("Checked 1 file(s).", out)
        self.assertEqual(err, "")

    def test_exit_zero_on_clean_file_with_limits(self):
        path = self.write("good.png", png_bytes(640, 480))
        code, out, err = run_cli(["--max-width", "1600", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(
            out, "OK — 1 file(s) checked, all images within limits.\n"
        )
        self.assertEqual(err, "")

    def test_exit_one_on_oversized_file(self):
        path = self.write("big.png", png_bytes(2000, 1500))
        code, out, err = run_cli(
            ["--max-width", "1600", "--max-height", "800", str(path)]
        )
        self.assertEqual(code, 1)
        self.assertIn(
            f"FAIL {path}: 2000x1500 (PNG) — too wide "
            "(2000 pixels, maximum 1600)",
            out,
        )
        self.assertIn(
            f"FAIL {path}: 2000x1500 (PNG) — too tall "
            "(1500 pixels, maximum 800)",
            out,
        )
        self.assertIn("Checked 1 file(s), 2 problem(s) in 1 file(s).", out)

    def test_exit_two_on_missing_path(self):
        code, out, err = run_cli([str(self.root / "nope.png")])
        self.assertEqual(code, 2)
        self.assertIn("no such file or folder", err)

    def test_exit_two_with_no_input(self):
        code, out, err = run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("no image files to check", err)

    def test_exit_two_on_empty_folder(self):
        code, out, err = run_cli([str(self.root)])
        self.assertEqual(code, 2)
        self.assertIn("no image files to check", err)

    def test_exit_two_on_zero_limit(self):
        path = self.write("good.png", png_bytes(640, 480))
        code, out, err = run_cli(["--max-width", "0", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("--max-width must be 1 or more", err)

    def test_exit_two_on_negative_limit(self):
        path = self.write("good.png", png_bytes(640, 480))
        code, out, err = run_cli(["--max-pixels", "-5", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("--max-pixels must be 1 or more", err)

    def test_bad_flag_exits_two(self):
        with self.assertRaises(SystemExit) as caught:
            run_cli(["--nope"])
        self.assertEqual(caught.exception.code, 2)

    def test_version(self):
        code, out, err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "image-dimension-checker-cli 1.0.0\n")

    def test_stdin_good_and_bad(self):
        code, out, err = run_cli(
            ["--stdin", "--max-width", "1600"], png_bytes(640, 480)
        )
        self.assertEqual(code, 0)
        self.assertIn("all images within limits", out)
        code, out, err = run_cli(
            ["--stdin", "--max-width", "1600"], png_bytes(2000, 1500)
        )
        self.assertEqual(code, 1)
        self.assertIn(
            "FAIL <stdin>: 2000x1500 (PNG) — too wide "
            "(2000 pixels, maximum 1600)",
            out,
        )

    def test_stdin_listing_mode(self):
        code, out, err = run_cli(["--stdin"], png_bytes(640, 480))
        self.assertEqual(code, 0)
        self.assertIn("<stdin>: 640x480 (PNG)", out)

    def test_stdin_empty_is_a_problem(self):
        code, out, err = run_cli(["--stdin"], b"")
        self.assertEqual(code, 1)
        self.assertIn("FAIL <stdin>: cannot read dimensions (empty file)", out)

    def test_stdin_text_is_not_an_image(self):
        code, out, err = run_cli(["--stdin"], b"hello\n")
        self.assertEqual(code, 1)
        self.assertIn("FAIL <stdin>: not a supported image file", out)

    def test_json_output_parses_and_summary_goes_to_stderr(self):
        path = self.write("big.png", png_bytes(2000, 1500))
        code, out, err = run_cli(["--json", "--max-width", "1600", str(path)])
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["summary"]["checked"], 1)
        self.assertEqual(result["summary"]["problems"], 1)
        self.assertEqual(result["summary"]["files_with_problems"], 1)
        self.assertEqual(result["summary"]["max_width"], 1600)
        self.assertIsNone(result["summary"]["max_height"])
        self.assertEqual(result["files"][0]["file"], str(path))
        self.assertEqual(result["files"][0]["format"], "PNG")
        self.assertEqual(result["files"][0]["width"], 2000)
        self.assertEqual(result["files"][0]["height"], 1500)
        self.assertEqual(
            result["files"][0]["problems"],
            [
                {
                    "line": 0,
                    "reason": "too wide (2000 pixels, maximum 1600)",
                }
            ],
        )
        self.assertIn("Checked 1 file(s), 1 problem(s) in 1 file(s).", err)
        self.assertNotIn("Checked", out)

    def test_max_pixels_flag(self):
        path = self.write("pic.png", png_bytes(1000, 1001))
        code, out, err = run_cli(["--max-pixels", "1000000", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("too many pixels (1001000 pixels, maximum 1000000)", out)

    def test_input_files_are_left_unchanged(self):
        path = self.write("big.png", png_bytes(2000, 1500))
        before = path.read_bytes()
        run_cli(["--max-width", "1600", str(path)])
        self.assertEqual(path.read_bytes(), before)

    def test_non_image_direct_file_is_a_problem(self):
        path = self.write("note.txt", b"this is not an image\n")
        code, out, err = run_cli([str(path)])
        self.assertEqual(code, 1)
        self.assertIn(f"FAIL {path}: not a supported image file", out)


class ExamplesTests(unittest.TestCase):
    def test_sample_output_matches_a_fresh_run(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        expected = (REPO_ROOT / "examples" / "sample-output.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(result.stdout, expected)

    def test_readme_quoted_outputs_are_real(self):
        cases = [
            (
                ["examples/small.png"],
                "examples/small.png: 640x480 (PNG)",
            ),
            (
                ["--max-width", "1600", "examples/wide.png"],
                "FAIL examples/wide.png: 1920x1080 (PNG) — too wide "
                "(1920 pixels, maximum 1600)",
            ),
            (
                ["--max-height", "800", "examples/tall.png"],
                "FAIL examples/tall.png: 800x1200 (PNG) — too tall "
                "(1200 pixels, maximum 800)",
            ),
            (
                [
                    "--max-width",
                    "1600",
                    "--max-height",
                    "800",
                    "--max-pixels",
                    "1000000",
                    "examples/big.jpg",
                ],
                "FAIL examples/big.jpg: 2000x1500 (JPEG) — too many "
                "pixels (3000000 pixels, maximum 1000000)",
            ),
            (
                ["--max-width", "1600", "examples/photos/"],
                "FAIL examples/photos/banner.png: 2000x500 (PNG) — too "
                "wide (2000 pixels, maximum 1600)",
            ),
            (
                ["--max-pixels", "1000000", "examples/small.png"],
                "OK — 1 file(s) checked, all images within limits.",
            ),
            (
                ["examples/corrupt.png"],
                "FAIL examples/corrupt.png: cannot read dimensions "
                "(truncated or corrupt file)",
            ),
            (
                ["examples/note.txt"],
                "FAIL examples/note.txt: not a supported image file "
                "(PNG, JPEG, GIF, BMP, WebP)",
            ),
        ]
        for argv, expected_line in cases:
            code, out, err = run_cli(argv)
            self.assertIn(expected_line, out, f"argv={argv}")

    def test_example_files_are_checked_by_the_tests(self):
        examples = REPO_ROOT / "examples"
        image_files = sorted(
            p
            for p in examples.rglob("*")
            if p.is_file()
            and p.suffix.lower()
            in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
        )
        self.assertGreaterEqual(len(image_files), 10)


class HygieneTests(unittest.TestCase):
    def _repo_files(self):
        for path in REPO_ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(REPO_ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if parts[0] == "tests":
                continue
            yield path

    def test_no_placeholder_text(self):
        banned = ["TODO", "FIXME", "XXX", "coming soon", "lorem"]
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append(f"{path.relative_to(REPO_ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for needle in ("/home/", "/Users/", "C:\\"):
                if needle in text:
                    hits.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        allowed = ALLOWED_STDLIB | {
            "io",
            "subprocess",
            "tempfile",
            "unittest",
            "image_dimension_checker",
        }
        hits = []
        for path in list((REPO_ROOT / "src").glob("*.py")) + list(
            (REPO_ROOT / "tests").glob("*.py")
        ):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                for prefix in ("import ", "from "):
                    if line.startswith(prefix):
                        name = line[len(prefix):].split()[0].split(".")[0]
                        if name not in allowed and name != "contextlib":
                            hits.append(f"{path.name}: {line}")
        self.assertEqual(hits, [])

    def test_env_is_first_line_of_gitignore(self):
        lines = (REPO_ROOT / ".gitignore").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertTrue(lines)
        self.assertEqual(lines[0], ".env")

    def test_ci_file_runs_the_test_file(self):
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 tests/test_image_dimension_checker.py", ci)
        self.assertIn("actions/checkout@v4", ci)
        self.assertIn("actions/setup-python@v5", ci)
        self.assertIn('python-version: "3.12"', ci)


if __name__ == "__main__":
    unittest.main()
