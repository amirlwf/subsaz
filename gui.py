"""ساب‌ساز GUI — CustomTkinter desktop app: media in, precise SRT out."""
import ctypes
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
    return os.path.abspath(__file__) and os.path.dirname(
        os.path.abspath(__file__))


_base = _app_base()
_exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_exe_dir, "gui_started.log")


def _bc(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


_bc("=== boot start (frozen=%s) ===" % bool(getattr(sys, "frozen", False)))

# Register bundled Persian font (Windows) so it works without installing.
FONT_FAMILY = "Segoe UI"


def _register_font():
    global FONT_FAMILY
    try:
        if os.name == "nt":
            ok = 0
            for _f in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"):
                ttf = os.path.join(_base, "assets", "fonts", _f)
                if os.path.isfile(ttf):
                    # returns number of fonts added (>0 on success)
                    ok += ctypes.windll.gdi32.AddFontResourceExW(ttf, 0x10, 0)
            if ok >= 2:
                FONT_FAMILY = "Vazirmatn"
                _bc("font registered: Vazirmatn (regular+bold)")
                return
            _bc("font register partial: %d" % ok)
    except Exception as e:  # noqa: BLE001
        _bc("font register failed: %r" % e)
    # fall back to a system font with good Persian shaping
    import tkinter.font as _tkfont
    for cand in ("Vazirmatn", "Segoe UI", "Tahoma"):
        try:
            if cand.lower() in {f.lower() for f in _tkfont.families()}:
                FONT_FAMILY = cand
                break
        except Exception:  # noqa: BLE001
            break
    _bc("font family: %s" % FONT_FAMILY)


import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from app import config as app_config
from app import bidi as bidi_helper
from app import hardware, model_manager
from app import transcribe as engine

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MODELS = ("auto", "large-v3-turbo", "medium", "small", "base", "tiny")
MODEL_MB = {"auto": 0, "large-v3-turbo": 1600, "medium": 1500,
            "small": 460, "base": 145, "tiny": 75}

# ---- Iranian palette: firoozeh / lajvard / saffron / pomegranate ----
TEAL = "#15919B"          # firoozeh — primary actions
TEAL_HOVER = "#0E6E76"
TEAL_TEXT = ("#0E6E76", "#5AD6DE")     # headings in light/dark mode
SAFFRON = "#D98E1B"       # zafaran — active segment
SAFFRON_TEXT = ("#9C6B0F", "#F0B43C")  # section titles
BORDO = "#A93226"         # anari — cancel/danger
BORDO_HOVER = "#7B241C"
SEG_OFF = ("#D8D8D8", "#4A4A4A")
SEG_OFF_TEXT = ("#333333", "#DDDDDD")
CARD = ("#FFFFFF", "#262626")          # section cards
ROOT_BG = ("#F4EEE1", "#1B1B1B")       # parchment / warm dark


class App:
    def __init__(self, root=None):
        _bc("App.__init__ begin")
        self.cfg = app_config.load()
        self.root = root or ctk.CTk()
        self.root.title("ساب‌ساز — زیرنویس دقیق کلمه‌به‌کلمه")
        # screen-aware: never open bigger than the display can show
        try:
            _sw = self.root.winfo_screenwidth()
            _sh = self.root.winfo_screenheight()
        except Exception:  # noqa: BLE001
            _sw, _sh = 1920, 1080
        self.root.geometry("%dx%d" % (min(820, int(_sw * 0.88)),
                                      min(700, int(_sh * 0.84))))
        self.root.minsize(600, 460)
        try:
            self.root.configure(fg_color=ROOT_BG)
        except Exception:  # noqa: BLE001
            pass
        self.q = queue.Queue()
        self.running = False
        self.downloading = False
        self.profile = None
        self._cancel = threading.Event()
        self._ensure_font()
        self._set_window_icon()
        self._build()
        self.root.after(120, self._poll)
        # hardware scan in background so the UI opens instantly
        threading.Thread(target=self._scan_hw, daemon=True).start()

    # ---------- fonts ----------
    def _font(self, size=13, bold=False):
        return (FONT_FAMILY, size, "bold" if bold else "normal")

    def _ensure_font(self):
        """After the Tk root exists, confirm the family is usable."""
        global FONT_FAMILY
        try:
            import tkinter.font as _tkfont
            fams = {f.lower() for f in _tkfont.families()}
            if "vazirmatn" in fams:
                FONT_FAMILY = "Vazirmatn"
            elif FONT_FAMILY.lower() not in fams:
                for cand in ("Segoe UI", "Tahoma"):
                    if cand.lower() in fams:
                        FONT_FAMILY = cand
                        break
        except Exception:  # noqa: BLE001
            pass
        _bc("ui font family: %s" % FONT_FAMILY)

    def _icon_path(self, name):
        """Logo asset path that works in dev AND frozen (dist/_internal)."""
        for cand in (os.path.join(_base, "assets", name),
                     os.path.join(_exe_dir, "assets", name),
                     os.path.join(_exe_dir, "_internal", "assets", name)):
            if os.path.isfile(cand):
                return cand
        return None

    def _set_window_icon(self):
        """Taskbar + title-bar logo (release builds showed default Tk icon).

        The EXE icon (spec) and installer icon (.iss) only cover Explorer;
        the running window needs iconbitmap/iconphoto explicitly.
        """
        try:
            ico = self._icon_path("icon.ico")
            png = self._icon_path("icon.png")
            if ico and os.name == "nt":
                try:
                    self.root.iconbitmap(default=ico)
                except Exception:  # noqa: BLE001
                    _bc("iconbitmap failed")
            if png:
                try:
                    _ph = tk.PhotoImage(file=png)
                    # keep a ref for the life of the app
                    self._win_icon_ref = _ph
                    self.root.iconphoto(True, _ph)
                except Exception:  # noqa: BLE001
                    _bc("iconphoto failed")
        except Exception:  # noqa: BLE001
            _bc("window icon failed")

    # ---------- layout ----------
    def _build(self):
        r = self.root

        head = ctk.CTkFrame(r, fg_color=CARD)
        head.pack(fill="x", padx=8, pady=(8, 3))
        # in-app logo (assets/icon.png), text-only fallback.
        # Plain tk.Label (not CTkLabel): no PIL/CTkImage dependency, and no
        # HighDPI-scaling warning — bg is synced to the card in both modes.
        self._logo_ref = None
        self._logo_label = None
        try:
            _lp = self._icon_path("icon.png")
            if _lp:
                _img = tk.PhotoImage(file=_lp)
                _k = max(1, round(max(_img.width(), _img.height()) / 52))
                _img = _img.subsample(_k, _k)
                self._logo_ref = _img
                self._logo_label = tk.Label(
                    head, image=_img, bg=self._card_bg(), borderwidth=0,
                    highlightthickness=0)
                self._logo_label.pack(side="right", padx=(10, 0), pady=6)
        except Exception:  # noqa: BLE001
            _bc("logo load failed")
        # RTL: primary content from the right
        ctk.CTkLabel(head, text="ساب‌ساز", text_color=TEAL_TEXT,
                     font=self._font(18, True)).pack(side="right", padx=10,
                                                    pady=6)
        ctk.CTkLabel(
            head, text="ویدیو یا صوت بده، فایل SRT دقیق بگیر",
            font=self._font(12)).pack(side="right", padx=4)
        self.theme_btn = ctk.CTkButton(head, text="☀ / 🌙", width=70,
                                       font=self._font(12),
                                       command=self._toggle_theme)
        self.theme_btn.pack(side="left", padx=12)

        # Scrollable body: every card below lives here, so a short window
        # can still reach all content (was the "can't scroll" bug — cards
        # were packed straight onto the root with a fixed oversized geom).
        body = ctk.CTkScrollableFrame(r, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=4, pady=(0, 6))
        r = body

        # 1. files
        files = ctk.CTkFrame(r, fg_color=CARD)
        files.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(files, text="۱. فایل‌ها (ویدیو یا صوت)",
                     text_color=SAFFRON_TEXT,
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        brow = ctk.CTkFrame(files, fg_color="transparent")
        brow.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(brow, text="+ فایل‌ها", font=self._font(12),
                      fg_color=TEAL, hover_color=TEAL_HOVER,
                      command=self._pick_files).pack(side="right", padx=4)
        ctk.CTkButton(brow, text="+ پوشه", font=self._font(12),
                      fg_color=TEAL, hover_color=TEAL_HOVER,
                      command=self._pick_folder).pack(side="right", padx=4)
        ctk.CTkButton(brow, text="پاک کردن", font=self._font(12),
                      fg_color="gray", command=self._clear).pack(side="right",
                                                                 padx=4)
        # listbox + scrollbar (plain tk: CTk has no Listbox; keep theme sync)
        lst_wrap = ctk.CTkFrame(files, fg_color="transparent")
        lst_wrap.pack(fill="x", padx=12, pady=(0, 4))
        self.lst = tk.Listbox(lst_wrap, height=4, activestyle="dotbox",
                              font=(FONT_FAMILY, 11),
                              bg="#2b2b2b", fg="#eee",
                              selectbackground=TEAL,
                              selectforeground="#fff",
                              highlightthickness=0, borderwidth=0,
                              exportselection=False)
        self.lst.pack(side="left", fill="x", expand=True)
        _lsb = tk.Scrollbar(lst_wrap, command=self.lst.yview,
                            width=10, takefocus=0,
                            highlightthickness=0, borderwidth=0)
        _lsb.pack(side="right", fill="y")
        self.lst.configure(yscrollcommand=_lsb.set)

        def _lst_wheel(e):
            # stop CTkScrollableFrame's bind_all from ALSO scrolling the
            # page while the wheel is over the list (double-scroll bug).
            self.lst.yview_scroll(-1 if e.delta > 0 else 1, "units")
            return "break"

        self.lst.bind("<MouseWheel>", _lst_wheel)
        self._dnd_hook()
        ctk.CTkLabel(files, text="فرمت‌ها: mp4 mov mkv webm … + mp3 wav m4a aac flac ogg opus wma",
                     font=self._font(10), text_color="gray").pack(anchor="e",
                                                                  padx=12,
                                                                  pady=(0, 6))

        # 2. system & model
        hw = ctk.CTkFrame(r, fg_color=CARD)
        hw.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(hw, text="۲. سیستم و مدل",
                     text_color=SAFFRON_TEXT,
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        self.hw_label = ctk.CTkLabel(hw, text="در حال اسکن سیستم…",
                                     font=self._font(11), wraplength=560,
                                     justify="right")
        self.hw_label.pack(anchor="e", padx=12, pady=2)
        self.rec_label = ctk.CTkLabel(hw, text="", font=self._font(12, True),
                                      wraplength=560, justify="right")
        self.rec_label.pack(anchor="e", padx=12, pady=2)
        mrow = ctk.CTkFrame(hw, fg_color="transparent")
        mrow.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(mrow, text="مدل:", font=self._font(12),
                     justify="right").pack(side="right", padx=4)
        self.model_var = tk.StringVar(value=self.cfg.get("model", "auto"))
        self.model_box = ctk.CTkComboBox(mrow, variable=self.model_var,
                                         values=list(MODELS), width=150,
                                         font=self._font(11),
                                         command=self._on_model_change)
        self.model_box.pack(side="right", padx=4)
        self.dl_btn = ctk.CTkButton(mrow, text="⬇ دانلود مدل",
                                    font=self._font(12),
                                    fg_color=TEAL, hover_color=TEAL_HOVER,
                                    command=self._download_model)
        self.dl_btn.pack(side="right", padx=4)
        ctk.CTkButton(mrow, text="🔄 اسکن مجدد", font=self._font(12),
                      fg_color="gray",
                      command=self._rescan).pack(side="right", padx=4)
        # hidden until a download starts — idle bar was wasted height
        self.dl_prog = ctk.CTkProgressBar(mrow, width=120,
                                          progress_color=TEAL)
        self.dl_prog.set(0)

        def _hide_dl_prog():
            # a new download may have started during the delay
            if not self.downloading:
                self.dl_prog.pack_forget()

        self._dl_prog_forget = _hide_dl_prog

        # 3. subtitle settings
        st = ctk.CTkFrame(r, fg_color=CARD)
        st.pack(fill="x", padx=8, pady=3)
        ctk.CTkLabel(st, text="۳. تنظیمات زیرنویس",
                     text_color=SAFFRON_TEXT,
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        g = ctk.CTkFrame(st, fg_color="transparent")
        g.pack(fill="x", padx=8, pady=4)

        # RTL grid: column 4 = rightmost (first item starts at right)
        ctk.CTkLabel(g, text="زبان:", font=self._font(12),
                     justify="right").grid(row=0, column=4, padx=4, sticky="e")
        self.lang_var = tk.StringVar(value=self.cfg.get("lang", "en"))
        ctk.CTkComboBox(g, variable=self.lang_var, values=("en", "fa", "auto"),
                        width=80, font=self._font(12),
                        command=self._on_setting_change).grid(
                            row=0, column=3, padx=4)

        ctk.CTkLabel(g, text="حالت: (مثل کپشن پریمیر)", font=self._font(12),
                     justify="right").grid(row=0, column=2, padx=4, sticky="e")
        # Premiere-style lines-per-cue segmented control (1 / 2 / 3 lines)
        self.lines_n = {"single": 1, "two": 2, "three": 3}.get(
            self.cfg.get("mode", "single"), 1)
        segf = ctk.CTkFrame(g, fg_color="transparent")
        segf.grid(row=0, column=0, columnspan=2, padx=4, sticky="w")
        self.seg_btns = {}
        for _n, _t in ((1, "۱ خط"), (2, "۲ خط"), (3, "۳ خط")):
            _b = ctk.CTkButton(segf, text=_t, width=58, font=self._font(11),
                               command=lambda n=_n: self._set_lines(n))
            _b.pack(side="right", padx=2)
            self.seg_btns[_n] = _b

        # sliders: words/line + chars/line, synced into words_var/chars_var
        # so the save/run paths below stay unchanged
        self.words_var = tk.StringVar(
            value=str(self.cfg.get("words_per_line", 3)))
        srow1 = ctk.CTkFrame(st, fg_color="transparent")
        srow1.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(srow1, text="کلمه/خط:", font=self._font(12)).pack(
            side="right", padx=4)
        self.words_val = ctk.CTkLabel(srow1, text=self.words_var.get(),
                                      font=self._font(12, True), width=28)
        self.words_val.pack(side="left", padx=4)
        self.words_slider = ctk.CTkSlider(srow1, from_=1, to=6,
                                          number_of_steps=5,
                                          progress_color=TEAL,
                                          button_color=TEAL,
                                          button_hover_color=TEAL_HOVER,
                                          command=self._on_words_slider)
        self.words_slider.pack(side="right", padx=4, fill="x", expand=True)
        try:
            self.words_slider.set(max(1, min(6, int(self.words_var.get()))))
        except ValueError:
            self.words_slider.set(3)

        self.chars_var = tk.StringVar(
            value=str(self.cfg.get("max_chars", 32)))
        srow2 = ctk.CTkFrame(st, fg_color="transparent")
        srow2.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(srow2, text="حروف/خط:", font=self._font(12)).pack(
            side="right", padx=4)
        self.chars_val = ctk.CTkLabel(srow2, text=self.chars_var.get(),
                                      font=self._font(12, True), width=28)
        self.chars_val.pack(side="left", padx=4)
        self.chars_slider = ctk.CTkSlider(srow2, from_=20, to=50,
                                          number_of_steps=15,
                                          progress_color=TEAL,
                                          button_color=TEAL,
                                          button_hover_color=TEAL_HOVER,
                                          command=self._on_chars_slider)
        self.chars_slider.pack(side="right", padx=4, fill="x", expand=True)
        try:
            _cv = max(20, min(50, int(self.chars_var.get())))
        except ValueError:
            _cv = 32
        self.chars_slider.set(_cv)

        ctk.CTkLabel(g, text="گپ (ثانیه):", font=self._font(12),
                     justify="right").grid(row=1, column=4, padx=4, pady=3,
                                           sticky="e")
        self.gap_var = tk.StringVar(value=str(self.cfg.get("max_gap", 0.8)))
        ctk.CTkEntry(g, textvariable=self.gap_var, width=70,
                     font=self._font(12), justify="right").grid(
                         row=1, column=3, padx=4, pady=3)
        ctk.CTkLabel(g, text="مکث (ثانیه):", font=self._font(12),
                     justify="right").grid(row=1, column=2, padx=4, pady=3,
                                           sticky="e")
        self.hold_var = tk.StringVar(value=str(self.cfg.get("hold", 1.0)))
        ctk.CTkEntry(g, textvariable=self.hold_var, width=70,
                     font=self._font(12), justify="right").grid(
                         row=1, column=1, padx=4, pady=3)

        prow = ctk.CTkFrame(st, fg_color="transparent")
        prow.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(prow, text="کلمات خاص:",
                     font=self._font(12)).pack(side="right", padx=4)
        self.prompt_var = tk.StringVar(value=self.cfg.get("prompt", ""))
        self.prompt_entry = ctk.CTkEntry(
            prow, textvariable=self.prompt_var, width=240,
            font=self._font(12), justify="right",
            placeholder_text="مثلا: WordLab, BrandX")
        self.prompt_entry.pack(side="right", padx=4)
        self.prompt_var.trace_add("write", lambda *_: self._prompt_preview())
        ctk.CTkLabel(prow, text="خروجی:",
                     font=self._font(12)).pack(side="right", padx=(12, 4))
        self.out_var = tk.StringVar(value=self.cfg.get("outdir", ""))
        ctk.CTkEntry(prow, textvariable=self.out_var, width=180,
                     font=self._font(12)).pack(side="right", padx=4, fill="x",
                                               expand=True)
        ctk.CTkButton(prow, text="…", width=40, font=self._font(12),
                      command=self._pick_out).pack(side="right", padx=4)
        # Echo of the prompt with BiDi isolates: what the user typed can
        # look shuffled inside a plain Entry (numbers/Latin jump sides),
        # so show the corrected rendering underneath while typing.
        self.prompt_echo = ctk.CTkLabel(
            st, text="", font=self._font(11), text_color="gray",
            justify="right", wraplength=540)
        self.prompt_echo.pack(anchor="e", padx=12, pady=(0, 2))

        # 4. run
        run = ctk.CTkFrame(r, fg_color=CARD)
        run.pack(fill="x", padx=8, pady=3)
        self.btn = ctk.CTkButton(run, text="▶  ساخت زیرنویس (SRT)",
                                 font=self._font(13, True),
                                 fg_color=TEAL, hover_color=TEAL_HOVER,
                                 command=self._start)
        self.btn.pack(side="right", padx=6, pady=6)
        self.cancel_btn = ctk.CTkButton(run, text="■ لغو", width=80,
                                        fg_color=BORDO,
                                        hover_color=BORDO_HOVER,
                                        font=self._font(12),
                                        state="disabled",
                                        command=self._cancel_run)
        self.cancel_btn.pack(side="right", padx=4)
        ctk.CTkButton(run, text="باز کردن پوشه خروجی", fg_color="gray",
                      font=self._font(12),
                      command=self._open_out).pack(side="right", padx=4)
        self.status = ctk.CTkLabel(run, text="", font=self._font(12))
        self.status.pack(side="left", padx=8)
        self.prog = ctk.CTkProgressBar(run, width=140,
                                        progress_color=TEAL)
        self.prog.pack(side="left", padx=4)
        self.prog.set(0)

        # log
        logf = ctk.CTkFrame(r, fg_color=CARD)
        logf.pack(fill="x", padx=8, pady=(3, 8))
        ctk.CTkLabel(logf, text="گزارش",
                     text_color=SAFFRON_TEXT,
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(6, 0))
        self.log = ctk.CTkTextbox(logf, height=72,
                                  font=self._font(11))
        self.log.pack(fill="x", padx=8, pady=(0, 6))
        self._log("آماده. اول «اسکن سیستم» را ببین، بعد مدل را دانلود کن.")
        self._paint_seg()
        try:
            self._prompt_preview()
        except Exception:  # noqa: BLE001
            pass

    # ---------- theme ----------
    @staticmethod
    def _card_bg():
        return "#FFFFFF" if ctk.get_appearance_mode() == "Light" \
            else "#262626"

    def _toggle_theme(self):
        mode = "light" if ctk.get_appearance_mode() == "Dark" else "dark"
        ctk.set_appearance_mode(mode)
        if self._logo_label is not None:
            try:
                self._logo_label.configure(bg=self._card_bg())
            except Exception:  # noqa: BLE001
                pass
        # plain-tk Listbox doesn't follow CTk theme — sync it manually
        try:
            if mode == "light":
                self.lst.configure(bg="#f0f0f0", fg="#111",
                                   selectbackground=TEAL,
                                   selectforeground="#fff")
            else:
                self.lst.configure(bg="#2b2b2b", fg="#eee",
                                   selectbackground=TEAL,
                                   selectforeground="#fff")
        except Exception:  # noqa: BLE001
            pass

    # ---------- log / poll ----------
    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _poll(self):
        # NOTE: after() is rescheduled in finally — a single bad message
        # must never kill the whole UI update loop.
        try:
            while True:
                try:
                    kind, data = self.q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_q(kind, data)
                except Exception:  # noqa: BLE001
                    _bc("poll handler failed: "
                        + repr(traceback.format_exc()[-500:]))
        finally:
            self.root.after(120, self._poll)

    def _handle_q(self, kind, data):
        if kind == "log":
            self._log(data)
        elif kind == "warn":
            # shown here (main thread) — tkinter dialogs are NOT
            # thread-safe, workers must queue warnings, not show them.
            title, msg = data
            try:
                messagebox.showwarning(title, msg)
            except Exception:  # noqa: BLE001
                self._log("⚠ %s" % msg)
        elif kind == "status":
            self.status.configure(text=data)
        elif kind == "dl_prog":
            try:
                self.dl_prog.set(max(0.0, min(1.0, float(data))))
            except (TypeError, ValueError):
                pass
        elif kind == "prog":
            # determinate overall batch progress 0..1 — garbage never
            # raises inside the poll loop (bad worker data is ignored).
            try:
                v = max(0.0, min(1.0, float(data)))
            except (TypeError, ValueError):
                return
            self.prog.configure(mode="determinate")
            self.prog.set(v)
        elif kind == "prog_start":
            self.prog.configure(mode="determinate")
            self.prog.set(0)
        elif kind == "prog_stop":
            try:
                self.prog.stop()
            except Exception:  # noqa: BLE001
                pass
            self.prog.set(1)
        elif kind == "hw":
            self._show_hw(data)
        elif kind == "dl_done":
            self.downloading = False
            self.dl_btn.configure(state="normal")
            # data = success; only a finished download fills the bar
            self.dl_prog.set(1 if data else 0)
            try:
                self.root.after(600, self._dl_prog_forget)
            except Exception:  # noqa: BLE001
                pass
            self._refresh_rec()
        elif kind == "done":
            self.running = False
            self.btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")

    # ---------- hardware ----------
    def _scan_hw(self):
        try:
            self.profile = hardware.classify()
            self.q.put(("hw", self.profile))
        except Exception as e:  # noqa: BLE001
            self.q.put(("log", "خطا در اسکن سیستم: %s" % e))

    def _rescan(self):
        self.hw_label.configure(text="در حال اسکن سیستم…")
        threading.Thread(target=self._scan_hw, daemon=True).start()

    def _show_hw(self, prof):
        self.hw_label.configure(text=hardware.describe_fa(prof))
        self._refresh_rec()

    def _rec_for(self, model, lang):
        if model == "auto":
            if self.profile is None:
                # scan still running — never block the UI thread with
                # classify() here (wmic/nvidia-smi can take seconds).
                return None, None
            rec = hardware.recommend(lang, self.profile)
            return rec["model"], rec
        return model, None

    def _need_profile(self):
        """True when the hardware scan hasn't finished yet."""
        if self.profile is None:
            messagebox.showwarning(
                "ساب‌ساز", "اسکن سیستم هنوز تمام نشده — یک لحظه صبر کن.")
            return True
        return False

    def _refresh_rec(self):
        lang = self.lang_var.get()
        model = self.model_var.get()
        name, rec = self._rec_for(model, lang)
        if name is None:
            self.rec_label.configure(text="در حال اسکن سیستم…")
            return
        if rec:
            extra = " — %s" % rec["reason_fa"] if rec.get("reason_fa") else ""
            self.rec_label.configure(
                text="مدل پیشنهادی برای این سیستم: %s (~%dMB)%s"
                     % (name, rec["mb"], extra))
        else:
            mb = MODEL_MB.get(name, 0)
            self.rec_label.configure(
                text="مدل انتخابی: %s%s"
                     % (name, " (~%dMB)" % mb if mb else ""))
        cached = model_manager.is_cached(name)
        self.dl_btn.configure(
            text="✓ دانلود شده" if cached else "⬇ دانلود مدل (%s)" % name)

    def _on_model_change(self, _value=None):
        self._save_cfg()
        self._refresh_rec()

    def _on_setting_change(self, _value=None):
        # lang combo: persist immediately, keep the model recommendation
        # in sync (lang affects the auto pick).
        self._save_cfg()
        self._refresh_rec()

    def _mode_name(self):
        return {1: "single", 2: "two", 3: "three"}[self.lines_n]

    def _set_lines(self, n):
        self.lines_n = n
        self._paint_seg()
        self._save_cfg()

    def _paint_seg(self):
        for n, b in self.seg_btns.items():
            try:
                if n == self.lines_n:
                    b.configure(fg_color=SAFFRON, hover_color=SAFFRON,
                                text_color="#1A1A1A")
                else:
                    b.configure(fg_color=SEG_OFF, text_color=SEG_OFF_TEXT)
            except Exception:  # noqa: BLE001
                pass

    def _on_words_slider(self, v):
        w = max(1, min(6, int(round(float(v)))))
        self.words_var.set(str(w))
        self.words_val.configure(text=str(w))
        self._save_cfg()

    def _on_chars_slider(self, v):
        c = max(20, min(50, int(round(float(v) / 2.0)) * 2))
        self.chars_var.set(str(c))
        self.chars_val.configure(text=str(c))
        self._save_cfg()

    # ---------- model download ----------
    def _download_model(self):
        if self.downloading:
            return
        lang = self.lang_var.get()
        name, _rec = self._rec_for(self.model_var.get(), lang)
        if name is None:
            self._need_profile()
            return
        if model_manager.is_cached(name):
            messagebox.showinfo("ساب‌ساز", "مدل %s قبلا دانلود شده." % name)
            return
        if not messagebox.askyesno(
                "ساب‌ساز",
                "مدل %s (~%dMB) دانلود شود؟\n(فقط یک‌بار، برای استفاده آفلاین)"
                % (name, MODEL_MB.get(name, 0))):
            return
        self.downloading = True
        self.dl_btn.configure(state="disabled")
        self.dl_prog.pack(side="left", padx=8, pady=2)
        self.dl_prog.set(0)
        threading.Thread(target=self._dl_worker, args=(name,),
                         daemon=True).start()

    def _dl_worker(self, name):
        q = self.q
        q.put(("log", "دانلود مدل %s شروع شد…" % name))
        ok = False
        try:
            model_manager.download(
                name,
                progress_cb=lambda d, t: q.put(("dl_prog", d / max(t, 1))),
                log=lambda m: q.put(("log", m)))
            ok = True
            q.put(("log", "✓ مدل %s آماده است." % name))
        except model_manager.ModelDownloadError as e:
            if e.need_vpn:
                q.put(("log", "✗ " + model_manager.VPN_MESSAGE_FA.replace(
                    "\n", " ")))
                # main thread shows the dialog (tkinter isn't thread-safe)
                q.put(("warn", ("ساب‌ساز — خطای دانلود",
                                model_manager.VPN_MESSAGE_FA)))
            else:
                q.put(("log", "✗ دانلود ناموفق: %s" % e))
        except Exception as e:  # noqa: BLE001
            q.put(("log", "✗ دانلود ناموفق: %s" % e))
        # success flag: a failed download must never show 100% on the bar
        q.put(("dl_done", ok))

    # ---------- file picking ----------
    def _pick_files(self):
        files = filedialog.askopenfilenames(
            title="انتخاب ویدیو یا صوت",
            filetypes=[("Media", "*.mp4 *.mov *.mkv *.webm *.ts *.flv *.wmv "
                        "*.avi *.m4v *.mpg *.mpeg *.3gp *.3g2 *.mp3 *.wav "
                        "*.m4a *.aac *.flac *.ogg *.opus *.wma"),
                       ("All files", "*.*")])
        for f in files:
            if f not in self.lst.get(0, "end"):
                self.lst.insert("end", f)

    def _pick_folder(self):
        d = filedialog.askdirectory(title="انتخاب پوشه")
        if d:
            self._pick_folder_into(d)

    def _pick_folder_into(self, d):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(engine.ALL_EXTS):
                p = os.path.join(d, f)
                if p not in self.lst.get(0, "end"):
                    self.lst.insert("end", p)

    def _clear(self):
        self.lst.delete(0, "end")

    def _pick_out(self):
        d = filedialog.askdirectory(title="پوشه ذخیره خروجی (SRT)")
        if d:
            self.out_var.set(d)
            self._save_cfg()

    def _open_out(self):
        d = self.out_var.get()
        if d and os.path.isdir(d):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(d)
                elif sys.platform == "darwin":
                    subprocess.run(["open", d], check=False)
                else:
                    subprocess.run(["xdg-open", d], check=False)
            except Exception as e:  # noqa: BLE001
                messagebox.showwarning(
                    "ساب‌ساز", "باز کردن پوشه ناموفق بود: %s" % e)

    def _dnd_hook(self):
        # Real drag&drop on a plain CTk root: load tkdnd into this
        # interpreter, then register the (plain-tk) file list as target.
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            TkinterDnD.require(self.root)
            self.lst.drop_target_register(DND_FILES)
            self.lst.bind("<<Drop>>", self._on_drop)
            self._dnd = True
            _bc("dnd enabled")
        except Exception as e:  # noqa: BLE001 — DnD stays optional
            _bc("dnd unavailable: %r" % e)

    def _on_drop(self, event):
        import re as _re
        for p in _re.findall(r"\{.+?\}|\S+", event.data):
            p = p.strip("{}")
            if os.path.isdir(p):
                self._pick_folder_into(p)
            elif p.lower().endswith(engine.ALL_EXTS) \
                    and p not in self.lst.get(0, "end"):
                self.lst.insert("end", p)

    def _prompt_preview(self):
        """Live BiDi-corrected echo of the prompt entry (typing helper)."""
        try:
            raw = self.prompt_var.get()
        except Exception:  # noqa: BLE001
            return
        try:
            if raw and bidi_helper.contains_rtl(raw):
                self.prompt_echo.configure(
                    text="نمایش صحیح: " + bidi_helper.display(raw))
            else:
                self.prompt_echo.configure(text="")
        except Exception:  # noqa: BLE001
            pass

    # ---------- config ----------
    def _save_cfg(self):
        self.cfg.update({
            "lang": self.lang_var.get(),
            "model": self.model_var.get(),
            "mode": self._mode_name(),
            # Persian digits tolerated («۳» == 3)
            "words_per_line": bidi_helper.parse_int(
                self.words_var.get(),
                self.cfg.get("words_per_line", 3)),
            "max_chars": bidi_helper.parse_int(
                self.chars_var.get(), self.cfg.get("max_chars", 32)),
            "max_gap": bidi_helper.parse_float(
                self.gap_var.get() or 0.8, self.cfg.get("max_gap", 0.8)),
            "hold": bidi_helper.parse_float(
                self.hold_var.get() or 1.0, self.cfg.get("hold", 1.0)),
            "prompt": self.prompt_var.get(),
            "outdir": self.out_var.get(),
        })
        app_config.save(self.cfg)

    # ---------- run ----------
    def _start(self):
        if self.running:
            return
        files = list(self.lst.get(0, "end"))
        if not files:
            messagebox.showwarning("ساب‌ساز", "اول فایل انتخاب کن.")
            return
        outdir = self.out_var.get().strip()
        if not outdir or not os.path.isdir(outdir):
            messagebox.showwarning("ساب‌ساز", "پوشه ذخیره خروجی را انتخاب کن.")
            return
        try:
            words = bidi_helper.parse_int(self.words_var.get(), None)
            max_chars = bidi_helper.parse_int(self.chars_var.get(), None)
            max_gap = bidi_helper.parse_float(
                self.gap_var.get() or 0.8, None)
            hold = bidi_helper.parse_float(self.hold_var.get() or 1.0, None)
            if words is None or max_chars is None \
                    or max_gap is None or hold is None:
                raise ValueError("bad numeric setting")
        except ValueError:
            messagebox.showwarning(
                "ساب‌ساز",
                "تنظیمات عددی معتبر نیست. (ارقام فارسی هم قبول است: ۳، ۰٫۸)")
            return
        if not 1 <= words <= 6:
            messagebox.showwarning("ساب‌ساز", "کلمه/خط باید بین ۱ تا ۶ باشد.")
            return
        if not 20 <= max_chars <= 50:
            messagebox.showwarning("ساب‌ساز", "حروف/خط باید بین ۲۰ تا ۵۰ باشد.")
            return
        if max_gap <= 0 or hold < 0:
            messagebox.showwarning("ساب‌ساز", "گپ باید مثبت و مکث نامنفی باشد.")
            return
        lang = self.lang_var.get()
        model = self.model_var.get()
        name, _rec = self._rec_for(model, lang)
        if name is None:
            self._need_profile()
            return
        # auto: the engine itself picks the best *cached* model, so only a
        # machine with nothing downloaded has to hit the download button.
        model_ready = bool(model_manager.cached_models()) if model == "auto" \
            else model_manager.is_cached(name)
        if not model_ready:
            messagebox.showwarning(
                "ساب‌ساز",
                "مدل %s هنوز دانلود نشده.\nاول «دانلود مدل» را بزن." % name)
            return
        self._save_cfg()
        self.running = True
        self._cancel.clear()
        self.btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.q.put(("prog_start", None))
        args = dict(outdir=outdir, lang=lang, model=model, words=words,
                    max_chars=max_chars, max_gap=max_gap, hold=hold,
                    mode=self._mode_name(),
                    prompt=self.prompt_var.get() or None,
                    profile=self.profile)
        threading.Thread(target=self._worker, args=(files, args, model),
                         daemon=True).start()

    def _cancel_run(self):
        if not self.running:
            return
        self._cancel.set()
        self.cancel_btn.configure(state="disabled")
        self.q.put(("log", "■ لغو درخواست شد… (توقف بعد از بخش فعلی)"))

    def _worker(self, files, args, disp_model):
        q = self.q
        t0 = time.time()
        q.put(("log",
               "در حال لود مدل… (اولین بار کمی طول می‌کشد)"
               if disp_model == "auto"
               else "مدل %s در حال لود… (اولین بار کمی طول می‌کشد)"
                    % disp_model))
        ok = 0
        cancelled = False
        total = len(files)
        # coarse per-stage weights inside one file: audio 10%, transcribe 80%,
        # subtitle 10% — honest about being stage-based, not byte-based.
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
                q.put(("prog", frac))

            try:
                if engine.process_file(
                        path, log=lambda m: q.put(("log", m)),
                        progress_cb=_cb, cancel_event=self._cancel,
                        **args):
                    ok += 1
                q.put(("prog", i / max(total, 1)))
            except engine.CancelledError:
                cancelled = True
                q.put(("log", "   ■ لغو شد: %s" % base))
                break
            except model_manager.ModelDownloadError as e:
                q.put(("log", "   FAILED: %s" % e))
                if e.need_vpn:
                    # main thread shows the dialog (tkinter isn't thread-safe)
                    q.put(("warn", ("ساب‌ساز — خطای دانلود",
                                    model_manager.VPN_MESSAGE_FA)))
            except Exception as e:  # noqa: BLE001
                q.put(("log", "   FAILED: %s" % e))
                _bc("worker failed: " + repr(traceback.format_exc()))
        q.put(("prog_stop", None))
        q.put(("status", ""))
        if cancelled:
            q.put(("log", "== لغو شد: %d/%d فایل در %.1fs"
                   % (ok, total, time.time() - t0)))
        else:
            q.put(("log", "== تمام شد: %d/%d فایل در %.1fs — خروجی SRT"
                   % (ok, total, time.time() - t0)))
        q.put(("done", True))

    def run(self):
        self.root.mainloop()


def boot():
    try:
        _register_font()
    except Exception:  # noqa: BLE001
        pass
    # NOTE: drag&drop stays optional — if tkinterdnd2 is installed the
    # file list accepts drops (see _dnd_hook); otherwise buttons are used.
    # We intentionally boot on a plain CTk root because CTk widgets are
    # not compatible with a TkinterDnD.Tk root.
    try:
        _bc("boot: plain CTk")
        App().run()
    except Exception:
        _bc("boot: plain CTk failed: " + repr(traceback.format_exc()))
        try:
            messagebox.showerror("ساب‌ساز", traceback.format_exc()[-1500:])
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    try:
        boot()
    except Exception:
        _bc("FATAL: " + repr(traceback.format_exc()))
        raise
