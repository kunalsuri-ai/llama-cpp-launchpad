# models/

Put your `.gguf` model files in this folder. They are not part of the repository (too large, and git-ignored),
so download them yourself from [Hugging Face](https://huggingface.co/ggml-org).

## Download

Run these from inside this `models/` folder (`curl` is built into Linux, macOS and Windows 10/11; in PowerShell use `curl.exe`).

| Model | Size (approx.) | Command |
|---|---|---|
| Gemma 3 1B (smallest, fastest) | ~0.8 GB | `curl -L -O https://huggingface.co/ggml-org/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf` |
| Qwen3 1.7B | ~1.3 GB | `curl -L -O https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf` |
| Gemma 3 4B (better answers, more RAM) | ~2.5 GB | `curl -L -O https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf` |

Or with the Hugging Face CLI (`pip install -U huggingface_hub`):

```bash
hf download ggml-org/gemma-3-1b-it-GGUF gemma-3-1b-it-Q4_K_M.gguf --local-dir .
```

## Other models

Any GGUF file works. Browse <https://huggingface.co/ggml-org> or search Hugging Face for "GGUF". `Q4_K_M` is a good
size/quality balance; bigger models need more RAM. Then run the launcher from the project root and pick your model.
