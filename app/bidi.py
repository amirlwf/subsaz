"""BiDi helpers for mixed Persian/English/number text (stdlib only).

Problem: Tk/CTk widgets use a simple BiDi rendering where a Latin or
number run inside a Persian line can jump to the wrong side while typing
or in the live preview (e.g. «قسمت 12» or «سلام Hello تست»).

SRT files on disk always stay in *logical* order (correct for players).
These helpers produce a *display* string with Unicode isolates so Tk
renders the same logical text correctly. Idempotent: calling display()
twice does not stack controls.
"""
import re

# Directional isolates / marks (all invisible, zero-width)
LRI = "\u2066"  # left-to-right isolate (wrap English / numbers)
RLI = "\u2067"  # right-to-left isolate (wrap whole FA line)
PDI = "\u2069"  # pop directional isolate
LRM = "\u200e"
RLM = "\u200f"
_FS = "\u2060"  # word joiner (unused, kept for reference)

# Strip set — removed before (re-)applying so display() is idempotent.
_STRIP_RE = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# Any strong RTL char: Hebrew, Arabic, Persian extensions, presentation forms.
_RTL_RE = re.compile(
    "[\u0591-\u07ff\ufb1d-\ufdfd\ufe70-\ufefc\U00010e60-\U00010e7f]")

# Latin/number runs that must stay LTR inside an RTL line:
# words, brands (WordLab), decimals, time-like 00:01, paths, @handles.
_LTR_RUN = re.compile(
    r"[A-Za-z0-9\u00c0-\u00ff]+(?:[._\-/@:][A-Za-z0-9\u00c0-\u00ff]+)*")

# Persian + Arabic-Indic digits -> ASCII (for numeric settings typed
# with a Persian keyboard, e.g. «۳» or «۰٫۸»).
_FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_EN_DIGITS = "0123456789"
_DIGIT_MAP = {ord(f): e for f, e in zip(_FA_DIGITS, _EN_DIGITS)}
_DIGIT_MAP.update({ord(a): e for a, e in zip(_AR_DIGITS, _EN_DIGITS)})
_DIGIT_MAP.update({
    ord("٫"): ".",  # Arabic decimal separator
    ord("٬"): "",   # thousands separator -> drop
    ord("٪"): "%",
})


def contains_rtl(text: str) -> bool:
    """True when the text has any strong right-to-left character."""
    return bool(text and _RTL_RE.search(text))


def en_digits(text: str) -> str:
    """Convert Persian/Arabic digits to ASCII («۳» -> «3», «۰٫۸» -> «0.8»)."""
    if not text:
        return text
    return str(text).translate(_DIGIT_MAP)


def parse_int(text, default):
    """Parse an int setting tolerating Persian digits; fallback= default."""
    try:
        return int(en_digits(str(text)).strip())
    except (ValueError, TypeError):
        return default


def parse_float(text, default):
    """Parse a float setting tolerating Persian digits; fallback= default."""
    try:
        return float(en_digits(str(text)).strip())
    except (ValueError, TypeError):
        return default


def display(text: str, base_dir: str = "auto") -> str:
    """Return a Tk-display-safe string for mixed-direction text.

    - Pure LTR/neutral text is returned unchanged.
    - RTL lines get Latin/number runs wrapped in LRI...PDI and the
      whole line wrapped in RLI...PDI so numbers don't jump sides.
    - The SRT/engine text is NEVER modified — apply only at widget level.
    """
    if not text:
        return text
    clean = _STRIP_RE.sub("", text)
    if base_dir == "ltr":
        return clean
    if base_dir == "auto" and not contains_rtl(clean):
        return clean
    wrapped = _LTR_RUN.sub(lambda m: LRI + m.group(0) + PDI, clean)
    return RLI + wrapped + PDI


def display_cue(lines, lang: str = "fa") -> str:
    """Render preview cue lines (list of word-dict lines) for Tk display.

    Each line is joined logically then passed through display().
    File output must keep using plain " ".join — never this function.
    """
    rendered = []
    for ln in lines:
        logical = " ".join(w["word"] for w in ln)
        if lang == "fa" or contains_rtl(logical):
            rendered.append(display(logical, base_dir="rtl"))
        else:
            rendered.append(logical)
    return "\n".join(rendered)
