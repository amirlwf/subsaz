"""Shared processing runner: media -> word-timed SRT (smart model pick)."""
import os
import time

from asr import extract_audio, transcribe
import srtout
import normalize
import smart


def process_file(path, outdir, lang="en", model="auto", words=3,
                 prompt=None, log=print):
    """Transcribe one media file -> SRT. model='auto' = smart selection.

    Returns dict {srt, lang, words, secs, model, confidence, reran} or None.
    """
    base = os.path.splitext(os.path.basename(path))[0]
    t0 = time.time()
    from asr import probe_full
    meta = probe_full(path)
    td = os.path.join(os.environ.get("TEMP", "."), "subsaz_tmp")
    os.makedirs(td, exist_ok=True)
    wav = os.path.join(td, "%d_%s.wav" % (os.getpid(), base[:80]))
    extract_audio(path, wav)

    def run_once(m):
        wl, det, st = transcribe(wav, m, lang, prompt)
        normalize.apply(wl, det)
        return wl, det, st

    reran = False
    if model == "auto":
        start_model = "small" if lang != "fa" else "base"
        wl, det, st = run_once(start_model)
        final, score, notes = smart.decide(det, wl, st, start_model)
        for n in notes:
            log("   " + n)
        if final != start_model:
            reran = True
            wl, det, st = run_once(final)
            score = smart.quality(wl, st)
            log("   final model=%s confidence=%.2f" % (final, score))
    else:
        final = model
        wl, det, st = run_once(final)
        score = smart.quality(wl, st)
        log("   model=%s confidence=%.2f" % (final, score))
    try:
        os.remove(wav)
    except OSError:
        pass
    if not wl:
        log("   SKIP: no speech")
        return None

    srt_path = os.path.join(outdir, base + ".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srtout.build_srt(wl, words))
    log("   lang=%s words=%d -> %s" % (det, len(wl), os.path.basename(srt_path)))
    log("   done in %.1fs" % (time.time() - t0))
    return {"srt": srt_path, "lang": det, "words": len(wl),
            "secs": time.time() - t0, "model": final,
            "confidence": score, "reran": reran}
