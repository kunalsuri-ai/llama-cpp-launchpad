<div align="center">

# 🚀 llama-cpp-launchpad

**Run local LLMs with one script. Pick a model, pick an interface, start chatting.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-blue)
![Powered by](https://img.shields.io/badge/powered%20by-llama.cpp-orange)
![Dependencies](https://img.shields.io/badge/dependencies-none-lightgrey)

</div>

A small terminal launcher for [llama.cpp](https://github.com/ggml-org/llama.cpp). It lists the `.gguf` files in
`models/`, lets you choose one with the arrow keys, starts `llama-server`, and opens the interface you pick in your
browser: llama.cpp's built-in chat, or a translator page that matches its look.

```
  ✻ llama-cpp-launchpad  local model server

  Choose a model  ↑/↓ move · enter select · q quit

  ❯ gemma-3-4b-it-Q4_K_M.gguf                      2.4G
    Qwen3-1.7B-Q4_K_M.gguf                         1.2G

  ✔ Model      gemma-3-4b-it-Q4_K_M.gguf

  Choose an interface  ↑/↓ move · enter select · q quit

  ❯ llama.cpp Default                       built-in chat
    Translation                                translator
```

## ✨ Highlights

- **Works everywhere.** Bash on Linux and macOS, PowerShell on Windows, with a double-click launcher for both macOS and Windows.
- **Private by default.** Everything runs on your machine, and the server listens on localhost only.
- **Two interfaces.** llama.cpp's own chat page, or a streaming **Translation** page with English → French preset, formal/informal French (*vous* / *tu*), tone and temperature controls.
- **No dependencies.** The translation UI is one HTML file served by `llama-server` itself.
- **Configurable.** Port, model folder, server path and extra flags are all environment variables.

## ⚡ Quick start

```bash
# 1. Get llama-server (skip if `llama-server --version` already works)
brew install llama.cpp            # macOS; Windows: winget install llama.cpp

# 2. Download a model into models/
cd models
curl -L -O https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf
cd ..

# 3. Launch
chmod +x scripts/unix/serve.sh scripts/mac/serve.command
./scripts/unix/serve.sh           # Windows: double-click scripts\win\serve.bat
```

Linux users: use a [release download](#1-get-llamacpp) instead of step 1. More models are listed in [`models/README.md`](models/README.md).

| Platform | Launcher | Needs |
|---|---|---|
| Linux | `scripts/unix/serve.sh` | bash, curl |
| macOS | `scripts/unix/serve.sh`, or double-click `scripts/mac/serve.command` | bash (the built-in one works), curl |
| Windows | double-click `scripts/win/serve.bat`, or run `scripts\win\serve.ps1` | PowerShell 5.1 (built in) or 7 |

## 📁 Project layout

```
llama-cpp-launchpad/
├── models/            put your .gguf model files here (ignored by git)
├── scripts/
│   ├── unix/serve.sh      Linux and macOS
│   ├── mac/serve.command  macOS double-click launcher
│   └── win/serve.ps1, serve.bat   Windows
├── ui/translation/    the Translation interface (one index.html, no dependencies)
├── bin/               optional: drop llama-server here (ignored by git)
├── LICENSE
└── README.md
```

## 🔧 Setup in detail

### 1. Get llama.cpp

First check whether you already have it:

```bash
llama-server --version
```

If it prints a version you're done. The launcher finds it through your `PATH`, including installs made earlier with
`winget install llama.cpp`. If the command isn't found, install it:

- **Windows:** `winget install llama.cpp`, then open a **new** terminal so it is on your `PATH`.
- **macOS:** `brew install llama.cpp`, or use a release download (below). If macOS blocks a downloaded binary, run
  `xattr -dr com.apple.quarantine <folder>` on the unpacked folder.
- **Linux:** use a release download (below). `brew install llama.cpp` also works, but in one test on Linux the
  Homebrew build's web page returned 404 (the API still worked). If that happens, use the release build.
- **Any platform:** build from source (see the llama.cpp README).

**Release download (no installer, no compiling).** Get the build for your system from the
[releases page](https://github.com/ggml-org/llama.cpp/releases): for example `ubuntu-x64` for plain CPU, `vulkan` for
AMD/Intel GPUs, `macos-arm64` for Apple Silicon. Unpack it, then copy **everything in the unpacked folder** (not just
`llama-server`, since it needs the library files next to it) into this project's `bin/` folder:

```bash
mkdir -p bin
tar -xzf llama-*-bin-ubuntu-x64.tar.gz
cp -r llama-*/* bin/              # the folder name inside the archive can differ; check with ls
```

The launcher checks `bin/` automatically. On Windows, unzip into `bin\` so that `bin\llama-server.exe` exists.

### 2. Get a model

Download any `.gguf` file into `models/`. Copy-paste commands for a few good starters are in
[`models/README.md`](models/README.md); browse more at <https://huggingface.co/ggml-org>. Bigger models give better
answers but need more RAM. (`curl` is built into Windows 10/11; in PowerShell use `curl.exe`.)

### 3. Run

**Linux / macOS**

```bash
chmod +x scripts/unix/serve.sh scripts/mac/serve.command
./scripts/unix/serve.sh
```

**Windows:** double-click `scripts\win\serve.bat`, or in a terminal:

```powershell
.\scripts\win\serve.bat
```

The launcher looks for `llama-server` in this order: the `LLAMA_SERVER` setting, your `PATH`, the project's `bin/`
folder, and (Linux/macOS) `~/llama.cpp/build/bin/`. If yours is somewhere else, point to it:

```bash
LLAMA_SERVER=/path/to/llama-server ./scripts/unix/serve.sh            # Linux / macOS
```
```powershell
$env:LLAMA_SERVER = "C:\path\to\llama-server.exe"; .\scripts\win\serve.bat   # Windows
```

## 🖥️ Interfaces

After you pick a model, the launcher asks which interface to open:

| Interface | What it is |
|---|---|
| **llama.cpp Default** | llama.cpp's own chat page, built into `llama-server` |
| **Translation** | a translator page in `ui/translation/`, styled to match the default page (same colors, light and dark) |

### Translation

It opens with a two-line English example already in the box and **English → French** selected, so you can press the
send button right away. It always opens in this state, and the "new translation" button in the left bar returns to it.
From there you can:

- pick the source language (or auto-detect) and the target language, and swap them
- when the target is **French**, choose **Formal (vous)** or **Normal (tu)** with the switch next to the language
  (formal is the default; the switch hides for other target languages)
- press Enter to translate (Shift+Enter for a new line); the result streams in with token and speed stats, and you can
  copy it or translate it again
- open the gear icon to set the tone (for languages other than French) and the temperature

Translation quality depends on the model. Small models (1B) are rough; 4B and up are noticeably better, including at
keeping to *vous* or *tu*.

To skip the interface question, set `UI` (Windows: `$env:UI = "translation"`):

```bash
UI=translation ./scripts/unix/serve.sh
UI=default ./scripts/unix/serve.sh
```

## ⚙️ Options

Set these as environment variables (same names on every platform):

| Variable | Default | Meaning |
|---|---|---|
| `MODELS_DIR` | `models/` in the project | where your `.gguf` files are |
| `LLAMA_SERVER` | auto-detected | path to the `llama-server` binary |
| `PORT` | `8080` | port to serve on |
| `KILL_EXISTING` | `1` | stop any running `llama-server` first (this affects every `llama-server` process you own) |
| `OPEN_BROWSER` | `1` | open the web UI when the server is ready |
| `UI` | ask | `default` or `translation`: skip the interface menu and use this one |
| `EXTRA_ARGS` | empty | extra flags for `llama-server`, e.g. `"-t 8 -c 8192"` |

Example: `PORT=9000 MODELS_DIR=~/models ./scripts/unix/serve.sh`
(Windows: `$env:PORT = "9000"; .\scripts\win\serve.bat`)

## 🔒 Notes

- The server listens on localhost only by default and has no API key. Don't expose the port to a network you don't trust.
- Model files are ignored by git (see `.gitignore`).
- Press `Ctrl+C` in the terminal to stop the server.

## 🩺 Troubleshooting

| Problem | Fix |
|---|---|
| "Could not find llama-server" | Run `llama-server --version`. If it's not found, install it (step 1), or set `LLAMA_SERVER`. On Windows after `winget`, open a new terminal. |
| Browser shows `{"error": ... "File Not Found"}` | Your `llama-server` build has no built-in chat page (seen with Homebrew on Linux). Choose **Translation** (our own page, which doesn't need it), or use a release build. |
| "No .gguf models found" | Put a `.gguf` file in `models/` (step 2). |
| Port already in use | Another program is on that port. Use `PORT=9000` (Windows: `$env:PORT = "9000"`). |
| Very slow replies | Use a smaller model, or add threads: `EXTRA_ARGS="-t 8"`. |
| Model fails to load / out of memory | The model is too big for your RAM. Pick a smaller or more compressed one (for example `Q4_K_M`). |

## 📄 License

[MIT](LICENSE) © Kunal Suri
