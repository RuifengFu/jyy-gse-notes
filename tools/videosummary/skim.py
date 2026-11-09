"""金字塔外层：只留标题、一句话、## 小节标题、「要点」行、第 1 层列表项。用来测「只读外层能读到多少核心论点」。
    python skim.py <笔记.md> [--bold-only] > <外层.md>
--bold-only：第 1 层只取粗体部分。v3 是平铺列表（第 1 层就是全文），只能这样取；v4 第 1 层是「粗体结论 + 一句理由」，取整行。"""
import re, sys
bold_only = "--bold-only" in sys.argv
out = []
for ln in open(sys.argv[1], encoding="utf-8").read().splitlines():
    if ln.startswith(("# ", "## ", "**一句话**", "**要点**")):
        out.append(ln)
    elif m := re.match(r"^[-*+] \*\*(.+?)\*\*(.*)$", ln):  # 第 1 层（无缩进）列表项
        out.append(f"- {m.group(1)}" + ("" if bold_only else m.group(2)))
print("\n".join(out))
