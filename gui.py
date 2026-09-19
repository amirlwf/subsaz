"""ساب‌ساز GUI — CustomTkinter desktop app: media in, precise SRT out."""
import ctypes
import os
import queue
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
from app import hardware, model_manager
from app import transcribe as engine

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MODELS = ("auto", "large-v3-turbo", "medium", "small", "base", "tiny")
MODEL_MB = {"auto": 0, "large-v3-turbo": 1600, "medium": 1500,
            "small": 460, "base": 145, "tiny": 75}


class App:
    def __init__(self, root=None):
        _bc("App.__init__ begin")
        self.cfg = app_config.load()
        self.root = root or ctk.CTk()
        self.root.title("ساب‌ساز — زیرنویس دقیق کلمه‌به‌کلمه")
        self.root.geometry("860x760")
        self.root.minsize(760, 680)
        self.q = queue.Queue()
        self.running = False
        self.downloading = False
        self.profile = None
        self._ensure_font()
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

    # ---------- layout ----------
    def _build(self):
        r = self.root

        head = ctk.CTkFrame(r)
        head.pack(fill="x", padx=10, pady=(10, 4))
        # RTL: primary content from the right
        ctk.CTkLabel(head, text="ساب‌ساز",
                     font=self._font(20, True)).pack(side="right", padx=12,
                                                    pady=8)
        ctk.CTkLabel(
            head, text="ویدیو یا صوت بده، فایل SRT دقیق بگیر",
            font=self._font(12)).pack(side="right", padx=4)
        self.theme_btn = ctk.CTkButton(head, text="☀ / 🌙", width=70,
                                       font=self._font(12),
                                       command=self._toggle_theme)
        self.theme_btn.pack(side="left", padx=12)

        # 1. files
        files = ctk.CTkFrame(r)
        files.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(files, text="۱. فایل‌ها (ویدیو یا صوت)",
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        brow = ctk.CTkFrame(files, fg_color="transparent")
        brow.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(brow, text="+ فایل‌ها", font=self._font(12),
                      command=self._pick_files).pack(side="right", padx=4)
        ctk.CTkButton(brow, text="+ پوشه", font=self._font(12),
                      command=self._pick_folder).pack(side="right", padx=4)
        ctk.CTkButton(brow, text="پاک کردن", font=self._font(12),
                      fg_color="gray", command=self._clear).pack(side="right",
                                                                 padx=4)
        self.lst = tk.Listbox(files, height=5, activestyle="dotbox",
                              font=(FONT_FAMILY, 11),
                              bg="#2b2b2b", fg="#eee",
                              selectbackground="#1f6feb")
        self.lst.pack(fill="x", padx=12, pady=(0, 8))
        self._dnd_hook()
        ctk.CTkLabel(files, text="فرمت‌ها: mp4 mov mkv webm … + mp3 wav m4a aac flac ogg opus wma",
                     font=self._font(11), text_color="gray").pack(anchor="e",
                                                                  padx=12,
                                                                  pady=(0, 8))

        # 2. system & model
        hw = ctk.CTkFrame(r)
        hw.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(hw, text="۲. سیستم و مدل",
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        self.hw_label = ctk.CTkLabel(hw, text="در حال اسکن سیستم…",
                                     font=self._font(11), wraplength=780,
                                     justify="right")
        self.hw_label.pack(anchor="e", padx=12, pady=2)
        self.rec_label = ctk.CTkLabel(hw, text="", font=self._font(12, True),
                                      wraplength=780, justify="right")
        self.rec_label.pack(anchor="e", padx=12, pady=2)
        mrow = ctk.CTkFrame(hw, fg_color="transparent")
        mrow.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(mrow, text="مدل:", font=self._font(12),
                     justify="right").pack(side="right", padx=4)
        self.model_var = tk.StringVar(value=self.cfg.get("model", "auto"))
        self.model_box = ctk.CTkComboBox(mrow, variable=self.model_var,
                                         values=list(MODELS), width=170,
                                         font=self._font(12),
                                         command=self._on_model_change)
        self.model_box.pack(side="right", padx=4)
        self.dl_btn = ctk.CTkButton(mrow, text="⬇ دانلود مدل",
                                    font=self._font(12),
                                    command=self._download_model)
        self.dl_btn.pack(side="right", padx=4)
        ctk.CTkButton(mrow, text="🔄 اسکن مجدد", font=self._font(12),
                      fg_color="gray",
                      command=self._rescan).pack(side="right", padx=4)
        self.dl_prog = ctk.CTkProgressBar(mrow, width=160)
        self.dl_prog.pack(side="left", padx=8)
        self.dl_prog.set(0)

        # 3. subtitle settings
        st = ctk.CTkFrame(r)
        st.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(st, text="۳. تنظیمات زیرنویس",
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(8, 0))
        g = ctk.CTkFrame(st, fg_color="transparent")
        g.pack(fill="x", padx=8, pady=4)

        # RTL grid: column 4 = rightmost (first item starts at right)
        ctk.CTkLabel(g, text="زبان:", font=self._font(12),
                     justify="right").grid(row=0, column=4, padx=4, sticky="e")
        self.lang_var = tk.StringVar(value=self.cfg.get("lang", "en"))
        ctk.CTkComboBox(g, variable=self.lang_var, values=("en", "fa"),
                        width=80, font=self._font(12)).grid(row=0, column=3,
                                                            padx=4)

        ctk.CTkLabel(g, text="حالت:", font=self._font(12),
                     justify="right").grid(row=0, column=2, padx=4, sticky="e")
        self.mode_var = tk.StringVar(value=self.cfg.get("mode", "single"))
        ctk.CTkComboBox(g, variable=self.mode_var,
                        values=("single", "two"), width=100,
                        font=self._font(12)).grid(row=0, column=1, padx=4)
        ctk.CTkLabel(g, text="(two = دوخطی پریمیر)",
                     font=self._font(11), justify="right",
                     text_color="gray").grid(row=0, column=0, padx=4,
                                             sticky="e")

        ctk.CTkLabel(g, text="کلمه/خط:", font=self._font(12),
                     justify="right").grid(row=1, column=3, padx=4, pady=4,
                                           sticky="e")
        self.words_var = tk.StringVar(
            value=str(self.cfg.get("words_per_line", 3)))
        ctk.CTkComboBox(g, variable=self.words_var,
                        values=("1", "2", "3", "4", "5", "6"), width=80,
                        font=self._font(12)).grid(row=1, column=2, padx=4,
                                                  pady=4)

        ctk.CTkLabel(g, text="حروف/خط:", font=self._font(12),
                     justify="right").grid(row=1, column=1, padx=4, pady=4,
                                           sticky="e")
        self.chars_var = tk.StringVar(
            value=str(self.cfg.get("max_chars", 32)))
        ctk.CTkComboBox(g, variable=self.chars_var,
                        values=("20", "24", "28", "32", "36", "42", "50"),
                        width=80, font=self._font(12)).grid(row=1, column=0,
                                                            padx=4, pady=4)

        ctk.CTkLabel(g, text="گپ (ثانیه):", font=self._font(12),
                     justify="right").grid(row=2, column=3, padx=4, pady=4,
                                           sticky="e")
        self.gap_var = tk.StringVar(value=str(self.cfg.get("max_gap", 0.8)))
        ctk.CTkEntry(g, textvariable=self.gap_var, width=80,
                     font=self._font(12), justify="right").grid(
                         row=2, column=2, padx=4, pady=4)
        ctk.CTkLabel(g, text="مکث (ثانیه):", font=self._font(12),
                     justify="right").grid(row=2, column=1, padx=4, pady=4,
                                           sticky="e")
        self.hold_var = tk.StringVar(value=str(self.cfg.get("hold", 1.0)))
        ctk.CTkEntry(g, textvariable=self.hold_var, width=80,
                     font=self._font(12), justify="right").grid(
                         row=2, column=0, padx=4, pady=4)

        prow = ctk.CTkFrame(st, fg_color="transparent")
        prow.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(prow, text="کلمات خاص:",
                     font=self._font(12)).pack(side="right", padx=4)
        self.prompt_var = tk.StringVar(value=self.cfg.get("prompt", ""))
        ctk.CTkEntry(prow, textvariable=self.prompt_var, width=340,
                     font=self._font(12), justify="right",
                     placeholder_text="مثلا: WordLab, BrandX").pack(
                         side="right", padx=4)
        ctk.CTkLabel(prow, text="خروجی:",
                     font=self._font(12)).pack(side="right", padx=(12, 4))
        self.out_var = tk.StringVar(value=self.cfg.get("outdir", ""))
        ctk.CTkEntry(prow, textvariable=self.out_var, width=220,
                     font=self._font(12)).pack(side="right", padx=4, fill="x",
                                               expand=True)
        ctk.CTkButton(prow, text="…", width=40, font=self._font(12),
                      command=self._pick_out).pack(side="right", padx=4)

        # 4. run
        run = ctk.CTkFrame(r)
        run.pack(fill="x", padx=10, pady=4)
        self.btn = ctk.CTkButton(run, text="▶  ساخت زیرنویس (SRT)",
                                 font=self._font(14, True),
                                 command=self._start)
        self.btn.pack(side="right", padx=8, pady=8)
        ctk.CTkButton(run, text="باز کردن پوشه خروجی", fg_color="gray",
                      font=self._font(12),
                      command=self._open_out).pack(side="right", padx=4)
        self.status = ctk.CTkLabel(run, text="", font=self._font(12))
        self.status.pack(side="left", padx=8)
        self.prog = ctk.CTkProgressBar(run, width=140)
        self.prog.pack(side="left", padx=4)
        self.prog.set(0)

        # log
        logf = ctk.CTkFrame(r)
        logf.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        ctk.CTkLabel(logf, text="گزارش",
                     font=self._font(13, True)).pack(anchor="e", padx=12,
                                                    pady=(6, 0))
        self.log = ctk.CTkTextbox(logf, height=110,
                                  font=self._font(12))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self._log("آماده. اول «اسکن سیستم» را ببین، بعد مدل را دانلود کن.")

    # ---------- theme ----------
    def _toggle_theme(self):
        mode = "light" if ctk.get_appearance_mode() == "Dark" else "dark"
        ctk.set_appearance_mode(mode)

    # ---------- log / poll ----------
    def _log(self, msg):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "status":
                    self.status.configure(text=data)
                elif kind == "dl_prog":
                    self.dl_prog.set(data)
                elif kind == "prog_start":
                    self.prog.configure(mode="indeterminate")
                    self.prog.start()
                elif kind == "prog_stop":
                    self.prog.stop()
                    self.prog.set(0)
                elif kind == "hw":
                    self._show_hw(data)
                elif kind == "dl_done":
                    self.downloading = False
                    self.dl_btn.configure(state="normal")
                    self.dl_prog.set(1)
                    self._refresh_rec()
                elif kind == "done":
                    self.running = False
                    self.btn.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

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
            rec = hardware.recommend(lang, self.profile or
                                     hardware.classify())
            return rec["model"], rec
        return model, None

    def _refresh_rec(self):
        lang = self.lang_var.get()
        model = self.model_var.get()
        name, rec = self._rec_for(model, lang)
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

    # ---------- model download ----------
    def _download_model(self):
        if self.downloading:
            return
        lang = self.lang_var.get()
        name, _rec = self._rec_for(self.model_var.get(), lang)
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
        self.dl_prog.set(0)
        threading.Thread(target=self._dl_worker, args=(name,),
                         daemon=True).start()

    def _dl_worker(self, name):
        q = self.q
        q.put(("log", "دانلود مدل %s شروع شد…" % name))
        try:
            model_manager.download(
                name,
                progress_cb=lambda d, t: q.put(("dl_prog", d / max(t, 1))),
                log=lambda m: q.put(("log", m)))
            q.put(("log", "✓ مدل %s آماده است." % name))
        except model_manager.ModelDownloadError as e:
            if e.need_vpn:
                q.put(("log", "✗ " + model_manager.VPN_MESSAGE_FA.replace(
                    "\n", " ")))
                try:
                    messagebox.showwarning("ساب‌ساز — خطای دانلود",
                                           model_manager.VPN_MESSAGE_FA)
                except Exception:  # noqa: BLE001
                    pass
            else:
                q.put(("log", "✗ دانلود ناموفق: %s" % e))
        except Exception as e:  # noqa: BLE001
            q.put(("log", "✗ دانلود ناموفق: %s" % e))
        q.put(("dl_done", True))

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
            os.startfile(d)

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

    # ---------- config ----------
    def _save_cfg(self):
        try:
            self.cfg.update({
                "lang": self.lang_var.get(),
                "model": self.model_var.get(),
                "mode": self.mode_var.get(),
                "words_per_line": int(self.words_var.get()),
                "max_chars": int(self.chars_var.get()),
                "max_gap": float(self.gap_var.get() or 0.8),
                "hold": float(self.hold_var.get() or 1.0),
                "prompt": self.prompt_var.get(),
                "outdir": self.out_var.get(),
            })
        except ValueError:
            pass
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
            words = int(self.words_var.get())
            max_chars = int(self.chars_var.get())
            max_gap = float(self.gap_var.get() or 0.8)
            hold = float(self.hold_var.get() or 1.0)
        except ValueError:
            messagebox.showwarning("ساب‌ساز", "تنظیمات عددی معتبر نیست.")
            return
        lang = self.lang_var.get()
        model = self.model_var.get()
        name, _rec = self._rec_for(model, lang)
        if not model_manager.is_cached(name):
            messagebox.showwarning(
                "ساب‌ساز",
                "مدل %s هنوز دانلود نشده.\nاول «دانلود مدل» را بزن." % name)
            return
        self._save_cfg()
        self.running = True
        self.btn.configure(state="disabled")
        self.q.put(("prog_start", None))
        args = dict(outdir=outdir, lang=lang, model=model, words=words,
                    max_chars=max_chars, max_gap=max_gap, hold=hold,
                    mode=self.mode_var.get(),
                    prompt=self.prompt_var.get() or None,
                    profile=self.profile)
        threading.Thread(target=self._worker, args=(files, args),
                         daemon=True).start()

    def _worker(self, files, args):
        q = self.q
        t0 = time.time()
        q.put(("log", "مدل %s در حال لود… (اولین بار کمی طول می‌کشد)"
               % args["model"]))
        ok = 0
        for i, path in enumerate(files, 1):
            q.put(("status", "%d/%d" % (i, len(files))))
            q.put(("log", "== %s" % os.path.basename(path)))
            try:
                if engine.process_file(path, log=lambda m: q.put(("log", m)),
                                       **args):
                    ok += 1
            except model_manager.ModelDownloadError as e:
                q.put(("log", "   FAILED: %s" % e))
                if e.need_vpn:
                    try:
                        messagebox.showwarning(
                            "ساب‌ساز — خطای دانلود",
                            model_manager.VPN_MESSAGE_FA)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as e:  # noqa: BLE001
                q.put(("log", "   FAILED: %s" % e))
                _bc("worker failed: " + repr(traceback.format_exc()))
        q.put(("prog_stop", None))
        q.put(("status", ""))
        q.put(("log", "== تمام شد: %d/%d فایل در %.1fs — خروجی SRT"
               % (ok, len(files), time.time() - t0)))
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
