# 生成这些笔记用到的工具

## 基础：VideoSummary

- 原仓库：[NothingToSay0031/VideoSummary](https://github.com/NothingToSay0031/VideoSummary)（作者 [@NothingToSay0031](https://github.com/NothingToSay0031)，MIT License）
- 本仓库的笔记基于它的 commit `5e6e169`，再加上 `videosummary/` 里的改动。

`videosummary/` 里的文件：

| 文件 | 作用 |
|---|---|
| `video_summary_app.patch` | 改写逐段总结的提示词（v3）：按讲者的论证写成逻辑链；老师没说、由模型补上的衔接标（整理者串联）；不加课外公式和例子；修正字幕识别错误 |
| `vsum.py` | 一条命令批量处理：展开合集、每个视频单独目录（避免原工具按关键词模糊匹配时串课）、预先下载中文字幕、自动刷新 B 站 cookie、跑完调用下面两个脚本 |
| `outline.py` | 读完整份逐段总结，在开头加「全课主线」 |
| `export_notes.py` | 整理成 原文 / 摘要 / PDF 三个文件夹（pandoc + Chrome 导出 PDF） |

用法：把原仓库 clone 下来，`git apply video_summary_app.patch`，把三个 `.py` 放进仓库根目录，在 `.env` 里配好 `DEEPSEEK_API_KEY`，然后：

```bash
python vsum.py <B站视频或合集链接> -o output/<名字> -d <输出目录>
```

## Agent skill

`skills/` 下是给 Claude Code / Codex 等编程 agent 用的 skill（`SKILL.md` 是给 agent 读的操作说明）。放进 `~/.claude/skills/`（或其他 agent 的 skills 目录）即可使用。

- **voice-summary**：调用上面的 VideoSummary 流程，只读字幕。**本仓库的 PDF 和 Markdown 都是用它生成的。**
- **video-summary**：实验版，由 agent 自己看视频截图（幻灯片、代码、板书）写图文笔记，适合幻灯片内容重要的课。本仓库的笔记没有用它。脚本在 `scripts/`，需要 `opencv-python` 和 `numpy`。

skill 里写的路径（如 `~/project/VideoSummary`）是原作者本机的位置，用的时候按自己的目录改。
