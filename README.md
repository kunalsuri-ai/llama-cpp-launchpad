# llama-cpp-launchpad

A small terminal launcher for [llama.cpp](https://github.com/ggml-org/llama.cpp) on **Linux, macOS and Windows**.
Run one script, pick a model from the `.gguf` files in the `models/` folder with the arrow keys, and it starts
`llama-server`, then choose an interface: **llama.cpp Default** (its built-in chat) or **Translation** (a translator page
that matches its look). The chosen page opens in your browser.

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

| Platform | Launcher | Needs |
|---|---|---|
| Linux | `scripts/unix/serve.sh` | bash, curl |
| macOS | `scripts/unix/serve.sh`, or double-click `scripts/mac/serve.command` | bash (the built-in one works), curl |
| Windows | double-click `scripts/win/serve.bat`, or run `scripts\win\serve.ps1` | PowerShell 5.1 (built in) or 7 |

## Project layout

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

## Quick start

1. **Have `llama-server`?** Check (step 1 below). If not, install it.
2. **Put a model** (a `.gguf` file) in the `models/` folder (step 2).
3. **Run the launcher** for your system (step 3), pick a model, and chat in the browser.

## 1. Get llama.cpp (the `llama-server` program)

**First, check whether you already have it.** Open a terminal and run:

```bash
llama-server --version          # Linux / macOS
```
```powershell
llama-server --version          # Windows (PowerShell)
```

If it prints a version, you're done: the launcher finds it automatically through your `PATH`.
This includes Windows users who installed it earlier with `winget install llama.cpp`.
If the command isn't found, install it:

- **Windows:** `winget install llama.cpp`, then open a **new** terminal so it is on your `PATH`.
- **macOS:** `brew install llama.cpp`, or use a release download (below).
  If macOS blocks a downloaded binary, run `xattr -dr com.apple.quarantine <folder>` on the unpacked folder.
- **Linux:** use a release download (below). `brew install llama.cpp` also works, but in one test on Linux the
  Homebrew build's web page returned 404 (the API still worked). If that happens, use the release build.
- **Any platform:** build from source (see the llama.cpp README).

**Release download (no installer, no compiling):** get the build for your system from the
[releases page](https://github.com/ggml-org/llama.cpp/releases) (for example `ubuntu-x64` for plain CPU,
`vulkan` for AMD/Intel GPUs, `macos-arm64` for Apple Silicon). Unpack it, then copy **everything in the unpacked
folder** (not just `llama-server`, since it needs the library files next to it) into this project's `bin/` folder:

```bash
mkdir -p bin
tar -xzf llama-*-bin-ubuntu-x64.tar.gz
cp -r llama-*/* bin/              # the folder name inside the archive can differ; check with ls
```

The launcher checks `bin/` automatically. On Windows, unzip into `bin\` so that `bin\llama-server.exe` exists.

## 2. Get a model

Download any `.gguf` file into the `models/` folder, for example:

```bash
cd models
curl -L -O https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf
```

(`curl` is also built into Windows 10/11; in PowerShell use `curl.exe`.)
Browse more at <https://huggingface.co/ggml-org>. Bigger models give better answers but need more RAM.

## 3. Run

**Linux / macOS**

```bash
chmod +x scripts/unix/serve.sh scripts/mac/serve.command
./scripts/unix/serve.sh
```

**Windows**: double-click `scripts\win\serve.bat`, or in a terminal:

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

## Interfaces

After you pick a model, the launcher asks which interface to open:

| Interface | What it is |
|---|---|
| **llama.cpp Default** | llama.cpp's own chat page, built into `llama-server` |
| **Translation** | a translator page in `ui/translation/`, styled to match the default page (same colors, light and dark) |

**Translation** opens with a two-line English example already in the box and **English → French** selected, so you can
press the send button right away to see a translation. (It always opens in this default state, and the "new translation"
button in the left bar returns to it.) Then you can:

- pick the source language (or auto-detect) and the target language, and swap them
- when the target is **French**, choose **Formal (vous)** or **Normal (tu)** with the switch next to the language
  (formal is the default; the switch hides for other target languages)
- press Enter to translate (Shift+Enter for a new line); the result streams in with token and speed stats, and you can
  copy it or translate it again
- open the gear icon to set the tone (for languages other than French) and the temperature

It is a single HTML file with no outside dependencies, served by `llama-server` itself. Translation quality depends on
the model: small models (1B) are rough, and 4B and up are noticeably better, including at keeping to *vous* or *tu*.

To skip the interface question, set `UI` (Windows: `$env:UI = "translation"`):

```bash
UI=translation ./scripts/unix/serve.sh
UI=default ./scripts/unix/serve.sh
```

## Options

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

## Notes

- The server listens on localhost only by default and has no API key. Don't expose the port to a network you don't trust.
- Model files are ignored by git (see `.gitignore`).
- Press `Ctrl+C` in the terminal to stop the server.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not find llama-server" | Run `llama-server --version`. If it's not found, install it (step 1), or set `LLAMA_SERVER`. On Windows after `winget`, open a new terminal. |
| Browser shows `{"error": ... "File Not Found"}` | Your `llama-server` build has no built-in chat page (seen with Homebrew on Linux). Choose **Translation** (our own page, which doesn't need it), or use a release build. |
| "No .gguf models found" | Put a `.gguf` file in `models/` (step 2). |
| Port already in use | Another program is on that port. Use `PORT=9000` (Windows: `$env:PORT = "9000"`). |
| Very slow replies | Use a smaller model, or add threads: `EXTRA_ARGS="-t 8"`. |
| Model fails to load / out of memory | The model is too big for your RAM. Pick a smaller or more compressed one (for example `Q4_K_M`). |

## License

[MIT](LICENSE)
