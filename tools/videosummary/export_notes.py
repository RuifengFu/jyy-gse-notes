"""把 video_summary_app.py 的产出整理成「原文 / 摘要 / PDF」三份，放到一个目标目录。

用法:
    python export_notes.py <输出目录，如 output/gse> <目标目录，如 ~/Desktop/课程名>

对输出目录（及其每个 <视频id>/ 子目录）里的 `<标题>.md`（摘要），找到旁边 downloads/ 下同名的 .srt（原文），生成:
    目标/原文/<名字>.md      按停顿合并成段落，每段带时间戳
    目标/摘要/<名字>.md      摘要，截图复制到 目标/摘要/images/<名字>/
    目标/PDF/<名字>.pdf      摘要渲染的 PDF（pandoc → HTML → Chrome 打印）
已存在且比源文件新的结果会跳过，所以可以反复运行。
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
body { font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", sans-serif;
       max-width: 820px; margin: 0 auto; padding: 24px; line-height: 1.7; color: #1d1d1f; }
h1 { font-size: 1.7em; border-bottom: 2px solid #ddd; padding-bottom: .3em; }
h2 { font-size: 1.35em; margin-top: 1.6em; border-bottom: 1px solid #eee; break-after: avoid; }
h3 { break-after: avoid; }
h3 { font-size: 1.15em; }
img { max-width: 100%; display: block; margin: 12px auto; border: 1px solid #eee; }
table { border-collapse: collapse; width: 100%; font-size: .92em; }
th, td { border: 1px solid #ddd; padding: 6px 10px; vertical-align: top; }
th { background: #f5f5f7; }
code { background: #f5f5f7; padding: 1px 4px; border-radius: 3px; font-size: .9em; }
pre { background: #f5f5f7; padding: 10px; overflow-x: auto; }
blockquote { color: #555; border-left: 4px solid #ddd; margin-left: 0; padding-left: 12px; }
@page { margin: 16mm 14mm; }
"""

TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def short_name(title: str) -> str:
    """'欢迎来到未来 [01-Raw⧸26生成式软件工程⧸NJU]' -> '01-欢迎来到未来'"""
    m = re.search(r"\[(\d+)-", title)
    base = re.sub(r"\s*\[.*?\]\s*", "", title).strip() or title
    base = re.sub(r'[<>:"/\\|?*⧸]', "_", base)
    return f"{m.group(1)}-{base}" if m else base


def parse_srt(path: Path):
    cues, start, end, text = [], None, None, []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        s = line.strip()
        m = TIME.match(s)
        if m:
            g = list(map(int, m.groups()))
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            text = []
        elif s == "":
            if start is not None and text:
                cues.append((start, end, " ".join(text)))
            start, text = None, []
        elif start is not None:
            text.append(s)
    return cues


def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def transcript_md(title: str, srt: Path) -> str:
    """字幕合并成段落：停顿超过 1.5 秒且段落够长时断开，太长也断开。"""
    out = [f"# {title}（原文）", "", f"> 自动字幕整理，未校对。来源字幕：`{srt.name}`", ""]
    para, para_start, last_end = [], None, None
    for start, end, text in parse_srt(srt):
        size = sum(len(t) for t in para)
        if para and ((start - last_end > 1.5 and size > 120) or size > 350):
            out += [f"**[{ts(para_start)}]** " + " ".join(para), ""]
            para = []
        if not para:
            para_start = start
        para.append(text)
        last_end = end
    if para:
        out += [f"**[{ts(para_start)}]** " + " ".join(para), ""]
    return "\n".join(out)


def copy_summary(md: Path, dest_md: Path, img_dir: Path) -> str:
    """复制摘要，把截图拷到 img_dir 并改写链接为相对路径。"""
    text = md.read_text(encoding="utf-8")
    img_dir.mkdir(parents=True, exist_ok=True)

    def fix(m):
        src = md.parent / urllib.parse.unquote(m.group(2))
        if not src.exists():
            return m.group(0)
        target = img_dir / f"{src.parent.name}_{src.name}"
        if not target.exists():
            shutil.copy2(src, target)
        rel = target.relative_to(dest_md.parent).as_posix()
        return f"![{m.group(1)}]({urllib.parse.quote(rel)})"

    text = re.sub(r"!\[([^\]]*)\]\(((?:[^()\s]|\([^()]*\))+)\)", fix, text)  # 路径里可能有 (2)
    dest_md.write_text(text, encoding="utf-8")
    return text


def render_pdf(md: Path, pdf: Path):
    with tempfile.TemporaryDirectory() as tmp:
        css = Path(tmp) / "style.css"
        css.write_text(CSS, encoding="utf-8")
        # HTML 放在摘要旁边，图片相对路径才能解析
        html = md.with_suffix(".tmp.html")
        try:
            subprocess.run(["pandoc", str(md), "-s", "--embed-resources", "-c", str(css),
                            "--metadata", f"pagetitle={md.stem}", "-f", "gfm+tex_math_dollars", "--mathml", "-o", str(html)],
                           check=True, cwd=md.parent)
            pdf.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--print-to-pdf={pdf}", html.as_uri()],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            html.unlink(missing_ok=True)


def fresh(target: Path, *sources: Path) -> bool:
    return target.exists() and all(target.stat().st_mtime >= s.stat().st_mtime for s in sources)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("dest", type=Path)
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()

    # vsum.py 把每个视频放在 <output_dir>/<视频id>/ 下；也兼容直接放在 output_dir 里
    summaries = sorted((p for p in [*args.output_dir.glob("*.md"), *args.output_dir.glob("*/*.md")]
                        if not p.name.endswith("_summary_temp.md")), key=lambda p: short_name(p.stem))
    if not summaries:
        sys.exit(f"没有找到摘要 .md：{args.output_dir}")
    for md in summaries:
        title = md.stem
        name = short_name(title)
        # 同一视频可能有多种语言字幕（ai-zh / ai-en …），优先中文
        srts = sorted((md.parent / "downloads").glob(f"{glob_escape(title)}*.srt"),
                      key=lambda p: (0 if re.search(r"\.(ai-)?zh", p.name) else 1, p.name))
        print(f"• {name}")

        if srts:
            t = args.dest / "原文" / f"{name}.md"
            if not fresh(t, srts[0]):
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text(transcript_md(title, srts[0]), encoding="utf-8")
            print(f"    原文 → {t}")
        else:
            print("    ⚠️ 没找到字幕 .srt，跳过原文")

        s = args.dest / "摘要" / f"{name}.md"
        if not fresh(s, md):
            s.parent.mkdir(parents=True, exist_ok=True)
            copy_summary(md, s, args.dest / "摘要" / "images" / name)
        print(f"    摘要 → {s}")

        if not args.no_pdf:
            p = args.dest / "PDF" / f"{name}.pdf"
            if not fresh(p, s):
                render_pdf(s, p)
            print(f"    PDF  → {p}")


def glob_escape(s: str) -> str:
    return re.sub(r"([\[\]*?])", r"[\1]", s)


if __name__ == "__main__":
    main()
