"""评测课程笔记：信息覆盖率（recall）、重复率、长度。和生成方法无关，换方法也能用同一把尺子。

    python eval_notes.py <字幕.srt> --label 08 --note old=<旧笔记.md> --note v1=<...> --note v2=<...> -w output/eval

1. 抽事实：把字幕按固定 10 分钟一窗（不看任何笔记的分节），让评测模型列出每窗里的实质信息，
   每条标 core（论证必需）/ detail（例子、数字、机制）/ aside（闲聊、八卦）。一节课只抽一次，缓存后所有版本共用。
2. 判覆盖：把笔记按小节切块编号，让评测模型逐条判断事实在不在笔记里（yes / partial / no），以及出现在哪些块。
3. 玩笑（--humor）：同样按 10 分钟一窗，列出讲者的玩笑、吐槽、自嘲、好笑的比喻和金句（原话 + 背景），
   再判断笔记里是否保留：yes = 保留了笑点（原话或接近原话），partial = 只提到或意思在但笑点没了，no = 没有。
4. 指标：recall（yes=1，partial=0.5，按 weight 分开算）；重复率 = 被覆盖的事实里出现在 ≥2 个正文块的比例
   （全课主线、术语表、课程事务、提到的资料这类汇总块不算正文块）；正文字数。

评测模型默认用 Claude（claude -p --model sonnet），和生成笔记的 DeepSeek 不是同一家，避免自己给自己打分。
"""

import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topic_notes import parse_srt, timed_text, mmss  # noqa: E402

EXTRACT = """下面是一节软件工程课第 {lo}–{hi} 分钟的字幕（语音识别，有错字，请按上下文理解）。
列出这一段里讲者讲到的全部实质信息：论点、理由（为什么）、例子、数字、提到的项目/文章/工具/人、演示和它的结果、建议。
不列：口头禅、点名提问之类的课堂互动、同一段里的重复。

每条要求：
- 一句话，不超过 40 字，自足：不看上下文也能懂。
- type：论点 / 理由 / 例子 / 数据 / 资料 / 演示 / 建议 之一。
- weight：core（这节课论证链上必需的）/ detail（具体例子、数字、机制细节）/ aside（跑题、闲聊、八卦、课程事务）。

只输出 JSON，不要其他文字：{{"facts": [{{"fact": "...", "type": "...", "weight": "..."}}]}}

字幕：
{text}
"""

JUDGE = """下面是一份课堂笔记（按块编号 [B1] [B2] …）和一组从课堂字幕里抽出来的事实。
逐条判断：这条事实的意思是否在笔记里。
- yes：意思完整地写在笔记里（措辞不同没关系）。
- partial：只写了一部分，或写得笼统、丢了关键细节（例如丢了数字、例子、理由）。
- no：笔记里没有。
blocks：写到这条事实的所有块编号（数字列表）；no 时为空。

只输出 JSON，不要其他文字：{{"results": [{{"id": 1, "status": "yes", "blocks": [3]}}]}}

事实：
{facts}

笔记：
{note}
"""

HUMOR = """下面是一节软件工程课第 {lo}–{hi} 分钟的字幕（语音识别，有错字，请按上下文理解）。
列出这一段里讲者的玩笑、吐槽、自嘲、好笑的比喻和让人印象深的金句：听课的人会笑、或者下课后会转述给别人的话。
不列：普通的论点和解释（哪怕说得清楚）；口头禅；课堂点名。没有就返回空列表。

每条：
- line：讲者原话，按字幕改正错字，不超过 50 字。
- about：一句话背景，不超过 30 字，说明这句话在讲什么时说的。

只输出 JSON，不要其他文字：{{"jokes": [{{"line": "...", "about": "..."}}]}}

字幕：
{text}
"""

HUMOR_JUDGE = """下面是一份课堂笔记（按块编号 [B1] [B2] …）和讲者在课上说过的一组玩笑、吐槽、比喻和金句。
逐条判断笔记有没有保留它：
- yes：笔记里有这句话，保留了笑点或味道（原话，或者很接近原话的转述），读者读到能感到好笑或有印象。
- partial：笔记只提到了它（例如「讲者开了个玩笑」），或者意思写进了笔记但笑点、味道没了。
- no：笔记里没有。

只输出 JSON，不要其他文字：{{"results": [{{"id": 1, "status": "yes"}}]}}

玩笑：
{jokes}

笔记：
{note}
"""

SUMMARY_BLOCKS = re.compile(r"全课主线|术语表|课程事务|提到的资料|一句话")


def ask_claude(prompt: str, model: str) -> dict:
    last = ""
    for _ in range(3):
        r = subprocess.run(["claude", "-p", "--model", model], input=prompt, capture_output=True, text=True)
        last = r.stdout
        m = re.search(r"\{.*\}", r.stdout, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise RuntimeError(f"评测模型没有返回 JSON：{last[:300]}")


def blocks_of(md: str) -> list[tuple[str, str]]:
    """笔记切块：旧格式按「## 全课主线 / ## 第 N 部分」，新格式按「## 」。去掉图片和链接地址。"""
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\]\(https?://[^)]*\)", "]", md)
    md = re.sub(r"<https?://[^>]*>", "", md)
    pat = r"^## (?:全课主线|第 \d+ 部分).*$" if re.search(r"^## 第 1 部分", md, re.M) else r"^## .*$"
    heads = list(re.finditer(pat, md, re.M))
    out = [("开头", md[: heads[0].start()] if heads else md)]
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(md)
        out.append((h.group(0)[3:].strip(), md[h.start():end]))
    return [(t, b) for t, b in out if b.strip()]


def body_chars(md: str) -> int:
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\(https?://[^)]*\)|<https?://[^>]*>", "", md)
    md = re.sub(r"^\|.*\|$", "", md, flags=re.M)  # 表格（目录表、术语表）不算正文
    return len(re.sub(r"\s", "", md))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", action="append", default=[], help="名字=路径，可以写多个")
    ap.add_argument("-w", "--work", type=Path, default=Path("output/eval"))
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--window", type=int, default=600)
    ap.add_argument("--humor", action="store_true", help="同时评测玩笑保留率")
    a = ap.parse_args()
    work = a.work / a.label
    work.mkdir(parents=True, exist_ok=True)

    cues = parse_srt(a.srt)
    end = cues[-1][0] + 5
    windows = [(t, min(t + a.window, end)) for t in range(0, int(end), a.window)]

    def extract(w):
        p = work / f"facts_{w[0]:05d}.json"
        if p.exists():
            return json.loads(p.read_text())
        d = ask_claude(EXTRACT.format(lo=mmss(w[0]), hi=mmss(w[1]), text=timed_text(cues, *w, every=30)), a.model)
        facts = [dict(f, at=mmss(w[0])) for f in d.get("facts", [])]
        p.write_text(json.dumps(facts, ensure_ascii=False, indent=1))
        return facts

    with ThreadPoolExecutor(5) as ex:
        facts = [f for fs in ex.map(extract, windows) for f in fs]
    for i, f in enumerate(facts):
        f["id"] = i + 1
    print(f"[{a.label}] 事实 {len(facts)} 条（core {sum(f['weight']=='core' for f in facts)}，"
          f"detail {sum(f['weight']=='detail' for f in facts)}，aside {sum(f['weight']=='aside' for f in facts)}）", flush=True)

    jokes = []
    if a.humor:
        def extract_h(w):
            p = work / f"humor_{w[0]:05d}.json"
            if p.exists():
                return json.loads(p.read_text())
            d = ask_claude(HUMOR.format(lo=mmss(w[0]), hi=mmss(w[1]), text=timed_text(cues, *w, every=30)), a.model)
            js = [dict(j, at=mmss(w[0])) for j in d.get("jokes", [])]
            p.write_text(json.dumps(js, ensure_ascii=False, indent=1))
            return js
        with ThreadPoolExecutor(5) as ex:
            jokes = [j for js in ex.map(extract_h, windows) for j in js]
        for i, j in enumerate(jokes):
            j["id"] = i + 1
        print(f"[{a.label}] 玩笑 {len(jokes)} 条", flush=True)

    def judge(spec):
        name, path = spec.split("=", 1)
        md = Path(path).read_text(encoding="utf-8")
        blocks = blocks_of(md)
        p = work / f"judge_{name}.json"
        if p.exists():
            res = json.loads(p.read_text())
        else:
            note = "\n\n".join(f"[B{i+1}] {b}" for i, (_, b) in enumerate(blocks))
            flist = "\n".join(f"{f['id']}. {f['fact']}" for f in facts)
            res = ask_claude(JUDGE.format(facts=flist, note=note), a.model).get("results", [])
            p.write_text(json.dumps(res, ensure_ascii=False, indent=1))
        by_id = {r["id"]: r for r in res if isinstance(r, dict) and "id" in r}
        summary_ids = {i + 1 for i, (t, _) in enumerate(blocks) if SUMMARY_BLOCKS.search(t)}
        score = {"yes": 1.0, "partial": 0.5}
        row = {"note": name, "chars": body_chars(md)}
        for wname in ("core", "detail", "aside", "all"):
            fs = [f for f in facts if wname == "all" or f["weight"] == wname]
            row[wname] = sum(score.get(by_id.get(f["id"], {}).get("status"), 0) for f in fs) / max(1, len(fs))
        covered = [by_id[f["id"]] for f in facts if by_id.get(f["id"], {}).get("status") in score]
        rep = [r for r in covered if len({b for b in r.get("blocks", []) if b not in summary_ids}) >= 2]
        row["repeat"] = len(rep) / max(1, len(covered))
        row["missing"] = [f for f in facts if by_id.get(f["id"], {}).get("status") not in score]
        if jokes:
            hp = work / f"judge_humor_{name}.json"
            if hp.exists():
                hres = json.loads(hp.read_text())
            else:
                note = "\n\n".join(f"[B{i+1}] {b}" for i, (_, b) in enumerate(blocks))
                jl = "\n".join(f"{j['id']}. 「{j['line']}」（{j.get('about','')}）" for j in jokes)
                hres = ask_claude(HUMOR_JUDGE.format(jokes=jl, note=note), a.model).get("results", [])
                hp.write_text(json.dumps(hres, ensure_ascii=False, indent=1))
            hb = {r["id"]: r.get("status") for r in hres if isinstance(r, dict) and "id" in r}
            row["humor"] = sum(score.get(hb.get(j["id"]), 0) for j in jokes) / len(jokes)
            row["humor_yes"] = sum(hb.get(j["id"]) == "yes" for j in jokes) / len(jokes)
        return row

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(judge, a.note))
    h = " 玩笑（yes+½partial） | 玩笑（yes） |" if jokes else ""
    print(f"| {a.label} | 正文字数 | core | detail | aside | 全部 | 重复率 |{h}")
    print("|---|---|---|---|---|---|---|" + ("---|---|" if jokes else ""))
    for r in rows:
        hv = f" {r['humor']:.0%} | {r['humor_yes']:.0%} |" if jokes else ""
        print(f"| {r['note']} | {r['chars']} | {r['core']:.0%} | {r['detail']:.0%} | {r['aside']:.0%} | {r['all']:.0%} | {r['repeat']:.0%} |{hv}")
    (work / "summary.json").write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "missing"} | {"missing": [m["fact"] for m in r["missing"]]} for r in rows],
        ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
