"""按主题（不按时间切块）把一节课的字幕写成短笔记：结构图目录 + 每节一个主题 + 术语表。

    python topic_notes.py <字幕.srt> --title "DeepSeek Harness" --num 09 --url <视频链接> \
        [--video <视频.mp4>] -o <输出目录> [--force] [--no-pdf]

为什么这样做：旧流程每 3.5 分钟切一段、各段独立总结，同一话题跨段重复，一讲约 3.5 万字，
比字幕原文（约 3 万字）还长。这里改成两步：
  1. 模型通读全文，切成 5–9 个连续的主题小节，每个要点只分给一个小节，并统一术语写法；
  2. 每个小节只读自己那段字幕，同时看到全课大纲，用简明技术中文写，篇幅按时长给预算。
截图：小节写作时由模型指出讲者在屏幕上展示东西的时刻，用 ffmpeg 截那一帧。

产出（-o 目录）：
  <NN-标题>.md、<NN-标题>.pdf、images/<NN-标题>/（toc.svg 结构图 + 截图）
  .cache/<NN>/ 下是模型的中间 JSON，重跑时复用；--force 重新生成。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})")
LINKS = ["开场", "因此", "但是", "举例", "进一步", "转向", "回到"]

STYLE = """写作规则（简明技术中文，读一遍就不会读错）：
- 一句只说一件事。一句不超过 40 字。不用分号把两句并成一句。
- 一个概念全文只用一个词，用术语表里的写法。不换同义词。
- 新概念第一次出现时，用一句大白话说清它是什么、解决什么问题。
- 写出主语（讲者 / 开发者 / agent / 模型）。用主动句。笔记写的都是讲者的内容，不在每条开头重复「讲者说」「讲者认为」；只在要区分讲者和别人的观点时写。
- 直接用动词，不写「进行」「加以」「作出」+ 动词。
- 不用没有数值的程度词（很、非常、大量、极其）。讲者给了数字就写数字。
- 不用反问、设问、感叹。讲者的反问改写成陈述句。（「」里引用的讲者原话除外，原话保持原样。）
- 不用黑话：赋能、抓手、闭环、拉通、沉淀、痛点、对标、打法。
- 不用「等」结尾的开放列举：列全，或写「包括 N 个：……」。
- 保留确定程度：讲者说「可能」，你也写「可能」。
- 只写讲者讲的内容，不加课外知识、公式、例子。讲者没说、你补上的推理衔接，句末标「（整理者补充）」。
- 字幕是语音识别，有错字。按上下文和术语表改正；拿不准的词写成「词（字幕原文：xx，待确认）」。"""

OUTLINE_PROMPT = """下面是一个视频（课程、讲座或演讲）的完整字幕（语音识别或人工字幕，带 [分:秒] 时间戳）。{who}
请先通读全文，再输出这个视频的结构，作为笔记的目录。只输出一个 JSON 对象，字段如下：

{
  "one_line": "这节课的核心主张。直接写主张本身，不要写「讲者想让听众相信」这类开头。不超过 60 字。",
  "sections": [
    {
      "title": "小节标题，不超过 14 字，说内容不说形式（不写「引言」「总结」）",
      "start": "分:秒，本节开始时间",
      "claim": "本节的核心论点，一个完整的判断句，不超过 32 字。它会当本节的标题，要说出结论，不是话题标签",
      "link": "本节和上一节的关系，只能从这几个词选一个：开场 因此 但是 举例 进一步 转向 回到",
      "covers": ["本节负责的话题，每条不超过 20 字，3 到 6 条。这是话题归属，不是内容清单：写作时本节时间范围内的实质内容都会写"]
    }
  ],
  "terms": [
    {"term": "统一写法", "asr": ["字幕里的错误识别写法，没有就空"], "meaning": "一句话含义，不超过 30 字", "sure": true}
  ],
  "admin": ["课程事务：实验发布、截止时间、考试安排之类，每条不超过 30 字；没有就空数组"]
}

要求：
- sections 有 5 到 9 个，按时间顺序，首尾相接，覆盖整节课。第一个的 start 是 "00:00"。
- 按话题切，不按时长切。一个话题讲了 20 分钟就是一个小节；讲者跑题 1 分钟不单独成节。
- 每个话题只放进一个小节的 covers。不同小节的 covers 不重复。讲者在后面又回到前面的话题时，归第一次展开它的小节。
- 不同小节的 claim 说不同的事。讲者在两处讲同一个观点时，claim 只写在第一次展开它的小节。
- 课程事务放进 admin，不放进 sections。
- terms 收 8 到 20 个本课的关键术语、产品名、人名，尤其是字幕识别错了的。
- sure：你确定这个统一写法是讲者说的那个词，写 true。只是从读音猜的产品名、项目名，写 false。
- 字幕里只是被识别成英文的普通中文词（例如「许愿」），不收进 terms。
- 用中文。

字幕：
"""

SECTION_PROMPT = """你在写一个视频（课程、讲座或演讲）的笔记，现在只写其中一个小节。

全课核心主张：{one_line}

全课目录：
{toc}

下面这些由别的小节负责。你可以用半句话提到，后面写「（见第 N 节）」，但不展开、不举它们的例子：
{others}

术语表（统一写法，字幕错字按此改正）：
{terms}

你现在写第 {idx} 节「{title}」，时间 {start}–{end}，约 {minutes} 分钟。
本节核心论点：{claim}
本节负责的话题：{covers}

写什么：本节字幕里的实质内容都要写（结构见下面 body 的说明），不只是上面的话题。包括：
- 论点，以及讲者给的理由：讲者说了「为什么」，就写出来。
- 例子和演示：哪个项目、哪个工具、做了什么、结果是什么。
- 数字：时间、数量、比例、版本号。
- 讲者提到的文章、论文、项目、产品、工具、人、推文、书。
- 讲者给听众的建议和做法。
- 讲者顺带讲的观察和判断，只要有信息量，也写。
- 讲者的玩笑、吐槽、自嘲、好笑的比喻和金句。这些让笔记读起来像在听课，要留下来：
  单独写成一个第 2 层或第 3 层子项，放在它所在话题的分论点下面（不塞进别的条目中间），开头用 **玩笑**、**吐槽** 或 **自嘲**，先用半句话交代背景，再用「」引讲者原话（按字幕改正错字，保留口语和语气）。
  不解释笑点，不改写成「讲者开玩笑说……」。放在它出现的位置，不集中到最后。
  讲者说得有味道的话一律引原话，不转述：狠话、反讽、模仿别人的内心独白、对着现场的自嘲、给东西起的外号。转述会丢掉笑点。
不写什么：口头禅（「对吧」「是不是」）；没有内容的点名提问；本段里的重复；上面列出的别的小节负责的话题。

{style}

输出一个 JSON 对象：
{{
  "body": "本节正文，Markdown 嵌套列表，每层缩进 2 个空格。按金字塔结构写：外层概括内层，读者只读外层也不漏核心结论。\n第 1 层：2 到 5 个分论点，合起来支撑本节核心论点。每项先写一个粗体判断句：**主语 + 结论，不超过 30 字**；后面接一句不加粗的话（不超过 50 字），写讲者给的最主要的理由、证据或做法。它要说出结论（例如「**让两个不同的模型互相挑错，比一个模型自查更有效**」），不能只是话题标签（例如「**多模型 review**」）。读者只读第 1 层，就要知道本节的全部核心结论和讲者的主要理由。\n第 2 层：支撑这个分论点的论据，每个分论点下 2 到 6 条。每条是一个完整的论据：一个理由、一个例子或故事、一组数字、一个演示和它的结果、一个资料、一条建议或一个玩笑。每条先写它说明了什么，再写细节。一个故事或例子只写成一条，不拆成几条；故事的经过超过 2 句时，第 2 层写一个粗体句子说明这个故事证明了什么，经过放进第 3 层。\n第 3 层：故事的经过、演示的步骤、并列的细节。\n一个分论点下的论据超过 6 条时，先分组：每组写成一个第 2 层条目，用一个粗体句子概括这组，组内条目放进第 3 层。\n有子项的条目，开头都写一个粗体句子概括它的子项；没有子项的条目不加粗。每个列表项都以「- 」开头，包括第 1 层。\n分论点按讲者的推进顺序排；每条内容放在它支撑的那个分论点下面。有信息量但不支撑任何分论点的内容（顺带的观察、闲谈），放进最后一个第 1 层条目，粗体写成一句概括，例如「**讲者顺带讲了 3 件和主线无关的事**」。\n如果讲者有一句话说得特别准，在列表后加一行「> 原话：「……」」，最多 1 句，按字幕改正错字后原样引用。\n不写标题，不写「要点」行（本节标题已经是核心论点）。不写本节以外的内容；需要提到别的小节时写「（见第 N 节）」。正文总长不超过 {budget} 字（玩笑原话另计，不为省字删玩笑）。",
  "refs": [{{"name": "讲者提到的文章/论文/项目/产品/工具/推文/书的名字", "what": "它是什么、讲者为什么提，不超过 25 字"}}],
  "shots": [{{"time": "分:秒", "caption": "画面内容，不超过 20 字"}}]
}}

shots：讲者在屏幕上展示东西（幻灯片、代码、网页、终端、演示）并且看图有助于理解的时刻，0 到 2 个。
时间取讲者开始讲解这个画面后 3 到 10 秒。只讲话没有展示时，给空数组。

本节字幕：
{text}
"""

COVER_PROMPT = """下面是一节课某个小节的字幕和这个小节的笔记草稿。
第 1 步：找出字幕里讲者讲了、但草稿没写的实质内容：论点、理由、例子、数字、提到的资料、演示结果、建议、有信息量的判断，
以及讲者的玩笑、吐槽、好笑的比喻和金句，包括草稿里只转述了意思、没有引原话的（补的时候单独写成一个子项，用 **玩笑**、**吐槽** 或 **自嘲** 开头，用「」引讲者原话，不塞进别的列表项中间）。
不算：口头禅、课堂互动、重复，以及下面这些别的小节负责的话题：
{others}
第 2 步：把漏掉的内容补进草稿。草稿是金字塔结构的嵌套列表：第 1 层是粗体结论句，下面是支撑它的内容。
每条补充写成子项，放在它支撑的那个第 1 层结论下面；补充的是已有故事或例子的细节时，放进那个故事的子项；不支撑任何结论的，放进最后一个「顺带」条目（没有就新建一个，粗体写一句概括）。
只有补的内容是一个新的核心结论时，才新增第 1 层条目。已有内容不删、不改意思，缩进层次不变。
补进去的叙述句同样遵守：一句一事，一句不超过 40 字，只写讲者讲的内容。「」里的原话保持原样。
第 3 步（单独做，不和第 1 步合并）：从头到尾再读一遍字幕，只找讲者有味道的原话：玩笑、吐槽、自嘲、反讽、狠话、
模仿别人的内心独白、对着现场的即兴话（例如找不到东西、点评屏幕上的东西）、好笑的比喻、给东西起的外号。
对每一句检查草稿里有没有用「」引它；没有引、或者只转述了意思的，补成一个 **玩笑** / **吐槽** / **自嘲** 子项，放在它所在话题的结论下面，用「」引原话（按字幕改正错字）。
输出 JSON：{{"missing": ["第 1 步找到的漏掉的内容，每条一句话"], "quotes": ["第 3 步补上的原话"], "body": "补好的全文"}}
如果没有漏掉的，missing 为空数组，body 原样返回。

字幕：
{text}

草稿：
{body}
"""

FIX_PROMPT = """下面是一段课堂笔记，以及简明技术中文检查脚本对它的发现。
请只改被点名的句子：拆长句、换掉禁用词、汉字数字改阿拉伯数字。
不改事实、数字、例子和确定程度，不删内容，不改 Markdown 结构（列表的嵌套和缩进）和「> 原话」引用行。
拆开的句子留在原来那个列表项里。
「> 原话」行、「」里引用的讲者原话、术语表里的写法保持原样。
输出 JSON：{{"body": "改好的全文"}}

检查发现：
{findings}

笔记：
{body}
"""

STC_CHECK = Path(os.environ.get("STC_CHECK", "/Volumes/AppStorage/project/skills/simplified-technical-chinese/tools/check.py"))


def stc_findings(body: str) -> list[dict]:
    """用简明技术中文检查脚本查一段正文，只要【必须】级别；脚本不在就跳过。"""
    if not STC_CHECK.exists():
        return []
    r = subprocess.run([sys.executable, str(STC_CHECK), "-", "--kind", "描述", "--json"],
                       input=body, capture_output=True, text=True)
    try:
        found = json.loads(r.stdout).get("findings", [])
    except json.JSONDecodeError:
        return []
    return [f for f in found if f.get("level") == "必须" and not f.get("text", "").startswith(">")]


# ---------- 字幕 ----------

def parse_srt(path: Path):
    cues, start, text = [], None, []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        s = line.strip()
        m = TIME.match(s)
        if m:
            g = list(map(int, m.groups()))
            start, text = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, []
        elif s == "":
            if start is not None and text:
                cues.append((start, " ".join(text)))
            start, text = None, []
        elif start is not None and not s.isdigit():
            text.append(s)
    return cues


def mmss(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def parse_mmss(s: str) -> int:
    parts = [int(p) for p in re.findall(r"\d+", str(s))]
    if not parts:
        return 0
    sec = 0
    for p in parts[-3:]:
        sec = sec * 60 + p
    return sec


def timed_text(cues, lo=0, hi=1e9, every=30) -> str:
    """字幕拼成带时间戳的文本，每 every 秒插一个 [分:秒]。"""
    out, last = [], -1e9
    for t, s in cues:
        if lo <= t < hi:
            if t - last >= every:
                out.append(f"\n[{mmss(t)}] ")
                last = t
            out.append(s)
    return "".join(out).strip()


# ---------- 模型 ----------

def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                if not os.environ.get(k.strip()):  # 空值也算未设置
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")


# 默认用 Claude Code（claude -p，走订阅额度，不花 DeepSeek token）；VSUM_LLM=deepseek 或 --llm deepseek 切回 DeepSeek API。
LLM = os.environ.get("VSUM_LLM", "claude")
CLAUDE_MODEL = os.environ.get("VSUM_CLAUDE_MODEL", "sonnet")
CLAUDE_SYS = ("你是笔记整理工具里的一个步骤。严格按用户消息的要求，只输出一个 JSON 对象，不输出任何其他文字、"
              "不用代码块。JSON 里的内容用用户消息要求的语言（中文）写。")


def ask_claude_json(prompt: str) -> dict:
    """无工具、无 MCP、不存会话的 claude -p 调用；cwd 放在临时目录，不读项目的 CLAUDE.md。"""
    import tempfile
    cmd = ["claude", "-p", "--model", CLAUDE_MODEL, "--tools", "", "--strict-mcp-config",
           "--disable-slash-commands", "--no-session-persistence", "--system-prompt", CLAUDE_SYS]
    last = ""
    for _ in range(3):
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=tempfile.gettempdir())
        last = (r.stdout or r.stderr)[-300:]
        m = re.search(r"\{.*\}", r.stdout, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise RuntimeError(f"claude -p 连续 3 次没有返回可用 JSON：{last}")


def ask_json(client, prompt: str) -> dict:
    if LLM == "claude":
        try:
            return ask_claude_json(prompt)
        except RuntimeError as e:
            # Claude 的网络安全防护偶尔误拦课堂内容（例如讲「隔离机器怎么传数据」）。这一次调用改用 DeepSeek。
            load_env()
            if not os.environ.get("DEEPSEEK_API_KEY"):
                raise
            print(f"  ⚠️ claude -p 失败，这一步改用 DeepSeek：{str(e)[:80]}", flush=True)
            from openai import OpenAI
            client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    last = None
    for _ in range(3):
        try:
            resp = client.chat.completions.create(
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            txt = (resp.choices[0].message.content or "").strip()
            txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
            return json.loads(txt)
        except Exception as e:  # 空回复 / JSON 坏了：重试
            last = e
    raise RuntimeError(f"模型连续 3 次没有返回可用 JSON：{last}")


def cached(path: Path, force: bool, make):
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    data = make()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def normalize(outline: dict, duration: float) -> list[dict]:
    secs = sorted(outline["sections"], key=lambda s: parse_mmss(s.get("start", 0)))
    for i, s in enumerate(secs):
        s["t0"] = 0 if i == 0 else parse_mmss(s["start"])
    for i, s in enumerate(secs):
        s["t1"] = secs[i + 1]["t0"] if i + 1 < len(secs) else duration
        if s.get("link") not in LINKS:
            s["link"] = "开场" if i == 0 else "进一步"
    return [s for s in secs if s["t1"] > s["t0"]]


# ---------- 截图 ----------

def grab(video: Path, sec: int, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(sec), "-i", str(video),
                        "-frames:v", "1", "-q:v", "3", "-vf", "scale='min(1280,iw)':-2", str(out)])
    return r.returncode == 0 and out.exists()


def same_frame(a: Path, b: Path) -> bool:
    try:
        import cv2
        import numpy as np
        x, y = (cv2.resize(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), (160, 90)) for p in (a, b))
        return float(np.mean(np.abs(x.astype(int) - y.astype(int)))) < 4
    except Exception:
        return False


# ---------- 结构图 ----------

def wrap(text: str, width: int) -> list[str]:
    """按显示宽度折行：汉字算 1，ASCII 算 0.55。"""
    lines, cur, w = [], "", 0.0
    for ch in text:
        cw = 0.55 if ord(ch) < 128 else 1.0
        if w + cw > width and cur:
            lines.append(cur)
            cur, w = "", 0.0
        cur += ch
        w += cw
    if cur:
        lines.append(cur)
    return lines


def toc_svg(title: str, one_line: str, secs: list[dict]) -> str:
    W, X, BW, FS = 760, 70, 670, 15
    y, parts = 20, []
    n = max(1, -(-len(one_line) // 42))  # 行数；再按行数均分，避免最后一行只剩几个字
    head = wrap(one_line, -(-len(one_line) // n) + 2)
    parts.append(f'<text x="{W/2}" y="{y+18}" text-anchor="middle" font-size="19" font-weight="700" fill="#1d1d1f">{escape(title)}</text>')
    y += 34
    for ln in head:
        parts.append(f'<text x="{W/2}" y="{y+16}" text-anchor="middle" font-size="{FS}" fill="#444">{escape(ln)}</text>')
        y += 22
    y += 14
    palette = ["#e8f0fe", "#e6f4ea", "#fef7e0", "#fce8e6", "#f3e8fd", "#e4f7fb", "#fdeee0", "#eceff1", "#e8eaf6"]
    stroke = ["#4a7bd0", "#3c8c55", "#c9a227", "#c5523f", "#8a55c9", "#2b93a8", "#d27b2c", "#78909c", "#5c6bc0"]
    for i, s in enumerate(secs):
        if i:
            parts.append(f'<line x1="{X+28}" y1="{y-26}" x2="{X+28}" y2="{y-4}" stroke="#999" stroke-width="2" marker-end="url(#arr)"/>')
            parts.append(f'<text x="{X+44}" y="{y-11}" font-size="13" fill="#777">{escape(s["link"])}</text>')
        claim = wrap(s.get("claim", ""), 39)
        h = 40 + 21 * len(claim)
        c = i % len(palette)
        parts.append(f'<rect x="{X}" y="{y}" width="{BW}" height="{h}" rx="10" fill="{palette[c]}" stroke="{stroke[c]}" stroke-width="1.5"/>')
        parts.append(f'<circle cx="{X+28}" cy="{y+22}" r="13" fill="{stroke[c]}"/>')
        parts.append(f'<text x="{X+28}" y="{y+27}" text-anchor="middle" font-size="14" font-weight="700" fill="#fff">{i+1}</text>')
        parts.append(f'<text x="{X+52}" y="{y+27}" font-size="16" font-weight="700" fill="#1d1d1f">{escape(s["title"])}</text>')
        parts.append(f'<text x="{X+BW-14}" y="{y+27}" text-anchor="end" font-size="13" fill="#666">{mmss(s["t0"])}–{mmss(s["t1"])}</text>')
        for k, ln in enumerate(claim):
            parts.append(f'<text x="{X+52}" y="{y+50+21*k}" font-size="{FS-1}" fill="#333">{escape(ln)}</text>')
        y += h + 34
    H = y - 14
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="PingFang SC, Hiragino Sans GB, Noto Sans CJK SC, Microsoft YaHei, sans-serif">'
            f'<defs><marker id="arr" markerWidth="10" markerHeight="10" refX="5" refY="5" orient="auto">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="#999"/></marker></defs>'
            f'<rect width="100%" height="100%" fill="#fff"/>' + "".join(parts) + "</svg>\n")


# ---------- 金字塔结构 ----------

LIST = re.compile(r"^( *)([-*+]|\d+[.)]) ")


def renest(body: str) -> str:
    """模型的缩进单位不固定（2 或 4 个空格），统一成每层 4 个空格，pandoc 和 GitHub 都认。"""
    lines = [("- " + ln if re.match(r"^\*\*[^*]+\*\*[：:]?\s*$", ln) else ln) for ln in body.splitlines()]
    ind = sorted({len(m.group(1)) for ln in lines if (m := LIST.match(ln)) and m.group(1)})
    if not ind:
        return punct("\n".join(lines))
    unit = ind[0]
    out = []
    for ln in lines:
        m = re.match(r"^( +)(\S.*)$", ln)
        out.append(" " * 4 * round(len(m.group(1)) / unit) + m.group(2) if m else ln)
    return punct("\n".join(out))


def punct(body: str) -> str:
    """「**结论**理由」中间补一个句号：模型常把粗体结论和后面的理由直接连在一起。"""
    return re.sub(r"^(\s*[-*+] \*\*[^*]+?)([^\s*。！？：:.!?])\*\*(?=[^\s：:。，,）)])", r"\1\2。**", body, flags=re.M)


def pyramid_stats(body: str) -> dict:
    """第 1 层条目数、其中写成结论句（粗体 ≥ 10 字）的比例、最深层数。粗体太短多半是话题标签。"""
    tops, claims, depth = 0, 0, 0
    for ln in body.splitlines():
        m = LIST.match(ln)
        if not m:
            continue
        lvl = len(m.group(1)) // 4
        depth = max(depth, lvl + 1)
        if lvl == 0:
            tops += 1
            b = re.match(r"^\s*\S+ \*\*(.+?)\*\*", ln)
            claims += bool(b and len(re.sub(r"\s", "", b.group(1))) >= 10)
    return {"tops": tops, "claims": claims, "depth": depth}


# ---------- 组装 ----------

def tlink(url: str, sec: float) -> str:
    if not url:
        return mmss(sec)
    sep = "&" if "?" in url else "?"
    return f"[{mmss(sec)}]({url}{sep}t={int(sec)})"


def main():
    global LLM
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", type=Path)
    ap.add_argument("--title", required=True)
    ap.add_argument("--num", default="")
    ap.add_argument("--name", default="", help="文件名（不含扩展名），默认 <编号>-<标题>")
    ap.add_argument("--url", default="")
    ap.add_argument("--collection", default="")
    ap.add_argument("--speaker", default="")
    ap.add_argument("--video", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-cover", action="store_true", help="跳过补漏这一步（对照实验用）")
    ap.add_argument("--llm", choices=["claude", "deepseek"], default=LLM,
                    help="写笔记用的模型：claude（claude -p，默认）或 deepseek（API，要 .env 里的 key）")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SUMMARY_WORKERS", 6)))
    a = ap.parse_args()
    a.out = a.out.resolve()  # pandoc 在笔记目录里运行，路径必须是绝对的

    LLM = a.llm
    client = None
    if LLM == "deepseek":
        load_env()
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    cues = parse_srt(a.srt)
    if not cues:
        sys.exit(f"字幕是空的：{a.srt}")
    duration = cues[-1][0] + 5
    name = f"{a.num}-{a.title}" if a.num else a.title
    safe = a.name or re.sub(r'[<>:"/\\|?*⧸\s]', "", name)
    cache = a.out / ".cache" / safe
    img_dir = a.out / "images" / safe

    print(f"▶ {name}（模型：{CLAUDE_MODEL if LLM == 'claude' else 'deepseek'}）：字幕 {sum(len(s) for _, s in cues)} 字，{duration/60:.0f} 分钟", flush=True)
    outline = cached(cache / "outline.json", a.force,
                     lambda: ask_json(client, OUTLINE_PROMPT.replace("{who}", f"讲者是{a.speaker}。" if a.speaker else "")
                                      + timed_text(cues, every=30)))
    # 旧缓存里的一句话可能带着提示词的说法开头，去掉
    outline["one_line"] = re.sub(r"^(讲者)?(想让听众相信|想让听众|的核心主张是?)[：:，,]?\s*", "", outline.get("one_line", ""))
    secs = normalize(outline, duration)
    print(f"  目录：{len(secs)} 节", flush=True)

    toc = "\n".join(f"{i+1}. {s['title']}（{mmss(s['t0'])}–{mmss(s['t1'])}）：{s.get('claim','')}\n   covers：{'；'.join(s.get('covers', []))}"
                    for i, s in enumerate(secs))
    terms = "\n".join(f"- {t['term']}" + (f"（字幕可能写成：{'、'.join(t['asr'])}）" if t.get("asr") else "") + f"：{t.get('meaning','')}"
                      for t in outline.get("terms", []))

    def write(i):
        s = secs[i]
        minutes = (s["t1"] - s["t0"]) / 60
        prompt = SECTION_PROMPT.format(
            one_line=outline.get("one_line", ""), toc=toc, terms=terms, idx=i + 1, title=s["title"],
            others="\n".join(f"- 第 {j+1} 节：{o.get('claim','')}；{'；'.join(o.get('covers', []))}"
                              for j, o in enumerate(secs) if j != i),
            start=mmss(s["t0"]), end=mmss(s["t1"]), minutes=round(minutes), claim=s.get("claim", ""),
            covers="；".join(s.get("covers", [])), style=STYLE, budget=int(max(500, min(2600, minutes * 110))),
            text=timed_text(cues, s["t0"], s["t1"], every=20))
        r = cached(cache / f"sec{i+1:02d}.json", a.force, lambda: ask_json(client, prompt))
        others = "\n".join(f"- 第 {j+1} 节：{'；'.join(o.get('covers', []))}" for j, o in enumerate(secs) if j != i)
        cov = {} if a.no_cover else cached(cache / f"sec{i+1:02d}.cover.json", a.force, lambda: ask_json(client, COVER_PROMPT.format(
            others=others, text=timed_text(cues, s["t0"], s["t1"], every=20), body=r.get("body", ""))))
        added = len(cov.get("missing") or []) + len(cov.get("quotes") or [])
        if len(cov.get("body", "")) >= 0.9 * len(r.get("body", "")):  # 只接受补充，不接受删减
            r = {**r, "body": cov["body"]}
        found = stc_findings(r.get("body", ""))
        if found:  # 修一轮：只改检查脚本点名的句子
            listing = "\n".join(f"- {f['message']} ←「{f['text']}」" for f in found)
            fixed = cached(cache / f"sec{i+1:02d}{'.nocover' if a.no_cover else ''}.fixed.json", a.force,
                           lambda: ask_json(client, FIX_PROMPT.format(findings=listing, body=r["body"])))
            if len(fixed.get("body", "")) > 0.7 * len(r["body"]):  # 防止修的时候删内容
                r = {**r, "body": fixed["body"]}
        left = len(stc_findings(r.get("body", "")))
        r = {**r, "body": renest(r.get("body", ""))}
        ps = pyramid_stats(r["body"])
        print(f"  ✓ 第 {i+1} 节 {s['title']}（{len(r.get('body',''))} 字，补漏 {added} 条，STC 必须项 {len(found)}→{left}，"
              f"第 1 层 {ps['tops']} 条其中结论句 {ps['claims']}，{ps['depth']} 层）", flush=True)
        return r

    with ThreadPoolExecutor(a.workers) as ex:
        bodies = list(ex.map(write, range(len(secs))))

    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "toc.svg").write_text(toc_svg(f"{a.num} · {a.title}" if a.num else a.title, outline.get("one_line", ""), secs), encoding="utf-8")
    rel = lambda p: urllib.parse.quote(p.relative_to(a.out).as_posix())

    shown = f"{a.num} · {a.title}" if a.num else a.title
    md = [f"# {shown}", ""]
    meta = [f"原视频：<{a.url}>" if a.url else "", f"课程合集：<{a.collection}>" if a.collection else "",
            f"讲者：{a.speaker}" if a.speaker else ""]
    if any(meta):
        md += ["> " + "　·　".join(m for m in meta if m), ""]
    md += [f"**一句话**：{outline.get('one_line', '')}", "",
           f"![本讲结构]({rel(img_dir / 'toc.svg')})", "",
           "| # | 本节结论 | 话题 | 时间 |", "|---|---|---|---|"]
    md += [f"| {i+1} | {s.get('claim') or s['title']} | {s['title']} | {tlink(a.url, s['t0'])}–{mmss(s['t1'])} |"
           for i, s in enumerate(secs)]
    md.append("")

    prev = None
    for i, (s, b) in enumerate(zip(secs, bodies)):
        # 标题写本节结论（金字塔：外层说结论），话题名放在下面的小字里
        md += [f"## {i+1}. {s.get('claim') or s['title']}", "",
               f"<small>▶ {tlink(a.url, s['t0'])}–{mmss(s['t1'])}　·　{s['link']}　·　话题：{s['title']}</small>", "",
               (b.get("body") or "").strip(), ""]
        if a.video and a.video.exists():
            for k, shot in enumerate((b.get("shots") or [])[:2]):
                t = min(max(parse_mmss(shot.get("time", 0)), s["t0"]), s["t1"] - 1)
                p = img_dir / f"s{i+1:02d}_{k+1}_{mmss(t).replace(':', '')}.jpg"
                if not grab(a.video, t, p):
                    continue
                if prev is not None and same_frame(prev, p):
                    p.unlink()
                    continue
                prev = p
                cap = shot.get("caption", "")
                md += [f"![{cap}]({rel(p)})", "", f"<small>图：{cap}（{tlink(a.url, t)}）</small>", ""]

    refs, seen = [], set()
    for i, b in enumerate(bodies):
        for ref in b.get("refs") or []:
            key = re.sub(r"\W", "", str(ref.get("name", ""))).lower()
            if key and key not in seen:
                seen.add(key)
                refs.append((ref["name"], ref.get("what", ""), i + 1))
    if refs:
        md += ["## 提到的资料", "", "| 名称 | 是什么、为什么提 | 小节 |", "|---|---|---|"]
        md += [f"| {n} | {w} | {k} |" for n, w, k in refs] + [""]
    if outline.get("admin"):
        md += ["## 课程事务", ""] + [f"- {x}" for x in outline["admin"]] + [""]
    if outline.get("terms"):
        md += ["## 术语表", "", "| 术语 | 含义 | 字幕原识别 |", "|---|---|---|"]
        md += [f"| {t['term']}{'' if t.get('sure', True) else '（拼写待确认）'} | {t.get('meaning','')} | {'、'.join(t.get('asr') or []) or '—'} |"
               for t in outline["terms"]]
        md.append("")
    md += ["---", "", "<small>笔记由模型根据字幕整理，按主题而不是按时间分节。每节标题是这节的结论，每条粗体是它下面内容的结论：只读粗体也能读到全部核心论点。标「（整理者补充）」的是整理者补上的推理。引用前请对照原视频。</small>", ""]

    out_md = a.out / f"{safe}.md"
    out_md.write_text(re.sub(r"\n{3,}", "\n\n", "\n".join(md)), encoding="utf-8")
    body_chars = sum(len(re.sub(r"\s", "", b.get("body", ""))) for b in bodies)
    print(f"  📝 {out_md}（正文 {body_chars} 字）", flush=True)

    if not a.no_pdf:
        sys.path.insert(0, str(ROOT))
        import export_notes
        from export_notes import render_pdf
        # 结构图和标题放在第 1 页：限制图高；页首的来源信息用小字
        export_notes.CSS += """
img[alt="本讲结构"] { max-height: 170mm; width: auto; border: none; margin: 4px auto; }
figcaption { display: none; }
figure { margin: 0; }
blockquote { font-size: .85em; }
small { color: #666; }
h2 ~ ul > li { margin-top: .6em; }
h2 ~ ul > li > strong:first-child { font-size: 1.04em; }
"""
        pdf = out_md.with_suffix(".pdf")
        render_pdf(out_md, pdf)
        print(f"  📄 {pdf}", flush=True)


if __name__ == "__main__":
    main()
