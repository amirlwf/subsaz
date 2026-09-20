"""Hardware detection + automatic model recommendation.

No heavy dependencies: CPU/RAM via stdlib+psutil (optional),
NVIDIA GPU via nvidia-smi, torch only if already installed.
"""
import os
import platform
import shutil
import subprocess

# Approximate download sizes (faster-whisper, int8 capable).
MODEL_INFO = {
    "tiny":           {"mb": 75,   "label": "tiny — fastest, draft quality"},
    "base":           {"mb": 145,  "label": "base — fast, ok for clear EN"},
    "small":          {"mb": 460,  "label": "small — best EN short-form sweet spot"},
    "medium":         {"mb": 1500, "label": "medium — high accuracy, slower"},
    "large-v3-turbo": {"mb": 1600, "label": "large-v3-turbo — best quality EN+FA"},
}

TIERS = ("GPU_STRONG", "GPU_MID", "CPU_STRONG", "CPU_WEAK")


def _windows_cpu_brand():
    """Real CPU name from the registry (platform.processor() is empty on Windows)."""
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            return (name or "").strip()
    except OSError:
        return ""


def _ram_gb_fallback():
    """RAM in GB without psutil (Windows API). Returns 0.0 on failure."""
    if os.name == "nt":
        try:
            import ctypes
            mem_kb = ctypes.c_ulonglong()
            if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(
                ctypes.byref(mem_kb)
            ):
                return round(mem_kb.value / 1e6, 1)
        except (OSError, AttributeError):
            pass
    return 0.0


def _disk_free_gb(path=None):
    """Free disk space in GB for the drive holding path (default: user home)."""
    try:
        return round(shutil.disk_usage(path or os.path.expanduser("~")).free / 1e9, 1)
    except OSError:
        return 0.0


def cpu_info():
    try:
        import psutil
        mem_gb = round(psutil.virtual_memory().total / 1e9, 1)
    except ImportError:
        mem_gb = _ram_gb_fallback()
    cpu = (
        _windows_cpu_brand()
        or platform.processor()
        or platform.uname().processor
        or "Unknown CPU"
    )
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "os": ("%s %s" % (platform.system(), platform.release())).strip(),
        "cpu": cpu,
        "cores": os.cpu_count() or 4,
        "ram_gb": mem_gb,
        "disk_free_gb": _disk_free_gb(),
    }


def _windows_display_gpus():
    """Names of all display adapters via WMI (Intel/AMD/iGPU included).

    These are display-only entries (no CUDA) — they only enrich the system
    report; compute decisions still use the CUDA-capable entries.
    """
    names = []
    if os.name != "nt":
        return names
    try:
        out = subprocess.run(
            ["wmic", "path", "win32_videocontroller", "get", "name", "/format:list"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.lower().startswith("name="):
                name = line.split("=", 1)[1].strip()
                if name:
                    names.append(name)
    except (OSError, subprocess.SubprocessError):
        pass
    return names


def _guess_vendor(name):
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n:
        return "NVIDIA"
    if "intel" in n:
        return "Intel"
    if "amd" in n or "radeon" in n:
        return "AMD"
    return "Other"


def gpu_info():
    """Return list of {name, vram_gb, vendor, cuda_capable}.

    NVIDIA (nvidia-smi) entries carry VRAM + cuda_capable=True. Other display
    adapters (Intel/AMD) are listed with cuda_capable=False for reporting.
    Empty only when nothing is detectable at all.
    """
    gpus = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=15).stdout
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 2:
                    try:
                        vram = round(float(parts[1]) / 1024, 1)
                    except ValueError:
                        vram = 0.0
                    gpus.append({"name": parts[0], "vram_gb": vram,
                                 "vendor": "NVIDIA", "cuda_capable": True})
        except (OSError, subprocess.SubprocessError):
            pass
    if not gpus:
        # torch fallback (only if the user already has it; never required)
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    p = torch.cuda.get_device_properties(i)
                    gpus.append({"name": p.name,
                                 "vram_gb": round(p.total_memory / 1e9, 1),
                                 "vendor": "NVIDIA", "cuda_capable": True})
        except ImportError:
            pass
    known = {g["name"].lower() for g in gpus}
    for name in _windows_display_gpus():
        if name.lower() not in known:
            gpus.append({"name": name, "vram_gb": 0.0,
                         "vendor": _guess_vendor(name),
                         "cuda_capable": False})
    return gpus


def _disk_note(cpu, notes):
    """Warn when free disk space is too low for model downloads (~1.6GB max)."""
    free = (cpu or {}).get("disk_free_gb") or 0.0
    if 0 < free < 3:
        notes.append("هشدار: فضای خالی دیسک کم است (%.1fGB) — "
                     "مدل‌ها تا ۱.۶GB جا می‌خواهند." % free)


def classify(cpu=None, gpus=None):
    """Return profile dict: tier, device, compute_type, threads, notes."""
    cpu = cpu or cpu_info()
    gpus = gpus if gpus is not None else gpu_info()
    cores = cpu.get("cores") or 4
    ram = cpu.get("ram_gb") or 0.0
    threads = max(2, min(cores, 8))
    notes = []

    cuda_gpus = [g for g in (gpus or []) if g.get("cuda_capable")]
    others = [g for g in (gpus or []) if not g.get("cuda_capable")]
    if cuda_gpus:
        best = max(cuda_gpus, key=lambda g: g.get("vram_gb", 0))
        vram = best.get("vram_gb", 0)
        notes.append("GPU: %s (%.1f GB VRAM)" % (best["name"], vram))
        for g in others:
            notes.append("Display: %s (%s، بدون CUDA)"
                         % (g["name"], g.get("vendor", "?")))
        tier = "GPU_STRONG" if vram >= 8 else "GPU_MID"
        _disk_note(cpu, notes)
        return {"tier": tier, "device": "cuda",
                "compute_type": "float16", "threads": threads,
                "gpu": best, "cpu": cpu, "notes": notes}

    for g in others:
        notes.append("Display: %s (%s، بدون CUDA)"
                     % (g["name"], g.get("vendor", "?")))
    notes.append("No CUDA GPU detected — CPU transcription "
                 "(same accuracy, slower).")
    if cores >= 8 or ram >= 16:
        tier = "CPU_STRONG"
    else:
        tier = "CPU_WEAK"
    _disk_note(cpu, notes)
    return {"tier": tier, "device": "cpu", "compute_type": "int8",
            "threads": threads, "gpu": None, "cpu": cpu, "notes": notes}


# (tier, lang) -> recommended model
RECOMMEND = {
    ("GPU_STRONG", "en"): "large-v3-turbo",
    ("GPU_STRONG", "fa"): "large-v3-turbo",
    ("GPU_MID", "en"): "small",
    ("GPU_MID", "fa"): "large-v3-turbo",
    ("CPU_STRONG", "en"): "small",
    ("CPU_STRONG", "fa"): "large-v3-turbo",
    ("CPU_WEAK", "en"): "small",
    ("CPU_WEAK", "fa"): "base",  # smart re-run upgrades to turbo if needed
}


def recommend(lang="en", profile=None):
    """Return {model, mb, device, compute_type, threads, tier, reason_fa}."""
    profile = profile or classify()
    tier = profile["tier"]
    lang = "fa" if lang == "fa" else "en"
    model = RECOMMEND.get((tier, lang), "small")
    info = MODEL_INFO[model]
    if tier == "CPU_WEAK" and lang == "fa":
        reason = ("سیستم سبک: اول با base سریع شروع می‌کنیم، "
                  "اگر اطمینان کم بود خودکار با turbo دقیق تکرار می‌شود.")
    elif profile["device"] == "cuda":
        reason = "کارت گرافیک قوی: دقیق‌ترین و سریع‌ترین مدل."
    elif lang == "fa":
        reason = "برای فارسی همیشه دقیق‌ترین مدل (turbo) پیشنهاد می‌شود."
    else:
        reason = "بهترین نقطه تعادل سرعت/دقت انگلیسی برای CPU."
    return {"model": model, "mb": info["mb"], "label": info["label"],
            "device": profile["device"],
            "compute_type": profile["compute_type"],
            "threads": profile["threads"], "tier": tier,
            "reason_fa": reason, "notes": profile.get("notes", [])}


def describe_fa(profile=None):
    """One-line Persian summary of the machine for the GUI."""
    profile = profile or classify()
    cpu = profile["cpu"]
    parts = ["CPU: %s (%d هسته)" % (cpu.get("cpu") or "؟", cpu.get("cores", 0))]
    if cpu.get("ram_gb"):
        parts.append("RAM: %.1fGB" % cpu["ram_gb"])
    if profile.get("gpu"):
        parts.append("GPU: %s" % profile["gpu"]["name"])
    else:
        parts.append("GPU: ندارد (CPU)")
    parts.append("Tier: %s" % profile["tier"])
    return " | ".join(parts)
