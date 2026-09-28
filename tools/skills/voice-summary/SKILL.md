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
- Collections/playlists get expanded. Videos under 10 minutes are skipped (`--min-minutes`). Videos that already have a summary are skipped too, so re-running resumes an interrupted batch.
- Bilibili subtitles need login. If `cookies.txt` has expired, vsum re-exports it from Chrome, keeping only bilibili.com cookies. If that fails, ask the user to log in to Bilibili in Chrome.
- Never call `video_summary_app.py` directly with a shared `-o` directory for several videos. It reuses local files by **fuzzy keyword match**, so lectures of one course pick up each other's video and subtitles and overwrite each other's summary. vsum gives every video its own `-o <out>/<video id>/`, which avoids this.
- To re-export only (no downloading, no LLM): `python export_notes.py output/<slug> <dest>`.

## Running it
- It takes about 15 minutes per 100-minute lecture, so run it in the background (`nohup … > output/<slug>.log 2>&1 &`) and poll the log. Report which videos finished or failed.
- Check free space first with `df -h /Volumes/AppStorage`: each lecture's video is about 150 MB and its frames about 12 MB.
- The summary prompt is `BASE_SYSTEM_PROMPT` in `video_summary_app.py`. Current version is v3 (2026-09-28): each chunk is rebuilt as the speaker's argument, with a logic chain. Links the model supplies itself are marked **（整理者串联）**. No invented formulas, no audience persona, no 记忆钩子 sections, and ASR errors are fixed. v3 beat the original prompt 3–0 in a blind test on jyy lecture 02.
- After each video, `outline.py` adds a **## 全课主线** section at the top: a 6–12-step argument chain across the whole lecture, each step citing 第 N 部分. Rerun it alone with `python outline.py <summary.md> --force`.
- vsum downloads subtitles itself before calling the app, because the app sometimes gets only danmaku and crashes. If a video has no subtitles at all, it still fails; say so and never invent a transcript.

## After
Tell the user the `-d` path and list the files. If the task came from the Bot reminders list (reminder-bot skill), close it with `rbot done <id> -n "结果：…; 产出：<dest>"`.
