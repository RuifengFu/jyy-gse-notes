"""给整份摘要加一节「全课主线」：把逐段总结串成一条全课论证链，插在标题下面。

    python outline.py <摘要.md> [--force]

逐段总结天然是碎片化的（每 3.5 分钟一段、各自总结）。这一步让模型读完全部分段，
写出讲者从开头到结尾的论证链，每一步注明出自第几部分；讲者没明说、由模型补上的衔接标（整理者串联）。
已经有「全课主线」的文件默认跳过。
"""

import argparse
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parent
HEADING = "## 全课主线"

PROMPT = """下面是一节讲座按时间切段后的逐段笔记（"第 N 部分"按时间顺序）。读者听课时觉得内容很碎，需要一条贯穿全课的论证主线。

请写「全课主线」：
1. 先用 2–3 句话说清这节课的核心主张（讲者想让听众相信什么、做什么）。
2. 然后用 6–12 个编号步骤，按讲者的推进顺序把论证串起来。每步一两句话：这一步的论点，以及它和上一步的关系（因此 / 但是 / 举例 / 推论……）。
   每步末尾标出处，如「（第 3、4 部分）」。
3. 讲者明确说过的衔接直接写；讲者没说、由你推断的衔接，在该处标注（整理者串联）。
4. 最后用一句话写出讲者的结论或号召。
要求：只用笔记里有的内容，不加新知识、公式或例子；不要复述细节；不要开场白和结束语；直接从内容开始，不要写标题。输出中文。

逐段笔记：
"""


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def strip_images(md: str) -> str:
    return re.sub(r"!\[[^\]]*\]\([^)]*\)\n?", "", md)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", type=Path)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    text = a.md.read_text(encoding="utf-8")
    if HEADING in text and not a.force:
        print(f"已有全课主线，跳过：{a.md.name}")
        return
    text = re.sub(rf"\n{HEADING}\n.*?(?=\n## |\n# )", "\n", text, flags=re.S)  # --force: 去掉旧的

    load_env()
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],
                    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    outline = ""
    for _ in range(3):  # 推理模型偶尔只返回思考、正文为空，重试即可
        resp = client.chat.completions.create(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": PROMPT + strip_images(text)}],
            temperature=0.3,
        )
        outline = (resp.choices[0].message.content or "").strip()
        if outline:
            break
    if not outline:
        sys.exit("模型连续 3 次没有返回内容")

    lines = text.split("\n")
    at = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 0)
    lines[at:at] = ["", HEADING, "", outline, ""]
    a.md.write_text("\n".join(lines), encoding="utf-8")
    print(f"已加全课主线：{a.md.name}（{len(outline)} 字）")


if __name__ == "__main__":
    main()
