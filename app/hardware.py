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


def cpu_info():
    try:
        import psutil
        mem_gb = round(psutil.virtual_memory().total / 1e9, 1)
    except ImportError:
        mem_gb = 0.0
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu": platform.processor() or platform.uname().processor or "Unknown CPU",
        "cores": os.cpu_count() or 4,
        "ram_gb": mem_gb,
    }


def gpu_info():
    """Return list of {name, vram_gb}. Empty when no detectable GPU."""
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
                                 "vendor": "NVIDIA"})
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
                                 "vendor": "NVIDIA"})
        except ImportError:
            pass
    return gpus


def classify(cpu=None, gpus=None):
    """Return profile dict: tier, device, compute_type, threads, notes."""
    cpu = cpu or cpu_info()
    gpus = gpus if gpus is not None else gpu_info()
    cores = cpu.get("cores") or 4
    ram = cpu.get("ram_gb") or 0.0
    threads = max(2, min(cores, 8))
    notes = []

    if gpus:
        best = max(gpus, key=lambda g: g.get("vram_gb", 0))
        vram = best.get("vram_gb", 0)
        notes.append("GPU: %s (%.1f GB VRAM)" % (best["name"], vram))
        if vram >= 8:
            return {"tier": "GPU_STRONG", "device": "cuda",
                    "compute_type": "float16", "threads": threads,
                    "gpu": best, "cpu": cpu, "notes": notes}
        return {"tier": "GPU_MID", "device": "cuda",
                "compute_type": "float16", "threads": threads,
                "gpu": best, "cpu": cpu, "notes": notes}

    notes.append("No CUDA GPU detected — CPU transcription "
                 "(same accuracy, slower).")
    if cores >= 8 or ram >= 16:
        tier = "CPU_STRONG"
    else:
        tier = "CPU_WEAK"
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
