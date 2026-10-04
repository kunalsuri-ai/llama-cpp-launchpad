#!/usr/bin/env python3
"""llama-cpp-launchpad: model-setup.

Picks a model that fits your hardware, downloads it, speed-tests it, and later checks
Hugging Face for newer models that fit. One script for Linux, macOS and Windows.

Python standard library only. It reads your RAM/GPU, the model catalog next to it, and
talks to huggingface.co. It writes only into models/ and a small .launchpad-state file.

Usage:
  model_setup.py                   first-time wizard (detect hardware, recommend, download, test)
  model_setup.py --check-updates   look for new Hugging Face models that fit this machine
  model_setup.py --test [file]     speed-test an installed model
  model_setup.py --list            show recommendations only (no download)
  Options: --use chat|translation|coding|fast   --yes (accept defaults)

Settings (optional environment variables):
  MODELS_DIR   folder for .gguf files                 (default: <project>/models)
  CHECK_DAYS   days between update prompts, 0 = off   (default: 7)
  LP_RAM_MB, LP_VRAM_MB   override detected memory (if detection is wrong)
  LLAMA_SERVER / LLAMA_BENCH   paths to the llama.cpp binaries (default: auto-detected)
  INCLUDE_ALL  1 = --check-updates also suggests unknown authors and fine-tunes
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HF_API = os.environ.get("HF_API", "https://huggingface.co/api")
HF_BASE = os.environ.get("HF_BASE", "https://huggingface.co")
USER_AGENT = "llama-cpp-launchpad"

# Checked for new uploads:
FETCH_AUTHORS = ["ggml-org", "unsloth", "bartowski", "lmstudio-community"]
# Suggested by default: the quantizers above plus official model makers. INCLUDE_ALL=1 opens it up.
TRUSTED_AUTHORS = set(FETCH_AUTHORS) | {
    "Qwen", "google", "meta-llama", "microsoft", "mistralai", "openbmb", "LiquidAI",
    "ibm-granite", "HuggingFaceTB", "nvidia", "allenai", "deepseek-ai", "zai-org",
}
# Quantization preference for suggested downloads (balance of size and quality).
QUANT_ORDER = ["Q4_K_M", "Q4_K_S", "Q5_K_M", "Q4_0", "IQ4_XS", "Q3_K_M", "Q6_K", "Q8_0"]
MIN_MODEL_BYTES = 300_000_000   # smaller .gguf files are adapters or draft heads, not models


# --- Settings (read at call time so tests and users can change the environment) ----------
def models_dir() -> Path:
    return Path(os.environ.get("MODELS_DIR") or ROOT / "models")


def catalog_path() -> Path:
    return Path(os.environ.get("CATALOG") or ROOT / "scripts" / "models.catalog")


def state_path() -> Path:
    return Path(os.environ.get("STATE_FILE") or ROOT / ".launchpad-state")


def check_days() -> int:
    try:
        return int(os.environ.get("CHECK_DAYS", "7"))
    except ValueError:
        return 7


# --- Terminal output ---------------------------------------------------------------------
class Style:
    on = False
    B = D = R = ORANGE = GREEN = YELLOW = RED = ""


def init_style(stream=None) -> None:
    stream = stream or sys.stdout
    on = bool(getattr(stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ
    if on and platform.system() == "Windows":   # turn on ANSI colours in the Windows console
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            on = False
    Style.on = on
    Style.B, Style.D, Style.R = ("\033[1m", "\033[2m", "\033[0m") if on else ("", "", "")
    Style.ORANGE, Style.GREEN, Style.YELLOW, Style.RED = (
        ("\033[38;5;208m", "\033[32m", "\033[33m", "\033[31m") if on else ("", "", "", ""))


def say(msg: str = "") -> None:
    print(msg)


def err(msg: str) -> None:
    print(msg, file=sys.stderr)


# --- Dates ---------------------------------------------------------------------------------
def today() -> dt.date:
    return dt.date.fromisoformat(os.environ.get("LP_TODAY") or dt.date.today().isoformat())


def days_since(date_str: str) -> int:
    return (today() - dt.date.fromisoformat(date_str)).days


def add_days(date_str: str, n: int) -> str:
    return (dt.date.fromisoformat(date_str) + dt.timedelta(days=n)).isoformat()


# --- State file (key=value lines, parsed as data, never executed) -------------------------
def state_get(key: str) -> str:
    try:
        lines = state_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    value = ""
    for line in lines:
        k, sep, v = line.partition("=")
        if sep and k == key:
            value = v
    return value


def state_set(key: str, value) -> None:
    path = state_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    value = str(value).replace("\n", "").replace("\r", "")
    lines = [ln for ln in lines if ln.partition("=")[0] != key] + [f"{key}={value}"]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def state_int(key: str) -> int:
    try:
        return int(state_get(key))
    except ValueError:
        return 0


# --- Hardware --------------------------------------------------------------------------------
class Hw:
    def __init__(self, ram_mb=0, cores=1, gpu_kind="none", gpu_name="", vram_mb=0, gpu_usable=False):
        self.ram_mb, self.cores = ram_mb, cores
        self.gpu_kind, self.gpu_name = gpu_kind, gpu_name        # none | nvidia | apple | gpu
        self.vram_mb, self.gpu_usable = vram_mb, gpu_usable

    def sig(self) -> str:
        return f"{self.ram_mb}-{self.vram_mb}-{self.gpu_kind}-{int(self.gpu_usable)}-{self.cores}"


def run_cmd(args: list, timeout: int = 20) -> str:
    """Run a program (never through a shell) and return its stdout, or '' on any failure."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return done.stdout + done.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def find_llama_server() -> str:
    cands = [os.environ.get("LLAMA_SERVER", ""), shutil.which("llama-server") or "",
             str(ROOT / "bin" / "llama-server"), str(ROOT / "bin" / "llama-server.exe"),
             str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def gpu_usable() -> bool:
    """Does the installed llama.cpp build offer a GPU backend?"""
    srv = find_llama_server()
    if not srv:
        return False
    return bool(re.search(r"CUDA|Vulkan|ROCm|HIP|SYCL|Metal", run_cmd([srv, "--list-devices"]), re.I))


def read_ram_mb() -> int:
    system = platform.system()
    try:
        if system == "Linux":
            path = os.environ.get("MEMINFO_FILE", "/proc/meminfo")
            for line in Path(path).read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        elif system == "Darwin":
            return int(run_cmd(["sysctl", "-n", "hw.memsize"]).strip()) // 1048576
        elif system == "Windows":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("totpage", ctypes.c_ulonglong), ("availpage", ctypes.c_ulonglong),
                            ("totvirt", ctypes.c_ulonglong), ("availvirt", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            st = MemStatus()
            st.length = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.total) // 1048576
    except (OSError, ValueError, IndexError):
        pass
    return 0


def detect_hw() -> Hw:
    hw = Hw(ram_mb=read_ram_mb(), cores=os.cpu_count() or 1)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        hw.gpu_kind, hw.gpu_name, hw.gpu_usable = "apple", "Apple Silicon (unified memory)", True
    else:
        out = run_cmd(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        line = out.strip().splitlines()[0] if out.strip() else ""
        name, _, vram = line.rpartition(", ")
        if name and vram.strip().isdigit() and int(vram) > 0:
            hw.gpu_kind, hw.gpu_name, hw.vram_mb = "nvidia", name, int(vram)
            forced = os.environ.get("LP_GPU_USABLE")
            hw.gpu_usable = (forced == "1") if forced is not None else gpu_usable()
    if os.environ.get("LP_RAM_MB", "").isdigit():
        hw.ram_mb = int(os.environ["LP_RAM_MB"])
    if os.environ.get("LP_VRAM_MB", "").isdigit():
        hw.vram_mb = int(os.environ["LP_VRAM_MB"])
        if hw.gpu_kind == "none":
            hw.gpu_kind, hw.gpu_name, hw.gpu_usable = "gpu", "GPU (set by you)", True
    return hw


def save_hw(hw: Hw) -> None:
    for k, v in (("hw_ram_mb", hw.ram_mb), ("hw_vram_mb", hw.vram_mb), ("hw_kind", hw.gpu_kind),
                 ("hw_usable", int(hw.gpu_usable)), ("hw_cores", hw.cores), ("hw_sig", hw.sig())):
        state_set(k, v)


def describe_hw(hw: Hw) -> str:
    gpu, mode = "no GPU", "CPU mode"
    if hw.gpu_kind in ("nvidia", "gpu"):
        gpu = f"{hw.gpu_name}, {hw.vram_mb // 1024} GB"
        if hw.gpu_usable:
            mode = "GPU mode"
        else:
            gpu += " (not used by your llama.cpp build)"
    elif hw.gpu_kind == "apple":
        gpu, mode = hw.gpu_name, "GPU mode"
    return (f"{Style.B}Your system:{Style.R} {(hw.ram_mb + 512) // 1024} GB RAM · {hw.cores} cores · "
            f"{gpu}  →  {Style.GREEN}{mode}{Style.R}")


# --- Fit and speed estimates ----------------------------------------------------------------
def fit(size_bytes: int, hw: Hw) -> str:
    """Where would this model run? gpu | cpu | tight | no."""
    need = (size_bytes // 1048576) * 115 // 100 + 512      # weights + context cache + overhead
    if hw.gpu_kind in ("nvidia", "gpu") and hw.gpu_usable and need <= hw.vram_mb * 90 // 100:
        return "gpu"
    if hw.gpu_kind == "apple" and need <= hw.ram_mb * 65 // 100:
        return "gpu"
    if need <= hw.ram_mb * 60 // 100:
        return "cpu"
    if need <= hw.ram_mb * 80 // 100:
        return "tight"
    return "no"


def est_tps(size_bytes: int, mode: str, hw: Hw) -> int:
    """Estimated tokens/s. Generation is memory-bandwidth bound, so speed ~ bandwidth / model size.
    A speed measured on this machine replaces the default bandwidth."""
    size_mb = max(size_bytes // 1048576, 1)
    eff = state_int("eff_bw")
    if eff > 0 and mode == (state_get("eff_mode") or "cpu"):
        return eff // size_mb
    bw10 = {"gpu": 1000 if hw.gpu_kind == "apple" else 2500, "cpu": 150, "tight": 50}.get(mode, 150)
    return bw10 * 102 // size_mb


def verdict(tps: int) -> str:
    return "smooth" if tps >= 15 else "usable" if tps >= 5 else "slow"


def verdict_label(v: str) -> str:
    S = Style
    return {"smooth": f"{S.GREEN}✔ smooth{S.R}", "usable": f"{S.YELLOW}● usable{S.R}",
            "tight": f"{S.YELLOW}▲ tight fit{S.R}"}.get(v, f"{S.RED}✖ slow{S.R}")


def upgrade_label(size_mb: int, installed_mb: int) -> str:
    if installed_mb <= 0:
        return "new"
    if size_mb <= installed_mb * 80 // 100:
        return "lighter, faster"
    if size_mb >= installed_mb * 115 // 100:
        return "bigger, more capable"
    return "similar size, newer"


def human_size(n: int) -> str:
    return f"{n / 1073741824:.1f} GB" if n >= 1073741824 else f"{n // 1048576} MB"


# --- Catalog and recommendations ------------------------------------------------------------
def load_catalog() -> list:
    rows = []
    for line in catalog_path().read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, repo, file, size, tags, note = line.split("|", 5)
        rows.append({"name": name, "repo": repo, "file": file, "size": int(size),
                     "tags": tags.split(","), "note": note})
    return rows


def recommend(use: str, hw: Hw, catalog: list | None = None) -> list:
    """Up to 5 catalog models that fit, best first. Bigger = better, unless use is 'fast'."""
    ranked = []
    for m in catalog if catalog is not None else load_catalog():
        if use not in ("any", "") and use not in m["tags"]:
            continue
        mode = fit(m["size"], hw)
        if mode == "no":
            continue
        tps = est_tps(m["size"], mode, hw)
        if tps < 3:
            continue
        v, rank = verdict(tps), 0
        if mode == "tight":
            v = "tight"                  # may swap or crash: never shown as usable
        elif tps >= 5:
            rank = 1
        key = tps if use == "fast" else m["size"] // 1048576
        ranked.append((rank, key, dict(m, mode=mode, tps=tps, verdict=v)))
    ranked.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [r[2] for r in ranked[:5]]


# --- Hugging Face discovery --------------------------------------------------------------------
def http_get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def http_json(url: str):
    try:
        return json.loads(http_get(url, int(os.environ.get("LP_HTTP_TIMEOUT", "25"))))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def is_trusted(repo_id: str) -> bool:
    return repo_id.split("/", 1)[0] in TRUSTED_AUTHORS


def parse_models(data, since: str) -> list:
    """Model list JSON -> [(id, downloads, likes, created)] for public repos created on/after `since`."""
    out = []
    for m in data or []:
        created = (m.get("createdAt") or "")[:10]
        if m.get("private") or created < since or not m.get("id"):
            continue
        out.append((m["id"], int(m.get("downloads") or 0), int(m.get("likes") or 0), created))
    return out


def model_files(model: dict) -> list:
    """One model's JSON -> [(file, size)] of usable single-file GGUFs (nothing if gated or private)."""
    if not isinstance(model, dict) or model.get("gated") or model.get("private") or model.get("disabled"):
        return []
    out = []
    for s in model.get("siblings") or []:
        f = s.get("rfilename", "")
        if (re.search(r"\.gguf$", f, re.I)
                and not re.search(r"mmproj|-[0-9]+-of-[0-9]+|imatrix|/", f, re.I)):
            out.append((f, int(s.get("size") or 0)))
    return out


def choose_quant(files: list, hw: Hw):
    """Best quantization that fits this machine at 5+ t/s (tight fits are never suggested)."""
    for q in QUANT_ORDER:
        for f, size in files:
            if size < MIN_MODEL_BYTES or q not in f.upper():
                continue
            mode = fit(size, hw)
            if mode in ("no", "tight") or est_tps(size, mode, hw) < 5:
                continue
            return f, size
    return None


def fetch_candidates(since: str) -> list:
    seen, rows = {}, []
    urls = [f"{HF_API}/models?author={a}&filter=gguf&pipeline_tag=text-generation&sort=createdAt&direction=-1&limit=40"
            for a in FETCH_AUTHORS]
    urls.append(f"{HF_API}/models?filter=gguf&pipeline_tag=text-generation&sort=trendingScore&limit=40")
    for url in urls:
        for row in parse_models(http_json(url), since):
            seen.setdefault(row[0], row)
    include_all = os.environ.get("INCLUDE_ALL") == "1"
    exclude = re.compile(os.environ.get("EXCLUDE_RE", "abliterated|uncensored|nsfw"), re.I)
    min_dl = int(os.environ.get("MIN_DL", "100"))
    for rid, dl, likes, created in seen.values():
        if not include_all and (not is_trusted(rid) or exclude.search(rid)):
            continue
        if dl >= min_dl:
            rows.append((rid, dl, likes, created))
    return rows


def find_upgrades(since: str, hw: Hw) -> list:
    """Up to 5 candidates: dicts with repo, file, size, tps, label, downloads, likes, created."""
    installed_mb, installed_repo = state_int("installed_size_mb"), state_get("installed_repo")
    cands = sorted(fetch_candidates(since), key=lambda r: r[1] + r[2] * 20, reverse=True)
    out = []
    for rid, dl, likes, created in cands[: int(os.environ.get("LP_MAX_LOOKUPS", "20"))]:
        if rid == installed_repo:
            continue
        pick = choose_quant(model_files(http_json(f"{HF_API}/models/{rid}?blobs=true")), hw)
        if not pick:
            continue
        f, size = pick
        mode = fit(size, hw)
        out.append({"repo": rid, "file": f, "size": size, "tps": est_tps(size, mode, hw),
                    "label": upgrade_label(size // 1048576, installed_mb),
                    "downloads": dl, "likes": likes, "created": created})
    return out[:5]


# --- Download and speed test ------------------------------------------------------------------
def fetch_file(url: str, dest_part: Path, size: int) -> None:
    """Download with resume (HTTP Range) and a progress bar on stderr."""
    have = dest_part.stat().st_size if dest_part.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
        if have and resp.status != 206:      # server ignored Range: start over
            have = 0
        with open(dest_part, "ab" if have else "wb") as out:
            done = have
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if size and sys.stderr.isatty():
                    sys.stderr.write(f"\r  {done * 100 // size:3d}%  {human_size(done)} / {human_size(size)}")
                    sys.stderr.flush()
    if sys.stderr.isatty():
        sys.stderr.write("\n")


def download(repo: str, file: str, size: int):
    """Download into models/. Returns the final path, or None on failure (a partial file is kept for resume)."""
    dest = models_dir() / Path(file).name              # never write outside models/
    part = dest.with_name(dest.name + ".part")
    models_dir().mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(models_dir()).free
    if size and free < size * 105 // 100:
        err(f"{Style.RED}Not enough free disk space{Style.R}: need about {human_size(size * 105 // 100)}, "
            f"have {human_size(free)}.")
        return None
    err(f"{Style.ORANGE}●{Style.R} Downloading {dest.name} ({human_size(size)})")
    try:
        fetch_file(f"{HF_BASE}/{repo}/resolve/main/{file}", part, size)
    except (urllib.error.URLError, OSError) as e:
        err(f"{Style.RED}Download failed{Style.R} ({e}). Run the command again to resume.")
        return None
    got = part.stat().st_size if part.exists() else 0
    if size and got != size:
        err(f"{Style.RED}Downloaded size ({got}) does not match the expected size ({size}).{Style.R} Run again to resume.")
        return None
    os.replace(part, dest)
    return dest


def find_bench() -> str:
    srv = find_llama_server()
    cands = [os.environ.get("LLAMA_BENCH", ""),
             str(Path(srv).parent / ("llama-bench.exe" if srv.endswith(".exe") else "llama-bench")) if srv else "",
             shutil.which("llama-bench") or "",
             str(ROOT / "bin" / "llama-bench"), str(ROOT / "bin" / "llama-bench.exe")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def parse_bench_csv(text: str):
    """llama-bench CSV -> generation speed in tokens/s (rounded), or None if there is no generation row."""
    speed = None
    for row in csv.DictReader(io.StringIO(text)):
        try:
            if int(row.get("n_gen") or 0) > 0:
                speed = int(float(row["avg_ts"]) + 0.5)
        except (ValueError, KeyError):
            continue
    return speed


def run_bench(model: Path):
    """Returns tokens/s, None if the model did not load, or raises FileNotFoundError without llama-bench."""
    bench = find_bench()
    if not bench:
        raise FileNotFoundError("llama-bench")
    env = dict(os.environ)
    libdir = str(Path(bench).parent)
    for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        env[var] = libdir + (os.pathsep + env[var] if env.get(var) else "")
    try:
        done = subprocess.run([bench, "-m", str(model), "-p", "32", "-n", "24", "-r", "1", "-o", "csv"],
                              capture_output=True, text=True, timeout=300, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_bench_csv(done.stdout)


def check_model_speed(path: Path, size: int, hw: Hw) -> int:
    S = Style
    say(f"{S.ORANGE}●{S.R} Testing speed (about 10 seconds)...")
    try:
        tps = run_bench(path)
    except FileNotFoundError:
        say(f"{S.YELLOW}llama-bench not found, skipping the speed test.{S.R} Install llama.cpp first "
            "(README step 1), then run: model-setup --test")
        return 2
    if tps is None:
        say(f"{S.RED}The model did not load or the test failed.{S.R} The model may be too big for this machine.")
        return 1
    v = verdict(tps)
    state_set("measured_tps", tps)
    state_set("eff_bw", tps * max(size // 1048576, 1))
    state_set("eff_mode", fit(size, hw))
    say(f"{S.GREEN}✔{S.R} Generation speed: {S.B}{tps} t/s{S.R}  {verdict_label(v)}")
    say({"smooth": "  Smooth for chat. You could try a bigger model with --check-updates.",
         "usable": "  Usable. Replies take a moment; a smaller model would feel snappier."}.get(
        v, "  Slow on this machine. Run model-setup again and pick a smaller model."))
    return 0


def record_installed(name: str, repo: str, size: int) -> None:
    state_set("installed", name)
    state_set("installed_repo", repo)
    state_set("installed_size_mb", size // 1048576)


# --- Prompts ------------------------------------------------------------------------------------
class Ctx:
    assume_yes = False


def prompt(text: str) -> str:
    """Show a question on stderr (so stdout stays clean) and read one line; '' at end of input."""
    sys.stderr.write(text + " ")
    sys.stderr.flush()
    try:
        return input().strip()
    except EOFError:
        return ""


def ask(question: str, default: str) -> str:
    if Ctx.assume_yes:
        return default
    return prompt(f"{question} {Style.D}[{default}]{Style.R}") or default


def ask_use() -> str:
    err("What will you use it for?")
    err("  1) General chat   2) Translation   3) Coding   4) Smallest and fastest")
    return {"2": "translation", "translation": "translation", "3": "coding", "coding": "coding",
            "4": "fast", "fast": "fast"}.get(ask("Choose", "1"), "chat")


# --- Flows -----------------------------------------------------------------------------------------
def banner() -> None:
    say(f"\n  {Style.ORANGE}✻ llama-cpp-launchpad{Style.R}  model setup\n")


def print_rows(rows: list) -> None:
    for i, m in enumerate(rows, 1):
        say(f"  {Style.B}{i}){Style.R} {m['name']:<34} {human_size(m['size']):>8}  "
            f"{verdict_label(m['verdict'])}  {Style.D}~{m['tps']} t/s{Style.R}")
        say(f"       {Style.D}{m['note']}{Style.R}")


def pick_and_install(rows: list, hw: Hw) -> int:
    choice = ask(f"Download which one? (1-{len(rows)}, or n to skip)", "1")
    if choice.lower() in ("n", "no", ""):
        say("Skipped.")
        return 0
    if not choice.isdigit() or not 1 <= int(choice) <= len(rows):
        say(f"{Style.RED}Invalid choice.{Style.R}")
        return 1
    m = rows[int(choice) - 1]
    path = models_dir() / Path(m["file"]).name
    if path.is_file():
        say(f"{Style.GREEN}✔{Style.R} {path.name} is already in {models_dir()}")
    else:
        path = download(m["repo"], m["file"], m["size"])
        if not path:
            return 1
    record_installed(m["name"], m["repo"], m["size"])
    check_model_speed(path, m["size"], hw)
    state_set("last_checked", today().isoformat())
    say(f"\nReady. Start it with: {Style.B}./scripts/unix/serve.sh{Style.R}  (Windows: scripts\\win\\serve.bat)")
    return 0


def wizard(use_arg: str | None, list_only: bool) -> int:
    banner()
    say(f"{Style.B}1/3{Style.R} Scanning your system...")
    hw = detect_hw()
    save_hw(hw)
    say(describe_hw(hw))
    if hw.ram_mb <= 0:
        say(f"{Style.RED}Could not read your RAM.{Style.R} Set LP_RAM_MB=<megabytes> and run again.")
        return 1
    if not find_llama_server():
        say(f"{Style.YELLOW}llama-server was not found.{Style.R} Install it before launching (README step 1).")
    say(f"\n{Style.B}2/3{Style.R} Choose a use")
    use = use_arg or ask_use()
    state_set("use", use)
    say(f"\n{Style.B}3/3{Style.R} Recommended for you")
    rows = recommend(use, hw)
    if not rows:
        say(f"{Style.RED}No catalog model fits this machine well.{Style.R} "
            "Try a smaller model from https://huggingface.co/ggml-org")
        return 1
    print_rows(rows)
    say()
    return 0 if list_only else pick_and_install(rows, hw)


def check_updates() -> int:
    banner()
    hw = detect_hw()
    old_sig = state_get("hw_sig")
    if old_sig and old_sig != hw.sig():
        say(f"{Style.YELLOW}Your hardware changed since the last setup.{Style.R} Fit estimates use the new values.")
        state_set("eff_bw", "")
    save_hw(hw)
    say(describe_hw(hw))
    since = state_get("last_checked") or add_days(today().isoformat(), -30)
    say(f"{Style.ORANGE}●{Style.R} Checking Hugging Face for GGUF models released since {since}...")
    if http_json(f"{HF_API}/models?limit=1") is None:
        say(f"{Style.YELLOW}Could not reach Hugging Face.{Style.R} Check your connection and try again later.")
        return 1
    rows = find_upgrades(since, hw)
    state_set("last_checked", today().isoformat())
    state_set("next_prompt", add_days(today().isoformat(), check_days()))
    if not rows:
        say(f"{Style.GREEN}✔{Style.R} Nothing new fits your hardware at a usable speed. Checked {today()}.")
        return 0
    installed = state_get("installed")
    say(f"New models that fit your machine{f' (you run {installed})' if installed else ''}:\n")
    for i, r in enumerate(rows, 1):
        say(f"  {Style.B}{i}){Style.R} {r['repo']:<40} {human_size(r['size']):>8}  {Style.D}~{r['tps']} t/s{Style.R}")
        say(f"       {Style.D}{r['label']} · {r['downloads']} downloads · {r['likes']} likes · released {r['created']}{Style.R}")
    say(f"{Style.D}Community popularity is a hint, not a quality score. The speed test below shows what it does on your machine.{Style.R}\n")
    choice = ask(f"Download which one? (1-{len(rows)}, or n to skip)", "n")
    if choice.lower() in ("n", "no", ""):
        return 0
    if not choice.isdigit() or not 1 <= int(choice) <= len(rows):
        say(f"{Style.RED}Invalid choice.{Style.R}")
        return 1
    r = rows[int(choice) - 1]
    path = download(r["repo"], r["file"], r["size"])
    if not path:
        return 1
    record_installed(Path(r["file"]).stem, r["repo"], r["size"])
    check_model_speed(path, r["size"], hw)
    say(f"Start it with: {Style.B}./scripts/unix/serve.sh{Style.R}  (Windows: scripts\\win\\serve.bat)")
    return 0


def should_prompt(interactive: bool | None = None) -> bool:
    """Weekly nudge rule: True = ask the user now."""
    if interactive is None:
        interactive = sys.stdin.isatty() or os.environ.get("LP_ASSUME_TTY") == "1"
    if not interactive or check_days() <= 0 or not state_get("hw_sig"):
        return False                                    # no profile yet: the wizard handles that
    if state_get("check_updates") == "off":
        return False
    np, last = state_get("next_prompt"), state_get("last_checked")
    if np and today() < dt.date.fromisoformat(np):
        return False
    if last and days_since(last) < check_days():
        return False
    return True


def weekly_prompt() -> int:
    if not should_prompt():
        return 0
    last = state_get("last_checked")
    say(f"It has been {days_since(last)} days since your last model check." if last
        else "You have not checked for new models yet.")
    ans = prompt(f"Check Hugging Face for new models that fit your machine? "
                 f"{Style.D}[y = yes / n = in {check_days()} days / later / never]{Style.R}").lower()
    if ans in ("y", "yes"):
        check_updates()
        say()
    elif ans in ("n", "no"):
        state_set("next_prompt", add_days(today().isoformat(), check_days()))
    elif ans == "never":
        state_set("check_updates", "off")
        say("OK. Run model-setup --check-updates whenever you like.")
    return 0                                            # anything else = later: ask again next launch


def test_cmd(file: str | None) -> int:
    path = Path(file) if file else None
    if not path:
        inst = state_get("installed")
        found = sorted(models_dir().glob(f"{inst}*.gguf")) if inst else []
        found = found or sorted(models_dir().glob("*.gguf"))
        path = found[0] if found else None
    if not path or not path.is_file():
        say(f"No model to test. Put a .gguf in {models_dir()} or run model-setup.")
        return 1
    say(f"Testing {path.name}...")
    return 1 if check_model_speed(path, path.stat().st_size, detect_hw()) == 1 else 0


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(prog="model-setup", description="Pick, download and test a model for this machine.")
    p.add_argument("--check-updates", action="store_true", help="look for new models that fit this machine")
    p.add_argument("--test", nargs="?", const="", metavar="FILE", help="speed-test an installed model")
    p.add_argument("--list", action="store_true", help="show recommendations only (no download)")
    p.add_argument("--weekly-prompt", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--use", choices=["chat", "translation", "coding", "fast"])
    p.add_argument("--yes", "-y", action="store_true", help="accept the defaults")
    a = p.parse_args(argv)
    init_style()
    Ctx.assume_yes = a.yes
    if a.weekly_prompt:
        return weekly_prompt()
    if a.check_updates:
        return check_updates()
    if a.test is not None:
        return test_cmd(a.test or None)
    return wizard(a.use, a.list)


if __name__ == "__main__":
    sys.exit(main())
