== small.png: no limits, lists its size ==
examples/small.png: 640x480 (PNG)
Checked 1 file(s).

== wide.png: too wide for a 1600-pixel limit ==
FAIL examples/wide.png: 1920x1080 (PNG) — too wide (1920 pixels, maximum 1600)
Checked 1 file(s), 1 problem(s) in 1 file(s).

== big.jpg: too wide, too tall, too many pixels ==
FAIL examples/big.jpg: 2000x1500 (JPEG) — too wide (2000 pixels, maximum 1600)
FAIL examples/big.jpg: 2000x1500 (JPEG) — too tall (1500 pixels, maximum 800)
FAIL examples/big.jpg: 2000x1500 (JPEG) — too many pixels (3000000 pixels, maximum 1000000)
Checked 1 file(s), 3 problem(s) in 1 file(s).

== photos/: a folder walk with a 1600-pixel limit ==
FAIL examples/photos/banner.png: 2000x500 (PNG) — too wide (2000 pixels, maximum 1600)
Checked 2 file(s), 1 problem(s) in 1 file(s).
