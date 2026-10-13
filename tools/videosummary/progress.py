"""看 vsum.py 跑到哪了：读它的日志，画进度条，估算剩余时间。

    python progress.py                  # 最新的 output/*.log，打印一次
    python progress.py output/x.log     # 指定日志
    python progress.py -w               # 每 5 秒刷新，vsum 结束后自动退出
    python progress.py --line           # 只打一行（给 agent 定时汇报用）
    python progress.py --profile        # 每个视频各阶段耗时（下载 / 总结 / 截图 / 全课主线）

进度怎么算：每个视频按「下载 5% + 逐段总结 90% + 写文档/全课主线 5%」计；
剩余时间 = 还没总结的段数 × 已完成段的平均耗时。
"""

import argparse
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+")


def bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.0, frac))
    n = round(frac * width)
    return "█" * n + "░" * (width - n)


def parse(log: Path) -> dict:
    s = {"total": 0, "skipped": 0, "videos": [], "finished": False}
    cur = None
    last_t = None  # 「[步骤 N/5]」这类行自己不带时间戳，用前一行的
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TS.match(line)
        t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None
        last_t = t or last_t
        if line.startswith("共 "):
            s["total"] = int(re.search(r"\d+", line).group())
            continue
        if line.startswith("- 跳过") or line.startswith("- 已完成，跳过"):
            s["skipped"] += 1
            continue
        if line.startswith("失败的视频") or "PDF  →" in line:
            s["finished"] = True  # 已经到 export_notes 阶段
        if mm := re.match(r"⏱ 导出.*用时 (\d+)s", line):
            s["export_s"] = int(mm.group(1))
        if line.startswith("▶ 处理："):
            cur = {"title": re.sub(r"（[\d.]+ 分钟）$", "", line[5:]).strip(), "stage": "下载",
                   "done": 0, "chunks": 0, "frames": 0, "times": [], "state": "running", "ev": {}}
            s["videos"].append(cur)
            continue
        if cur is None:
            continue
        ev = cur["ev"]
        if t:
            ev.setdefault("start", t)
        if "[步骤 2/5]" in line:
            ev["dl_end"] = last_t
        elif mm := re.search(r"并发总结：\d+ 路，共 (\d+) 段", line):
            cur["conc"], cur["stage"], cur["chunks"] = True, "总结", int(mm.group(1))
            if t:
                cur["times"].append(t)  # 起点
        elif mm := re.search(r"完成片段 (\d+)/(\d+)", line):
            cur["done"], cur["chunks"] = int(mm.group(1)), int(mm.group(2))
            if t:
                cur["times"].append(t)
        elif mm := re.search(r"总结片段 (\d+)/(\d+)", line):
            if not cur.get("conc"):  # 旧版逐段串行：开始第 i 段 = 已完成 i-1 段
                cur["stage"], cur["done"], cur["chunks"] = "总结", int(mm.group(1)) - 1, int(mm.group(2))
                if t:
                    cur["times"].append(t)
        elif mm := re.search(r"片段 (\d+)/(\d+): .*提取帧", line):
            cur["frames"], cur["chunks"] = int(mm.group(1)), int(mm.group(2))
            if t:
                ev.setdefault("frm_start", t)
        elif ("去重后保留" in line or "提取了" in line) and t:
            ev["frm_end"] = t
        elif "[步骤 5/5]" in line:
            cur["stage"], cur["done"] = "写文档", cur["chunks"]
            ev["sum_end"] = last_t
        elif "✅ 处理完成" in line:
            ev["end"] = t
        elif mm := re.match(r"⏱ 全课主线 用时 (\d+)s；本视频共 (\d+)s", line):
            ev["outline_s"], ev["total_s"] = int(mm.group(1)), int(mm.group(2))
        elif line.startswith("已加全课主线") or "全课主线已存在" in line:
            cur["state"] = "ok"
        elif line.strip().startswith("❌ 失败"):
            cur["state"] = "failed"
    return s


def video_frac(v: dict) -> float:
    if v["state"] in ("ok", "failed"):
        return 1.0
    if v["stage"] == "下载":
        return 0.0
    if v["stage"] == "写文档":
        return 0.95
    return 0.05 + 0.90 * (v["done"] / v["chunks"] if v["chunks"] else 0)


def avg_chunk_seconds(videos: list) -> float | None:
    gaps = [(b - a).total_seconds() for v in videos for a, b in zip(v["times"], v["times"][1:])]
    return sum(gaps) / len(gaps) if gaps else None


def report(s: dict, running: bool) -> tuple[str, str]:
    todo = max(s["total"] - s["skipped"], len(s["videos"])) or 1
    vids = s["videos"]
    frac = sum(video_frac(v) for v in vids) / todo
    avg = avg_chunk_seconds(vids)
    cur = next((v for v in reversed(vids) if v["state"] == "running"), None)

    eta = ""
    if avg and running:
        left = (cur["chunks"] - cur["done"]) if cur and cur["chunks"] else 0
        known = [v["chunks"] for v in vids if v["chunks"]]
        per_video = sum(known) / len(known) if known else 28
        left += per_video * (todo - len(vids))
        eta = f"，预计还要约 {max(1, round(left * avg / 60))} 分钟"

    ok = sum(v["state"] == "ok" for v in vids)
    bad = [v["title"] for v in vids if v["state"] == "failed"]
    if not running:
        status = "已结束" + (f"，失败 {len(bad)} 个" if bad else "，全部成功")
        frac = 1.0 if s["finished"] or not bad else frac
    else:
        status = f"第 {len(vids)}/{todo} 个视频{eta}"

    line = f"{bar(frac, 20)} {frac:4.0%}  {status}"
    if cur and running:
        line += f" | {cur['title'][:30]}：{cur['stage']}"
        if cur["stage"] == "总结" and cur["chunks"]:
            line += f" {cur['done']}/{cur['chunks']}"

    out = [f"总进度  {bar(frac)} {frac:4.0%}   {status}", f"已完成 {ok} 个" + (f"，跳过 {s['skipped']} 个（已做过或太短）" if s["skipped"] else "")]
    for v in vids:
        mark = {"ok": "✅", "failed": "❌", "running": "▶ "}[v["state"]]
        out.append(f"\n{mark} {v['title']}")
        if v["state"] == "running":
            if v["chunks"]:
                out.append(f"   总结  {bar(v['done'] / v['chunks'], 20)} {v['done']}/{v['chunks']} 段")
                out.append(f"   截图  {bar(v['frames'] / v['chunks'], 20)} {v['frames']}/{v['chunks']} 段")
            out.append(f"   当前：{v['stage']}" + (f"（平均 {avg:.0f} 秒/段）" if avg and v["stage"] == "总结" else ""))
    return line, "\n".join(out)


def pad(text: str, width: int, right: bool = False) -> str:
    """按终端显示宽度补空格（中文占两格）。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    fill = " " * max(0, width - w)
    return fill + text if right else text + fill


def fmt(sec) -> str:
    if sec is None:
        return "—"
    sec = int(sec)
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


def profile(s: dict) -> str:
    """各阶段耗时。总结和截图是并行的，所以本视频总耗时 ≈ 下载 + max(总结, 截图) + 全课主线。"""
    cols = [("视频", 26), ("下载", 6), ("总结", 10), ("每段", 6), ("截图", 8), ("全课主线", 10), ("合计", 10)]
    rows = ["".join(pad(n, w, i > 0) for i, (n, w) in enumerate(cols))]
    for v in s["videos"]:
        ev = v["ev"]
        d = lambda a, b: (ev[b] - ev[a]).total_seconds() if a in ev and b in ev else None
        summ = d("dl_end", "sum_end")
        times = v["times"]
        per = (summ / len(times)) if summ and times else None
        total = ev.get("total_s") or d("start", "end")
        title = re.sub(r"\s*\[.*?\]\s*", "", v["title"]) or v["title"]
        cells = [title, fmt(d("start", "dl_end")), fmt(summ), fmt(per), fmt(d("frm_start", "frm_end")),
                 fmt(ev.get("outline_s")), fmt(total)]
        rows.append("".join(pad(c, w, i > 0) for i, (c, (_, w)) in enumerate(zip(cells, cols))))
    if "export_s" in s:
        rows.append(f"导出（原文/摘要/PDF）：{fmt(s['export_s'])}")
    rows.append("说明：总结和截图同时进行；总结（DeepSeek 逐段调用）通常是最慢的一步。")
    return "\n".join(rows)


def vsum_running(log: Path) -> bool:
    # 只认「python … vsum.py」本身；只写 vsum.py 会匹配到命令行里恰好带这串字的 shell（比如监控循环）
    r = subprocess.run(["pgrep", "-f", r"[Pp]ython[^ ]* ([^ ]*/)?vsum\.py"], capture_output=True, text=True)
    if not r.stdout.strip():
        return False
    # 有 vsum 在跑，且日志最近 10 分钟内还在写
    return time.time() - log.stat().st_mtime < 600


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", type=Path)
    ap.add_argument("-w", "--watch", action="store_true", help="每 5 秒刷新")
    ap.add_argument("--line", action="store_true", help="只输出一行")
    ap.add_argument("--profile", action="store_true", help="各阶段耗时")
    args = ap.parse_args()
    log = args.log or max((ROOT / "output").glob("*.log"), key=lambda p: p.stat().st_mtime, default=None)
    if not log or not log.exists():
        sys.exit("没找到日志：python progress.py output/<名字>.log")

    if args.profile:
        print(profile(parse(log)))
        return

    while True:
        running = vsum_running(log)
        line, full = report(parse(log), running)
        if args.line:
            print(line, flush=True)
        else:
            if args.watch:
                print("\033[2J\033[H", end="")
            print(f"日志：{log}\n\n{full}", flush=True)
        if not args.watch or not running:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
