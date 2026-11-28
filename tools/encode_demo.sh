#!/bin/sh
# Encode the raw demo (tools/record_demo.py) for the README:
#   docs/demo/demo.webp  animated WebP shown inline by GitHub (960 px, 12 fps)
#   docs/demo/demo.mp4   full quality (1280x800, H.264), linked under it
# Usage: tools/encode_demo.sh <demo.webm> <output folder>
set -e
SRC="$1"; OUT="${2:-docs/demo}"
mkdir -p "$OUT"
ffmpeg -v error -y -ss 0.6 -i "$SRC" -c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p \
  -movflags +faststart -an "$OUT/demo.mp4"
ffmpeg -v error -y -ss 0.6 -i "$SRC" -vf "fps=12,scale=960:-2:flags=lanczos" -c:v libwebp_anim \
  -lossless 0 -quality 70 -compression_level 6 -loop 0 -an "$OUT/demo.webp"
ls -l "$OUT"/demo.mp4 "$OUT"/demo.webp
