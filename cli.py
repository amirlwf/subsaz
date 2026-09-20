"""subsaz - video/audio in, word-timed SRT out (EN/FA, local faster-whisper).

Usage:
  python cli.py video.mp4 [--lang en] [--model auto] [--words 3]
  python cli.py video.mp4 --mode two --max-chars 36
  python cli.py --dir FOLDER [...]
  python cli.py --scan                  # show hardware profile + recommendation
  python cli.py --download-model small  # pre-download a model
"""
import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app import hardware, model_manager
from app import transcribe as engine


def run_one(path, args):
    outdir = args.out or (os.path.dirname(os.path.abspath(path)) or ".")
    os.makedirs(outdir, exist_ok=True)
    r = engine.process_file(
        path, outdir, lang=args.lang, model=args.model, words=args.words,
        max_chars=args.max_chars, max_gap=args.max_gap, hold=args.hold,
        mode=args.mode, prompt=args.prompt)
    if not r:
        return False
    print("wrote", r["srt"])
    return True


def main():
    ap = argparse.ArgumentParser(description="subsaz: word-timed SRT, local")
    ap.add_argument("video", nargs="?", default=None)
    ap.add_argument("--dir", default=None,
                    help="batch: all videos/audios in folder")
    ap.add_argument("--model", default="auto",
                    help="auto (hardware pick) or "
                         "tiny/base/small/medium/large-v3-turbo")
    ap.add_argument("--lang", default="en", help="en, fa, or auto")
    ap.add_argument("--words", type=int, default=3,
                    help="words per line (default 3)")
    ap.add_argument("--mode", default="single", choices=("single", "two", "three"),
                    help="single: 1 line/cue; two: Premiere-style 2 lines/cue; "
                         "three: roll-up 3 lines/cue")
    ap.add_argument("--max-chars", type=int, default=32,
                    help="max characters per line (default 32)")
    ap.add_argument("--max-gap", type=float, default=0.8,
                    help="gap (s) forcing a line break (default 0.8)")
    ap.add_argument("--hold", type=float, default=1.0,
                    help="max extra hold of a line (s, default 1.0)")
    ap.add_argument("--prompt", default=None,
                    help="hint for brand/technical words")
    ap.add_argument("--out", default=None)
    ap.add_argument("--scan", action="store_true",
                    help="print hardware profile + recommended models and exit")
    ap.add_argument("--download-model", default=None, metavar="MODEL",
                    help="download a model then exit")
    a = ap.parse_args()

    if a.scan:
        prof = hardware.classify()
        print(hardware.describe_fa(prof))
        for lang in ("en", "fa"):
            rec = hardware.recommend(lang, prof)
            print("%s -> %s (~%dMB): %s"
                  % (lang, rec["model"], rec["mb"], rec["reason_fa"]))
        print("cached:", ", ".join(model_manager.cached_models()) or "(none)")
        return

    if a.download_model:
        try:
            model_manager.download(a.download_model, log=print)
            print("done:", a.download_model)
        except model_manager.ModelDownloadError as e:
            if e.need_vpn:
                print(model_manager.VPN_MESSAGE_FA)
            print("FAILED:", e)
            sys.exit(1)
        return

    if a.dir:
        vids, seen = [], set()
        for f in sorted(os.listdir(a.dir)):
            b = os.path.splitext(f)[0].lower()
            if f.lower().endswith(engine.ALL_EXTS) and b not in seen \
                    and not os.path.exists(os.path.join(
                        a.dir, os.path.splitext(f)[0] + ".srt")):
                seen.add(b)
                vids.append(f)
        if not vids:
            sys.exit("no videos without SRT in " + a.dir)
        print("batch: %d file(s)" % len(vids))
        for f in vids:
            print("==", f)
            try:
                run_one(os.path.join(a.dir, f), a)
            except model_manager.ModelDownloadError as e:
                if e.need_vpn:
                    print(model_manager.VPN_MESSAGE_FA)
                print("FAILED:", f, "-", e)
            except Exception as e:  # noqa: BLE001
                print("FAILED:", f, "-", e)
        return

    if not a.video or not os.path.isfile(a.video):
        sys.exit("not found: " + (a.video or "(no file given)"))
    try:
        run_one(a.video, a)
    except model_manager.ModelDownloadError as e:
        if e.need_vpn:
            print(model_manager.VPN_MESSAGE_FA)
        sys.exit("FAILED: %s" % e)


if __name__ == "__main__":
    main()
