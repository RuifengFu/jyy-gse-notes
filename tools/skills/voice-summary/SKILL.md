---
name: voice-summary
description: Subtitle-driven video notes with the local VideoSummary tool — the LLM reads only the subtitles/transcript; screenshots are picked by frame-change detection and attached per time chunk, not chosen by content. Produces a summary, a timestamped full transcript and a summary PDF for Bilibili/YouTube videos or whole collections. Use when the user asks for voice-summary / 语音摘要 / 字幕总结, wants a fast, cheap batch of a whole course, or asks to 转文字稿. For image-heavy lectures where slides matter, prefer the video-summary skill.
---

# voice-summary

How it works: yt-dlp → subtitles split into ~1000-char chunks → DeepSeek summarizes each chunk (text only) → outline.py strings the chunk summaries into one lecture-wide argument → in parallel, frames every 2 s per chunk, kept only when the block-wise pixel change is large, then de-duplicated → final markdown = each chunk's frames + that chunk's summary.

Tool: `~/project/VideoSummary` (Python venv at `.venv`; LLM = DeepSeek via `.env`; Bilibili AI subtitles via `cookies.txt`).

## One command

```bash
cd ~/project/VideoSummary && source .venv/bin/activate
python vsum.py <video-or-collection-url>... -o output/<slug> -d ~/Desktop/<课程名>
```

- `-o`: intermediate results (videos, frames, raw summary). Always relative to the repo, i.e. on the external drive.
- `-d`: final, tidy output:
  ```
  <dest>/原文/NN-标题.md     full transcript, paragraphs with [hh:mm:ss] timestamps
  <dest>/摘要/NN-标题.md     summary + screenshots (images in 摘要/images/)
  <dest>/PDF/NN-标题.pdf     the summary rendered to PDF
  ```
- `--text-only`: for interviews, podcasts and talking heads, skip the video download and screenshots entirely (passes `-n` to the app). When the video has subtitles, it needs no audio either. Use it by default when the screen doesn't matter.
- If the log says `DEEPSEEK_API_KEY 未设置` although `.env` has it, the shell exports an **empty** `DEEPSEEK_API_KEY`, and the `.env` loader never overrides existing variables. Run with `env -u DEEPSEEK_API_KEY python vsum.py …`.
- Collections/playlists get expanded. Videos under 10 minutes are skipped (`--min-minutes`). Videos that already have a summary are skipped too, so re-running resumes an interrupted batch.
- Bilibili subtitles need login. If `cookies.txt` has expired, vsum re-exports it from Chrome, keeping only bilibili.com cookies. If that fails, ask the user to log in to Bilibili in Chrome.
- Never call `video_summary_app.py` directly with a shared `-o` directory for several videos. It reuses local files by **fuzzy keyword match**, so lectures of one course pick up each other's video and subtitles and overwrite each other's summary. vsum gives every video its own `-o <out>/<video id>/`, which avoids this.
- To re-export only (no downloading, no LLM): `python export_notes.py output/<slug> <dest>`.

## Running it
- It takes about 5 minutes per 100-minute lecture. Almost all of it is waiting for DeepSeek; chunks are summarized concurrently (default 6, env `SUMMARY_WORKERS`), so ~9 s per chunk instead of ~40 s. Activate `.venv` first (otherwise the app calls an outdated Homebrew `yt-dlp` that gets HTTP 412 from Bilibili), then run it in the background (`nohup … > output/<slug>.log 2>&1 &`).
- **Do not leave the user waiting blindly.** Right after launching, tell them `python progress.py -w` (live progress bar in their terminal), and arm a Monitor that prints `python progress.py output/<slug>.log --line` every ~3 minutes until vsum exits. When it ends, report which videos finished or failed; `python progress.py output/<slug>.log --profile` shows per-stage timing.
- `~/.zshrc` exports an empty `DEEPSEEK_API_KEY`; the `.env` loaders treat an empty value as unset, so `.env` wins. If you see 「DEEPSEEK_API_KEY 未设置」, check that first.
- Check free space first with `df -h /Volumes/AppStorage`: each lecture's video is about 150 MB and its frames about 12 MB.
- The summary prompt is `BASE_SYSTEM_PROMPT` in `video_summary_app.py`. Current version is v3 (2026-09-28): each chunk is rebuilt as the speaker's argument, with a logic chain. Links the model supplies itself are marked **（整理者串联）**. No invented formulas, no audience persona, no 记忆钩子 sections, and ASR errors are fixed. v3 beat the original prompt 3–0 in a blind test on jyy lecture 02.
- After each video, `outline.py` adds a **## 全课主线** section at the top: a 6–12-step argument chain across the whole lecture, each step citing 第 N 部分. Rerun it alone with `python outline.py <summary.md> --force`.
- vsum downloads subtitles itself before calling the app, because the app sometimes gets only danmaku and crashes. If a video has no subtitles at all, it still fails; say so and never invent a transcript.

## After
Tell the user the `-d` path and list the files. If the task came from the Bot reminders list (reminder-bot skill), close it with `rbot done <id> -n "结果：…; 产出：<dest>"`.
