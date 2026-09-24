"""Normalizer: fix common Persian/Arabic-script ASR slips + digits."""
import re

# Arabic letter -> Persian letter
_AR2FA = {"ي": "ی", "ك": "ک", "ة": "ه", "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا"}

# word-level fixes seen in Whisper FA output (applied via regex, whole words)
_WORD_FIX = {
    "زرنویس": "زیرنویس",
    "زبرنویس": "زیرنویس",
    "دقات": "دقت",
    "دقاته": "دقت",
    "عبزار": "ابزار",
    "ابزار": "ابزار",   # keep (no-op anchor)
}

_DIGIT_FA = "۰۱۲۳۴۵۶۷۸۹"


def fix_text(text: str, lang: str) -> str:
    if not text:
        return text
    if lang == "fa":
        for ar, fa in _AR2FA.items():
            text = text.replace(ar, fa)
        for wrong, right in _WORD_FIX.items():
            if wrong != right:
                text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text)
    return text


def fa_digits(text: str) -> str:
    return text.translate(str.maketrans("0123456789", _DIGIT_FA))


def apply(words: list, lang: str, to_fa_digits: bool = False) -> list:
    """Normalize word dicts in place-safe way; returns same list.

    to_fa_digits was previously named `fa_digits`, which shadowed the
    module-level fa_digits() function and crashed with TypeError as soon
    as a caller passed True for a Persian transcript.

    to_fa_digits is opt-in and currently has no production caller: the SRT
    keeps ASCII digits on purpose so numbers stay searchable and editable
    in editors/Premiere. Pass True if a Persian-digit style is ever wanted.
    """
    for w in words:
        t = fix_text(w["word"], lang)
        if to_fa_digits and lang == "fa":
            t = fa_digits(t)
        w["word"] = t
    return words
