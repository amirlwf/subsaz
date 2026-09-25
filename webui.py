"""ساب‌ساز WebView — pywebview/WebView2 shell around the engine gui.py drives.

The TypeScript page (web/src) talks to this file through the contract in
web/API.md: the `Api` object is handed to pywebview as `js_api`, so the page
calls `window.pywebview.api.<method>(...)`, and every UI event goes back out
as `window.__push("<kind>", <json>)` (defined by web/src/bridge.ts).

Design notes (why this looks like gui.py minus Tk):
- gui.py's `self.q` queue survives: workers only ever `put()`, one flush
  thread owns the browser, so events stay ordered and can be buffered until
  the page has defined `__push`.
- app/bidi.py is Tk-only (visual-order reshaping for widgets that paint
  left-to-right). The browser does bidi itself, so every Persian string here
  goes out in LOGICAL order — never through bidi.display().
- API methods run on pywebview worker threads, so they must never block:
  long work (scan, download, transcription) always goes to a thread.
"""
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def _app_base():
    # frozen onedir: datas live in sys._MEIPASS (_internal); fallback to exe dir
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and os.path.isdir(os.path.join(meipass, "assets")):
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_base = _app_base()
_exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_exe_dir, "web_started.log")


def _bc(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:  # noqa: BLE001 — logging must never break startup
        pass


_bc("=== web boot start (frozen=%s) ===" % bool(getattr(sys, "frozen", False)))

try:
    import webview
except Exception as e:  # noqa: BLE001
    _bc("pywebview import failed: %r" % e)
    raise

from app import config as app_config
from app import hardware, model_manager
from app import transcribe as engine

TITLE = "ساب‌ساز — زیرنویس دقیق کلمه‌به‌کلمه"
MODELS = ("auto", "large-v3-turbo", "medium", "small", "base", "tiny")
LANGS = ("auto", "en", "fa")
# state.settings.mode (web/API.md: «۱ خط» / «۲ خط») <-> engine mode
# (app/subtitles.py: single / two / three). The web UI only offers two
# choices, so a leftover gui.py "three" shows — and runs — as "word".
MODES = {"segment": "single", "word": "two"}
SETTING_KEYS = ("language", "mode", "chars_per_line", "words_per_line",
                "special_words", "outdir", "formats",
                "formats.srt", "formats.vtt")
# Settings the page edits in place — main.ts binds them to `input` events and
# re-renders every field on each `state` push, so echoing state back after one
# of these would rewrite the control the user is still typing in (caret jumps).
# They round-trip through get_state() and are range-checked in start() instead.
IN_PLACE_KEYS = ("chars_per_line", "words_per_line", "special_words")
# pywebview wants Windows filter strings: "Desc (*.ext;*.ext)" (gui.py used
# Tk's space-separated spelling instead).
FILE_TYPES = (
    "Media (%s)" % ";".join("*" + ext for ext in engine.ALL_EXTS),
    "All files (*.*)",
)


# ---- numeric settings come in as JSON numbers or Persian digits ----------
# Same tolerance gui.py gets from app/bidi.parse_int («۳» == 3, «۰٫۸» == 0.8)
# but reimplemented here: app/bidi is a Tk helper and must not be imported.
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫",
                                 "01234567890123456789.")


def _num(value):
    """int/float from a JSON number or a Persian/ASCII-digit string."""
    if isinstance(value, bool) or value is None:
        raise ValueError("مقدار عددی نامعتبر است.")
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.strip().translate(_PERSIAN_DIGITS))
    except ValueError:
        pass
    raise ValueError("مقدار عددی نامعتبر است: %r" % (value,))


def _state_mode(engine_mode):
    """Engine mode -> state.settings.mode (only two buttons in the web UI)."""
    return "segment" if engine_mode == "single" else "word"


def _dialog_paths(result):
    """create_file_dialog returns tuple / str / None depending on dialog."""
    if not result:
        return []
    if isinstance(result, (list, tuple)):
        return [p for p in result if p]
    return [result]


def _srt_to_vtt(srt_path, vtt_path):
    """SRT -> WebVTT: header, no cue numbers, 00:00:00,000 -> 00:00:00.000."""
    with open(srt_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    out = ["WEBVTT", ""]
    for i, line in enumerate(lines):
        # the numeric cue index sits right above its timing line — WebVTT
        # has no counters, and only that position may be dropped (a caption
        # that happens to be a bare number must survive).
        if line.strip().isdigit() and i + 1 < len(lines) \
                and "-->" in lines[i + 1]:
            continue
        out.append(line.replace(",", ".") if "-->" in line else line)
    with open(vtt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def _web_cfg_path():
    return os.path.join(app_config.config_dir(), "webui.json")


def _load_web_cfg():
    """WebView-only preferences (theme + output formats).

    app/config.py persists a fixed key set and drops anything else on load,
    and gui.py rewrites config.json wholesale — so the web UI keeps its own
    settings in a sibling file instead of fighting over the shared one.
    """
    try:
        with open(_web_cfg_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_web_cfg(data):
    try:
        with open(_web_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _window_size():
    """Screen-aware default size — gui.py does the same with winfo_*."""
    w, h = 900, 740
    try:
        if os.name == "nt":
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            if sw and sh:
                w, h = min(w, int(sw * 0.9)), min(h, int(sh * 0.86))
    except (OSError, AttributeError, ValueError, TypeError):
        pass
    return w, h


def _push_script(kind, data):
    """One line of JS: window.__push("<kind>", <json>).

    Returns false while bridge.ts hasn't defined __push yet (the flush
    thread then holds the event and retries — nothing is lost and order is
    kept), true once delivered, 'err' if __push itself threw.
    """
    payload = json.dumps(data, ensure_ascii=False)
    # U+2028/U+2029 are legal in JSON but used to break JS string literals.
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return ("(function(){try{if(typeof window.__push!=='function'){return false;}"
            "window.__push(%s,%s);return true;}catch(e){return 'err';}})()"
            % (json.dumps(kind), payload))


# Shown only when web_dist/index.html has not been built yet — a real page
# plus a live bridge probe, so a half-built checkout still opens something.
_PLACEHOLDER_HTML = """<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>ساب‌ساز</title>
<style>
 body{font-family:Vazirmatn,Segoe UI,Tahoma,sans-serif;background:#1B1B1B;
      color:#EEE;margin:0;padding:28px;line-height:1.7}
 h1{color:#5AD6DE;font-size:22px;margin:0 0 8px}
 code,pre{background:#262626;border-radius:6px;padding:2px 6px;
      direction:ltr;text-align:left;unicode-bidi:isolate}
 pre{padding:10px;overflow:auto;max-height:40vh}
 .ok{color:#7BD88F}.bad{color:#E06C75}.dim{color:#999;font-size:13px}
 #evt{color:#F0B43C;font-size:14px}
</style></head><body>
<h1>رابط وب هنوز ساخته نشده</h1>
<p>فایل <code>web_dist/index.html</code> پیدا نشد. برای ساخت رابط:</p>
<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p id="probe" class="dim">در حال بررسی پل Python↔JS…</p>
<pre id="state" class="dim">—</pre>
<div id="evt" class="dim">—</div>
<script>
window.__push = function (kind, data) {
  document.getElementById('evt').textContent =
    'آخرین رویداد: ' + kind + ' = ' + JSON.stringify(data);
};
function boot() {
  window.pywebview.api.get_state().then(function (s) {
    document.getElementById('probe').className = 'ok';
    document.getElementById('probe').textContent =
      '✓ پل Python↔JS کار می‌کند (get_state OK)';
    document.getElementById('state').textContent = JSON.stringify(s, null, 2);
  }).catch(function (e) {
    document.getElementById('probe').className = 'bad';
    document.getElementById('probe').textContent = '✗ get_state: ' + e;
  });
}
if (window.pywebview && window.pywebview.api) { boot(); }
else { window.addEventListener('pywebviewready', boot); }
</script></body></html>"""


class Api:
    """The `js_api` object — exactly the methods listed in web/API.md.

    Public surface is deliberately limited to those 15 methods: pywebview
    exposes every public attribute/method it can find, so all helpers and
    state below are underscore-prefixed.
    """

    def __init__(self):
        self._cfg = app_config.load()
        web = _load_web_cfg()
        self._theme = "light" if web.get("theme") == "light" else "dark"
        fmt = web.get("formats") or {}
        self._formats = {"srt": bool(fmt.get("srt", True)),
                         "vtt": bool(fmt.get("vtt", False))}
        self._files = []            # real paths; the page renders them as-is
        self._lock = threading.RLock()
        self._q = queue.Queue()
        self._window = None
        self._stop = False
        self._ready_logged = False
        self._running = False
        self._downloading = False
        self._profile = None
        self._cancel = threading.Event()
        self._push("log", "آماده. اول «اسکن سیستم» را ببین، بعد مدل را دانلود کن.")
        # hardware scan in background so the UI opens instantly
        threading.Thread(target=self._scan_hw, daemon=True).start()

    # ---------- plumbing ----------
    def _attach(self, window):
        """Bind the window after create_window() and start the flush loop."""
        self._window = window
        window.events.closed += self._on_closed
        threading.Thread(target=self._flush, daemon=True).start()

    def _on_closed(self):
        self._stop = True

    def _push(self, kind, data):
        self._q.put((kind, data))

    def _push_files(self):
        with self._lock:
            files = list(self._files)
        self._push("files", files)
        self._push("state", self._state())

    def _push_hw(self):
        self._push("hw", self._hw())
        self._push("state", self._state())

    def _warn(self, msg, title="ساب‌ساز"):
        # the Tk build showed a messagebox from the main thread; here the
        # page owns its dialog, we only hand it the {title, msg} payload.
        self._push("warn", {"title": title, "msg": msg})

    def _reject(self, msg):
        """Validation failure of start(): warn + authoritative state.

        main.ts disables the start button and shows «در حال ساخت…» *before*
        it awaits start(), so a rejection that only warned would leave the
        page stuck on a disabled button — the state push (running=false) is
        what re-enables it.
        """
        self._warn(msg)
        self._push("state", self._state())
        return None

    def _flush(self):
        """Single thread that talks to the browser.

        Events queue up until the page defines window.__push (bridge.ts),
        then flush in order. A failure never drops an event immediately —
        only a 60s-stuck payload is discarded with a log line, so one bad
        message can't jam the queue forever.
        """
        pending = None
        failed_since = None
        while not self._stop:
            if pending is None:
                try:
                    pending = self._q.get(timeout=0.2)
                except queue.Empty:
                    continue
                failed_since = None
            if self._window is None or \
                    not self._window.events._pywebviewready.is_set():
                time.sleep(0.1)
                continue
            kind, data = pending
            try:
                res = self._window.evaluate_js(_push_script(kind, data))
            except Exception as e:  # noqa: BLE001 — page may be navigating
                _bc("push %s failed: %r" % (kind, e))
                res = None
            if res is True:
                if not self._ready_logged:
                    _bc("bridge ready: first '%s' event delivered" % kind)
                    self._ready_logged = True
                pending = None
            elif res == "err":
                # __push threw — retrying the same payload would throw again
                _bc("push %s rejected by __push" % kind)
                pending = None
            else:
                now = time.time()
                if failed_since is None:
                    failed_since = now
                elif now - failed_since > 60:
                    _bc("dropped '%s' event after 60s without __push" % kind)
                    pending = None
                time.sleep(0.15)

    # ---------- state ----------
    def _state(self):
        with self._lock:
            files = list(self._files)
            cfg = dict(self._cfg)
            formats = dict(self._formats)
            theme = self._theme
            running = self._running
        # never let a hand-edited config.json kill get_state(): 0 is a real
        # value (the page sends it for an empty number box), only junk falls
        # back to the default that start() would reject anyway.
        try:
            chars = int(cfg.get("max_chars", 32))
        except (TypeError, ValueError):
            chars = 32
        try:
            per_line = int(cfg.get("words_per_line", 3))
        except (TypeError, ValueError):
            per_line = 3
        lang = cfg.get("lang")
        return {
            "files": files,
            "settings": {
                "language": lang if lang in LANGS else "auto",
                "mode": _state_mode(cfg.get("mode", "single")),
                "chars_per_line": chars,
                "words_per_line": per_line,
                "special_words": cfg.get("prompt", "") or "",
                "outdir": cfg.get("outdir", "") or "",
                "formats": formats,
            },
            "hw": self._hw(cfg),
            "models": self._models(),
            "theme": theme,
            "running": running,
        }

    def _hw(self, cfg=None):
        with self._lock:
            if cfg is None:
                cfg = dict(self._cfg)
            profile = self._profile
        ready = profile is not None
        rec = ""
        if ready:
            # hardware.recommend() folds anything but 'fa' into 'en'
            rec = hardware.recommend(cfg.get("lang", "en"), profile)["model"]
        return {
            "desc": hardware.describe_fa(profile) if ready
            else "در حال اسکن سیستم…",
            "tier": (profile or {}).get("tier", ""),
            "rec": rec,
            "selected": cfg.get("model", "auto"),
            "ready": ready,
        }

    def _models(self):
        out = []
        for m in MODELS:
            if m == "auto":
                # auto is "usable" once ANY model is on disk; size_label can't
                # be a number (auto picks whatever is cached) but must not be
                # empty either — the page renders "label (size_label)".
                out.append({"id": "auto", "label": "auto — خودکار",
                            "size_label": "—",
                            "downloaded": bool(model_manager.cached_models())})
                continue
            info = hardware.MODEL_INFO.get(m, {})
            out.append({
                "id": m,
                "label": info.get("label", m),
                "size_label": "~%dMB" % info.get("mb", 0),
                "downloaded": model_manager.is_cached(m),
            })
        return out

    def get_state(self):
        return self._state()

    # ---------- files ----------
    def pick_files(self):
        selected = self._dialog(webview.FileDialog.OPEN,
                                allow_multiple=True, file_types=FILE_TYPES)
        added = self._accept_many(selected)
        if added:
            self._push_files()
        return added

    def pick_folder(self):
        selected = self._dialog(webview.FileDialog.FOLDER)
        added = self._accept_many(selected)
        if added:
            self._push_files()
        return added

    def pick_outdir(self):
        # the page's outdir field is readonly, so this is the only way the
        # setting changes — persist it and hand the path back for display.
        selected = self._dialog(webview.FileDialog.FOLDER)
        if not selected:
            return ""
        outdir = selected[0]
        with self._lock:
            self._cfg["outdir"] = outdir
            app_config.save(self._cfg)
        self._push("state", self._state())
        return outdir

    def add_paths(self, paths):
        added = self._accept_many(paths)
        if added:
            self._push_files()
        return added

    def remove_file(self, path):
        with self._lock:
            changed = path in self._files
            if changed:
                self._files.remove(path)
        if changed:
            self._push_files()
        return None

    def clear_files(self):
        with self._lock:
            self._files = []
        self._push_files()
        return None

    def _accept_many(self, paths):
        """Validate + expand, then append what is not queued yet.

        Directories behave like gui.py's drop handler (top level, engine
        extension list); junk and duplicates are silently skipped, and only
        the *new* paths are returned, per web/API.md.
        """
        if isinstance(paths, str):
            paths = [paths]
        added = []
        for path in paths or []:
            for candidate in self._expand(path):
                with self._lock:
                    if candidate in self._files:
                        continue
                    self._files.append(candidate)
                added.append(candidate)
        return added

    @staticmethod
    def _expand(path):
        if not isinstance(path, str) or not path.strip():
            return []
        path = path.strip()
        if os.path.isdir(path):
            out = []
            try:
                for name in sorted(os.listdir(path)):
                    if name.lower().endswith(engine.ALL_EXTS):
                        out.append(os.path.join(path, name))
            except OSError:
                pass
            return out
        if os.path.isfile(path) and path.lower().endswith(engine.ALL_EXTS):
            return [path]
        return []

    def _dialog(self, dialog_type, allow_multiple=False, file_types=()):
        if self._window is None:
            return []
        try:
            selected = self._window.create_file_dialog(
                dialog_type, allow_multiple=allow_multiple,
                file_types=file_types)
        except Exception as e:  # noqa: BLE001 — dialog errors are not fatal
            _bc("dialog failed: %r" % e)
            self._push("err", "باز کردن پنجره انتخاب ناموفق بود: %s" % e)
            return []
        return _dialog_paths(selected)

    # ---------- hardware ----------
    def rescan(self):
        with self._lock:
            selected = self._cfg.get("model", "auto")
        # immediate feedback: the result itself arrives as a later `hw` event
        self._push("hw", {"desc": "در حال اسکن سیستم…", "tier": "",
                          "rec": "", "selected": selected, "ready": False})
        _bc("rescan requested")
        threading.Thread(target=self._scan_hw, daemon=True).start()
        return None

    def _scan_hw(self):
        try:
            self._profile = hardware.classify()
            _bc("hw scan: %s" % self._profile.get("tier"))
            self._push_hw()
        except Exception as e:  # noqa: BLE001
            _bc("hw scan failed: %r" % e)
            self._push("log", "خطا در اسکن سیستم: %s" % e)
            self._push("err", "خطا در اسکن سیستم: %s" % e)

    def _rec_for(self, model, lang):
        """(name, rec) for a model id — same rules as gui.py."""
        if model == "auto":
            with self._lock:
                profile = self._profile
            if profile is None:
                # scan still running — never block a call on classify()
                # (wmic/nvidia-smi can take seconds).
                return None, None
            rec = hardware.recommend(lang, profile)
            return rec["model"], rec
        return model, None

    # ---------- model / download ----------
    def set_model(self, model_id):
        if model_id not in MODELS:
            raise ValueError("مدل نامعتبر: %s" % model_id)
        with self._lock:
            self._cfg["model"] = model_id
            app_config.save(self._cfg)
        self._push_hw()
        return None

    def download_model(self, model_id):
        name = self._resolve_model(model_id)
        if name is None:
            # page already unhid its progress bar for this click — close it
            # again instead of raising into the page's error log.
            self._warn("اسکن سیستم هنوز تمام نشده — یک لحظه صبر کن.")
            self._push("dl_done", {"id": model_id})
            return None
        if self._downloading:
            self._push("log", "یک دانلود دیگر در جریان است — تا پایان آن صبر کن.")
            self._push("dl_done", {"id": name})
            return None
        if model_manager.is_cached(name):
            self._push("log", "مدل %s قبلا دانلود شده." % name)
            self._push("state", self._state())
            self._push("dl_done", {"id": name})
            return None
        with self._lock:
            self._downloading = True
        threading.Thread(target=self._dl_worker, args=(name,),
                         daemon=True).start()
        return None

    def _resolve_model(self, model_id):
        """Concrete model id for a request; None while the scan still runs."""
        if model_id not in MODELS:
            raise ValueError("مدل نامعتبر: %s" % model_id)
        if model_id != "auto":
            return model_id
        with self._lock:
            lang = self._cfg.get("lang", "en")
        name, _rec = self._rec_for("auto", lang)
        return name

    def _dl_worker(self, name):
        q = self._q
        q.put(("log", "دانلود مدل %s شروع شد…" % name))
        ok = False
        try:
            model_manager.download(
                name,
                progress_cb=lambda d, t: q.put(
                    ("dl_prog", {"id": name,
                                 "pct": round(100.0 * d / max(t, 1), 1)})),
                log=lambda m: q.put(("log", m)))
            ok = True
            q.put(("log", "✓ مدل %s آماده است." % name))
        except model_manager.ModelDownloadError as e:
            if e.need_vpn:
                q.put(("log", "✗ " + model_manager.VPN_MESSAGE_FA.replace(
                    "\n", " ")))
                q.put(("warn", {"title": "ساب‌ساز — خطای دانلود",
                                "msg": model_manager.VPN_MESSAGE_FA}))
            else:
                q.put(("log", "✗ دانلود ناموفق: %s" % e))
            q.put(("err", str(e)))
        except Exception as e:  # noqa: BLE001
            q.put(("log", "✗ دانلود ناموفق: %s" % e))
            q.put(("err", str(e)))
            _bc("download failed: " + repr(traceback.format_exc()))
        with self._lock:
            self._downloading = False
        # dl_done always fires (contract: dl_prog … then dl_done) so the
        # page's bar cannot get stuck, and `ok` is carried by the state's
        # downloaded flags rather than by a payload field.
        q.put(("state", self._state()))
        q.put(("dl_done", {"id": name}))
        if not ok:
            _bc("download of %s finished without weights" % name)

    # ---------- settings ----------
    def set_setting(self, key, value):
        # main.ts sends formats as dotted keys ("formats.srt" / "formats.vtt")
        # with a boolean; a whole {"srt","vtt"} object is accepted too.
        if key not in SETTING_KEYS:
            raise ValueError("تنظیم نامعتبر: %s" % key)
        hw_changed = False
        with self._lock:
            if key == "language":
                if value not in LANGS:
                    raise ValueError("زبان نامعتبر: %s" % value)
                self._cfg["lang"] = value
                hw_changed = True
            elif key == "mode":
                if value not in MODES:
                    raise ValueError("حالت نامعتبر: %s" % value)
                self._cfg["mode"] = MODES[value]
            elif key == "chars_per_line":
                # stored as sent — gui.py does the same (parse_int keeps the
                # typed value) and _start() is where the 20..50 range bites.
                self._cfg["max_chars"] = int(round(_num(value)))
            elif key == "words_per_line":
                self._cfg["words_per_line"] = int(round(_num(value)))
            elif key == "special_words":
                self._cfg["prompt"] = "" if value is None else str(value)
            elif key == "outdir":
                self._cfg["outdir"] = ("" if value is None
                                       else str(value).strip())
            elif key.startswith("formats"):
                fmt_value = value if key == "formats" \
                    else {key.split(".", 1)[1]: value}
                if not isinstance(fmt_value, dict):
                    raise ValueError("فرمت‌ها باید {srt, vtt} باشد.")
                for fmt in ("srt", "vtt"):
                    if fmt in fmt_value:
                        self._formats[fmt] = bool(fmt_value[fmt])
                _save_web_cfg({"theme": self._theme,
                               "formats": dict(self._formats)})
            app_config.save(self._cfg)
        if key not in IN_PLACE_KEYS:
            # controls backed by a select/checkbox: safe to re-render
            self._push("state", self._state())
        if hw_changed:
            # language feeds the model recommendation
            self._push("hw", self._hw())
        return None

    def toggle_theme(self):
        with self._lock:
            self._theme = "light" if self._theme == "dark" else "dark"
            _save_web_cfg({"theme": self._theme,
                           "formats": dict(self._formats)})
        self._push("state", self._state())
        return self._theme

    # ---------- run ----------
    def start(self):
        with self._lock:
            if self._running:
                return None
            files = list(self._files)
            cfg = dict(self._cfg)
            formats = dict(self._formats)
            profile = self._profile
        if not files:
            return self._reject("اول فایل انتخاب کن.")
        outdir = (cfg.get("outdir") or "").strip()
        if not outdir or not os.path.isdir(outdir):
            return self._reject("پوشه ذخیره خروجی را انتخاب کن.")
        if not formats.get("srt") and not formats.get("vtt"):
            return self._reject(
                "حداقل یک فرمت خروجی (SRT یا VTT) را روشن کن.")
        # set_setting() stores numbers as typed, so config.json (hand-edited
        # or filled by the page) still gets gui.py's range checks right here.
        try:
            words = int(round(_num(cfg.get("words_per_line", 3))))
            max_chars = int(round(_num(cfg.get("max_chars", 32))))
            max_gap = _num(cfg.get("max_gap", 0.8))
            hold = _num(cfg.get("hold", 1.0))
        except ValueError:
            return self._reject(
                "تنظیمات عددی معتبر نیست. (ارقام فارسی هم قبول است: ۳، ۰٫۸)")
        if not 1 <= words <= 6:
            return self._reject("کلمه/خط باید بین ۱ تا ۶ باشد.")
        if not 20 <= max_chars <= 50:
            return self._reject("حروف/خط باید بین ۲۰ تا ۵۰ باشد.")
        if max_gap <= 0 or hold < 0:
            return self._reject("گپ باید مثبت و مکث نامنفی باشد.")
        lang = cfg.get("lang", "en")
        model = cfg.get("model", "auto")
        name, _rec = self._rec_for(model, lang)
        if name is None:
            return self._reject("اسکن سیستم هنوز تمام نشده — یک لحظه صبر کن.")
        # auto: the engine itself picks the best *cached* model, so only a
        # machine with nothing downloaded has to hit the download button.
        model_ready = bool(model_manager.cached_models()) if model == "auto" \
            else model_manager.is_cached(name)
        if not model_ready:
            return self._reject("مدل %s هنوز دانلود نشده.\n"
                                "اول «دانلود مدل» را بزن." % name)
        with self._lock:
            self._running = True
        self._cancel.clear()
        self._push("state", self._state())
        self._push("prog", 0)
        args = dict(outdir=outdir, lang=lang, model=model, words=words,
                    max_chars=max_chars, max_gap=max_gap, hold=hold,
                    mode=MODES[_state_mode(cfg.get("mode", "single"))],
                    prompt=cfg.get("prompt") or None,
                    profile=profile)
        threading.Thread(target=self._worker, args=(files, args, model),
                         daemon=True).start()
        return None

    def cancel(self):
        with self._lock:
            if not self._running:
                return None
        self._cancel.set()
        self._push("log", "■ لغو درخواست شد… (توقف بعد از بخش فعلی)")
        return None

    def open_outdir(self):
        with self._lock:
            outdir = (self._cfg.get("outdir") or "").strip()
        if not outdir or not os.path.isdir(outdir):
            self._warn("پوشه ذخیره خروجی را انتخاب کن.")
            return None
        try:
            if hasattr(os, "startfile"):
                os.startfile(outdir)
            elif sys.platform == "darwin":
                subprocess.run(["open", outdir], check=False)
            else:
                subprocess.run(["xdg-open", outdir], check=False)
        except Exception as e:  # noqa: BLE001
            self._warn("باز کردن پوشه ناموفق بود: %s" % e)
        return None

    def _worker(self, files, args, disp_model):
        """Batch run — gui.py's _worker with web payloads (0…100 prog,
        {outdir,srt,words,secs} done, state instead of widget updates)."""
        q = self._q
        with self._lock:
            formats = dict(self._formats)
        t0 = time.time()
        q.put(("log",
               "در حال لود مدل… (اولین بار کمی طول می‌کشد)"
               if disp_model == "auto"
               else "مدل %s در حال لود… (اولین بار کمی طول می‌کشد)"
                    % disp_model))
        ok = 0
        cancelled = False
        total = len(files)
        words_total = 0
        last_out = ""
        # coarse per-stage weights inside one file: audio 10%, transcribe
        # 90%, subtitle 100% — stage-based, not byte-based (same as gui.py).
        _weights = {"audio": 0.1, "transcribe": 0.9, "subtitle": 1.0}
        for i, path in enumerate(files, 1):
            if self._cancel.is_set():
                cancelled = True
                break
            base = os.path.basename(path)
            q.put(("status", "%d/%d: %s" % (i, total, base)))
            q.put(("log", "== [%d/%d] %s" % (i, total, base)))

            def _cb(stage, _i=i, _total=total):
                frac = ((_i - 1) + _weights.get(stage, 0.0)) / max(_total, 1)
                q.put(("prog", round(100.0 * frac, 1)))

            try:
                res = engine.process_file(
                    path, log=lambda m: q.put(("log", m)),
                    progress_cb=_cb, cancel_event=self._cancel, **args)
                if res:
                    ok += 1
                    words_total += int(res.get("words") or 0)
                    out = self._finish_formats(res, formats, q)
                    if out:
                        last_out = out
                q.put(("prog", round(100.0 * i / max(total, 1), 1)))
            except engine.CancelledError:
                cancelled = True
                q.put(("log", "   ■ لغو شد: %s" % base))
                break
            except model_manager.ModelDownloadError as e:
                q.put(("log", "   FAILED: %s" % e))
                q.put(("err", str(e)))
                if e.need_vpn:
                    q.put(("warn", {"title": "ساب‌ساز — خطای دانلود",
                                    "msg": model_manager.VPN_MESSAGE_FA}))
            except Exception as e:  # noqa: BLE001
                q.put(("log", "   FAILED: %s" % e))
                q.put(("err", str(e)))
                _bc("worker failed: " + repr(traceback.format_exc()))
        secs = time.time() - t0
        q.put(("prog", 100))
        q.put(("status", ""))
        if cancelled:
            q.put(("log", "== لغو شد: %d/%d فایل در %.1fs"
                   % (ok, total, secs)))
        else:
            q.put(("log", "== تمام شد: %d/%d فایل در %.1fs — خروجی SRT"
                   % (ok, total, secs)))
        with self._lock:
            self._running = False
        # batch totals: `words` counts every cue written, `secs` the whole
        # run, `srt` the last file's primary output (srt, or vtt when the
        # SRT format is switched off).
        q.put(("done", {"outdir": args["outdir"], "srt": last_out,
                        "words": words_total, "secs": round(secs, 2)}))
        q.put(("state", self._state()))

    @staticmethod
    def _finish_formats(res, formats, q):
        """Honor settings.formats: optional .vtt twin, optional .srt drop."""
        srt = res.get("srt")
        if not srt:
            return ""
        out = srt
        if formats.get("vtt"):
            vtt = os.path.splitext(srt)[0] + ".vtt"
            try:
                _srt_to_vtt(srt, vtt)
                q.put(("log", "   WEBVTT: %s" % os.path.basename(vtt)))
                out = vtt
            except Exception as e:  # noqa: BLE001
                # keep the SRT — a failed conversion must not lose output
                q.put(("log", "   warn: VTT ناموفق بود: %s" % e))
                return srt
        if not formats.get("srt") and out != srt:
            try:
                os.remove(srt)
            except OSError:
                pass
        return out


def boot():
    api = Api()
    width, height = _window_size()
    index = os.path.join(_base, "web_dist", "index.html")
    # pywebview serves local urls from its built-in http server rooted at
    # the file's directory (vite.config.ts emits with base "./"), so an
    # absolute path here maps straight onto http://127.0.0.1:<port>/index.html
    if os.path.isfile(index):
        _bc("loading %s" % index)
        window = webview.create_window(
            TITLE, url=index, js_api=api, width=width, height=height,
            min_size=(600, 460), background_color="#1B1B1B")
    else:
        _bc("web_dist/index.html missing — placeholder "
            "(build with: cd web && npm run build)")
        window = webview.create_window(
            TITLE, html=_PLACEHOLDER_HTML, js_api=api, width=width,
            height=height, min_size=(600, 460), background_color="#1B1B1B")
    api._attach(window)
    webview.start(debug=os.environ.get("SUBSAZ_WEB_DEBUG") == "1")
    _bc("web stopped")


if __name__ == "__main__":
    try:
        boot()
    except Exception:
        _bc("FATAL: " + repr(traceback.format_exc()))
        raise
