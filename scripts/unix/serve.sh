#!/usr/bin/env bash
# llama-cpp-launchpad: pick a .gguf model and an interface with the arrow keys, then serve it
# with llama.cpp's llama-server and open it in your browser.
#
# Settings (all optional, via environment variables):
#   MODELS_DIR      folder with your .gguf files          (default: <project>/models)
#   LLAMA_SERVER    path to the llama-server binary       (default: auto-detected)
#   PORT            port to serve on                      (default: 8080)
#   UI              default | translation: skip the interface menu and use this one
#   KILL_EXISTING   1 = stop running llama-server first   (default: 1, set 0 to disable)
#   OPEN_BROWSER    1 = open the web UI when ready        (default: 1, set 0 to disable)
#   EXTRA_ARGS      extra flags passed to llama-server    (e.g. EXTRA_ARGS="-t 8 -c 8192")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"   # project root (scripts/unix -> root)
MODELS_DIR="${MODELS_DIR:-$ROOT_DIR/models}"
PORT="${PORT:-8080}"
KILL_EXISTING="${KILL_EXISTING:-1}"
OPEN_BROWSER="${OPEN_BROWSER:-1}"
UI_CHOICE="$(printf '%s' "${UI:-}" | tr '[:upper:]' '[:lower:]')"

# Colors (disabled when not writing to a terminal)
if [ -t 1 ]; then
  B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
  ORANGE=$'\e[38;5;208m'; GREEN=$'\e[32m'; CYAN=$'\e[36m'; RED=$'\e[31m'
else
  B=; D=; R=; ORANGE=; GREEN=; CYAN=; RED=
fi

trap 'printf "\e[?25h"' EXIT   # always restore the cursor

# --- Locate llama-server -----------------------------------------------------
find_llama_server() {
  if [ -n "$LLAMA_SERVER" ]; then echo "$LLAMA_SERVER"; return; fi
  local c
  for c in "$(command -v llama-server 2>/dev/null)" \
           "$ROOT_DIR/bin/llama-server" \
           "$HOME/llama.cpp/build/bin/llama-server"; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return; }
  done
}
LLAMA_SERVER="$(find_llama_server)"
if [ -z "$LLAMA_SERVER" ] || [ ! -x "$LLAMA_SERVER" ]; then
  echo "${RED}Could not find llama-server.${R}"
  echo "Looked in: \$LLAMA_SERVER, your PATH, $ROOT_DIR/bin, ~/llama.cpp/build/bin"
  echo
  echo "Install llama.cpp, for example:"
  case "$(uname -s)" in
    Darwin) echo "  brew install llama.cpp" ;;
    *)      echo "  download a release from https://github.com/ggml-org/llama.cpp/releases" ;;
  esac
  echo "Then put it on your PATH or in $ROOT_DIR/bin (see README.md), or run:"
  echo "  LLAMA_SERVER=/path/to/llama-server $0"
  exit 1
fi

# --- Stop any running server -------------------------------------------------
if [ "$KILL_EXISTING" = "1" ] && pgrep -x llama-server >/dev/null 2>&1; then
  printf "%s●%s Stopping running llama-server... " "$ORANGE" "$R"
  pkill -x llama-server
  for _ in $(seq 1 50); do pgrep -x llama-server >/dev/null 2>&1 || break; sleep 0.1; done
  echo "done"
fi

# --- Weekly nudge: offer to check for new models that fit this machine ------------
# (silent unless interactive, set up before, and the check is due; CHECK_DAYS=0 disables)
PY="$(command -v python3 || command -v python)"   # model-setup is optional: skipped without Python
[ -n "$PY" ] && "$PY" "$ROOT_DIR/scripts/model_setup.py" --weekly-prompt

# --- Collect models (skip multimodal projector files) ------------------------
models=(); sizes=()
for f in "$MODELS_DIR"/*.gguf; do
  [ -f "$f" ] || continue
  case "$(basename "$f")" in mmproj*) continue ;; esac
  models+=("$(basename "$f")")
  sizes+=("$(du -h "$f" | cut -f1)")
done
if [ ${#models[@]} -eq 0 ]; then
  echo "${RED}No .gguf models found in $MODELS_DIR${R}"
  if [ -n "$PY" ]; then
    echo "Not sure which model suits your machine? ${B}model-setup${R} picks one for you:"
    echo "  ./scripts/unix/model-setup.sh"
    if [ -t 0 ]; then
      printf 'Run it now? %s[Y/n]%s ' "$D" "$R"; read -r ans
      case "$ans" in n|N|no) ;; *) exec "$PY" "$ROOT_DIR/scripts/model_setup.py" ;; esac
    fi
  else
    echo "Download one, e.g. from https://huggingface.co/ggml-org (see README.md)."
  fi
  exit 1
fi

# --- Arrow-key menu ----------------------------------------------------------
# Usage: set M_ITEMS and M_NOTES (same length), call menu_select "Heading"; the chosen index is in M_SEL.
draw_items() {
  local i
  for i in "${!M_ITEMS[@]}"; do
    if [ "$i" -eq "$sel" ]; then
      printf "  %s❯ %-42s%s %s%8s%s\e[K\n" "$ORANGE$B" "${M_ITEMS[$i]}" "$R" "$CYAN" "${M_NOTES[$i]}" "$R"
    else
      printf "    %s%-42s %8s%s\e[K\n" "$D" "${M_ITEMS[$i]}" "${M_NOTES[$i]}" "$R"
    fi
  done
}

menu_select() {
  local title="$1" n=${#M_ITEMS[@]} sel=0 key rest last=$(( ${#M_ITEMS[@]} - 1 ))
  echo "  ${B}${title}${R}  ${D}↑/↓ move · enter select · q quit${R}"
  echo
  printf "\e[?25l"
  draw_items
  while true; do
    IFS= read -rsn1 key
    if [[ $key == $'\e' ]]; then
      read -rsn2 -t 1 rest
      case "$rest" in
        '[A') [ "$sel" -gt 0 ] && sel=$((sel - 1)) ;;
        '[B') [ "$sel" -lt "$last" ] && sel=$((sel + 1)) ;;
      esac
    elif [[ $key == "" ]]; then
      break
    elif [[ $key == k ]]; then [ "$sel" -gt 0 ] && sel=$((sel - 1))
    elif [[ $key == j ]]; then [ "$sel" -lt "$last" ] && sel=$((sel + 1))
    elif [[ $key == q ]]; then printf "\e[?25h\n"; exit 0
    fi
    printf "\e[%dA" "$n"
    draw_items
  done
  # Collapse the menu (items + blank line + heading) so the next step starts clean
  printf "\e[%dA\e[J\e[?25h" "$((n + 2))"
  M_SEL=$sel
}

interactive=0
[ -t 0 ] && [ -t 1 ] && interactive=1

# --- Step 1: model -----------------------------------------------------------
if [ "$interactive" = 1 ]; then
  echo
  echo "  ${ORANGE}${B}✻ llama-cpp-launchpad${R}  ${D}local model server${R}"
  echo "  ${D}$MODELS_DIR${R}"
  echo
  M_ITEMS=("${models[@]}"); M_NOTES=("${sizes[@]}")
  menu_select "Choose a model"
  model_idx=$M_SEL
else
  read -r n; model_idx=$((n - 1))
  [ "$model_idx" -ge 0 ] && [ "$model_idx" -lt ${#models[@]} ] || { echo "Invalid model choice"; exit 1; }
fi
name="${models[$model_idx]}"

# --- Step 2: interface -------------------------------------------------------
UI_NAMES=("llama.cpp Default" "Translation")
UI_KEYS=("default" "translation")
ui_idx=-1
for i in "${!UI_KEYS[@]}"; do [ "$UI_CHOICE" = "${UI_KEYS[$i]}" ] && ui_idx=$i; done
[ "$interactive" = 1 ] && echo "  ${GREEN}✔${R} ${D}Model${R}      ${B}$name${R}"
if [ "$ui_idx" -lt 0 ]; then
  if [ "$interactive" = 1 ]; then
    echo
    M_ITEMS=("${UI_NAMES[@]}"); M_NOTES=("built-in chat" "translator")
    menu_select "Choose an interface"
    ui_idx=$M_SEL
  else
    read -r u || u=1
    ui_idx=$(( ${u:-1} - 1 ))
    [ "$ui_idx" -ge 0 ] && [ "$ui_idx" -lt ${#UI_KEYS[@]} ] || { echo "Invalid interface choice"; exit 1; }
  fi
fi
echo "  ${GREEN}✔${R} ${D}Interface${R}  ${B}${UI_NAMES[$ui_idx]}${R}"
UI_MODE="${UI_KEYS[$ui_idx]}"

# --- Serve -------------------------------------------------------------------
URL="http://localhost:$PORT"
echo
echo "  ${GREEN}●${R} Loading ${B}$name${R}"
echo "  ${D}Serving at${R} ${CYAN}$URL${R}  ${D}(Ctrl+C to stop)${R}"
echo

# Open the browser once the server is up
if [ "$OPEN_BROWSER" = "1" ]; then
  opener="$(command -v xdg-open || command -v open)"
  if [ -n "$opener" ]; then
    (
      for _ in $(seq 1 120); do
        if curl -s -o /dev/null "$URL/health"; then "$opener" "$URL" >/dev/null 2>&1; exit 0; fi
        sleep 1
      done
    ) &
  fi
fi

ui_args=()
if [ "$UI_MODE" = "translation" ]; then
  if [ -f "$ROOT_DIR/ui/translation/index.html" ]; then
    ui_args=(--path "$ROOT_DIR/ui/translation")
  else
    echo "${RED}Translation UI not found at $ROOT_DIR/ui/translation, using the default.${R}"
  fi
fi

# shellcheck disable=SC2086
exec "$LLAMA_SERVER" -m "$MODELS_DIR/$name" --port "$PORT" ${ui_args[@]+"${ui_args[@]}"} $EXTRA_ARGS
