# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the SubSaz WebView UI (TypeScript frontend).

The frontend is prebuilt (`cd web && npm run build` → web_dist/) and
shipped as data; pywebview opens it in the system WebView2 runtime.
"""
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("web_dist", "web_dist")]
binaries = []
hiddenimports = ["huggingface_hub", "psutil", "arabic_reshaper",
                 "bidi.algorithm", "webview", "bottle"]

for pkg in ("faster_whisper", "ctranslate2", "av", "webview", "bottle"):
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]

a = Analysis(
    ["webui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SubSaz-Web",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SubSaz-Web",
)
