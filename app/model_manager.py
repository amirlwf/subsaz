"""Model download manager: check cache, download with progress,
and classify network errors (VPN hint for sanctioned regions).
"""
import os

REPO_IDS = {
    # (repo_id, filename_hint) candidates per model; first hit wins for cache check
    "tiny": ["Systran/faster-whisper-tiny"],
    "base": ["Systran/faster-whisper-base"],
    "small": ["Systran/faster-whisper-small"],
    "medium": ["Systran/faster-whisper-medium"],
    "large-v3-turbo": ["Systran/faster-whisper-large-v3-turbo",
                       "mobiuslabsgmbh/faster-whisper-large-v3-turbo"],
}


class ModelDownloadError(Exception):
    def __init__(self, msg, need_vpn=False):
        super().__init__(msg)
        self.need_vpn = need_vpn


def _hub_dir():
    try:
        from huggingface_hub import constants
        return constants.HF_HUB_CACHE
    except ImportError:
        return os.path.join(os.path.expanduser("~"), ".cache", "huggingface",
                            "hub")


def _dir_name(repo_id):
    return "models--" + repo_id.replace("/", "--")


# files that actually let faster-whisper load a model
WEIGHT_EXT = (".bin", ".safetensors", ".pt", ".pth")


def is_cached(model):
    """True only when real weights are on disk.

    A half-finished snapshot_download leaves a non-empty repo dir with no
    weight file; treating that as "cached" made WhisperModel try to load a
    model that isn't there. The old code also returned True for ANY
    non-empty dir and only looked for .bin.
    """
    hub = _hub_dir()
    for repo in REPO_IDS.get(model, []):
        d = os.path.join(hub, _dir_name(repo))
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            if any(f.endswith(WEIGHT_EXT) for f in files):
                return True
    return False


def cached_models():
    return [m for m in REPO_IDS if is_cached(m)]


def _looks_like_block(e):
    s = ("%s %s" % (type(e).__name__, e)).lower()
    keys = ("ssl", "connection", "reset", "timed out", "timeout", "403",
            "forbidden", "proxy", "max retries", "could not resolve",
            "unreachable", "handshake", "eof", "refused")
    return any(k in s for k in keys)


def download(model, progress_cb=None, log=None):
    """Download model weights. progress_cb(done_bytes, total_bytes)."""
    from huggingface_hub import snapshot_download

    last_exc = None
    for repo in REPO_IDS.get(model, []):
        try:
            if log:
                log("downloading %s (%s)..." % (model, repo))
            snapshot_download(repo_id=repo)
            if progress_cb:
                progress_cb(1, 1)
            return repo
        except Exception as e:  # noqa: BLE001 — classified below
            last_exc = e
            if log:
                log("   %s failed: %s" % (repo, e))
            continue
    msg = "دانلود مدل %s ناموفق بود: %s" % (model, last_exc)
    raise ModelDownloadError(msg, need_vpn=_looks_like_block(last_exc))


VPN_MESSAGE_FA = (
    "اتصال به سرور دانلود برقرار نشد.\n"
    "اگر در ایران هستی، لطفاً به VPN متصل شو و دوباره «دانلود مدل» را بزن.\n"
    "(مدل‌ها روی HuggingFace هستند و تحریم‌اند.)"
)
