"""Prepare a video for screenshot-driven notes: stable keyframes + the transcript spoken over each.

    python prep.py <url | video.mp4> [--srt subs.srt] [-w WORKDIR] [--cookies cookies.txt]

Writes to WORKDIR (default /Volumes/AppStorage/Scratch/video-summary/<id>/):
    frames/kNNN_hhmmss.jpg   one frame per *stable* screen (slide/code/diagram after it stopped changing)
    sheets/sheet_NN.jpg      contact sheets (4x3 thumbnails, labelled kNNN + time) for fast triage
    keyframes.json           [{id, t, t_end, file, change, text}] — text = transcript while that frame was on screen
    transcript.md            full transcript, one block per keyframe interval, with [hh:mm:ss]
A frame is "stable" when the block-wise change stays below --still for --hold seconds; it is kept
if it differs from every frame kept in the last 90 s by more than --new. Grid blocks that move most of
the time (the lecturer's camera, a webcam overlay) are detected first and ignored. So slide builds/animations settle first,
and camera jitter in one corner doesn't create a new keyframe.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

VS = Path.home() / "project/VideoSummary"   # reuse its venv, cookies and downloads
TIME = re.compile(r"(\d\d):(\d\d):(\d\d)[,.](\d{3})\s+-->\s+(\d\d):(\d\d):(\d\d)[,.](\d{3})")


def hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}"


def parse_srt(path: Path):
    cues, cur = [], None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        m = TIME.match(line.strip())
        if m:
            g = list(map(int, m.groups()))
            cur = [g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, []]
        elif not line.strip():
            if cur and cur[2]:
                cues.append((cur[0], cur[1], " ".join(cur[2])))
            cur = None
        elif cur is not None and not line.strip().isdigit():
            cur[2].append(line.strip())
    return cues


def fetch(url: str, work: Path, cookies: Path | None):
    """Download video + subtitles with yt-dlp (reuses files already in work/downloads)."""
    dl = work / "downloads"
    dl.mkdir(parents=True, exist_ok=True)
    vids = [p for p in dl.glob("*.mp4")]
    srts = sorted(dl.glob("*.srt"))
    base = [sys.executable, "-m", "yt_dlp", "--no-warnings", "-P", str(dl), "-o", "%(title)s.%(ext)s"]
    if cookies and cookies.exists():
        base += ["--cookies", str(cookies)]
    if not vids:
        subprocess.run(base + ["-f", "bv*[height<=720][ext=mp4]/bv*[height<=720]/bv*", "--remux-video", "mp4", url], check=True)
    if not srts:
        subprocess.run(base + ["--skip-download", "--write-subs", "--sub-langs", "ai-zh,zh-Hans,zh-CN,zh,en,ai-en",
                               "--sub-format", "srt", url], check=False)
    vids = sorted(dl.glob("*.mp4"))
    srts = sorted(dl.glob("*.srt"), key=lambda p: (0 if "zh" in p.name else 1, p.name))
    if not vids:
        sys.exit("video download failed")
    return vids[0], (srts[0] if srts else None)


def small(frame, w=160):
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h = max(1, int(g.shape[0] * w / g.shape[1]))
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


ROWS, COLS = 6, 8


def block_diffs(a, b):
    """Mean abs difference per grid block (ROWS x COLS)."""
    d = np.abs(a.astype(np.int16) - b.astype(np.int16)).astype(np.float32) / 255.0
    h, w = d.shape
    return np.array([[d[r * h // ROWS:(r + 1) * h // ROWS, c * w // COLS:(c + 1) * w // COLS].mean()
                      for c in range(COLS)] for r in range(ROWS)])


def change(a, b, mask, thr=0.06):
    """Fraction of *unmasked* blocks that changed noticeably (new text, new slide)."""
    hit = (block_diffs(a, b) > thr) & mask
    return hit.sum() / max(1, mask.sum())


def keyframes(video: Path, step: float, still: float, hold: float, new: float, window: float = 90.0):
    """One decode pass → small gray samples; then find stable screens offline."""
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    dur = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / fps
    every = max(1, round(fps * step))
    samples, i = [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % every == 0:
            ok, frame = cap.retrieve()
            if ok:
                g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                samples.append((i / fps, cv2.resize(g, (160, max(1, int(g.shape[0] * 160 / g.shape[1]))), interpolation=cv2.INTER_AREA)))
        i += 1

    # Blocks that change in most consecutive samples = live camera / talking head → ignore them.
    busy = np.zeros((ROWS, COLS))
    for (_, a), (_, b) in zip(samples, samples[1:]):
        busy += block_diffs(a, b) > 0.03
    busy /= max(1, len(samples) - 1)
    mask = busy < 0.25
    if mask.sum() < ROWS * COLS * 0.2:      # nearly everything moves (screen recording of video?) → use all
        mask = np.ones_like(mask, dtype=bool)

    kept, stable_since, taken = [], None, False
    for (t0, a), (t, b) in zip(samples, samples[1:]):
        if change(a, b, mask) <= still:
            if stable_since is None:
                stable_since, taken = t0, False
            if not taken and t - stable_since >= hold:
                taken = True
                recent = [k for k in kept if t - k["t"] <= window] or kept[-1:]
                ch = min((change(k["small"], b, mask) for k in recent), default=1.0)
                if ch >= new:
                    kept.append({"t": stable_since, "small": b, "change": round(float(ch), 3)})
        else:
            stable_since = None

    for k in kept:                            # grab full-resolution frames only for the kept ones
        cap.set(cv2.CAP_PROP_POS_MSEC, (k["t"] + hold / 2) * 1000)
        ok, frame = cap.read()
        k["frame"] = frame if ok else cv2.cvtColor(k["small"], cv2.COLOR_GRAY2BGR)
        del k["small"]
    cap.release()
    return kept, dur, float(1 - mask.mean())


def contact_sheets(kfs, sheets: Path, cols=4, rows=3, tw=400):
    sheets.mkdir(parents=True, exist_ok=True)
    per = cols * rows
    paths = []
    for i in range(0, len(kfs), per):
        tiles = []
        for k in kfs[i:i + per]:
            f = k["frame"]
            th = int(f.shape[0] * tw / f.shape[1])
            tile = cv2.resize(f, (tw, th), interpolation=cv2.INTER_AREA)
            cv2.rectangle(tile, (0, 0), (tw, 26), (0, 0, 0), -1)
            cv2.putText(tile, f"{k['id']}  {hms(k['t'])}", (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(tile)
        th = tiles[0].shape[0]
        blank = np.full_like(tiles[0], 255)
        tiles += [blank] * (per - len(tiles))
        grid = np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(rows)])
        p = sheets / f"sheet_{i // per + 1:02d}.jpg"
        cv2.imwrite(str(p), grid, [cv2.IMWRITE_JPEG_QUALITY, 80])
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="video URL or local .mp4")
    ap.add_argument("--srt", type=Path, help="subtitle file (auto for URLs / same-name .srt)")
    ap.add_argument("-w", "--work", type=Path)
    ap.add_argument("--cookies", type=Path, default=VS / "cookies.txt")
    ap.add_argument("--step", type=float, default=1.0, help="sampling interval, s")
    ap.add_argument("--still", type=float, default=0.04, help="max block-change between samples to count as still")
    ap.add_argument("--hold", type=float, default=2.0, help="seconds a screen must stay still")
    ap.add_argument("--new", type=float, default=0.10, help="min block-change vs last kept frame")
    a = ap.parse_args()

    if re.match(r"https?://", a.src):
        vid = re.search(r"(BV\w{10}|v=[\w-]{11}|youtu\.be/[\w-]{11})", a.src)
        key = vid.group(1).split("=")[-1].split("/")[-1] if vid else re.sub(r"\W+", "_", a.src)[-24:]
        work = a.work or Path("/Volumes/AppStorage/Scratch/video-summary") / key
        video, srt = fetch(a.src, work, a.cookies)
    else:
        video = Path(a.src).expanduser().resolve()
        work = a.work or Path("/Volumes/AppStorage/Scratch/video-summary") / re.sub(r"\W+", "_", video.stem)[:40]
        srt = a.srt or next(iter(sorted(video.parent.glob(glob_escape(video.stem) + "*.srt"))), None)
    srt = a.srt or srt
    work.mkdir(parents=True, exist_ok=True)

    kfs, dur, masked = keyframes(video, a.step, a.still, a.hold, a.new)
    frames = work / "frames"
    frames.mkdir(exist_ok=True)
    for old in frames.glob("k*.jpg"):
        old.unlink()
    for i, k in enumerate(kfs):
        k["id"] = f"k{i + 1:03d}"
        k["t_end"] = kfs[i + 1]["t"] if i + 1 < len(kfs) else dur
        k["file"] = f"frames/{k['id']}_{hms(k['t']).replace(':', '')}.jpg"
        cv2.imwrite(str(work / k["file"]), k["frame"], [cv2.IMWRITE_JPEG_QUALITY, 90])
    for old in (work / "sheets").glob("sheet_*.jpg"):
        old.unlink()
    sheets = contact_sheets(kfs, work / "sheets") if kfs else []

    cues = parse_srt(srt) if srt else []
    for k in kfs:
        k["text"] = " ".join(c[2] for c in cues if k["t"] <= (c[0] + c[1]) / 2 < k["t_end"])
    head = [c for c in cues if kfs and (c[0] + c[1]) / 2 < kfs[0]["t"]]

    meta = [{kk: v for kk, v in k.items() if kk != "frame"} for k in kfs]
    (work / "keyframes.json").write_text(json.dumps({"video": str(video), "srt": str(srt) if srt else None,
                                                     "duration": dur, "keyframes": meta}, ensure_ascii=False, indent=1))
    lines = [f"# transcript · {video.stem}", ""]
    if head:
        lines += [f"**[00:00:00] (before k001)** " + " ".join(c[2] for c in head), ""]
    for k in meta:
        lines += [f"**[{hms(k['t'])}] {k['id']}** {k['text']}", ""]
    (work / "transcript.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"work": str(work), "duration_min": round(dur / 60, 1), "keyframes": len(kfs), "masked_area": round(masked, 2),
                      "sheets": [str(p) for p in sheets], "subtitles": str(srt) if srt else None,
                      "transcript_chars": sum(len(k["text"]) for k in meta)}, ensure_ascii=False, indent=1))


def glob_escape(s):
    return re.sub(r"([\[\]*?])", r"[\1]", s)


if __name__ == "__main__":
    main()
