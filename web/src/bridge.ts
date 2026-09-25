/// <reference types="vite/client" />

/** Mirrors web/API.md — the contract with app/webui.py. */

export interface ModelInfo {
  id: string;
  label: string;
  size_label: string;
  downloaded: boolean;
}

export interface Settings {
  language: "auto" | "en" | "fa";
  mode: "segment" | "word";
  chars_per_line: number;
  words_per_line: number;
  special_words: string;
  outdir: string;
  formats: { srt: boolean; vtt: boolean };
}

export interface HwInfo {
  ready: boolean;
  desc: string;
  tier: string;
  rec: string;
  selected: string;
}

export interface SubsazState {
  files: string[];
  settings: Settings;
  hw: HwInfo;
  models: ModelInfo[];
  theme: "dark" | "light";
  running: boolean;
}

export interface DonePayload {
  outdir: string;
  srt: string;
  words: number;
  secs: number;
}

declare global {
  interface Window {
    /** Injected by pywebview once the bridge is ready. */
    pywebview?: { api: Record<string, (...args: unknown[]) => Promise<unknown>> };
    /** Called by Python via evaluate_js. */
    __push?: (kind: string, data: unknown) => void;
  }
}

export type EventKind =
  | "log"
  | "status"
  | "prog"
  | "hw"
  | "files"
  | "dl_prog"
  | "dl_done"
  | "done"
  | "warn"
  | "err"
  | "state";

type Handler = (data: unknown) => void;

const handlers = new Map<EventKind, Set<Handler>>();

/** Subscribe to a Python-pushed event. Returns an unsubscribe function. */
export function on(kind: EventKind, fn: Handler): () => void {
  let set = handlers.get(kind);
  if (!set) {
    set = new Set();
    handlers.set(kind, set);
  }
  set.add(fn);
  return () => set!.delete(fn);
}

function dispatch(kind: string, data: unknown): void {
  const set = handlers.get(kind as EventKind);
  if (!set) return;
  for (const fn of set) {
    try {
      fn(data);
    } catch (e) {
      console.error("handler failed", kind, e);
    }
  }
}

/** Installed on window so Python can push events. */
export function installPush(): void {
  window.__push = (kind, data) => dispatch(kind, data);
}

/** Set when the page is opened with ?preview=1 (browser, no Python). */
export const PREVIEW =
  typeof location !== "undefined" &&
  new URLSearchParams(location.search).has("preview");

/** pywebview attaches its api asynchronously — wait, but never forever:
 *  a missing bridge must surface as an error instead of a frozen UI. */
export function whenBridge(): Promise<boolean> {
  if (window.pywebview) return Promise.resolve(true);
  return new Promise((resolve) => {
    let settled = false;
    const settle = (ok: boolean): void => {
      if (settled) return;
      settled = true;
      clearInterval(poll);
      resolve(ok);
    };
    window.addEventListener("pywebviewready", () => settle(true), { once: true });
    const poll = setInterval(() => {
      if (window.pywebview) settle(true);
    }, 30);
    setTimeout(() => settle(Boolean(window.pywebview)), 1500);
  });
}

/** Call a Python method; route rejections to the log instead of throwing. */
export async function call<T>(name: string, ...args: unknown[]): Promise<T | undefined> {
  if (PREVIEW) {
    const { mockCall } = await import("./preview");
    return mockCall(name) as T;
  }
  const ready = await whenBridge();
  const api = window.pywebview?.api;
  if (!ready || !api || typeof api[name] !== "function") {
    dispatch("err", `bridge missing: ${name}`);
    return undefined;
  }
  try {
    return (await api[name](...args)) as T;
  } catch (e) {
    dispatch("err", `${name}: ${e instanceof Error ? e.message : String(e)}`);
    return undefined;
  }
}
