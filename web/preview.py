"""Preview the TypeScript UI in a real WebView2 window, no backend.

    python web/preview.py

Serves web_dist/ on a local port and opens it with ?preview=1, which makes
web/src/bridge.ts return canned data instead of calling Python — useful for
checking layout/RTL/font without starting the engine.
"""
import functools
import http.server
import os
import socketserver
import threading

import webview

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "web_dist")
PORT = 8123


def _dump_diag(window: "webview.Window", path: str) -> None:
    """After load, snapshot what the page actually shows (log + styles)."""
    import time

    time.sleep(4)
    js = """(() => {
      const log = document.getElementById('logBox');
      const st = getComputedStyle(document.body);
      return JSON.stringify({
        dir: document.documentElement.dir,
        bg: st.backgroundColor,
        color: st.color,
        font: st.fontFamily,
        items: document.querySelectorAll('#fileList li').length,
        hw: (document.getElementById('hwLine') || {}).textContent,
        fmt: (document.getElementById('fmtNote') || {}).textContent,
        log: log ? log.textContent.slice(0, 400) : null,
        preview: location.search,
      });
    })()"""
    try:
        out = window.evaluate_js(js)
    except Exception as exc:  # noqa: BLE001 — diagnostics must never crash
        out = "EVAL_ERR " + repr(exc)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out if isinstance(out, str) else repr(out))


def main() -> None:
    if not os.path.isfile(os.path.join(DIST, "index.html")):
        raise SystemExit("web_dist missing — run: cd web && npm run build")
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=DIST)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    window = webview.create_window(
        "ساب‌ساز — پیش‌نمایش رابط",
        f"http://127.0.0.1:{PORT}/?preview=1",
        width=1040,
        height=940,
        min_size=(760, 640),
    )
    diag_path = os.path.join(
        os.environ.get("TMPDIR") or ROOT, "subsaz_preview_diag.json")
    threading.Thread(
        target=_dump_diag, args=(window, diag_path), daemon=True).start()
    print("diag:", diag_path)
    try:
        webview.start()
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
