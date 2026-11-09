# 生成这些笔记用到的工具

## 基础：VideoSummary

- 原仓库：[NothingToSay0031/VideoSummary](https://github.com/NothingToSay0031/VideoSummary)（作者 [@NothingToSay0031](https://github.com/NothingToSay0031)，MIT License）
- 本仓库的笔记基于它的 commit `5e6e169`，再加上 `videosummary/` 里的改动。

`videosummary/` 里的文件：

| 文件 | 作用 |
|---|---|
| `video_summary_app.patch` | 改写逐段总结的提示词（v3）：按讲者的论证写成逻辑链；老师没说、由模型补上的衔接标（整理者串联）；不加课外公式和例子；修正字幕识别错误。各段总结同时发给 LLM（默认 6 路，环境变量 `SUMMARY_WORKERS` 可调），一讲约 4 分钟 |
| `topic_notes.py` | **现在的全部笔记（01–10）用它生成（v4：金字塔结构，模型默认 Claude，用 `claude -p`；`--llm deepseek` 改用 DeepSeek）。** 只读字幕：先通读全文按话题切 5–9 节、统一术语，再逐节按简明技术中文写全这一段的实质内容（别的小节负责的话题不展开），对照字幕补漏一轮，用[简明技术中文检查脚本](https://github.com/mzopedia/simplified-technical-chinese)查一遍、改一轮，讲者的玩笑、吐槽用「」引原话单独成条；最后画结构图 `toc.svg`、导出 PDF。模型输出缓存在 `<输出>/.cache/`，重跑不花钱 |
| `skim.py` | 取笔记的外层（标题、一句话、小节标题、第 1 层），配合 `eval_notes.py` 测「只读外层能读到多少核心论点」 |
| `eval_notes.py` | 评测笔记：用 Claude 从字幕按 10 分钟一窗抽事实，再逐条判断每个笔记版本覆盖了多少（核心 / 细节 / 旁支）、有多少跨小节重复。改提示词之前和之后都跑一遍，至少在 3 讲没看过的课上确认 |
| `vsum.py` | 一条命令批量处理：展开合集、每个视频单独目录（避免原工具按关键词模糊匹配时串课）、预先下载中文字幕、自动刷新 B 站 cookie、跑完调用下面两个脚本 |
| `outline.py` | 读完整份逐段总结，在开头加「全课主线」 |
| `export_notes.py` | 整理成 原文 / 摘要 / PDF 三个文件夹（pandoc + Chrome 导出 PDF） |
| `progress.py` | 看进度：`python progress.py -w` 实时进度条，`--profile` 各阶段耗时 |

用法：把原仓库 clone 下来，`git apply video_summary_app.patch`，把五个 `.py` 放进仓库根目录，装好并登录 Claude Code（`claude -p` 能用即可；用 DeepSeek 时在 `.env` 里配好 `DEEPSEEK_API_KEY`），然后：

```bash
python vsum.py <B站视频或合集链接> -o output/<名字> -d <输出目录>
```

默认走 `topic_notes.py`，只用字幕，不下载视频；产出 `<输出目录>/笔记/`、`PDF/`、`原文/`。`--shots` 才下载视频截图；`--legacy` 是 01–08 最早用的旧流程（逐段总结 + 全课主线），现在已不用。

## Agent skill

`skills/` 下是给 Claude Code / Codex 等编程 agent 用的 skill（`SKILL.md` 是给 agent 读的操作说明）。放进 `~/.claude/skills/`（或其他 agent 的 skills 目录）即可使用。

- **voice-summary**：调用上面的 VideoSummary 流程，只读字幕。**本仓库的 PDF 和 Markdown 都是用它生成的。**
- **video-summary**：实验版，由 agent 自己看视频截图（幻灯片、代码、板书）写图文笔记，适合幻灯片内容重要的课。本仓库的笔记没有用它。脚本在 `scripts/`，需要 `opencv-python` 和 `numpy`。

skill 里写的路径（如 `~/project/VideoSummary`）是整理者本机的位置，用的时候按自己的目录改。
