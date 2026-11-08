#!/bin/sh
# Check the bundled examples. The failing runs exit 1 on purpose,
# so each one ends with "|| true"; the script itself ends with
# exit 0 so it can be run as a demo. Run from the repo root:
# sh examples/run-example.sh
cd "$(dirname "$0")/.."
echo "== small.png: no limits, lists its size =="
python3 src/image_dimension_checker.py examples/small.png || true
echo
echo "== wide.png: too wide for a 1600-pixel limit =="
python3 src/image_dimension_checker.py --max-width 1600 examples/wide.png || true
echo
echo "== big.jpg: too wide, too tall, too many pixels =="
python3 src/image_dimension_checker.py --max-width 1600 --max-height 800 --max-pixels 1000000 examples/big.jpg || true
echo
echo "== photos/: a folder walk with a 1600-pixel limit =="
python3 src/image_dimension_checker.py --max-width 1600 examples/photos/ || true
