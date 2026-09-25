import {
  PREVIEW,
  call,
  installPush,
  on,
  whenBridge,
  type DonePayload,
  type SubsazState,
} from "./bridge";

const el = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing #${id}`);
  return node as T;
};

// Surface script failures in the app's own log — a silent boot failure
// would otherwise look like "the UI did nothing".
window.addEventListener("error", (e) => log(`js: ${e.message}`));
window.addEventListener("unhandledrejection", (e) =>
  log(`js: ${e.reason instanceof Error ? e.reason.message : String(e.reason)}`),
);

const fileEl = el<HTMLUListElement>("fileList");
const emptyEl = el<HTMLElement>("emptyHint");
const logEl = el<HTMLPreElement>("logBox");
const statusEl = el<HTMLSpanElement>("statusChip");
const themeBtn = el<HTMLButtonElement>("themeBtn");

/* ---------------- rendering ---------------- */

function log(line: string, cls = ""): void {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text: string, busy = false): void {
  statusEl.textContent = text;
  statusEl.classList.toggle("busy", busy);
}

function renderFiles(paths: string[]): void {
  fileEl.textContent = "";
  for (const [i, path] of paths.entries()) {
    const li = document.createElement("li");

    const idx = document.createElement("span");
    idx.className = "idx";
    idx.textContent = String(i + 1);

    const p = document.createElement("span");
    p.className = "path";
    p.textContent = path;
    p.title = path;

    const rm = document.createElement("button");
    rm.className = "rm";
    rm.title = "حذف";
    rm.textContent = "✕";
    rm.addEventListener("click", () => void call("remove_file", path));

    li.append(idx, p, rm);
    fileEl.appendChild(li);
  }
  const empty = paths.length === 0;
  fileEl.hidden = empty;
  emptyEl.hidden = !empty;
}

function renderModels(state: SubsazState): void {
  const select = el<HTMLSelectElement>("modelSelect");
  const current = select.value || state.hw.selected;
  select.textContent = "";
  for (const m of state.models) {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.label} (${m.size_label})${m.downloaded ? " ✓" : ""}`;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === current)) select.value = current;
  const picked = state.models.find((m) => m.id === select.value);
  const dl = el<HTMLButtonElement>("dlBtn");
  dl.textContent = picked?.downloaded ? "مدل دانلود شده ✓" : "دانلود مدل";
}

function renderHw(state: SubsazState): void {
  el<HTMLElement>("hwLine").textContent = state.hw.desc;
  el<HTMLElement>("recLine").textContent = state.models.find((m) => m.id === state.hw.rec)
    ? `مدل پیشنهادی: ${state.models.find((m) => m.id === state.hw.rec)?.label ?? ""}`
    : state.hw.rec;
}

function renderSettings(state: SubsazState): void {
  const s = state.settings;
  el<HTMLSelectElement>("language").value = s.language;
  el<HTMLSelectElement>("mode").value = s.mode;
  el<HTMLInputElement>("charsPerLine").value = String(s.chars_per_line);
  el<HTMLInputElement>("wordsPerLine").value = String(s.words_per_line);
  el<HTMLInputElement>("specialWords").value = s.special_words;
  el<HTMLInputElement>("outDir").value = s.outdir;
  el<HTMLInputElement>("fmtSrt").checked = s.formats.srt;
  el<HTMLInputElement>("fmtVtt").checked = s.formats.vtt;
}

function renderState(state: SubsazState): void {
  renderFiles(state.files);
  renderModels(state);
  renderHw(state);
  renderSettings(state);
  applyTheme(state.theme);
  el<HTMLButtonElement>("startBtn").disabled = state.running;
  el<HTMLButtonElement>("cancelBtn").hidden = !state.running;
}

function applyTheme(theme: "dark" | "light"): void {
  document.documentElement.dataset.theme = theme;
  themeBtn.textContent = theme === "dark" ? "☀" : "🌙";
}

function setProgress(pct: number): void {
  el<HTMLElement>("progBar").style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

/* ---------------- events from Python ---------------- */

on("log", (d) => log(String(d)));
on("status", (d) => setStatus(String(d), true));
on("prog", (d) => setProgress(Number(d)));
on("files", (d) => renderFiles(d as string[]));
on("state", (d) => renderState(d as SubsazState));
on("err", (d) => log(String(d), "err"));

on("hw", (d) => {
  const hw = d as { desc: string; rec: string; selected?: string };
  el<HTMLElement>("hwLine").textContent = hw.desc;
  if (hw.rec) el<HTMLElement>("recLine").textContent = `مدل پیشنهادی: ${hw.rec}`;
  const select = el<HTMLSelectElement>("modelSelect");
  if (hw.selected) select.value = hw.selected;
});

on("dl_prog", (d) => {
  const p = d as { id: string; pct: number };
  el<HTMLElement>("dlBarWrap").hidden = false;
  el<HTMLElement>("dlBar").style.width = `${p.pct}%`;
  setStatus(`در حال دانلود مدل… ${Math.round(p.pct)}٪`, true);
});

on("dl_done", (d) => {
  const p = d as { id: string };
  el<HTMLElement>("dlBarWrap").hidden = true;
  el<HTMLElement>("dlBar").style.width = "0%";
  log(`مدل ${p.id} دانلود شد.`, "ok");
  setStatus("مدل آماده است.");
  void call("get_state").then((s) => s && renderState(s as SubsazState));
});

on("done", (d) => {
  const p = d as DonePayload;
  setProgress(100);
  log(`✓ تمام شد — ${p.words} کلمه در ${Math.round(p.secs)} ثانیه.`, "ok");
  log(`خروجی: ${p.srt}`);
  setStatus("ساخت زیرنویس تمام شد.");
  el<HTMLButtonElement>("startBtn").disabled = false;
  el<HTMLButtonElement>("cancelBtn").hidden = true;
});

on("warn", (d) => {
  const w = d as { title: string; msg: string };
  log(`${w.title}: ${w.msg}`);
  setStatus(w.title, false);
});

/* ---------------- user actions ---------------- */

function bind(): void {
  el<HTMLButtonElement>("btnAddFiles").addEventListener("click", () => void call("pick_files"));
  el<HTMLButtonElement>("btnAddFolder").addEventListener("click", () => void call("pick_folder"));
  el<HTMLButtonElement>("btnClear").addEventListener("click", () => void call("clear_files"));
  el<HTMLButtonElement>("btnRescan").addEventListener("click", () => {
    el<HTMLElement>("hwLine").textContent = "در حال اسکن سیستم…";
    el<HTMLElement>("recLine").textContent = "در حال اسکن سیستم…";
    void call("rescan");
  });
  el<HTMLButtonElement>("btnPickOut").addEventListener("click", () => void call("pick_outdir"));
  el<HTMLButtonElement>("openOutBtn").addEventListener("click", () => void call("open_outdir"));
  el<HTMLButtonElement>("themeBtn").addEventListener("click", async () => {
    const t = await call<string>("toggle_theme");
    if (t) applyTheme(t as "dark" | "light");
  });

  el<HTMLSelectElement>("modelSelect").addEventListener("change", (e) => {
    const v = (e.target as HTMLSelectElement).value;
    void call("set_model", v);
    void call("get_state").then((s) => s && renderModels(s as SubsazState));
  });
  el<HTMLButtonElement>("dlBtn").addEventListener("click", () => {
    const id = el<HTMLSelectElement>("modelSelect").value;
    el<HTMLElement>("dlBarWrap").hidden = false;
    void call("download_model", id);
  });

  const setting = (id: string, key: string, conv: (v: string) => unknown = (v) => v): void => {
    const node = el<HTMLInputElement | HTMLSelectElement>(id);
    const ev = node instanceof HTMLSelectElement ? "change" : "input";
    node.addEventListener(ev, () => void call("set_setting", key, conv(node.value)));
  };
  setting("language", "language");
  setting("mode", "mode");
  setting("charsPerLine", "chars_per_line", (v) => Number(v) || 0);
  setting("wordsPerLine", "words_per_line", (v) => Number(v) || 0);
  setting("specialWords", "special_words");

  el<HTMLInputElement>("fmtSrt").addEventListener("change", (e) => {
    void call("set_setting", "formats.srt", (e.target as HTMLInputElement).checked);
  });
  el<HTMLInputElement>("fmtVtt").addEventListener("change", (e) => {
    void call("set_setting", "formats.vtt", (e.target as HTMLInputElement).checked);
  });

  el<HTMLButtonElement>("startBtn").addEventListener("click", async () => {
    setProgress(0);
    el<HTMLButtonElement>("startBtn").disabled = true;
    el<HTMLButtonElement>("cancelBtn").hidden = false;
    setStatus("در حال ساخت زیرنویس…", true);
    await call("start");
  });
  el<HTMLButtonElement>("cancelBtn").addEventListener("click", () => void call("cancel"));
}

/* ---------------- boot ---------------- */

async function boot(): Promise<void> {
  installPush();
  bind();
  await whenBridge();
  el<HTMLElement>("fmtNote").textContent =
    "فرمت‌ها: mp4 mov m4a wav mp3 aac flac ogg wma";
  const state = await call<SubsazState>("get_state");
  if (state) renderState(state);
  setStatus("آماده");
  if (PREVIEW) {
    log("پیش‌نمایش بدون بک‌اند — داده‌ها شبیه‌سازی شده‌اند.");
  } else {
    log("آماده. اول سیستم را اسکن کن، بعد مدل را دانلود کن.");
  }
}

void boot();
