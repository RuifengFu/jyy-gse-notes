"""Crop frames to a region given as fractions of width/height (e.g. the slide half of a camera+slides layout).

    python crop.py x0 y0 x1 y1 in.jpg [in2.jpg ...] -o OUTDIR
    python crop.py 0.43 0 1 1 frames/k012_*.jpg -o note/images/02
    python crop.py 0.02 0.08 0.42 0.84 frames/k057_*.jpg -o note/images/02 --suffix _board
"""
import argparse
from pathlib import Path

import cv2

ap = argparse.ArgumentParser()
ap.add_argument("box", nargs=4, type=float, metavar=("x0", "y0", "x1", "y1"))
ap.add_argument("files", nargs="+", type=Path)
ap.add_argument("-o", "--out", type=Path, required=True)
ap.add_argument("--suffix", default="", help="added before .jpg, for a second crop of the same frame")
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
x0, y0, x1, y1 = a.box
for f in a.files:
    img = cv2.imread(str(f))
    h, w = img.shape[:2]
    dst = a.out / f"{f.stem}{a.suffix}{f.suffix}"
    cv2.imwrite(str(dst), img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)], [cv2.IMWRITE_JPEG_QUALITY, 92])
    print(dst)
