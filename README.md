<div align="center">

# 🚀 llama-cpp-launchpad

**Local AI in one command.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Powered by](https://img.shields.io/badge/powered%20by-llama.cpp-orange)

</div>

Pick a model. Pick an interface. Start chatting. Everything runs on your machine.

```
  ✻ llama-cpp-launchpad  local model server

  Choose a model  ↑/↓ move · enter select · q quit

  ❯ gemma-3-4b-it-Q4_K_M.gguf                      2.4G
    Qwen3-1.7B-Q4_K_M.gguf                         1.2G

  Choose an interface  ↑/↓ move · enter select · q quit

  ❯ llama.cpp Default                       built-in chat
    Translation                                translator
```

## Start

**1. Get llama.cpp**

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows (then open a new terminal)
```

Linux: download a [release](https://github.com/ggml-org/llama.cpp/releases) and copy everything from it into `bin/`.
Already have it? Check with `llama-server --version`.

**2. Get a model that fits your machine**

```bash
./scripts/unix/model-setup.sh          # Windows: scripts\win\model-setup.bat
```

It reads your hardware, recommends models that will run well, downloads one, and tests its speed.
Needs Python 3. Prefer to do it by hand? Drop any `.gguf` file into `models/` ([how](models/README.md)).

**3. Run**

```bash
./scripts/unix/serve.sh                # Windows: double-click scripts\win\serve.bat
```

## model-setup

Which model should you run? It tells you.

- **First run:** detects RAM and GPU, asks what you'll use it for, shows up to five models that fit with an estimated speed, downloads your pick, and measures the real speed.
- **Every week:** `serve` offers to check for new models that fit your hardware and beat what you run now. Say `y`, `n`, `later` or `never`.
- **On demand:**

```bash
./scripts/unix/model-setup.sh --check-updates   # anything new for my machine?
./scripts/unix/model-setup.sh --test            # re-run the speed test
./scripts/unix/model-setup.sh --list            # recommendations only
```

Estimates are estimates until the speed test runs. Hugging Face popularity is a hint, not a quality score.
By default it only suggests uploads from trusted quantizers and official model makers (`INCLUDE_ALL=1` shows everything).

**Safe to read.** One file, `scripts/model_setup.py`. Python standard library only. It talks to `huggingface.co`
and writes only to `models/` and `.launchpad-state`. Tests fail if it ever imports anything else, starts a shell, runs
dynamic code or contacts another host.

## Interfaces

| | |
|---|---|
| **llama.cpp Default** | llama.cpp's own chat page |
| **Translation** | a translator page that matches its look: pick languages, swap them, choose formal (*vous*) or informal (*tu*) French, tune tone and temperature. One HTML file, no dependencies. |

Small models (1B) translate roughly; 4B and up are noticeably better.

## Options

Environment variables, same on every platform:

| Variable | Default | Meaning |
|---|---|---|
| `MODELS_DIR` | `models/` | where your `.gguf` files are |
| `LLAMA_SERVER` | auto-detected | path to `llama-server` |
| `PORT` | `8080` | port to serve on |
| `UI` | ask | `default` or `translation`: skip the menu |
| `OPEN_BROWSER` | `1` | open the web UI when ready |
| `KILL_EXISTING` | `1` | stop any running `llama-server` first (affects all yours) |
| `EXTRA_ARGS` | empty | extra `llama-server` flags, e.g. `"-t 8 -c 8192"` |
| `CHECK_DAYS` | `7` | days between update prompts, `0` = never |
| `INCLUDE_ALL` | off | `1` = suggest unknown authors and fine-tunes |
| `LP_RAM_MB`, `LP_VRAM_MB` | detected | override hardware detection |

Example: `PORT=9000 UI=translation ./scripts/unix/serve.sh` (Windows: `$env:PORT = "9000"`).

`serve` looks for `llama-server` in `$LLAMA_SERVER`, your `PATH`, `bin/`, then `~/llama.cpp/build/bin/`.
It listens on localhost only and has no API key, so don't expose the port. `Ctrl+C` stops it.

## Troubleshooting

| Problem | Fix |
|---|---|
| Could not find llama-server | Install it (step 1) or set `LLAMA_SERVER`. On Windows, open a new terminal after `winget`. |
| Browser shows `File Not Found` | Your build has no chat page (seen with Homebrew on Linux). Pick **Translation**, or use a release build. |
| No `.gguf` models found | Run `model-setup`, or put a model in `models/`. |
| Port in use | Set `PORT=9000`. |
| Very slow replies | Use a smaller model, or `EXTRA_ARGS="-t 8"`. |
| Out of memory | Pick a smaller model (`Q4_K_M` is a good balance). |
| model-setup says "GPU not used" | Your llama.cpp build is CPU-only. Install a CUDA, Vulkan or Metal build. |
| model-setup needs Python | `winget install Python.Python.3.12`, `brew install python`, or `sudo apt install python3`. |

## Develop

```bash
python3 -m unittest discover -s tests -v
```

No network, GPU or llama.cpp needed.

```
models/              your .gguf files (git-ignored)
bin/                 optional llama-server (git-ignored)
scripts/             serve and model-setup launchers, model_setup.py, models.catalog
ui/translation/      the translation interface
tests/               unit tests and source audit
```

## License

[MIT](LICENSE) © Kunal Suri
