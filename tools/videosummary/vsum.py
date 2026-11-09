"""一条命令：视频/合集链接 → 笔记（带结构图和截图）+ 原文 + PDF。

    python vsum.py <链接或合集链接>... -o output/<名字> -d ~/Desktop/<名字>

- 默认用 topic_notes.py：只用字幕（不下载视频和音频），按主题分 5–9 节，开头一张结构图当目录，
  简明技术中文，约 1.6 万字一讲（旧流程约 4 万字，信息覆盖率相当）。--shots 时才下载视频，截讲者展示画面的那几帧。
  产出：-d 下的 笔记/<名字>.md（图片在 笔记/images/）、PDF/<名字>.pdf、原文/<名字>.md。
- --legacy：旧流程（每 3.5 分钟一段逐段总结 + 全课主线，约 3.5 万字一讲），产出 摘要/ 原文/ PDF/。

- 合集/列表会自动展开；短于 --min-minutes 的视频跳过（默认 10 分钟，过滤预告片之类）。
- 已经有摘要的视频跳过，所以中断后重跑即可续上。
- B 站 AI 字幕需要登录：如果 cookies.txt 失效，会自动从 Chrome 重新导出（只保留 bilibili 的 cookie）。
- 全部处理完后调用 export_notes.py 把结果整理到 -d 目录（原文/ 摘要/ PDF/）。
"""

import argparse
import json
import os
import re
import glob
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
COOKIES = ROOT / "cookies.txt"


def ytdlp(*args, cookies=True):
    cmd = [PY, "-m", "yt_dlp", "--no-warnings"]
    if cookies and COOKIES.exists():
        cmd += ["--cookies", str(COOKIES)]
    return subprocess.run(cmd + list(args), capture_output=True, text=True)


def expand(url: str) -> list[str]:
    r = ytdlp("--flat-playlist", "--print", "%(id)s", url)
    ids = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    if len(ids) <= 1:
        return [url]
    base = "https://www.bilibili.com/video/" if "bilibili" in url else "https://www.youtube.com/watch?v="
    return [base + i for i in ids]


def info(url: str) -> dict:
    r = ytdlp("-J", "--skip-download", url)
    return json.loads(r.stdout) if r.returncode == 0 else {}


def has_login_subs(url: str) -> bool:
    out = ytdlp("--list-subs", url).stdout
    return bool(re.search(r"^ai-zh|^zh", out, re.M))


def logged_in() -> bool:
    """cookies.txt 里的 B 站登录是否还有效（问 nav 接口）。"""
    if not COOKIES.exists():
        return False
    r = subprocess.run(["curl", "-s", "-m", "10", "-b", str(COOKIES), "-A", "Mozilla/5.0",
                        "https://api.bilibili.com/x/web-interface/nav"], capture_output=True, text=True)
    try:
        return bool(json.loads(r.stdout)["data"].get("isLogin"))
    except Exception:
        return False


def refresh_cookies_from_chrome(url: str) -> bool:
    """从 Chrome 导出 cookie，只保留 bilibili.com 的行。"""
    with tempfile.TemporaryDirectory(dir="/Volumes/AppStorage/Scratch" if Path("/Volumes/AppStorage/Scratch").is_dir() else None) as tmp:
        jar = Path(tmp) / "all.txt"
        subprocess.run([PY, "-m", "yt_dlp", "--no-warnings", "--cookies-from-browser", "chrome",
                        "--cookies", str(jar), "--simulate", url], capture_output=True)
        if not jar.exists():
            return False
        keep = [l for l in jar.read_text().splitlines()
                if re.match(r"^(#HttpOnly_)?\.?([a-z0-9-]+\.)*bilibili\.com\t", l)]
    if not keep:
        return False
    COOKIES.write_text("# Netscape HTTP Cookie File\n" + "\n".join(keep) + "\n")
    os.chmod(COOKIES, 0o600)
    return True


# yt-dlp 生成文件名时把这些字符换成全角，摘要文件名沿用视频文件名
YTDLP_SAFE = str.maketrans({'/': '⧸', '\\': '⧹', ':': '：', '*': '＊', '?': '？', '"': '＂', '<': '＜', '>': '＞', '|': '｜'})


def summary_path(out: Path, title: str) -> Path | None:
    # 纯文本模式下文件名会带字幕后缀，例如 <标题>.NA.ai-zh.md
    stem = title.translate(YTDLP_SAFE)
    exact = out / f"{stem}.md"
    if exact.exists():
        return exact
    return next(iter(sorted(out.glob(f"{glob.escape(stem)}.*.md"))), None)


def summary_exists(out: Path, title: str) -> bool:
    return summary_path(out, title) is not None


def topic_done(dest: Path, title: str) -> bool:
    from export_notes import short_name
    return (dest / "笔记" / f"{short_name(title)}.md").exists()


def topic_note(url: str, title: str, vout: Path, args, collection: str) -> bool:
    """新流程：字幕（+ 视频截图）→ topic_notes.py → 笔记/ PDF/ 原文/。"""
    from export_notes import short_name, transcript_md
    name = short_name(title)
    m = re.match(r"(\d+)-(.*)", name)
    num, base = (m.group(1), m.group(2)) if m else ("", name)
    dl = vout / "downloads"
    srts = sorted(dl.glob("*.srt"), key=lambda p: (0 if re.search(r"\.(ai-)?zh", p.name) else 1, p.name))
    if not srts:
        print("  ⚠️ 没有字幕，不能生成笔记（不编造文字稿）")
        return False
    video = None
    if args.shots:
        video = next(iter(dl.glob("video.*")), None)
        if video is None:  # 截图够用就行：H.264、宽不超过 1280；B 站限流（HTTP 567）时指数退避重试
            print("  下载视频（只用来截图）…", flush=True)
            ytdlp("--retries", "30", "--retry-sleep", "exp=2:60",
                  "-f", "bv*[vcodec^=avc1][width<=1280]/bv*[width<=1280]/bv*",
                  "-P", str(dl), "-o", "video.%(ext)s", url)
            video = next(iter(p for p in dl.glob("video.*") if not p.name.endswith(".part")), None)
        if video is None:
            print("  ⚠️ 视频下载失败，这一讲没有截图")
    notes = args.dest / "笔记"
    cmd = [PY, str(ROOT / "topic_notes.py"), str(srts[0]), "--title", base, "--num", num, "--name", name,
           "--url", url, "-o", str(notes)]
    cmd += ["--collection", collection] if collection else []
    cmd += ["--speaker", args.speaker] if args.speaker else []
    cmd += ["--video", str(video)] if video else []
    cmd += ["--no-pdf"] if args.no_pdf else []
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        return False
    raw = args.dest / "原文" / f"{name}.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(transcript_md(title, srts[0]), encoding="utf-8")
    pdf = notes / f"{name}.pdf"
    if pdf.exists():
        (args.dest / "PDF").mkdir(parents=True, exist_ok=True)
        pdf.replace(args.dest / "PDF" / pdf.name)
    print(f"  📁 {notes / (name + '.md')}", flush=True)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("-o", "--out", type=Path, required=True, help="中间结果目录（放外置盘，视频/截图都在这）")
    ap.add_argument("-d", "--dest", type=Path, required=True, help="最终整理目录（原文/摘要/PDF）")
    ap.add_argument("--min-minutes", type=float, default=10)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--text-only", action="store_true", help="不下载视频、不截图，只用字幕做文字摘要（访谈/播客）")
    ap.add_argument("--legacy", action="store_true", help="旧流程：逐段总结 + 全课主线（很长）")
    ap.add_argument("--shots", action="store_true", help="新流程默认只用字幕、不下载视频；加这个才下载视频截图")
    ap.add_argument("--speaker", default="", help="写进笔记开头的讲者信息")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out

    pairs = []  # (视频链接, 所属合集链接)
    for url in args.urls:
        ex = expand(url)
        pairs += [(u, url if len(ex) > 1 else "") for u in ex]
    urls = [u for u, _ in pairs]
    collection = dict(pairs)
    print(f"共 {len(urls)} 个视频")
    print("看进度：python progress.py -w（耗时明细：python progress.py --profile）", flush=True)
    cookies_checked = False
    failed = []
    for url in urls:
        meta = info(url)
        title, dur = meta.get("title", url), (meta.get("duration") or 0) / 60
        if dur and dur < args.min_minutes:
            print(f"- 跳过（{dur:.0f} 分钟，太短）：{title}")
            continue
        vid = meta.get("id") or re.sub(r"\W+", "_", url)[-20:]
        vout = out / vid  # 每个视频单独目录：video_summary_app 会按关键词模糊匹配目录里的旧文件，混放会串
        if not args.legacy and topic_done(args.dest, title):
            print(f"- 已完成，跳过：{title}")
            continue
        if args.legacy and summary_exists(vout, title):
            print(f"- 已完成，跳过：{title}")
            continue
        if "bilibili" in url and not cookies_checked:
            cookies_checked = True
            if not has_login_subs(url) and logged_in():
                print("  B 站已登录，但这个视频没有字幕（UP 主没传 CC，B 站也没生成 AI 字幕）")
            elif not has_login_subs(url):
                print("  B 站字幕需要登录，尝试从 Chrome 刷新 cookies…")
                ok = refresh_cookies_from_chrome(url) and has_login_subs(url)
                print("  ✅ cookies 已刷新" if ok else "  ⚠️ 刷新失败：请在 Chrome 里登录 B 站后重试")
        print(f"▶ 处理：{title}（{dur:.0f} 分钟）", flush=True)
        t0 = time.time()
        # 先自己下好字幕：video_summary_app 的字幕下载偶尔只拿到弹幕（danmaku），会直接崩
        for langs in ("ai-zh,zh-Hans,zh-CN,zh", "en,ai-en"):  # 先中文；没有中文才下英文
            ytdlp("--skip-download", "--write-subs", "--sub-langs", langs,
                  "--sub-format", "srt", "-P", str(vout / "downloads"), "-o", "%(title)s.NA.%(ext)s", url)
            if list((vout / "downloads").glob("*.srt")):
                break
        if not args.legacy:
            if not topic_note(url, title, vout, args, collection.get(url, "")):
                failed.append(title)
                print(f"  ❌ 失败：{title}")
            print(f"⏱ 本视频共 {time.time() - t0:.0f}s", flush=True)
            continue
        r = subprocess.run([PY, str(ROOT / "video_summary_app.py"), url, "-o", str(vout), "-c", str(COOKIES)] + (["-n"] if args.text_only else []), cwd=ROOT)
        if r.returncode != 0 or not summary_exists(vout, title):
            failed.append(title)
            print(f"  ❌ 失败：{title}")
            continue
        # 逐段总结是碎片化的：再串一条全课论证主线，插到最前面
        t1 = time.time()
        subprocess.run([PY, str(ROOT / "outline.py"), str(summary_path(vout, title))], cwd=ROOT)
        print(f"⏱ 全课主线 用时 {time.time() - t1:.0f}s；本视频共 {time.time() - t0:.0f}s", flush=True)

    if not args.legacy:
        if failed:
            print("失败的视频：\n  " + "\n  ".join(failed))
            sys.exit(1)
        return
    t1 = time.time()
    subprocess.run([PY, str(ROOT / "export_notes.py"), str(out), str(args.dest)] + (["--no-pdf"] if args.no_pdf else []), check=False)
    print(f"⏱ 导出（原文/摘要/PDF）用时 {time.time() - t1:.0f}s", flush=True)
    if failed:
        print("失败的视频：\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
