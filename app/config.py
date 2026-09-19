"""Persistent user config (JSON in %LOCALAPPDATA%/WordSub)."""
import json
import os

APP_NAME = "WordSub"

DEFAULTS = {
    "lang": "en",
    "model": "auto",          # auto | tiny | base | small | medium | large-v3-turbo
    "mode": "single",         # single (1 line) | two (Premiere-style 2 lines)
    "words_per_line": 3,
    "max_chars": 32,
    "max_gap": 0.8,
    "hold": 1.0,
    "prompt": "",
    "outdir": "",
    "device": "auto",         # auto | cpu | cuda
    "accepted_model_download": False,
}


def config_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def config_path():
    return os.path.join(config_dir(), "config.json")


def load():
    cfg = dict(DEFAULTS)
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULTS:
                if k in data:
                    cfg[k] = data[k]
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
