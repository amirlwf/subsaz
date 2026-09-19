# WordSub — precise word-by-word subtitles, offline

Drop in a video or audio file, get back an accurate `.srt`.
Local transcription with `faster-whisper` — no API, no upload.

![WordSub](assets/icon.png)

## Download

From the [Releases](../../releases) page:

| File | What it is |
|---|---|
| `WordSub-Setup-x.y.z.exe` | Windows installer (Start-menu + desktop shortcut, uninstaller) |
| `WordSub-portable-win64.zip` | Portable — unzip and run `WordSub.exe`, no install |

> 🇮🇷 If a model download fails, connect to a VPN and retry — model weights
> are hosted on HuggingFace, which is sanctioned. The app tells you this itself.

## First run (2 minutes)

1. Open WordSub.
2. Look at **section 2 — System & model**: the app scans your machine
   (CPU / RAM / NVIDIA GPU) and suggests the best model for it.
3. Press **⬇ Download model** and approve — one-time download, then fully offline.
4. Add files → choose subtitle style → **▶ Build subtitles (SRT)**.

## How the auto model pick works

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
wordsub-cli --scan
```

## Subtitle styles

- **single** — 1 line per cue (classic short-form / TikTok style)
- **two** — up to 2 lines per cue, Adobe Premiere style
- **words per line** (1–6), **max characters per line** (20–50)
- **gap** (s) that forces a line break, **hold** (s) that keeps a line
  on screen until the next one starts (no flashing)
- **custom words** prompt — brand/technical names transcribed correctly

Lines break on sentence punctuation first, then on the character budget —
never mid-word.

## Formats

Video: `mp4 mov mkv webm ts flv wmv avi m4v mpg mpeg 3gp 3g2`
Audio: `mp3 wav m4a aac flac ogg opus wma`

## CLI

```bat
wordsub-cli video.mp4 --lang en
wordsub-cli video.mp4 --lang fa --mode two --max-chars 36
wordsub-cli song.mp3 --lang en --words 2
wordsub-cli --dir C:\clips --lang en
wordsub-cli --scan
wordsub-cli --download-model small
```

## Accuracy details

- Word-level timestamps (`word_timestamps=True`, VAD on)
- Punctuation-aware grouping + character budget + orphan-line merging
- `condition_on_previous_text=False` (no hallucination drift on music/noise)
- Persian normalizer (Arabic→Persian letters, common ASR slips)
- Confidence re-run: a fast model transcribes first; if confidence is low
  the accurate model re-runs automatically

## Run from source (developers)

```bat
pip install -r requirements.txt
python gui.py
```

Requires Python 3.11+ and `ffmpeg`/`ffprobe` on PATH
(the packaged app bundles them — only source runs need this).

## Project layout

```
app/hardware.py       machine scan + model recommendation
app/model_manager.py  one-time download, resume, VPN error hint
app/transcribe.py     media -> words pipeline
app/subtitles.py      single / two-line SRT builder
app/config.py         persistent settings (%LOCALAPPDATA%/WordSub)
gui.py                CustomTkinter desktop app
cli.py                terminal interface (same engine)
installer/wordsub.iss Inno Setup script
```

## License

MIT — see [LICENSE](LICENSE). Font: [Vazirmatn](https://github.com/rastikerdar/vazirmatn) (OFL).
