"""Smart model selection: fast model first, re-run with the accurate one
if confidence is low. One measurement pass, no guessing."""

# (speed tier) -> (quality tier) upgrade chain per language
UPGRADE = {
    "en": {"tiny": "small", "base": "small"},
    # FA: base/small are unreliable -> always settle at turbo unless tiny+great
    "fa": {"tiny": "large-v3-turbo", "base": "large-v3-turbo",
           "small": "large-v3-turbo", "medium": "large-v3-turbo"},
}
ACCURATE = {"en": "small", "fa": "large-v3-turbo"}
# FA text from fast models is often confidently wrong -> demand high confidence
THRESHOLD = {"en": 0.75, "fa": 0.90}


def quality(words: list, stats: dict) -> float:
    """0..1 confidence from ASR signals + text sanity checks."""
    if not words:
        return 0.0
    score = 1.0
    lp = stats.get("avg_logprob", 0.0)
    if lp < -1.2:
        score *= 0.25
    elif lp < -0.7:
        score *= 0.55
    elif lp < -0.45:
        score *= 0.8
    ns = stats.get("no_speech", 0.0)
    if ns > 0.75:
        score *= 0.3
    elif ns > 0.5:
        score *= 0.7
    # garbled-text heuristics
    n = len(words)
    chars = sum(len(w["word"]) for w in words)
    if chars / max(n, 1) < 1.6:          # broken into tiny fragments
        score *= 0.6
    joined = " ".join(w["word"] for w in words)
    if len(joined) >= 40:
        letters = sum(c.isalpha() for c in joined)
        ratio = letters / len(joined)
        if ratio < 0.55:                  # lots of junk symbols
            score *= 0.6
    repeated = len(joined.split()) - len(set(joined.lower().split()))
    if n >= 8 and repeated / n > 0.5:     # hallucination loop
        score *= 0.3
    return max(0.0, min(1.0, score))


def needs_upgrade(model: str, lang: str, score: float) -> bool:
    up = UPGRADE.get(lang, {}).get(model)
    if not up:
        return False
    return score < THRESHOLD.get(lang, 0.75)


def decide(lang: str, words: list, stats: dict, model: str):
    """Returns (final_model, words, stats, notes:list)."""
    notes = []
    score = quality(words, stats)
    notes.append("model=%s confidence=%.2f" % (model, score))
    if needs_upgrade(model, lang, score):
        better = UPGRADE[lang][model]
        notes.append("low confidence -> re-running with %s" % better)
        return better, score, notes
    return model, score, notes
