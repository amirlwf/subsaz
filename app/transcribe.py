"""Transcription pipeline: media -> word-timed SRT.

Self-contained engine with:
- bundled ffmpeg/ffprobe (assets/bin) or system fallback,
- hardware-driven device / compute_type / threads,
- subtitle styles (single / two / three lines, max chars),
- model auto-download check with a clear Persian error.
"""
import os
import sys
import time

from . import normalize
from . import smart
from app import hardware, model_manager
from app import subtitles

VID_EXTS = (".mp4", ".mov", ".mkv", ".webm", ".ts", ".flv", ".wmv",
            ".avi", ".m4v", ".mpg", ".mpeg", ".3gp", ".3g2")
AUD_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma")
ALL_EXTS = VID_EXTS + AUD_EXTS


class CancelledError(Exception):
    """Raised when the user cancels a batch run via cancel_event."""
    pass


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("لغو شد توسط کاربر.")


def _base_dir():
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.isdir(os.path.join(meipass, "assets")):
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tool(name):
    """Bundled binary first (assets/bin), then PATH."""
    bundled = os.path.join(_base_dir(), "assets", "bin", name)
    if os.path.isfile(bundled):
        return bundled
    if os.name == "nt" and not bundled.lower().endswith(".exe"):
        if os.path.isfile(bundled + ".exe"):
            return bundled + ".exe"
    return name


def probe_full(path):
    import json
    import subprocess
    out = subprocess.run(
        [_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "format=duration:stream=width,height,avg_frame_rate",
         "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    w = h = fps = None
    if d.get("streams"):
        s = d["streams"][0]
        w, h = s.get("width"), s.get("height")
        if s.get("avg_frame_rate") and s["avg_frame_rate"] != "0/0":
            num, den = s["avg_frame_rate"].split("/")
            fps = round(float(num) / float(den), 3)
    return {"duration": float(d["format"]["duration"]), "width": w,
            "height": h, "fps": fps or 30.0}


def extract_audio(src, wav):
    import subprocess
    subprocess.run(
        [_tool("ffmpeg"), "-y", "-v", "error", "-i", src,
         "-vn", "-ac", "1", "-ar", "16000", wav],
        check=True, capture_output=True, text=True)


_model_cache = {}


def _get_model(name, device, compute_type, threads):
    key = (name, device, compute_type, threads)
    if key not in _model_cache:
        from faster_whisper import WhisperModel
        _model_cache[key] = WhisperModel(
            name, device=device, compute_type=compute_type,
            cpu_threads=threads)
    return _model_cache[key]


def transcribe(audio, model_name="small", language=None, prompt=None,
               batched=True, threads=8, beam=5, device="auto",
               compute_type="int8"):
    from faster_whisper import BatchedInferencePipeline
    model = _get_model(model_name, device, compute_type, threads)
    kw = dict(language=language, vad_filter=True, word_timestamps=True,
              beam_size=beam, condition_on_previous_text=False)
    if prompt is None and language == "fa":
        prompt = "زیرنویس فارسی با املای درست."
    if prompt:
        kw["initial_prompt"] = prompt
    if batched:
        pipe = BatchedInferencePipeline(model=model)
        kw["batch_size"] = 8
        segments, info = pipe.transcribe(audio, **kw)
    else:
        segments, info = model.transcribe(audio, **kw)
    words = []
    lp_sum, ns_sum, n_seg = 0.0, 0.0, 0
    for seg in segments:
        lp_sum += seg.avg_logprob
        ns_sum += seg.no_speech_prob
        n_seg += 1
        for w in (seg.words or []):
            text = w.word.strip()
            if text:
                words.append({"word": text, "start": w.start, "end": w.end})
    stats = {"avg_logprob": (lp_sum / n_seg) if n_seg else 0.0,
             "no_speech": (ns_sum / n_seg) if n_seg else 0.0}
    return words, info.language, stats


def resolve_model(lang, model, profile=None):
    """Return (model_name, device, compute_type, threads, auto_notes).

    model='auto' picks from hardware; otherwise honors the explicit choice
    but still applies hardware device/compute. Raises ModelDownloadError
    with a Persian message when weights are missing.
    """
    profile = profile or hardware.classify()
    notes = list(profile.get("notes", []))
    if model == "auto":
        rec = hardware.recommend(lang, profile)
        notes.append("مدل پیشنهادی سیستم: %s (%.0fMB)" % (rec["model"], rec["mb"]))
        notes.append(rec["reason_fa"])
        return (rec["model"], rec["device"], rec["compute_type"],
                rec["threads"], notes)
    return model, profile["device"], profile["compute_type"], \
        profile["threads"], notes


def process_file(path, outdir, lang="en", model="auto", words=3, max_chars=32,
                 max_gap=0.8, hold=1.0, mode="single", prompt=None,
                 profile=None, log=print, progress_cb=None,
                 cancel_event=None):
    """Transcribe one media file -> SRT. Returns result dict or None.

    progress_cb(stage) is called with 'audio' / 'transcribe' / 'subtitle'
    so batch UIs can show per-file progress. cancel_event (threading.Event)
    aborts between stages with CancelledError.
    """
    def _prog(stage):
        if progress_cb is not None:
            try:
                progress_cb(stage)
            except Exception:  # noqa: BLE001 — progress must never break run
                pass

    _check_cancel(cancel_event)
    if model != "auto" and not model_manager.is_cached(model):
        raise model_manager.ModelDownloadError(
            "مدل %s دانلود نشده. از بخش «مدل و سیستم» دانلودش کن." % model,
            need_vpn=False)
    base = os.path.splitext(os.path.basename(path))[0]
    t0 = time.time()
    try:
        meta = probe_full(path)
    except Exception:
        meta = {}
    td = os.path.join(os.environ.get("TEMP", "."), "subsaz_tmp")
    os.makedirs(td, exist_ok=True)
    wav = os.path.join(td, "%d_%s.wav" % (os.getpid(), base[:80]))
    _prog("audio")
    _check_cancel(cancel_event)
    extract_audio(path, wav)

    name, device, compute, threads, notes = resolve_model(
        lang, model, profile)
    prof = profile or hardware.classify()
    for n in notes:
        log("   " + n)
    if not model_manager.is_cached(name):
        try:
            os.remove(wav)
        except OSError:
            pass
        raise model_manager.ModelDownloadError(
            "مدل %s روی سیستم نیست. اول دانلودش کن." % name, need_vpn=False)

    beam = 5 if device == "cuda" else (1 if threads <= 4 else 5)

    def run_once(m):
        wl, det, st = transcribe(wav, m, lang, prompt, threads=threads,
                                 beam=beam, device=device,
                                 compute_type=compute)
        normalize.apply(wl, det)
        return wl, det, st

    reran = False
    if model == "auto":
        start = "small" if lang != "fa" else "base"
        # strong rigs jump straight to the recommended model
        if prof["tier"] in (
                "GPU_STRONG", "GPU_MID", "CPU_STRONG"):
            start = name
        _prog("transcribe")
        _check_cancel(cancel_event)
        wl, det, st = run_once(start)
        final, score, snotes = smart.decide(det, wl, st, start)
        for n in snotes:
            log("   " + n)
        if final != start:
            if not model_manager.is_cached(final):
                log("   مدل %s دانلود نشده — با همان %s ادامه می‌دهم." % (final, start))
                final = start
            else:
                reran = True
                _check_cancel(cancel_event)
                wl, det, st = run_once(final)
                score = smart.quality(wl, st)
                log("   final model=%s confidence=%.2f" % (final, score))
    else:
        final = name
        _prog("transcribe")
        _check_cancel(cancel_event)
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

    _prog("subtitle")
    _check_cancel(cancel_event)
    srt_path = os.path.join(outdir, base + ".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(subtitles.build_srt(wl, words, max_chars, max_gap, hold, mode))
    log("   lang=%s words=%d -> %s" % (det, len(wl), os.path.basename(srt_path)))
    log("   done in %.1fs" % (time.time() - t0))
    return {"srt": srt_path, "lang": det, "words": len(wl),
            "secs": time.time() - t0, "model": final,
            "confidence": score, "reran": reran}
