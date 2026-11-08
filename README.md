# image-dimension-checker-cli

Check images are not bigger than your limits, fail CI on an oversized image.

[![CI](https://github.com/haiderstudio/image-dimension-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/image-dimension-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`image_dimension_checker` reads pixel dimensions
straight from image file headers and checks each image
against the limits you set:

- An oversized image slows a page down and breaks a
  layout, and the person who uploaded it never notices —
  the image itself looks fine on screen. Bloggers and
  site owners upload them constantly. This tool reports
  every image that is bigger than your limits, with its
  file, its size, and the exact reason, and exits 1 when
  any problem is found — so it can fail a CI run. A clean
  folder exits 0.
- Three limits, each on its own: `--max-width` in pixels,
  `--max-height` in pixels, and `--max-pixels` for the
  total (width times height). A size exactly on a limit
  passes — only bigger fails. An image can fail more than
  one limit at once, and each reason is reported.
- With no limits set, the tool just lists every image's
  size — handy when you only want to see what you have.
- Dimensions come from the headers only, so the tool
  never decodes a pixel: a PNG's IHDR chunk, a JPEG's
  SOF marker (baseline, extended, progressive, and
  lossless all work), a GIF's header, a BMP's DIB
  header (including the old 12-byte core header and
  top-down images with a negative height), and a WebP's
  VP8X, VP8L, or VP8 chunk.
- A file whose size cannot be read — a truncated or
  corrupt file, or a file that is not an image at all —
  is reported as a problem, not skipped, because a file
  that cannot be checked cannot be trusted.
- Images come from the command line (one or more), or
  from a folder walk: every `.png`, `.jpg`, `.jpeg`,
  `.gif`, `.bmp`, and `.webp` file under a folder,
  recursively by default (`--no-recursive` stops at the
  top level). `.git` folders are never walked, and
  directory links are never followed, so a link cycle
  cannot loop the check.
- `--exclude PATTERN` skips files by glob, for example
  `--exclude 'draft-*'`. It can be repeated. A file passed
  directly on the command line is always checked, even if
  it matches an exclude pattern and even if it has no
  image extension.
- `--stdin` reads one image from standard input.
- `--json` prints the result as machine-readable JSON (the
  summary goes to standard error, so standard output stays
  clean JSON).
- It is report-only and runs fully offline: it never
  resizes an image, sends nothing anywhere, and needs no
  API key. No Pillow, no image library of any kind —
  sizes are read from the headers by hand with `struct`.

## What it does NOT do

- It does not resize, recompress, or rewrite an image. An
  oversized image is reported; shrinking it is your job.
- It does not check file size in bytes — that is Day 34's
  `file-size-checker-cli`. This tool's one job is pixels.
- It does not check alt text — that is Day 30's
  `image-alt-checker-cli`.
- It does not fetch images from a live site. Every input
  is a local file or standard input — an image that only
  exists on the web is not this tool's job.

## Who it is for

Anyone who puts images on a site and wants them to stay
within bounds: a blogger checking a batch of uploads, a
developer adding a CI step that fails the build when an
image ships too big, or anyone tidying a folder of old
photos. An oversized image is invisible in the file
itself — this catches it before it goes live.

## How this differs from similar tools

The exact name `image-dimension-checker-cli` matches 0
repositories on GitHub (checked Nov 8, 2026), and
`image size checker cli` and `image dimension checker
cli` match 0 too. The wider field is small: `image
dimension checker` matches 8 repositories. The top one,
AnurupaK/ImageDimensionChecker, 3 stars, is a Python
package for analysing image datasets — consistency
checks, not a max-size gate for CI. Next,
kitconcept/image-checker, 1 star, is a GitHub Action
that validates image constraints in pull requests —
an Action, not a local CLI you can run on your own
machine or in any CI. The rest are 0-star scripts,
including one that checks `<img>` tags in a site's
HTML (a different job — tags, not image files) and
one that checks a share image against Open Graph
rules. None of them is a tested CLI that walks a
folder of local image files, reads pixel dimensions
from the headers with no image library, and exits 1
for CI. This tool does that one job: a Python
standard-library-only CLI that checks PNG, JPEG,
GIF, BMP, and WebP files against the limits you set
— no install beyond Python, no website, no network.

## Install

Python standard library only — no packages to download. You need
Python 3.8 or newer. Clone the repo and run it in place:

```
git clone https://github.com/haiderstudio/image-dimension-checker-cli.git
cd image-dimension-checker-cli
python3 src/image_dimension_checker.py examples/small.png
```

```
examples/small.png: 640x480 (PNG)
Checked 1 file(s).
```

## Usage

List one image's size, no limits:

```
python3 src/image_dimension_checker.py examples/small.png
```

```
examples/small.png: 640x480 (PNG)
Checked 1 file(s).
```

Check an image against a width limit:

```
python3 src/image_dimension_checker.py --max-width 1600 examples/wide.png
```

```
FAIL examples/wide.png: 1920x1080 (PNG) — too wide (1920 pixels, maximum 1600)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Check an image against a height limit:

```
python3 src/image_dimension_checker.py --max-height 800 examples/tall.png
```

```
FAIL examples/tall.png: 800x1200 (PNG) — too tall (1200 pixels, maximum 800)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Check an image against all three limits at once:

```
python3 src/image_dimension_checker.py --max-width 1600 --max-height 800 --max-pixels 1000000 examples/big.jpg
```

```
FAIL examples/big.jpg: 2000x1500 (JPEG) — too wide (2000 pixels, maximum 1600)
FAIL examples/big.jpg: 2000x1500 (JPEG) — too tall (1500 pixels, maximum 800)
FAIL examples/big.jpg: 2000x1500 (JPEG) — too many pixels (3000000 pixels, maximum 1000000)
Checked 1 file(s), 3 problem(s) in 1 file(s).
```

Check a whole folder:

```
python3 src/image_dimension_checker.py --max-width 1600 examples/photos/
```

```
FAIL examples/photos/banner.png: 2000x500 (PNG) — too wide (2000 pixels, maximum 1600)
Checked 2 file(s), 1 problem(s) in 1 file(s).
```

Check against a total-pixel limit — a small image passes:

```
python3 src/image_dimension_checker.py --max-pixels 1000000 examples/small.png
```

```
OK — 1 file(s) checked, all images within limits.
```

Check a corrupt file — reported, not skipped:

```
python3 src/image_dimension_checker.py examples/corrupt.png
```

```
FAIL examples/corrupt.png: cannot read dimensions (truncated or corrupt file)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Check a file that is not an image at all:

```
python3 src/image_dimension_checker.py examples/note.txt
```

```
FAIL examples/note.txt: not a supported image file (PNG, JPEG, GIF, BMP, WebP)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Check one image from standard input:

```
python3 src/image_dimension_checker.py --stdin --max-width 1600 < examples/small.png
```

```
OK — 1 file(s) checked, all images within limits.
```

Machine-readable output with `--json` (the summary goes to
standard error, so standard output stays clean JSON):

```
python3 src/image_dimension_checker.py --json --max-height 800 examples/tall.png
```

```
{
  "files": [
    {
      "file": "examples/tall.png",
      "format": "PNG",
      "width": 800,
      "height": 1200,
      "problems": [
        {
          "line": 0,
          "reason": "too tall (1200 pixels, maximum 800)"
        }
      ]
    }
  ],
  "summary": {
    "checked": 1,
    "files_with_problems": 1,
    "problems": 1,
    "skipped": 0,
    "max_width": null,
    "max_height": 800,
    "max_pixels": null
  }
}
```

Exit codes: 0 when every checked image is within the
limits (or just listed, when no limits are set), 1 when
any image is oversized or unreadable, 2 for a usage
problem (no image files given, a bad flag, a bad limit,
or a missing file or folder).

## Examples

### 1. A folder of uploads with a 1600-pixel width limit

`examples/photos/` holds two images. One is fine, one is
too wide:

```
python3 src/image_dimension_checker.py --max-width 1600 examples/photos/
```

```
FAIL examples/photos/banner.png: 2000x500 (PNG) — too wide (2000 pixels, maximum 1600)
Checked 2 file(s), 1 problem(s) in 1 file(s).
```

### 2. Listing a whole folder with no limits

With no limits set, every image's size is listed — and
the one file that cannot be read is still reported:

```
python3 src/image_dimension_checker.py examples/
```

```
examples/big.jpg: 2000x1500 (JPEG)
FAIL examples/corrupt.png: cannot read dimensions (truncated or corrupt file)
examples/icon.gif: 64x64 (GIF)
examples/photo.bmp: 300x200 (BMP)
examples/small.png: 640x480 (PNG)
examples/small.webp: 320x240 (WebP)
examples/tall.png: 800x1200 (PNG)
examples/wide.png: 1920x1080 (PNG)
examples/wide.webp: 1600x900 (WebP)
examples/photos/banner.png: 2000x500 (PNG)
examples/photos/hero.png: 1200x800 (PNG)
Checked 11 file(s), 1 problem(s) in 1 file(s).
```

### 3. The bundled examples, all at once

```
sh examples/run-example.sh
```

The script lists one image (pass), then checks the wide
image against a width limit (fail, on purpose), then the
big photo against all three limits (fail, on purpose),
then the `examples/photos/` folder (fail, on purpose —
it picks up `photos/banner.png`). Its full output is in
`examples/sample-output.md`, ending with `Checked 2
file(s), 1 problem(s) in 1 file(s).` The failing runs exit
1, which is the expected result — the script ends with
exit 0 so it can be run as a demo.

## How it is tested

69 tests, standard library `unittest` only, no packages to install:

```
python3 tests/test_image_dimension_checker.py
```

The tests cover: reading dimensions (PNG, JPEG baseline /
extended / progressive SOF markers, JPEG APP segments and
padding, SOS before SOF, GIF 87a and 89a, BMP info and
core headers, top-down negative height, WebP VP8X / VP8L
/ lossy VP8, truncated and corrupt headers, zero size,
text that is not an image, empty input, and every bundled
example file read back with its real size), the limits
(no limits, exact-limit pass, one pixel over on each
limit, all three limits at once), file collection (good
file, missing file, corrupt file, text file), folder
walking (only image extensions, `--no-recursive`, `.git`
skipped, `--exclude`, a direct file checked even without
an image extension and even if excluded, uppercase
extensions, missing path), the CLI (exit 0/1/2, listing
mode, each limit flag, bad limits, `--stdin` good and bad
and empty, `--json` output, `--version`, bad flags,
missing paths, empty folders, input files left unchanged,
a non-image file passed directly), the bundled examples
(sample output compared byte-for-byte against a fresh run,
and the README-quoted outputs checked against it), and
hygiene checks (no placeholder text, no absolute paths,
stdlib imports only, `.env` first in `.gitignore`, CI
file runs the test file).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The idea
of checking image sizes is not new — the similar tools
named above (the 3-star dataset package, the 1-star
GitHub Action, the 0-star scripts) are listed in "How
this differs" — but every line of code here is original,
and the tool builds on nothing but Python's standard
library.
