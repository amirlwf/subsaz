"""Benchmark faster-whisper CPU settings on a test clip."""
import subprocess
import sys
import time


def words_from(segments):
    out = []
    for seg in segments:
        for w in (seg.words or []):
            t = w.word.strip()
            if t:
                out.append((t, w.start, w.end))
    return out


def run(tag, model_name, batched, beam, threads, wav):
    from faster_whisper import WhisperModel
    t0 = time.time()
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=threads)
    load = time.time() - t0
    kw = dict(language="en", vad_filter=True, word_timestamps=True,
              beam_size=beam, condition_on_previous_text=False)
    t1 = time.time()
    if batched:
        from faster_whisper import BatchedInferencePipeline
        pipe = BatchedInferencePipeline(model=model)
        segments, info = pipe.transcribe(wav, batch_size=8, **kw)
    else:
        segments, info = model.transcribe(wav, **kw)
    words = words_from(segments)
    dt = time.time() - t1
    text = " ".join(w[0] for w in words)
    print("%-28s asr=%.1fs load=%.1fs words=%d | %s"
          % (tag, dt, load, len(words), text[:70]))


if __name__ == "__main__":
    mp4 = sys.argv[1]
    wav = "bench.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4,
                    "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    run("beam5 thr4 (current)", "small", False, 5, 4, wav)
    run("beam1 thr8", "small", False, 1, 8, wav)
    run("batched beam1 thr8", "small", True, 1, 8, wav)
    run("batched beam5 thr8", "small", True, 5, 8, wav)
