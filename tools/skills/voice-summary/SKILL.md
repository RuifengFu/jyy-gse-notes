---
name: voice-summary
description: Subtitle-driven video notes with the local VideoSummary tool — the LLM reads only the subtitles/transcript. Default output is a short topic-based note per video (5–9 topic sections, a structure diagram as table of contents, simplified technical Chinese, optional screenshots), plus a timestamped full transcript and a PDF, for Bilibili/YouTube videos or whole collections. Use when the user asks for voice-summary / 语音摘要 / 字幕总结 / 课程笔记, wants a fast, cheap batch of a whole course, or asks to 转文字稿. For image-heavy lectures where the agent itself should look at slides, prefer the video-summary skill.
---

# voice-summary

Tool: `~/project/VideoSummary` (Python venv at `.venv`; LLM = Claude Sonnet via `claude -p` (subscription, no DeepSeek tokens; `--llm deepseek` or env `VSUM_LLM=deepseek` switches back; `VSUM_CLAUDE_MODEL` picks the model); Bilibili AI subtitles via `cookies.txt`).

## How the default (topic) flow works

`vsum.py` → downloads subtitles only (no video, no audio: Bilibili AI subtitles are already text) → `topic_notes.py`:

1. **Outline pass.** The model reads the whole transcript once and returns JSON: 5–9 contiguous topic sections (title, start time, one-sentence claim, relation to the previous section, the *topics* this section owns), a term list with ASR corrections (`sure: false` for names guessed from sound), and course admin items.
   Every topic belongs to exactly one section. This is what removes the overlap. The topic list is ownership, not a content list.
2. **Section pass** (6 in parallel). Body is a **pyramid** (the user's rule: every outer level summarizes the level below, so a reader can stop at any depth and still have the core): heading = the section's claim; level 1 = 2–5 points, each a **bold conclusion sentence** + one plain sentence with the main reason; level 2 = ≤6 pieces of evidence per point (a story is one item, its steps go to level 3); any item with children starts with a bold summary. Each section reads only its own transcript slice, sees the full outline, and must write *all* substantive content of that slice (claims and the speaker's reasons, examples, numbers, named articles/projects/tools, demo results, advice), skipping only filler and topics owned by other sections. Budget ~110 chars per minute (500–2600). It also returns the references it mentions, and 0–2 screenshot timestamps (used only with `--shots`, which downloads a ≤1280-px video).
3. **Coverage pass.** The model compares the slice with the draft, lists what's missing, inserts it under the point it supports, then does a separate scan for quotable lines (jokes, roasts, inner monologues) that are missing or only paraphrased (a result shorter than 90% of the draft is rejected). The log prints `补漏 N 条`.
4. **STC repair.** The simplified-technical-Chinese checker (`/Volumes/AppStorage/project/skills/simplified-technical-chinese/tools/check.py`, override with env `STC_CHECK`) checks each section; flagged sentences go back to the model once. The log prints `STC 必须项 N→M`.
5. **Assemble.** `renest()` normalizes list indentation to 4 spaces and `punct()` puts a full stop between bold claim and reason; the log prints `第 1 层 N 条其中结论句 M，K 层`. Title, one-line claim, `toc.svg` structure diagram (fits on PDF page 1), a table of section claims with time links into the video, the sections, 提到的资料, 课程事务, 术语表. Then a PDF (pandoc + Chrome).

Why, with numbers (2026-11-03, `eval_notes.py`, Claude Sonnet as judge; 08 = dev lecture, the other 7 held out and run once):

| per lecture, avg | body chars | core recall | all-fact recall | repeated facts | jokes kept with punchline |
|---|---|---|---|---|---|
| `--legacy` (chunk summaries + outline), 01–08 | ~39k | 99.7% | 99.3% | ~9% | 97% |
| topic v1 (3–6 points per section), 03/05/07/08 | ~7.7k | 79% | 68% | ~1% | – |
| topic v2 (write all content + coverage pass), 01–08 | ~15.2k | 97.8% | 96.2% | 0.6% | 77% (held out) |
| topic v3 (DeepSeek, flat bullets + 要点 line), 01–08 | ~17.1k | 97.9% | 97.2% | 0.8% | 91% |
| topic v4 (current: pyramid + Claude Sonnet), 02/03/05/07/08 | ~18.6k | 99.4% | 98.6% | 0.8% | 90% |

v4 skim test (2026-11-08, `output/eval/skim.py`: keep only title, one-liner, headings and level-1 lines, then score core recall): v4 avg 54% (55/52/57/50/55) vs v3 48% (54/64/44/38/40) at similar length (~2.4k chars). A first v4 with bold-only level 1 and no reason sentence scored 38–42%, worse than v3: the outer layer needs the reason, not just the claim. Claude also dropped jokes until the coverage pass got its own quote scan (08: 79% → 86%).

v1 was short but dropped reasons, named sources, demo results and side remarks. v2 kept the facts but flattened or dropped about a quarter of the jokes. The user wants the jokes kept so the notes are fun to read. v3 writes each joke, roast or funny comparison as its own bullet (**玩笑** / **吐槽** / **自嘲**) with the speaker's words in 「」. The STC rules apply to narration, not to the quotes. `topic_notes_v2.py` / `topic_notes_v3.py` are frozen v2 / v3.

## Evaluating a change to the prompts

Never judge a prompt change by reading one note. Run `eval_notes.py --humor` (see its docstring): it extracts facts from the transcript in fixed 10-minute windows with Claude (`claude -p --model sonnet`; since v4 the generator is also Claude, so self-preference bias is possible: spot-check verdicts), then judges each note version for recall (core / detail / aside) and for facts repeated across sections. `--humor` also extracts the speaker's jokes per window and checks whether each note keeps the punchline. Facts are cached per lecture in `-w <dir>/<label>/`, so every version is scored against the same list. Tune on one lecture; confirm on at least 3 others you didn't look at. For reading-experience changes also run the skim test (`output/eval/run_v4.sh` shows how). Spot-check ~15 judge verdicts by hand. The 2026-11-02 run is in `~/project/VideoSummary/output/eval/` (`work/*.table`).

## One command

```bash
cd ~/project/VideoSummary && source .venv/bin/activate
python vsum.py <video-or-collection-url>... -o output/<slug> -d <dest> [--speaker "姓名（课程）"]
```

Output in `<dest>`:
```
笔记/NN-标题.md        the note; images in 笔记/images/NN-标题/ (toc.svg + screenshots)
PDF/NN-标题.pdf        the note as PDF
原文/NN-标题.md        full transcript, paragraphs with [hh:mm:ss] timestamps
```

- `-o`: intermediate files (subtitles, video). Keep it relative to the repo, so it stays on the external drive.
- Default: subtitles only. The user said the notes need no video content, so do not download video unless asked.
- `--shots`: also download a ≤1280-px video and add 0–2 screenshots per section. Use it only when the user asks for screenshots.
- `--legacy`: the old chunk-by-chunk flow (摘要/ 原文/ PDF/). Use it only if the user asks for the long version.
- Collections get expanded; videos under 10 minutes are skipped (`--min-minutes`). Videos whose `笔记/<name>.md` exists are skipped, so re-running resumes a batch.
- One video only, or re-render after editing prompts: `python topic_notes.py <srt> --title <标题> --num NN --name NN-标题 --url <url> [--video <mp4>] -o <dest>/笔记`. Model output is cached in `<dest>/笔记/.cache/<name>/`, so a re-run without `--force` costs nothing and only redoes screenshots, the diagram and the PDF. `--force` asks the model again.

## Running it
- About 2–3 minutes per 90-minute lecture, almost all of it model time. With `--shots`, the video download is the slow part: Bilibili sometimes answers HTTP 567 (rate limit). vsum retries with exponential backoff. If the video still fails, the note is written without screenshots.
- Activate `.venv` first. Otherwise the Homebrew `yt-dlp` runs, and it is too old for Bilibili (HTTP 412). Run long batches in the background (`nohup … > output/<slug>.log 2>&1 &`) and tell the user where the log is. For `--legacy` runs, `python progress.py -w` shows a progress bar.
- Only with `--llm deepseek` / `--legacy`: `~/.zshrc` exports an empty `DEEPSEEK_API_KEY`; run with `env -u DEEPSEEK_API_KEY`.
- `--speaker` also goes into the outline prompt (the prompts no longer assume a software-engineering course); always pass it.
- No subtitles on Bilibili? First tell the two cases apart: vsum asks `api.bilibili.com/x/web-interface/nav` whether `cookies.txt` is still logged in. Logged in + no subs = the video has none (burned-in subs are common in reposts); do not tell the user to log in again.
  Then (1) look for the original upload (e.g. YouTube) with manual subs: `yt-dlp --skip-download --write-subs --sub-langs zh-Hans,en --sub-format srt`; or (2) transcribe locally with Qwen3-ASR (`~/project/ASR-models/Qwen3-ASR-1.7B`: download audio as 16 kHz mono wav, `.venv/bin/python bench_offline.py <wav> --batch 4 --prompt "<names, terms>"`, srt in `results/`; ~9× real time, 51 min in 5.5 min; English audio works, the note is still Chinese). Run `topic_notes.py` on that srt, write the transcript with `export_notes.transcript_md`, and tell the user which source you used.
- Bilibili AI subtitles need login. If `--list-subs` shows only `danmaku`, `cookies.txt` has expired. vsum re-exports it from Chrome (bilibili.com cookies only). If that fails, ask the user to log in to Bilibili in Chrome.
- `vsum.py` itself stops on a video without subtitles; use the fallbacks above. Never invent a transcript.
- With `--shots`, check free space with `df -h /Volumes/AppStorage`. One lecture video at 1280 px is about 130 MB.

## Check before you hand it over
1. Open the note. Read the section table and 2 sections. Look for repeated content between sections and for terms marked `（拼写待确认）`.
2. Look at page 1 of the PDF (`pdftoppm -png -r 60 -f 1 -l 1`, then Read the png). Page 1 must hold the title and the whole structure diagram. With `--shots`, also look at 2–3 screenshots.
3. Tell the user the `<dest>` path, the files, body length and the STC numbers from the log.

If the task came from the Bot reminders list (reminder-bot skill), close it with `rbot done <id> -n "结果：…; 产出：<dest>"`.
