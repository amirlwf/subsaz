"""BiDi helpers for mixed Persian/English/number text.

Why this module exists: Tk 8.6 applies Arabic *shaping* but has **no bidi
engine** — it paints every string in logical (storage) order, left to right.
Measured on this project's own widgets (pixel probe of a tk.Text / tk.Label):

* «سلام» was drawn with the first letter on the left, i.e. mirrored;
* «سلام ZZZ» drew سلام leftmost while «ZZZ سلام» drew ZZZ leftmost, so
  runs inside a line were never reordered at all;
* U+2066/U+2069 isolates (the previous "fix") are *drawn as tofu boxes*,
  because Vazirmatn has no glyph for them.

So Persian sentences came out backwards and Latin words embedded in Persian
landed on the wrong side. display() therefore does the work a bidi-aware
renderer would do for us:

1. reshape Arabic letters to their presentation forms (U+FE70..U+FEFC /
   U+FB50..U+FDFF) so the glyph shapes survive reordering, then
2. reorder the string to visual order with the Unicode bidi algorithm.

The result is handed to Tk as-is: a left-to-right painter now draws exactly
what a correct renderer would draw.

SRT/engine/file text is NEVER modified — apply this only at widget level.
Idempotent: text that already carries presentation forms is returned as is,
so double-wrapping a widget string cannot garble it.
"""
import re

try:  # runtime deps (see requirements.txt); degrade to logical order
    import arabic_reshaper as _arabic_reshaper
    from bidi.algorithm import get_display as _bidi_get_display
except Exception:  # noqa: BLE001 — optional, display() falls back
    _arabic_reshaper = None
    _bidi_get_display = None

# The UI must know when it is running WITHOUT these: display() then falls
# back to logical order, so Persian renders mirrored / letters unjoined.
DISPLAY_READY = _arabic_reshaper is not None and _bidi_get_display is not None

# Directional isolates / marks — stripped before processing so old
# persisted strings (and any leftover control chars) never reach Tk.
LRI = "\u2066"
RLI = "\u2067"
PDI = "\u2069"
LRM = "\u200e"
RLM = "\u200f"
_STRIP_RE = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")

# Any strong RTL char: Hebrew, Arabic, Persian extensions, presentation forms.
_RTL_RE = re.compile(
    "[\u0591-\u07ff\ufb1d-\ufdfd\ufe70-\ufefc\U00010e60-\U00010e7f]")

# Blocks that hold Arabic-script *letters* we can reshape.
_AR_BLOCK_RE = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")

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

_BASE_DIR = {"rtl": "R", "ltr": "L", "auto": None}


def contains_rtl(text: str) -> bool:
    """True when the text has any strong right-to-left character."""
    return bool(text and _RTL_RE.search(text))


def _has_arabic_letters(text: str) -> bool:
    """True when there is at least one reshappable Arabic-script letter."""
    for ch in text:
        if ch.isalpha() and _AR_BLOCK_RE.match(ch):
            return True
    return False


def _has_presentation_forms(text: str) -> bool:
    """True when the text already went through the reshaper."""
    for ch in text:
        o = ord(ch)
        if 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
            return True
    return False


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
    """Return a Tk-display-safe (visual order) string for mixed text.

    - Pure LTR/neutral text is returned unchanged.
    - Arabic letters are reshaped, then the line is reordered to visual
      order, so a dumb left-to-right painter draws it correctly.
    - base_dir forces the paragraph direction («rtl»/«ltr»), «auto» takes
      it from the first strong character.
    - Idempotent: a string that already carries presentation forms is
      returned untouched, so applying it twice is harmless.
    - The SRT/engine text is NEVER modified — apply only at widget level.
    """
    if not text:
        return text
    clean = _STRIP_RE.sub("", str(text))
    if base_dir == "ltr":
        return clean
    if not contains_rtl(clean):
        return clean
    # Nothing reshappable (Hebrew/digits only) or already display-ordered.
    if not _has_arabic_letters(clean) or _has_presentation_forms(clean):
        return clean
    if _arabic_reshaper is None or _bidi_get_display is None:
        return clean
    try:
        shaped = _arabic_reshaper.reshape(clean)
        out = _bidi_get_display(shaped, base_dir=_BASE_DIR.get(base_dir))
        return out if isinstance(out, str) else clean
    except Exception:  # noqa: BLE001 — a bad string must never kill the UI
        return clean


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
