# SubSaz web UI contract

The Python side (`app/webui.py`) exposes one object to pywebview as
`js_api`. The TS side calls `window.pywebview.api.<method>(...)`.
Every method returns a promise and may raise; JS wraps calls in
`call("name", ...args)` which pushes failures to the log.

Python pushes UI events by evaluating
`window.__push("<kind>", <json>)` — `__push` is defined in
`web/src/bridge.ts` and dispatches a `CustomEvent("subsaz")` with
`{ kind, data }`.

## JS → Python methods

| method | args | returns |
|---|---|---|
| `get_state()` | – | full state object (below) |
| `pick_files()` | – | `string[]` new paths (already added to state) |
| `pick_folder()` | – | `string[]` |
| `pick_outdir()` | – | `string` new output dir (already saved) |
| `add_paths(paths)` | `string[]` | `string[]` accepted paths |
| `remove_file(path)` | `string` | `null` |
| `clear_files()` | – | `null` |
| `rescan()` | – | `null` (result arrives as `hw` event) |
| `set_model(id)` | `string` | `null` |
| `download_model(id)` | `string` | `null` (progress via `dl_prog`, then `dl_done`) |
| `set_setting(key, value)` | `string`, `unknown` | `null` |
| `start()` | – | `null` (uses current file list) |
| `cancel()` | – | `null` |
| `open_outdir()` | – | `null` |
| `toggle_theme()` | – | `string` new theme (`"dark"` / `"light"`) |

## state object

```ts
interface SubsazState {
  files: string[];              // logical paths, RTL-safe to display as-is
  settings: {
    language: "auto" | "en" | "fa";
    mode: "segment" | "word";   // «۱ خط» / «۲ خط»
    chars_per_line: number;
    words_per_line: number;
    special_words: string;
    outdir: string;
    formats: { srt: boolean; vtt: boolean };
  };
  hw: {
    ready: boolean;
    desc: string;               // one-line Persian summary
    tier: string;               // CPU_STRONG / GPU / …
    rec: string;                // recommended model id
    selected: string;           // currently selected model id
  };
  models: ModelInfo[];          // id, label, size_label, downloaded
  theme: "dark" | "light";
  running: boolean;
}
```

## events (Python → JS)

| kind | payload |
|---|---|
| `log` | `string` line appended to the report box |
| `status` | `string` status bar text |
| `prog` | `number` 0…100 |
| `hw` | `{ desc, tier, rec, selected, ready }` |
| `files` | `string[]` full list (after add/remove/clear) |
| `dl_prog` | `{ id, pct }` |
| `dl_done` | `{ id }` |
| `done` | `{ outdir, srt, words, secs }` |
| `warn` | `{ title, msg }` |
| `err` | `string` |
| `state` | full `SubsazState` (after any change worth a full redraw) |
