"""SRT writer: short-form word-by-word lines (CapCut-style grouping)."""

HARD = ".!?…؟。"      # always break the line after these
SOFT = ",;:،؛"        # prefer breaking after these
MAX_LEN = 28          # chars per line guard


def fmt(t):
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d,%03d" % (h, m, s, cs)


def group(words, max_words=3, max_gap=0.8):
    """Split words into caption lines: punctuation-aware, gap-aware."""
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = w["word"]
        gap = (words[i + 1]["start"] - w["end"]) if i + 1 < len(words) else 9
        if any(text.endswith(c) for c in HARD):
            lines.append(cur); cur = []
        elif len(cur) >= max_words + 2:
            lines.append(cur); cur = []
        elif len(cur) >= max_words:
            soft = any(text.endswith(c) for c in SOFT)
            if soft or gap > 0.3:
                lines.append(cur); cur = []
        elif gap > max_gap:
            lines.append(cur); cur = []
    if cur:
        lines.append(cur)
    # merge tiny orphan lines (<2 words) into neighbors
    merged = []
    for line in lines:
        if merged and len(line) == 1 and len(merged[-1]) < max_words + 1 \
                and line[0]["start"] - merged[-1][-1]["end"] < 0.5:
            merged[-1].extend(line)
        else:
            merged.append(line)
    return merged


def build_srt(words, max_words=3, hold=1.0):
    lines = group(words, max_words)
    blocks = []
    for n, line in enumerate(lines, 1):
        start = line[0]["start"]
        end = max(line[-1]["end"], start + 0.05)
        # hold until next line starts (cap at +hold) so lines don't flash
        if n < len(lines):
            end = min(lines[n][0]["start"], end + hold)
        text = " ".join(w["word"] for w in line)
        blocks.append("%d\n%s --> %s\n%s\n" % (n, fmt(start), fmt(end), text))
    return "\n".join(blocks)
