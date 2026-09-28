"""一条命令：视频/合集链接 → 摘要（带截图）+ 原文 + PDF。

    python vsum.py <链接或合集链接>... -o output/<名字> -d ~/Desktop/<名字>

- 合集/列表会自动展开；短于 --min-minutes 的视频跳过（默认 10 分钟，过滤预告片之类）。
- 已经有摘要的视频跳过，所以中断后重跑即可续上。
- B 站 AI 字幕需要登录：如果 cookies.txt 失效，会自动从 Chrome 重新导出（只保留 bilibili 的 cookie）。
- 全部处理完后调用 export_notes.py 把结果整理到 -d 目录（原文/ 摘要/ PDF/）。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
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


def summary_exists(out: Path, title: str) -> bool:
    return (out / f"{title.translate(YTDLP_SAFE)}.md").exists()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("-o", "--out", type=Path, required=True, help="中间结果目录（放外置盘，视频/截图都在这）")
    ap.add_argument("-d", "--dest", type=Path, required=True, help="最终整理目录（原文/摘要/PDF）")
    ap.add_argument("--min-minutes", type=float, default=10)
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()
    out = args.out if args.out.is_absolute() else ROOT / args.out

    urls = [u for url in args.urls for u in expand(url)]
    print(f"共 {len(urls)} 个视频")
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
        if summary_exists(vout, title):
            print(f"- 已完成，跳过：{title}")
            continue
        if "bilibili" in url and not cookies_checked:
            cookies_checked = True
            if not has_login_subs(url):
                print("  B 站字幕需要登录，尝试从 Chrome 刷新 cookies…")
                ok = refresh_cookies_from_chrome(url) and has_login_subs(url)
                print("  ✅ cookies 已刷新" if ok else "  ⚠️ 刷新失败：请在 Chrome 里登录 B 站后重试")
        print(f"▶ 处理：{title}（{dur:.0f} 分钟）", flush=True)
        # 先自己下好字幕：video_summary_app 的字幕下载偶尔只拿到弹幕（danmaku），会直接崩
        for langs in ("ai-zh,zh-Hans,zh-CN,zh", "en,ai-en"):  # 先中文；没有中文才下英文
            ytdlp("--skip-download", "--write-subs", "--sub-langs", langs,
                  "--sub-format", "srt", "-P", str(vout / "downloads"), "-o", "%(title)s.NA.%(ext)s", url)
            if list((vout / "downloads").glob("*.srt")):
                break
        r = subprocess.run([PY, str(ROOT / "video_summary_app.py"), url, "-o", str(vout), "-c", str(COOKIES)], cwd=ROOT)
        if r.returncode != 0 or not summary_exists(vout, title):
            failed.append(title)
            print(f"  ❌ 失败：{title}")
            continue
        # 逐段总结是碎片化的：再串一条全课论证主线，插到最前面
        subprocess.run([PY, str(ROOT / "outline.py"), str(vout / f"{title.translate(YTDLP_SAFE)}.md")], cwd=ROOT)

    subprocess.run([PY, str(ROOT / "export_notes.py"), str(out), str(args.dest)] + (["--no-pdf"] if args.no_pdf else []), check=False)
    if failed:
        print("失败的视频：\n  " + "\n  ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
