"""Triage view: crop every keyframe to the slide area and stack N per image at full resolution.

    python stack.py <workdir> x0 y0 x1 y1 [-n 4]      → <workdir>/stacks/stack_NN.jpg
Contact sheets are too small to read slide text; open these stacks to decide keep/drop.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("work", type=Path)
ap.add_argument("box", nargs=4, type=float)
ap.add_argument("-n", type=int, default=4)
a = ap.parse_args()
kfs = json.loads((a.work / "keyframes.json").read_text())["keyframes"]
out = a.work / "stacks"
out.mkdir(exist_ok=True)
for old in out.glob("stack_*.jpg"):
    old.unlink()
x0, y0, x1, y1 = a.box
for i in range(0, len(kfs), a.n):
    tiles = []
    for k in kfs[i:i + a.n]:
        img = cv2.imread(str(a.work / k["file"]))
        h, w = img.shape[:2]
        c = img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].copy()
        ch, cw = c.shape[:2]   # label bottom-right: slide titles sit top-left
        cv2.rectangle(c, (cw - 170, ch - 28), (cw, ch), (0, 0, 0), -1)
        cv2.putText(c, f"{k['id']} {int(k['t'])//60:02d}:{int(k['t'])%60:02d}", (cw - 164, ch - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(c)
    wmax = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 6, 0, wmax - t.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    p = out / f"stack_{i // a.n + 1:02d}.jpg"
    cv2.imwrite(str(p), np.vstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 85])
print(f"{len(list(out.glob('stack_*.jpg')))} stacks → {out}")
