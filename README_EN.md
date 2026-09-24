<p align="center">
  <img src="logo/with-background.png" width="280" alt="SubSaz">
</p>

<h1 align="center">SubSaz (ساب‌ساز) — precise word-by-word subtitles, offline</h1>

<p align="center">
  Drop in a video or audio file, get back an accurate <code>.srt</code>.
  Local transcription with <code>faster-whisper</code> — no API, no upload.
</p>

<p align="center">
  <a href="README.md">⬅ Back</a>
  &nbsp;•&nbsp;
  <a href="README_FA.md">راهنمای فارسی</a>
</p>

## ⬇ Download

From the [Releases](https://github.com/amirlwf/subsaz/releases) page:

| File | What it is |
|---|---|
| `SubSaz-Setup-x.y.z.exe` | Windows installer (Start-menu + desktop shortcut, uninstaller) |
| `SubSaz-portable-win64.zip` | Portable — unzip and run `SubSaz.exe`, no install |
| `SubSaz-cli-win64.zip` | Terminal version (`subsaz-cli`) — batch jobs and scripting, same engine |

> 🇮🇷 If a model download fails, connect to a VPN and retry — model weights
> are hosted on HuggingFace, which is sanctioned. The app tells you this itself.

## 🚀 First run (2 minutes)

1. Open SubSaz (ساب‌ساز).
2. Look at **section 2 — System & model**: the app scans your machine
   (CPU / RAM / NVIDIA GPU) and suggests the best model for it.
3. Press **⬇ Download model** and approve — one-time download, then fully offline.
4. Add files → choose subtitle style → **▶ Build subtitles (SRT)**.

## 🤖 How the auto model pick works

| Your machine | EN | FA | Engine |
|---|---|---|---|
| NVIDIA GPU ≥ 8GB VRAM | `large-v3-turbo` | `large-v3-turbo` | `float16` |
| NVIDIA GPU 4–8GB | `small` | `large-v3-turbo` | `float16` |
| Strong CPU (≥8 threads / ≥16GB RAM) | `small` | `large-v3-turbo` | `int8` |
| Weak CPU | `small` | `base` → auto-upgrade to `turbo` on low confidence | `int8` |

No-GPU machines get the **same accuracy**, just slower. Persian always
settles on the most accurate model; English uses the `small` sweet spot.
You can also pin any model manually (`auto` = hardware pick).

Check from the terminal anytime:

```bat
subsaz-cli --scan
```

## ✨ Subtitle styles

- **single** — 1 line per cue (classic short-form / TikTok style)
- **two** — up to 2 lines per cue, Adobe Premiere style
- **words per line** (1–6), **max characters per line** (20–50)
- **gap** (s) that forces a line break, **hold** (s) that keeps a line
  on screen until the next one starts (no flashing)
- **custom words** prompt — brand/technical names transcribed correctly

Lines break on sentence punctuation first, then on the character budget —
never mid-word.

## 🎞 Formats

Video: `mp4 mov mkv webm ts flv wmv avi m4v mpg mpeg 3gp 3g2`
Audio: `mp3 wav m4a aac flac ogg opus wma`

## ⌨ CLI

```bat
subsaz-cli video.mp4 --lang en
subsaz-cli video.mp4 --lang fa --mode two --max-chars 36
subsaz-cli song.mp3 --lang en --words 2
subsaz-cli --dir C:\clips --lang en
subsaz-cli --scan
subsaz-cli --download-model small
```

The `.exe` ships in `SubSaz-cli-win64.zip` — unzip and run it from that
folder, or add the folder to your `PATH`.

## 🎯 Accuracy details

- Word-level timestamps (`word_timestamps=True`, VAD on)
- Punctuation-aware grouping + character budget + orphan-line merging
- `condition_on_previous_text=False` (no hallucination drift on music/noise)
- Persian normalizer (Arabic→Persian letters, common ASR slips)
- Confidence re-run: a fast model transcribes first; if confidence is low
  the accurate model re-runs automatically

## 🛠 Run from source (developers)

```bat
pip install -r requirements.txt
python gui.py
```

Requires Python 3.11+ and `ffmpeg`/`ffprobe` on PATH
(the packaged app bundles them — only source runs need this).

## 🗂 Project layout

```
app/hardware.py       machine scan + model recommendation
app/model_manager.py  one-time download, resume, VPN error hint
app/transcribe.py     media -> words pipeline
app/subtitles.py      single / two-line SRT builder
app/config.py         persistent settings (%LOCALAPPDATA%/SubSaz)
gui.py                CustomTkinter desktop app
cli.py                terminal interface (same engine)
installer/subsaz.iss Inno Setup script
```

## ⚖ License

MIT — see [LICENSE](LICENSE). Font: [Vazirmatn](https://github.com/rastikerdar/vazirmatn) (OFL).
