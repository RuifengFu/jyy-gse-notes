# 南京大学《生成式软件工程》2026 · 课程笔记（非官方）

蒋炎岩（jyy）老师 2026 年《生成式软件工程》课程录像的 AI 辅助整理笔记，每讲一份 PDF。

- 课程合集（B 站）：<https://space.bilibili.com/202224425/lists/8942017>
- 内容版权归讲者所有；本仓库仅作个人学习笔记，**以原视频为准**。

| # | 讲次 | 笔记 | 原视频 |
|---|---|---|---|
| 01 | 欢迎来到未来 | [PDF](pdf/01-欢迎来到未来.pdf) · [Markdown](md/01-欢迎来到未来.md) | [BV1pb8o6yE8f](https://www.bilibili.com/video/BV1pb8o6yE8f) |
| 02 | 提示词工程 | [PDF](pdf/02-提示词工程.pdf) · [Markdown](md/02-提示词工程.md) | [BV1CQt365EzW](https://www.bilibili.com/video/BV1CQt365EzW) |
| 03 | 软件仓库管理 | [PDF](pdf/03-软件仓库管理.pdf) · [Markdown](md/03-软件仓库管理.md) | [BV1kybV6DE47](https://www.bilibili.com/video/BV1kybV6DE47) |
| 04 | 软件仓库管理 (2) | [PDF](pdf/04-软件仓库管理2.pdf) · [Markdown](md/04-软件仓库管理2.md) | [BV1Q6en6NEUo](https://www.bilibili.com/video/BV1Q6en6NEUo) |
| 05 | 软件工程的来龙去脉 | [PDF](pdf/05-软件工程的来龙去脉.pdf) · [Markdown](md/05-软件工程的来龙去脉.md) | [BV1Nyeq6qEt8](https://www.bilibili.com/video/BV1Nyeq6qEt8) |
| 06 | 需求和架构 (1) | [PDF](pdf/06-需求和架构1.pdf) · [Markdown](md/06-需求和架构1.md) | [BV1Rch76WEfQ](https://www.bilibili.com/video/BV1Rch76WEfQ) |

每份笔记的标题下方也写有对应的原视频链接。`md/` 下是 Markdown 源文件（截图在 `md/images/`），可以直接在 GitHub 上看，也方便搜索和复制。

## 怎么读

- **全课主线**（每份开头）：用约 10 步把整节课串成一条论证链，每步注明出自「第 N 部分」。
- **第 N 部分**：按时间顺序，每段约 3.5 分钟，附当时的画面截图。
- **（整理者串联）**：老师没明说、由整理者补上的推理衔接。没有这个标记的，是老师讲的内容。
- 字幕识别错误已按上下文修正；拿不准的词在括号里保留原文。

## 怎么做的

B 站 AI 中文字幕 → 按时间切段 → 大模型（DeepSeek）逐段整理论证 → 再通读全文写「全课主线」→ 截取对应画面 → pandoc + Chrome 导出 PDF。

工具基于 [NothingToSay0031/VideoSummary](https://github.com/NothingToSay0031/VideoSummary)（作者 [@NothingToSay0031](https://github.com/NothingToSay0031)，MIT License）修改。改动的脚本和生成用的 agent skill 都在 [`tools/`](tools/)，说明见 [tools/README.md](tools/README.md)。
笔记由模型生成，可能有理解偏差，引用前请对照原视频。
