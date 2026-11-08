#!/usr/bin/env python3
"""Check images are not bigger than your limits, fail CI on an oversized image.

Run: python3 src/image_dimension_checker.py examples/small.png
     python3 src/image_dimension_checker.py --max-width 1600 examples/wide.png
     python3 src/image_dimension_checker.py --max-width 1600 examples/photos/
     python3 src/image_dimension_checker.py examples/

The problem is quiet: an oversized image slows a page down
and breaks a layout, and the person who uploaded it never
notices — the image itself looks fine on screen. Bloggers
and site owners upload them constantly. This tool reads
pixel dimensions straight from the image file headers —
PNG, JPEG, GIF, BMP, and WebP — reports every image that is
bigger than the limits you set (--max-width, --max-height,
or --max-pixels), with its file, its size, and the exact
reason, and exits 1 when any problem is found, so it can
fail a CI run. A clean folder exits 0. With no limits set,
it just lists every image's size.

Dimensions come from the headers only, so the tool never
decodes a pixel: a PNG's IHDR chunk, a JPEG's SOF marker,
a GIF's header, a BMP's DIB header, and a WebP's VP8X,
VP8L, or VP8 chunk. A file whose size cannot be read — a
truncated or corrupt file, or a file that is not an image
at all — is reported as a problem, not skipped, because a
file that cannot be checked cannot be trusted.

It never rewrites a file. It is report-only and runs fully
offline: it sends nothing anywhere and needs no API key.

Exit codes: 0 when every checked image is within the
limits (or just listed, when no limits are set), 1 when
any image is oversized or unreadable, 2 for a usage or
input problem (a missing path, a bad flag, a bad limit, or
no image files to check).

Python standard library only. No Pillow, no image library
of any kind — sizes are read from the headers by hand with
struct.
"""

import argparse
import fnmatch
import json
import os
import struct
import sys
from pathlib import Path

VERSION = "1.0.0"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPPORTED_FORMATS = "PNG, JPEG, GIF, BMP, WebP"


def _read_jpeg(data):
    """Return (format, width, height) from JPEG bytes, or None.

    Walks the markers after SOI until a SOF marker (0, 1, 2, or
    3 — baseline, extended, progressive, or lossless) gives the
    size. Returns None when the file ends, hits SOS (scan data
    follows, so no SOF comes after it), or is malformed.
    """
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    standalone = {0x01} | set(range(0xD0, 0xDA))
    pos = 2
    size = len(data)
    while pos < size:
        if data[pos] != 0xFF:
            return None
        while pos < size and data[pos] == 0xFF:
            pos += 1
        if pos >= size:
            return None
        marker = data[pos]
        pos += 1
        if marker == 0x00:
            continue
        if marker in standalone:
            continue
        if marker == 0xDA:
            return None
        if pos + 2 > size:
            return None
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2 or pos + length > size:
            return None
        if marker in sof_markers:
            if length < 7 or pos + 7 > size:
                return None
            height = struct.unpack(">H", data[pos + 3:pos + 5])[0]
            width = struct.unpack(">H", data[pos + 5:pos + 7])[0]
            return ("JPEG", width, height)
        pos += length
    return None


def _read_webp(data):
    """Return (format, width, height) from WebP bytes, or None.

    The first chunk must be VP8X (extended), VP8L (lossless),
    or VP8 (lossy). Each one stores the size differently:
    VP8X keeps width and height minus one in three bytes each,
    VP8L packs them into 14 bits each, and lossy VP8 keeps
    them in two bytes each, also 14 bits.
    """
    if len(data) < 20:
        return None
    fourcc = data[12:16]
    chunk_size = struct.unpack("<I", data[16:20])[0]
    if len(data) < 20 + chunk_size:
        return None
    chunk = data[20:20 + chunk_size]
    if fourcc == b"VP8X":
        if len(chunk) < 10:
            return None
        width = int.from_bytes(chunk[4:7], "little") + 1
        height = int.from_bytes(chunk[7:10], "little") + 1
        return ("WebP", width, height)
    if fourcc == b"VP8L":
        if len(chunk) < 5 or chunk[0] != 0x2F:
            return None
        packed = struct.unpack("<I", chunk[1:5])[0]
        width = (packed & 0x3FFF) + 1
        height = ((packed >> 14) & 0x3FFF) + 1
        return ("WebP", width, height)
    if fourcc == b"VP8 ":
        if len(chunk) < 10:
            return None
        if chunk[3:6] != b"\x9d\x01\x2a":
            return None
        width = struct.unpack("<H", chunk[6:8])[0] & 0x3FFF
        height = struct.unpack("<H", chunk[8:10])[0] & 0x3FFF
        return ("WebP", width, height)
    return None


def read_dimensions(data):
    """Return (format, width, height) for image bytes.

    Raises ValueError with a plain reason when the size cannot
    be read: empty input, a truncated or corrupt header, or a
    file that is not a supported image at all.
    """
    if not data:
        raise ValueError("cannot read dimensions (empty file)")
    if data[:8] == PNG_SIGNATURE:
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ValueError(
                "cannot read dimensions (truncated or corrupt file)"
            )
        image_format = "PNG"
        width, height = struct.unpack(">II", data[16:24])
    elif data[:2] == b"\xff\xd8":
        result = _read_jpeg(data)
        if result is None:
            raise ValueError(
                "cannot read dimensions (truncated or corrupt file)"
            )
        return result
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        if len(data) < 10:
            raise ValueError(
                "cannot read dimensions (truncated or corrupt file)"
            )
        image_format = "GIF"
        width, height = struct.unpack("<HH", data[6:10])
    elif data[:2] == b"BM":
        if len(data) < 18:
            raise ValueError(
                "cannot read dimensions (truncated or corrupt file)"
            )
        image_format = "BMP"
        dib_size = struct.unpack("<I", data[14:18])[0]
        if dib_size == 12:
            if len(data) < 22:
                raise ValueError(
                    "cannot read dimensions (truncated or corrupt file)"
                )
            width, height = struct.unpack("<HH", data[18:22])
        else:
            if len(data) < 26:
                raise ValueError(
                    "cannot read dimensions (truncated or corrupt file)"
                )
            width, height = struct.unpack("<ii", data[18:26])
            height = abs(height)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        result = _read_webp(data)
        if result is None:
            raise ValueError(
                "cannot read dimensions (truncated or corrupt file)"
            )
        return result
    else:
        raise ValueError(
            f"not a supported image file ({SUPPORTED_FORMATS})"
        )
    if width <= 0 or height <= 0:
        raise ValueError(
            "cannot read dimensions (truncated or corrupt file)"
        )
    return (image_format, width, height)


def check_limits(image_format, width, height, limits):
    """Return the problems for one image against the limits.

    limits is (max_width, max_height, max_pixels); any of
    them may be None, which means no limit on that side.
    A size exactly on a limit passes — only bigger fails.
    """
    max_width, max_height, max_pixels = limits
    problems = []
    if max_width is not None and width > max_width:
        problems.append(
            {
                "line": 0,
                "reason": (
                    f"too wide ({width} pixels, "
                    f"maximum {max_width})"
                ),
            }
        )
    if max_height is not None and height > max_height:
        problems.append(
            {
                "line": 0,
                "reason": (
                    f"too tall ({height} pixels, "
                    f"maximum {max_height})"
                ),
            }
        )
    if max_pixels is not None and width * height > max_pixels:
        problems.append(
            {
                "line": 0,
                "reason": (
                    f"too many pixels ({width * height} pixels, "
                    f"maximum {max_pixels})"
                ),
            }
        )
    return problems


def collect_from_file(path, limits):
    """Return (problems, skipped, info) for one file.

    problems is a list of dicts; skipped is always False —
    nothing is skipped, a file that cannot be read is a
    problem. info is (format, width, height), or None when
    the size could not be read.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        return (
            [
                {
                    "line": 0,
                    "reason": f"cannot read file: {exc.strerror}",
                }
            ],
            False,
            None,
        )
    try:
        image_format, width, height = read_dimensions(data)
    except ValueError as exc:
        return ([{"line": 0, "reason": str(exc)}], False, None)
    return (
        check_limits(image_format, width, height, limits),
        False,
        (image_format, width, height),
    )


def _is_image(name):
    return Path(name).suffix.lower() in IMAGE_EXTENSIONS


def gather(paths, exclude, recursive, limits):
    """Walk the given paths and return (entries, checked, skipped).

    entries is a list of (file, problem); checked is a list of
    one dict per file the tool tried, with file, format, width,
    and height (None when the size could not be read); skipped
    is always an empty list — every file with an image
    extension is either checked or reported, never skipped.
    A file passed on the command line is always checked, even
    if it matches --exclude and even if it has no image
    extension. Inside a folder, only image files are checked.
    """
    entries = []
    checked = []
    skipped = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise FileNotFoundError(raw)
        if path.is_file():
            problems, _was_skipped, info = collect_from_file(path, limits)
            if info is None:
                checked.append(
                    {
                        "file": str(path),
                        "format": None,
                        "width": None,
                        "height": None,
                    }
                )
            else:
                image_format, width, height = info
                checked.append(
                    {
                        "file": str(path),
                        "format": image_format,
                        "width": width,
                        "height": height,
                    }
                )
            for problem in problems:
                entries.append((str(path), problem))
            continue
        if recursive:
            for dirpath, dirnames, filenames in _walk(path):
                for name in filenames:
                    if not _is_image(name):
                        continue
                    candidate = Path(dirpath) / name
                    if _excluded(candidate, path, exclude):
                        continue
                    problems, _was_skipped, info = collect_from_file(
                        candidate, limits
                    )
                    if info is None:
                        checked.append(
                            {
                                "file": str(candidate),
                                "format": None,
                                "width": None,
                                "height": None,
                            }
                        )
                    else:
                        image_format, width, height = info
                        checked.append(
                            {
                                "file": str(candidate),
                                "format": image_format,
                                "width": width,
                                "height": height,
                            }
                        )
                    for problem in problems:
                        entries.append((str(candidate), problem))
        else:
            for candidate in sorted(path.iterdir()):
                if not candidate.is_file():
                    continue
                if not _is_image(candidate.name):
                    continue
                if _excluded(candidate, path, exclude):
                    continue
                problems, _was_skipped, info = collect_from_file(
                    candidate, limits
                )
                if info is None:
                    checked.append(
                        {
                            "file": str(candidate),
                            "format": None,
                            "width": None,
                            "height": None,
                        }
                    )
                else:
                    image_format, width, height = info
                    checked.append(
                        {
                            "file": str(candidate),
                            "format": image_format,
                            "width": width,
                            "height": height,
                        }
                    )
                for problem in problems:
                    entries.append((str(candidate), problem))
    return entries, checked, skipped


def _walk(root):
    """os.walk that never enters .git and never follows links."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        yield dirpath, dirnames, sorted(filenames)


def _excluded(candidate, root, patterns):
    name = candidate.name
    try:
        rel = str(candidate.relative_to(root))
    except ValueError:
        rel = name
    return any(
        fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern)
        for pattern in patterns
    )


def _format_problem(location, problem, checked):
    dims = ""
    for entry in checked:
        if entry["file"] == location and entry["width"] is not None:
            dims = (
                f": {entry['width']}x{entry['height']} "
                f"({entry['format']})"
            )
            break
    return f"FAIL {location}{dims} — {problem['reason']}"


def _summary_line(checked, problems, has_limits):
    total = len(problems)
    bad_files = len({f for f, _p in problems})
    if total:
        return (
            f"Checked {len(checked)} file(s), {total} "
            f"problem(s) in {bad_files} file(s)."
        )
    if has_limits:
        return (
            f"OK — {len(checked)} file(s) checked, "
            f"all images within limits."
        )
    return f"Checked {len(checked)} file(s)."


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="image-dimension-checker-cli",
        description="Check images are not bigger than your limits.",
    )
    parser.add_argument("paths", nargs="*", help="files or folders to check")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read one image from standard input",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=None,
        metavar="N",
        help="fail an image wider than N pixels",
    )
    parser.add_argument(
        "--max-height",
        type=int,
        default=None,
        metavar="N",
        help="fail an image taller than N pixels",
    )
    parser.add_argument(
        "--max-pixels",
        type=int,
        default=None,
        metavar="N",
        help="fail an image with more than N pixels in total",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="skip files matching this glob (repeatable)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="do not walk into subfolders",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON (summary goes to stderr)",
    )
    parser.add_argument("--version", action="store_true", help="print the version")
    args = parser.parse_args(argv)

    if args.version:
        print(f"image-dimension-checker-cli {VERSION}")
        return 0

    for flag, value in (
        ("--max-width", args.max_width),
        ("--max-height", args.max_height),
        ("--max-pixels", args.max_pixels),
    ):
        if value is not None and value < 1:
            print(
                f"error: {flag} must be 1 or more",
                file=sys.stderr,
            )
            return 2

    limits = (args.max_width, args.max_height, args.max_pixels)
    has_limits = any(value is not None for value in limits)

    entries = []
    checked = []
    skipped = []
    try:
        if args.paths:
            found, found_checked, found_skipped = gather(
                args.paths,
                args.exclude,
                not args.no_recursive,
                limits,
            )
            entries.extend(found)
            checked.extend(found_checked)
            skipped.extend(found_skipped)
    except FileNotFoundError as exc:
        print(f"error: no such file or folder: {exc}", file=sys.stderr)
        return 2

    if args.stdin:
        data = sys.stdin.buffer.read()
        try:
            image_format, width, height = read_dimensions(data)
        except ValueError as exc:
            entries.append(
                ("<stdin>", {"line": 0, "reason": str(exc)})
            )
            checked.append(
                {
                    "file": "<stdin>",
                    "format": None,
                    "width": None,
                    "height": None,
                }
            )
        else:
            checked.append(
                {
                    "file": "<stdin>",
                    "format": image_format,
                    "width": width,
                    "height": height,
                }
            )
            for problem in check_limits(
                image_format, width, height, limits
            ):
                entries.append(("<stdin>", problem))

    if not checked:
        print("error: no image files to check", file=sys.stderr)
        return 2

    problems = entries
    bad_files = len({f for f, _p in problems})
    total = len(problems)
    summary = _summary_line(checked, problems, has_limits)

    if args.json:
        files = []
        for entry in checked:
            file_problems = [p for f, p in problems if f == entry["file"]]
            files.append(
                {
                    "file": entry["file"],
                    "format": entry["format"],
                    "width": entry["width"],
                    "height": entry["height"],
                    "problems": file_problems,
                }
            )
        result = {
            "files": files,
            "summary": {
                "checked": len(checked),
                "files_with_problems": bad_files,
                "problems": total,
                "skipped": len(skipped),
                "max_width": args.max_width,
                "max_height": args.max_height,
                "max_pixels": args.max_pixels,
            },
        }
        print(json.dumps(result, indent=2))
        print(summary, file=sys.stderr)
        return 1 if problems else 0

    if has_limits:
        for location, problem in problems:
            print(_format_problem(location, problem, checked))
    else:
        for entry in checked:
            file_problems = [p for f, p in problems if f == entry["file"]]
            if entry["width"] is None:
                for problem in file_problems:
                    print(f"FAIL {entry['file']}: {problem['reason']}")
            else:
                print(
                    f"{entry['file']}: {entry['width']}x"
                    f"{entry['height']} ({entry['format']})"
                )
    print(summary)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
