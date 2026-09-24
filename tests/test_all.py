"""SubSaz test suite: core engine + GUI. stdlib only.

Run from repo root:  python tests/test_all.py
GUI tests need a display; they skip cleanly headless (TclError).
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
from app import bidi as bidi_helper
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


class TestBidi(unittest.TestCase):
    def test_ltr_passthrough(self):
        self.assertEqual(bidi_helper.display("Hello 123"), "Hello 123")

    def test_fa_number_isolated(self):
        out = bidi_helper.display("سلام 12 تست")
        # Latin/number run wrapped so Tk keeps it LTR inside RTL
        self.assertIn("٬12٭".replace("٬", "\u2066").replace("٭", "\u2069"),
                      out)
        self.assertTrue(out.startswith("\u2067") and out.endswith("\u2069"))

    def test_fa_latin_isolated(self):
        out = bidi_helper.display("سلام Hello تست")
        self.assertIn("\u2066Hello\u2069", out)

    def test_idempotent(self):
        once = bidi_helper.display("سلام 12 تست")
        self.assertEqual(bidi_helper.display(once), once)

    def test_file_text_stays_logical(self):
        # engine output must NOT contain isolates — display layer only
        words = make_words("سلام 12 تست")
        line = " ".join(w["word"] for w in words[:3])
        self.assertNotIn("\u2066", line)
        self.assertIn("\u2066", bidi_helper.display(line))

    def test_persian_digits_parse(self):
        self.assertEqual(bidi_helper.parse_int("۳", 0), 3)
        self.assertAlmostEqual(bidi_helper.parse_float("۰٫۸", 0.0), 0.8)
        self.assertEqual(bidi_helper.parse_int("bogus", 7), 7)


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
            # temp wav must be gone even though it was never really made
            td_tmp = os.path.join(os.environ.get("TEMP", "."), "subsaz_tmp")
            left = [f for f in os.listdir(td_tmp)
                    if f.endswith(".wav")] if os.path.isdir(td_tmp) else []
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
        finally:
            (eng.probe_full, eng.extract_audio, eng.resolve_model,
             eng.transcribe) = orig
            mm.is_cached = cached


try:
    import tkinter as _tk
    _root = _tk.Tk()
    _root.withdraw()
    _root.destroy()
    _HAS_DISPLAY = True
except Exception:  # noqa: BLE001 — headless CI
    _HAS_DISPLAY = False


@unittest.skipUnless(_HAS_DISPLAY, "no display for GUI tests")
class TestGUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gui as _gui
        cls.gui_mod = _gui
        cls.cfg_backup = app_config.load()
        cls.app = _gui.App()
        cls.app.root.update_idletasks()
        cls.app.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.root.destroy()
        except Exception:  # noqa: BLE001
            pass
        app_config.save(cls.cfg_backup)

    def setUp(self):
        self.app.root.update()

    def test_theme_palette_applied(self):
        self.assertEqual(self.app.btn.cget("fg_color"), "#15919B")
        self.assertEqual(self.app.cancel_btn.cget("fg_color"), "#A93226")
        for b in self.app.seg_btns.values():
            self.assertTrue(b.cget("text"))

    def test_logo_loads_or_skips_cleanly(self):
        # must never crash; logo present in a normal checkout
        from gui import _base
        import os as _os
        if _os.path.isfile(_os.path.join(_base, "assets", "icon.png")):
            self.assertIsNotNone(self.app._logo_ref)

    def test_rec_never_blocks_on_scan(self):
        self.app.profile = None
        self.assertEqual(self.app._rec_for("auto", "en"), (None, None))
        self.app._refresh_rec()
        self.assertIn("اسکن", self.app.rec_label.cget("text"))

    def test_caption_panel_all_combos(self):
        a = self.app
        for n in (1, 2, 3):
            a._set_lines(n)
            self.assertEqual(a._mode_name(),
                             {1: "single", 2: "two", 3: "three"}[n])
            for w in (1, 6):
                a._on_words_slider(w)
                self.assertEqual(int(a.words_var.get()), w)
                for c in (20, 50):
                    a._on_chars_slider(c)
                    a.root.update()
                    self.assertEqual(int(a.chars_var.get()), c)

    def test_lang_switch_persists(self):
        a = self.app
        a.lang_var.set("fa")
        a._on_setting_change()
        self.assertEqual(a.lang_var.get(), "fa")
        a.lang_var.set("en")
        a._on_setting_change()
        self.assertEqual(a.lang_var.get(), "en")

    def test_preview_removed(self):
        # Premiere-style preview feature was fully removed
        a = self.app
        for attr in ("pv_text", "pv_count", "pv_time", "pv_warn",
                     "pv_box", "pv_stage", "pv_play_btn", "pv_idx",
                     "pv_playing"):
            self.assertFalse(hasattr(a, attr), attr)
        for meth in ("_preview_rebuild", "_preview_cues", "_pv_next",
                     "_pv_prev", "_pv_toggle_play", "_pv_tick",
                     "_sample_words"):
            self.assertFalse(hasattr(a, meth), meth)

    def test_poll_survives_garbage(self):
        a = self.app
        a.q.put(("prog", "not-a-float"))
        a.q.put(("bogus-kind", None))
        a._poll()  # must not raise; loop rescheduled in finally
        a.root.update()

    def test_warn_dispatched_on_main_thread(self):
        import tkinter.messagebox as mb
        seen = []
        old = mb.showwarning
        mb.showwarning = lambda t, m: seen.append((t, m))
        try:
            self.app._handle_q("warn", ("T", "M"))
        finally:
            mb.showwarning = old
        self.assertEqual(seen, [("T", "M")])

    def test_theme_toggle_both_modes(self):
        a = self.app
        a._toggle_theme()
        a.root.update()
        a._toggle_theme()
        a.root.update()

    def test_start_validation(self):
        import inspect
        src = inspect.getsource(self.gui_mod.App._start)
        self.assertIn("1 <= words <= 6", src)
        self.assertIn("20 <= max_chars <= 50", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
