import type { SubsazState } from "./bridge";

/** Canned data used only by `?preview=1` (browser preview, no Python). */

export const previewState: SubsazState = {
  files: [
    "D:\\ویدیو\\نمونه ۱.mp4",
    "D:\\ویدیو\\interview part2.mov",
    "D:\\صوت\\podcast 12.wav",
  ],
  settings: {
    language: "auto",
    mode: "word",
    chars_per_line: 42,
    words_per_line: 6,
    special_words: "WordLab, BrandX",
    outdir: "D:\\خروجی",
    formats: { srt: true, vtt: false },
  },
  hw: {
    ready: true,
    desc: "پردازنده: Intel Core i7-6700HQ (8 هسته) | RAM: 17.0GB | GPU: — | Tier: CPU_STRONG",
    tier: "CPU_STRONG",
    rec: "small",
    selected: "small",
  },
  models: [
    { id: "tiny", label: "tiny", size_label: "۷۵MB", downloaded: true },
    { id: "small", label: "small", size_label: "۴۶۰MB", downloaded: true },
    { id: "medium", label: "medium", size_label: "۱٫۵GB", downloaded: false },
  ],
  theme: "dark",
  running: false,
};

export function mockCall(name: string): unknown {
  switch (name) {
    case "get_state":
      return previewState;
    case "pick_files":
      return ["D:\\ویدیو\\فایل جدید.mp4"];
    case "toggle_theme":
      return previewState.theme === "dark" ? "light" : "dark";
    default:
      return undefined;
  }
}
