---
name: video-summary
description: Screenshot-driven video notes. The agent itself looks at the video's stable keyframes (slides, code, diagrams, blackboard) and writes an image-text note (图文笔记) that turns a lecture's video stream into a picture-and-text stream, with images placed where the speaker refers to them and a cover image. Use for lectures, tutorials and talks where what's on screen matters, when the user asks for 图文笔记 / 截图笔记 / video-summary / "把视频变成图文", or gives a Bilibili/YouTube link or local video and wants to learn from the slides. For a fast, text-only batch of a whole course use voice-summary instead.
---

# video-summary

Compared with **voice-summary** (the LLM reads only the subtitles, and frames are attached per time chunk),
here **you look at the frames yourself**. You decide which images carry information and write each section
from what is on screen plus what the speaker says while it is shown.

Tools live in this skill's `scripts/`. Run them with the VideoSummary venv, which has cv2:
`PY=~/project/VideoSummary/.venv/bin/python`. Run shell loops over frame lists in **bash** (`bash -c '…'`):
zsh doesn't word-split an unquoted `$VAR`. Bilibili login cookies: `~/project/VideoSummary/cookies.txt`
(refresh from Chrome as voice-summary does if subtitles say "login required").

## Workflow

1. **Prepare**: `$PY scripts/prep.py <url | local.mp4> [--srt subs.srt]`
   - If voice-summary already downloaded the video, pass the local mp4 from `~/project/VideoSummary/output/<slug>/<id>/downloads/` to avoid a second download.
   - Output goes to `/Volumes/AppStorage/Scratch/video-summary/<id>/`:
     - `sheets/` contact sheets
     - `frames/kNNN_hhmmss.jpg` the keyframes
     - `keyframes.json` each keyframe with `text`, the transcript spoken while that frame was on screen
     - `transcript.md` the full transcript
   - A 100-minute lecture yields about 100 keyframes (about 1 minute of CPU).
   - If `keyframes` is 0 or under 5 for a long video, the screen barely changes (podcast, talking head). Go to step 2 with mode = text-first.

2. **Decide whether images matter.** Look at 2–3 contact sheets.
   - **Image-rich** (slides, code, diagrams, demos, blackboard): make a full 图文笔记.
   - **Text-first** (talking head, interview, blog-style monologue, screen barely changes): write a text note with only a cover image and at most 1–3 frames that really add something. Don't pad with faces.
   - Tell the user which mode you picked, and why, in one line.

3. **Triage.** First find the crop box. Open one frame and note where the slide area sits (fractions of width/height).
   - Example, jyy lectures (1280x410, camera left, slides right): slides `0.43 0 1 1`; terminal-pane demos `0.713 0 1 1`; blackboard `0.02 0.08 0.42 0.84`.
   - Then run `$PY scripts/stack.py <work> x0 y0 x1 y1`. It crops every keyframe and stacks 4 per image at full resolution in `<work>/stacks/`. Triage from the stacks: contact sheets are only for a quick overview, because slide text is unreadable at thumbnail size.

   For each `kNNN`, decide *keep*, *drop* or *merge*:
   - drop: faces, transitions, blank screens, and near-duplicates (keep the most complete build of a slide)
   - merge: runs of the same slide
   Write the keep list with a 3–6-word label each. A typical lecture keeps 25–50 slide/screen frames.
   Blackboard and live-demo crops count separately, on top of that budget. Keep them when the board or demo carries content.

4. **Reverse check (speech → image).** Grep `transcript.md` for spoken references to the screen:
   `这张图|看这里|如图|这个代码|这里写着|大家看|你看|你们看|我们来看|看一下|看一眼|课件上|的主页|屏幕上|as you can see|this slide`.
   - Judge each hit by hand: 你看 is often filler. For each real reference, the frame on screen at that moment must be in the keep list. Add it if triage dropped it.
   - Report the hit count, how many were real, and how many frames were added.

5. **Look at kept frames at full resolution** (open the `frames/*.jpg` files), in batches of about 8. Read the text on the slide exactly; don't guess small text.
   - If the layout is camera + slides side by side, crop to the slide area:
     `$PY scripts/crop.py x0 y0 x1 y1 frames/k0*.jpg -o <note_dir>/images/<name>` (fractions of width/height).
   - Keep the camera when it shows something: blackboard writing, a live demo, a gesture at the screen.
     For a second crop of the same frame, add `--suffix _board`, which writes `k057_…_board.jpg` next to the slide crop.
   - Frames caught mid-transition or covered by an overlay: use a neighbouring keyframe of the same slide, or describe the slide in text and say it's partial.

6. **Write the note** at `<dest>/<NN-title>.md`, with images in `<dest>/images/<NN-title>/`, in transcript order.
   Format, so the PDF renders cleanly:
   - no YAML front matter; one `# title` H1
   - images as `![](images/…/kNNN_….jpg)` with an **empty** alt text, followed on the next line by the caption `*kNNN · hh:mm:ss · what it shows*`

   Content:
   - Top: title, source link, duration, **cover image** (the most representative slide, or the title slide), a 3–5-line 导读 (what the talk argues), and a table of contents.
   - One section per topic, not per frame. A section is:
     - heading
     - image(s) with a caption `*kNNN · hh:mm:ss*`
     - the explanation: what the slide says **plus** what the speaker adds (examples, stories, opinions, jokes worth keeping). Mark the speaker's opinions as theirs.
   - Code on slides: transcribe it into a code block under the image, so it can be copied.
   - Diagrams: explain how to read them (boxes, arrows, what flows where).
   - Keep the sources apart: 讲者说的 is plain prose. Slide material the speaker flags as not their own view (e.g. jyy marks AI-written lines with ✦) or only shows without discussing gets a marker, e.g. `（课件 ✦ 补充）`, **at each place it's used**, not just once in a caption.
   - End with: 要点回顾 (5–10 bullets), and 可以继续看 (links or terms mentioned).
   - **Oral-only pass**: after the draft, scan `transcript.md` block by block for substance that never appeared on screen (stories, live debates, trade-offs, asides with a point). Add what's missing to the right section. Slides-first notes tend to drop these.
   - Fix obvious subtitle recognition errors using the slides and context (e.g. "expect" → spec when the board says spec). If you're unsure, keep the original in brackets.
   - Language: Chinese. Keep technical terms in English where the speaker does.

7. **Render and check**: `$PY scripts/render_pdf.py <dest>/<NN-title>.md` writes the PDF next to it.
   - Check it with `pdfinfo <pdf>` (page count) and `pdftoppm -png -r 50 -f 1 -l 3 <pdf> <work>/pdfcheck`, then look at a page or two.
   - Verify every image link resolves and every copied image is used.
   - Report: paths, mode, frames kept out of total, reverse-check numbers, and anything unreadable.

## Rules
- Every image must earn its place: it shows something the text alone can't. No two images of the same slide, and no talking-head frames unless something is happening.
- Faithfulness: slide text is quoted as shown. Speech is summarized from `keyframes.json`/`transcript.md`, not invented. If subtitles are missing, say so and write from the slides only.
- Don't copy the whole transcript. A section is typically 80–250 characters of prose plus bullets.
- Heavy files (video, frames) stay on `/Volumes/AppStorage`. Only the final note, its images and the PDF go to `<dest>`.
- When this task comes from the Bot reminders list, close it with `rbot done <id> -n "结果：…; 产出：…"`.

## Comparing with voice-summary
To judge which skill works better on a given video, produce both notes for the same video, then use the darwin-skill idea: 3 independent judge agents each read **both** notes in one pass (A/B order shuffled, skill names hidden) and vote better/worse/tie on faithfulness, coverage of on-screen content, image usefulness, and readability. Majority wins. Absolute scores are too noisy to compare.
