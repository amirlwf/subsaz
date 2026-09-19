"""ASR: faster-whisper word-level transcription + ffprobe helpers."""
import json
import subprocess


def probe(path):
    """Return (duration, width, height) of a media file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    w = h = None
    if d.get("streams"):
        w = d["streams"][0].get("width")
        h = d["streams"][0].get("height")
    return float(d["format"]["duration"]), w, h


def probe_full(path):
    """Return dict: duration, width, height, fps of a media file."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "format=duration:stream=width,height,avg_frame_rate", "-of", "json",
         path],
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
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", src,
         "-vn", "-ac", "1", "-ar", "16000", wav],
        check=True, capture_output=True, text=True)


_model_cache = {}


def _get_model(name, threads):
    key = (name, threads)
    if key not in _model_cache:
        from faster_whisper import WhisperModel
        _model_cache[key] = WhisperModel(name, device="auto",
                                         compute_type="int8",
                                         cpu_threads=threads)
    return _model_cache[key]


def transcribe(audio, model_name="small", language=None, prompt=None,
               batched=True, threads=8, beam=5):
    """Return (words, detected_language). words: [{word,start,end}, ...]"""
    from faster_whisper import BatchedInferencePipeline
    model = _get_model(model_name, threads)
    kw = dict(language=language, vad_filter=True, word_timestamps=True,
              beam_size=beam, condition_on_previous_text=False)
    if prompt is None and language == "fa":
        prompt = "زیرنویس فارسی با املای درست."   # steers spelling + ZWNJ
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
    stats = {
        "avg_logprob": (lp_sum / n_seg) if n_seg else 0.0,
        "no_speech": (ns_sum / n_seg) if n_seg else 0.0,
    }
    return words, info.language, stats
