#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI não encontrado no PATH." >&2
  exit 1
fi

test -f "$ROOT/.agents/plugins/marketplace.json"
test -f "$ROOT/plugins/project-continuity/.codex-plugin/plugin.json"
python3 "$ROOT/plugins/project-continuity/scripts/validate_plugin.py" "$ROOT/plugins/project-continuity"

codex plugin marketplace add "$ROOT"
codex plugin add project-continuity --marketplace rafaelscosta-plugins
codex plugin marketplace list

echo
echo "Marketplace local registrado. Reinicie o ChatGPT Desktop e abra uma conversa nova."
