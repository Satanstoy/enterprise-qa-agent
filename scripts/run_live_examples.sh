#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/examples/live}"
PROVIDER="${OPENCODE_PROVIDER:-opencode-go}"
MODEL="${OPENCODE_MODEL:-deepseek-v4.1-flash}"
CLI_PATH="${OPENCODE_CLI_PATH:-}"

run_case() {
  local name="$1"
  local data_dir="$2"
  shift 2
  local dir="$OUT/$name"
  mkdir -p "$dir"
  cp "$ROOT/examples/$name/input.json" "$dir/input.json"

  python3 "$ROOT/run.py" run \
    --input "$dir/input.json" \
    --data-dir "$data_dir" \
    --state-dir "$dir" \
    --engine opencode-local \
    --provider "$PROVIDER" \
    --model "$MODEL" \
    --now "2026-11-10T09:00:00+08:00" \
    ${CLI_PATH:+--cli-path "$CLI_PATH"} \
    "$@"
}

run_case 01-clear "$ROOT/data"
run_case 02-conflict "$ROOT/data"
run_case 03-paraphrase "$ROOT/data"
run_case 04-out-of-corpus "$ROOT/data"
run_case 05-followup "$ROOT/data"
run_case 06-tool-failure "$ROOT/data" --fault search_docs:2
run_case 07-resolved-conflict "$ROOT/data"
run_case 08-doc-updated "$ROOT/examples/08-doc-updated/data"
