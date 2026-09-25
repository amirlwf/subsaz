"""SubSaz test suite: engine + WebView frontend.

Run from repo root:  python tests/test_all.py
The only UI is webui.py + the TypeScript frontend in web/ (no Tk), so the
frontend is covered by TestWebUIContract instead of widget tests.
"""
import math
import os
import re
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as app_config
from app import hardware
from app import model_manager
from app import normalize
from app import smart
from app import subtitles as subs
from app import transcribe as engine


def make_words(text, step=0.30, dur=0.24):
    words, t = [], 0.0
    for w in text.split():
        words.append({"word": w, "start": round(t, 2),
                      "end": round(t + dur, 2)})
        t += step
    return words


SAMPLE_EN = ("Hello! This is a live preview, showing exactly how your "
             "captions will roll on the video screen.")
SAMPLE_FA = ("سلام! این یک پیش‌نمایش زنده است، و دقیقاً نشان می‌دهد "
             "زیرنویس شما چطور روی صفحه ویدیو می‌آید.")


def parse_cues(srt):
    cues = []
    for block in srt.strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(\S+) --> (\S+)", lines[1])
        if m:
            cues.append((m.group(1), m.group(2), lines[2:]))
    return cues


def to_secs(ts):
    h, m, rest = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))


class TestSubtitles(unittest.TestCase):
    def test_modes_pack_correctly(self):
        words = make_words(SAMPLE_EN)
        for mode, step in (("single", 1), ("two", 2), ("three", 3)):
            out = subs.build_srt(words, 3, 32, 0.8, 1.0, mode)
            cues = parse_cues(out)
            nlines = len(subs._split_lines(words, 3, 32, 0.8))
            self.assertEqual(len(cues), math.ceil(nlines / step), mode)
            for _s, _e, text in cues:
                self.assertTrue(1 <= len(text) <= step, (mode, text))

    def test_unknown_mode_falls_back_to_single(self):
        words = make_words(SAMPLE_EN)
        self.assertEqual(subs.build_srt(words, 3, 32, 0.8, 1.0, "bogus"),
                         subs.build_srt(words, 3, 32, 0.8, 1.0, "single"))

    def test_char_budget_and_no_midword_split(self):
        words = make_words(SAMPLE_EN + " " + SAMPLE_FA)
        for mode in ("single", "two", "three"):
            for _s, _e, text in parse_cues(
                    subs.build_srt(words, 2, 24, 0.8, 1.0, mode)):
                for ln in text:
                    self.assertLessEqual(len(ln), 24, ln)
                    self.assertFalse(ln.startswith(" "), ln)
                    self.assertFalse(ln.endswith(" "), ln)

    def test_timings_monotonic(self):
        words = make_words(SAMPLE_EN)
        cues = parse_cues(subs.build_srt(words, 3, 32, 0.8, 1.0, "two"))
        prev_end = -1.0
        for s, e, _t in cues:
            ss, ee = to_secs(s), to_secs(e)
            self.assertGreater(ee, ss)
            self.assertGreaterEqual(ss, prev_end)
            prev_end = ee

    def test_empty_words_gives_empty(self):
        self.assertEqual(subs.build_srt([], 3, 32, 0.8, 1.0, "two").strip(),
                         "")

    def test_orphan_merge_respects_char_budget(self):
        # "aaaa bbbb cccc" (14) + long word + orphan: the old merge joined
        # them into 35/25-char lines, straight over the user's max_chars.
        words = make_words("aaaa bbbb cccc " + "d" * 20 + " eeee")
        for ln in subs._split_lines(words, 3, 24, 0.8):
            line = " ".join(w["word"] for w in ln)
            self.assertLessEqual(len(line), 24, line)
        # and with room to spare the same input still packs tightly
        loose = subs._split_lines(words, 3, 60, 0.8)
        self.assertLess(len(loose), len(subs._split_lines(words, 3, 24, 0.8))
                        + 3)

    def test_overlapping_cues_never_end_before_start(self):
        # ASR can hand two adjacent lines the same start timestamp; the
        # hold/next-start logic then produced end == start (zero-length cue).
        words = [
            {"word": "Alphaaaaaaaaaaaaaaaaaaaaaa.", "start": 1.0, "end": 2.0},
            {"word": "Bbbbbbbbbbbbbbbbbbbbbbbbbbbb", "start": 1.0, "end": 1.5},
        ]
        cues = parse_cues(subs.build_srt(words, 3, 32, 0.8, 1.0, "single"))
        self.assertEqual(len(cues), 2)
        for s, e, _t in cues:
            self.assertGreater(to_secs(e), to_secs(s), (s, e))


class TestHardware(unittest.TestCase):
    def test_cpu_info_keys(self):
        cpu = hardware.cpu_info()
        for k in ("system", "machine", "os", "cpu", "cores", "ram_gb",
                  "disk_free_gb"):
            self.assertIn(k, cpu)
        self.assertTrue(cpu["cores"] >= 1)

    def test_gpu_entries_carry_cuda_flag(self):
        for g in hardware.gpu_info():
            self.assertIn("cuda_capable", g)
            self.assertIn("vendor", g)

    def test_classify_gpu_strong(self):
        p = hardware.classify(
            {"cores": 8, "ram_gb": 16.0, "disk_free_gb": 100.0, "cpu": "t"},
            [{"name": "RTX", "vram_gb": 12.0, "vendor": "NVIDIA",
              "cuda_capable": True}])
        self.assertEqual((p["tier"], p["device"], p["compute_type"]),
                         ("GPU_STRONG", "cuda", "float16"))

    def test_classify_gpu_mid(self):
        p = hardware.classify(
            {"cores": 4, "ram_gb": 8.0, "disk_free_gb": 100.0, "cpu": "t"},
            [{"name": "GTX", "vram_gb": 4.0, "vendor": "NVIDIA",
              "cuda_capable": True}])
        self.assertEqual(p["tier"], "GPU_MID")

    def test_display_only_gpu_stays_cpu(self):
        p = hardware.classify(
            {"cores": 8, "ram_gb": 16.0, "disk_free_gb": 100.0, "cpu": "t"},
            [{"name": "Intel UHD", "vram_gb": 0.0, "vendor": "Intel",
              "cuda_capable": False}])
        self.assertEqual(p["device"], "cpu")
        self.assertTrue(any("بدون CUDA" in n for n in p["notes"]))

    def test_disk_warning(self):
        p = hardware.classify(
            {"cores": 4, "ram_gb": 8.0, "disk_free_gb": 2.0, "cpu": "t"}, [])
        self.assertTrue(any("دیسک" in n for n in p["notes"]))

    def test_recommend_table(self):
        prof = {"tier": "CPU_WEAK", "device": "cpu", "compute_type": "int8",
                "threads": 4, "notes": []}
        for tier in ("GPU_STRONG", "GPU_MID", "CPU_STRONG", "CPU_WEAK"):
            prof["tier"] = tier
            for lang in ("en", "fa"):
                rec = hardware.recommend(lang, dict(prof))
                self.assertIn(rec["model"], hardware.MODEL_INFO, (tier, lang))
                self.assertTrue(rec["reason_fa"])
        # FA on weak CPU starts at base with auto-upgrade reason
        rec = hardware.recommend(
            "fa", {"tier": "CPU_WEAK", "device": "cpu",
                   "compute_type": "int8", "threads": 4, "notes": []})
        self.assertEqual(rec["model"], "base")

    def test_describe_fa(self):
        s = hardware.describe_fa()
        self.assertIn("Tier:", s)


class TestConfig(unittest.TestCase):
    def test_roundtrip_isolated(self):
        tmp = tempfile.mkdtemp(prefix="subsaz_cfg_")
        old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = tmp
        try:
            cfg = app_config.load()
            self.assertEqual(cfg["mode"], "single")
            cfg["mode"] = "three"
            app_config.save(cfg)
            self.assertEqual(app_config.load()["mode"], "three")
            # unknown keys are ignored, known keys survive
            with open(app_config.config_path(), "w",
                       encoding="utf-8") as f:
                f.write('{"mode": "two", "bogus": 1}')
            loaded = app_config.load()
            self.assertEqual(loaded["mode"], "two")
            self.assertNotIn("bogus", loaded)
        finally:
            if old is None:
                del os.environ["LOCALAPPDATA"]
            else:
                os.environ["LOCALAPPDATA"] = old


class TestSmart(unittest.TestCase):
    def test_quality_bounds(self):
        words = make_words(SAMPLE_EN)
        q = smart.quality(words, {"avg_logprob": -0.2, "no_speech": 0.1})
        self.assertTrue(0.0 <= q <= 1.0)
        self.assertEqual(smart.quality([], {}), 0.0)

    def test_upgrade_chain(self):
        self.assertTrue(smart.needs_upgrade("tiny", "en", 0.1))
        self.assertFalse(smart.needs_upgrade("small", "en", 0.9))
        final, _score, notes = smart.decide(
            "en", make_words("hi " * 20),
            {"avg_logprob": -3.0, "no_speech": 0.9}, "tiny")
        self.assertEqual(final, "small")
        self.assertTrue(notes)


class TestNormalize(unittest.TestCase):
    def test_apply_passthrough_en(self):
        words = make_words(SAMPLE_EN)
        out = normalize.apply(words, "en")
        self.assertEqual([w["word"] for w in out],
                         [w["word"] for w in words])

    def test_fa_digits(self):
        self.assertIn("۱۲", normalize.fa_digits("12"))

    def test_apply_to_fa_digits_does_not_crash(self):
        # param used to be named fa_digits, shadowing the function above and
        # raising TypeError ('bool' object is not callable) for Persian
        out = normalize.apply(make_words("قیمت 12 تومان"), "fa",
                              to_fa_digits=True)
        self.assertIn("۱۲", out[1]["word"])
        keep = normalize.apply(make_words("قیمت 12"), "fa")
        self.assertIn("12", keep[1]["word"])


class TestModelManager(unittest.TestCase):
    def test_block_classification(self):
        self.assertTrue(model_manager._looks_like_block(
            ConnectionError("connection reset by peer")))
        self.assertTrue(model_manager._looks_like_block(
            Exception("403 Forbidden")))
        self.assertTrue(model_manager._looks_like_block(
            Exception("ProxyError: max retries exceeded")))
        self.assertFalse(model_manager._looks_like_block(
            ValueError("bad model name")))
        self.assertTrue(model_manager.VPN_MESSAGE_FA.strip())

    def test_cached_models_returns_list(self):
        self.assertIsInstance(model_manager.cached_models(), list)

    def test_partial_download_is_not_cached(self):
        tmp = tempfile.mkdtemp(prefix="subsaz_hf_")
        repo = os.path.join(tmp,
                            model_manager._dir_name("Systran/faster-whisper-tiny"))
        os.makedirs(os.path.join(repo, "blobs"))
        with open(os.path.join(repo, "blobs", "0badc0de"), "wb") as f:
            f.write(b"")  # interrupted download: no weights yet
        orig = model_manager._hub_dir
        model_manager._hub_dir = lambda: tmp
        try:
            self.assertFalse(model_manager.is_cached("tiny"))
            os.makedirs(os.path.join(repo, "snapshots", "rev"))
            with open(os.path.join(repo, "snapshots", "rev", "model.bin"),
                      "wb") as f:
                f.write(b"")
            self.assertTrue(model_manager.is_cached("tiny"))
        finally:
            model_manager._hub_dir = orig


class TestTranscribe(unittest.TestCase):
    def test_precancelled_raises(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(engine.CancelledError):
            engine.process_file("dummy.mp4", ".", cancel_event=ev,
                                progress_cb=lambda _s: None)

    def test_stage_order_with_mocks(self):
        import app.transcribe as eng
        import app.model_manager as mm
        seen = []
        orig = (eng.probe_full, eng.extract_audio, eng.resolve_model,
                eng.transcribe)
        cached = mm.is_cached
        eng.probe_full = lambda _p: {}
        eng.extract_audio = lambda _s, _w: None
        eng.resolve_model = lambda _l, _m, _p=None: ("tiny", "cpu", "int8",
                                                    2, [])
        eng.transcribe = lambda *a, **k: (
            [{"word": "hi", "start": 0.0, "end": 1.0}], "en",
            {"avg_logprob": -0.1, "no_speech": 0.0})
        # the pipeline under test is mocked — model cache state of the host
        # machine must not decide whether this test passes.
        mm.is_cached = lambda _m: True
        try:
            with tempfile.TemporaryDirectory() as td:
                r = eng.process_file("dummy.mp4", td, model="tiny",
                                     progress_cb=seen.append,
                                     cancel_event=threading.Event())
            self.assertEqual(seen, ["audio", "transcribe", "subtitle"])
            self.assertTrue(r["srt"].endswith(".srt"))
            self.assertEqual(r["words"], 1)
            # temp wav must be gone even though it was never really made —
            # scoped to this process's pid prefix: another process's leftover
            # in the shared TEMP dir must not fail this run.
            td_tmp = os.path.join(os.environ.get("TEMP", "."), "subsaz_tmp")
            mine = "%d_" % os.getpid()
            left = [f for f in os.listdir(td_tmp)
                    if f.startswith(mine) and f.endswith(".wav")
                    ] if os.path.isdir(td_tmp) else []
            self.assertFalse(left, left)
        finally:
            (eng.probe_full, eng.extract_audio, eng.resolve_model,
             eng.transcribe) = orig
            mm.is_cached = cached

    def test_missing_model_raises_clear_error(self):
        import app.model_manager as mm
        orig = mm.is_cached
        mm.is_cached = lambda _m: False
        try:
            with self.assertRaises(mm.ModelDownloadError):
                engine.process_file("dummy.mp4", ".", model="tiny")
        finally:
            mm.is_cached = orig

    def test_auto_start_only_uses_cached_models(self):
        # auto mode must never make faster-whisper reach for the network
        orig = model_manager.is_cached
        try:
            model_manager.is_cached = lambda m: m == "base"
            self.assertEqual(engine._pick_start("en", "small"), "base")
            model_manager.is_cached = lambda m: m in ("tiny",)
            self.assertEqual(engine._pick_start("fa", "large-v3-turbo"),
                             "tiny")
            model_manager.is_cached = lambda _m: False
            with self.assertRaises(model_manager.ModelDownloadError):
                engine._pick_start("en", "small")
        finally:
            model_manager.is_cached = orig

    def test_auto_falls_back_when_recommendation_not_cached(self):
        # Cross-module contract: GUI/CLI start an auto run when ANY model is
        # cached, so process_file must reach _pick_start() instead of raising
        # ModelDownloadError for the (not downloaded) recommendation.
        import app.transcribe as eng
        import app.model_manager as mm
        orig = (eng.probe_full, eng.extract_audio, eng.resolve_model,
                eng.transcribe, mm.is_cached)
        eng.probe_full = lambda _p: {}
        eng.extract_audio = lambda _i, _o: None
        eng.resolve_model = lambda _l, _m, _p=None: (
            "small", "cpu", "int8", 2, ["rec=small"])
        eng.transcribe = lambda *a, **k: (
            make_words("hello there"), "en",
            {"avg_logprob": -0.1, "no_speech": 0.0})
        mm.is_cached = lambda m: m == "tiny"  # only tiny is downloaded
        try:
            r = eng.process_file("dummy.mp4", tempfile.mkdtemp(),
                                 lang="en", model="auto")
            self.assertIsNotNone(r)
            self.assertEqual(r["model"], "tiny")
        finally:
            (eng.probe_full, eng.extract_audio, eng.resolve_model,
             eng.transcribe, mm.is_cached) = orig

    def test_probe_failure_is_advisory_and_wav_is_cleaned(self):
        import app.transcribe as eng
        import app.model_manager as mm
        orig = (eng.probe_full, eng.extract_audio, eng.resolve_model,
                eng.transcribe)
        cached = mm.is_cached
        logs = []

        def _boom(_p):
            raise RuntimeError("ffprobe exploded")

        eng.probe_full = _boom
        eng.extract_audio = lambda _s, _w: None
        eng.resolve_model = lambda _l, _m, _p=None: ("tiny", "cpu", "int8",
                                                    2, [])
        eng.transcribe = lambda *a, **k: (
            [], "en", {"avg_logprob": -0.1, "no_speech": 0.0})
        mm.is_cached = lambda _m: True
        try:
            with tempfile.TemporaryDirectory() as td:
                r = eng.process_file("dummy.mp4", td, model="tiny",
                                     log=logs.append)
            self.assertIsNone(r)  # no speech -> clean skip, no crash
            self.assertTrue(any("probe failed" in s for s in logs), logs)
            # and the temp wav from this very run is cleaned up too
            td_tmp = os.path.join(os.environ.get("TEMP", "."), "subsaz_tmp")
            mine = "%d_" % os.getpid()
            left = [f for f in os.listdir(td_tmp)
                    if f.startswith(mine) and f.endswith(".wav")
                    ] if os.path.isdir(td_tmp) else []
            self.assertFalse(left, left)
        finally:
            (eng.probe_full, eng.extract_audio, eng.resolve_model,
             eng.transcribe) = orig
            mm.is_cached = cached


class TestWebUIContract(unittest.TestCase):
    """The TypeScript UI and webui.py must stay in sync with web/API.md."""

    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_web_dist_is_prebuilt_and_rtl(self):
        index = os.path.join(self.ROOT, "web_dist", "index.html")
        self.assertTrue(
            os.path.isfile(index),
            "web_dist/index.html missing — run: cd web && npm run build")
        with open(index, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('dir="rtl"', html)
        self.assertIn('lang="fa"', html)

    def test_every_contract_method_is_implemented(self):
        api_md = os.path.join(self.ROOT, "web", "API.md")
        with open(api_md, encoding="utf-8") as fh:
            names = sorted(set(re.findall(r"\| `([a-z_]+)\(", fh.read())))
        self.assertTrue(names, "API.md documents no methods")

        import webui  # noqa: F401 — must import without side effects
        api_cls = next(
            (obj for _, obj in vars(webui).items()
             if isinstance(obj, type) and callable(getattr(obj, "get_state", None))),
            None)
        self.assertIsNotNone(api_cls, "webui.py exposes no API class with get_state()")
        missing = [n for n in names
                   if not callable(getattr(api_cls, n, None))]
        self.assertEqual(missing, [],
                         f"webui.py is missing contract methods: {missing}")

    def test_release_spec_ships_the_frontend(self):
        with open(os.path.join(self.ROOT, "subsaz-web.spec"),
                  encoding="utf-8") as fh:
            spec = fh.read()
        self.assertIn('["webui.py"]', spec)
        self.assertIn('("web_dist", "web_dist")', spec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
