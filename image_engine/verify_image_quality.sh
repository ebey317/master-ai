#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${SDCPP_OUT_DIR:-$HOME/scripts/image_engine/out}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$OUT_DIR/verify_quality_${STAMP}.png"
PROMPT="${1:-a sharp product photo of a red ceramic mug on a wooden desk, natural window light, detailed, clean background}"

mkdir -p "$OUT_DIR"

"$HOME/scripts/image_engine/stable-diffusion.cpp/build/bin/sd-cli" \
  -m "$HOME/scripts/image_engine/models/v1-5-pruned-emaonly.safetensors" \
  -p "$PROMPT<lora:lcm-lora-sdv1-5:1>" \
  --lora-model-dir "$HOME/scripts/image_engine/models" \
  --taesd "$HOME/scripts/image_engine/models/taesd-sdv1-5.safetensors" \
  --steps 4 \
  --sampling-method euler_a \
  --cfg-scale 1 \
  -W 512 \
  -H 512 \
  -s 12345 \
  -o "$OUT"

python3 - "$OUT" <<'PY'
import math
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

path = Path(sys.argv[1])
if not path.exists() or path.stat().st_size < 10_000:
    raise SystemExit(f"FAIL: output missing or too small: {path}")

im = Image.open(path).convert("RGB")
gray = im.convert("L")
stat = ImageStat.Stat(im)
hist = gray.histogram()
total = sum(hist)
entropy = -sum((count / total) * math.log2(count / total) for count in hist if count)
edge_mean = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]

flat = max(stat.stddev) < 8 or entropy < 3.0
low_detail = edge_mean < 5
wrong_size = im.size != (512, 512)

print(f"file={path}")
print(f"size={im.width}x{im.height} mode={im.mode}")
print(f"mean_rgb={stat.mean[0]:.1f},{stat.mean[1]:.1f},{stat.mean[2]:.1f}")
print(f"std_rgb={stat.stddev[0]:.1f},{stat.stddev[1]:.1f},{stat.stddev[2]:.1f}")
print(f"entropy={entropy:.2f} bits")
print(f"edge_mean={edge_mean:.2f}")

if wrong_size or flat or low_detail:
    raise SystemExit("FAIL: generated image looks invalid, flat, or too low-detail")

print("PASS: valid 512x512 PNG with non-flat image detail")
PY
