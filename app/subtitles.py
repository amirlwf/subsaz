"""SRT writer: word-by-word captions, single/two/three lines per cue.

Modes:
  single — each cue holds one line (classic short-form / TikTok style).
  two    — each cue holds up to 2 lines (Adobe Premiere style).
  three  — each cue holds up to 3 lines (Premiere roll-up style).
"""
from . import srtout as _legacy

HARD = _legacy.HARD
SOFT = _legacy.SOFT


def fmt(t):
    return _legacy.fmt(t)


def _split_lines(words, max_words=3, max_chars=32, max_gap=0.8):
    """Split words into lines: punctuation-aware, gap-aware, char-budgeted."""
    lines, cur, cur_len = [], [], 0
    for i, w in enumerate(words):
        text = w["word"]
        # char budget: break *before* appending if this word would overflow
        # (but never leave an empty line).
        add = len(text) + (1 if cur else 0)
        if cur and cur_len + add > max_chars:
            lines.append(cur)
            cur, cur_len = [], 0
            add = len(text)
        cur.append(w)
        cur_len += add
        gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 9
        if any(text.endswith(c) for c in HARD):
            lines.append(cur)
            cur, cur_len = [], 0
        elif len(cur) >= max_words + 2:
            lines.append(cur)
            cur, cur_len = [], 0
        elif len(cur) >= max_words:
            soft = any(text.endswith(c) for c in SOFT)
            if soft or gap > 0.3:
                lines.append(cur)
                cur, cur_len = [], 0
        elif gap > max_gap:
            lines.append(cur)
            cur, cur_len = [], 0
    if cur:
        lines.append(cur)
    # merge tiny orphan lines (<2 words) into neighbors
    merged = []
    for line in lines:
        if (merged and len(line) == 1 and len(merged[-1]) < max_words + 1
                and line[0]["start"] - merged[-1][-1]["end"] < 0.5):
            merged[-1].extend(line)
        else:
            merged.append(line)
    return merged


def build_srt(words, max_words=3, max_chars=32, max_gap=0.8, hold=1.0,
              mode="single"):
    """Build SRT text. mode: 'single' (1 line/cue), 'two' (<=2), 'three' (<=3)."""
    lines = _split_lines(words, max_words, max_chars, max_gap)
    step = {"single": 1, "two": 2, "three": 3}.get(mode, 1)
    cues = [lines[i:i + step] for i in range(0, len(lines), step)]
    blocks = []
    for n, cue in enumerate(cues, 1):
        first, last = cue[0][0], cue[-1][-1]
        start = first["start"]
        end = max(last["end"], start + 0.05)
        if n < len(cues):
            end = min(cues[n][0][0]["start"], end + hold)
        text = "\n".join(" ".join(w["word"] for w in ln) for ln in cue)
        blocks.append("%d\n%s --> %s\n%s\n" % (n, fmt(start), fmt(end), text))
    return "\n".join(blocks)
