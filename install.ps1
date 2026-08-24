$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
  throw "Codex CLI não encontrado no PATH."
}

if (-not (Test-Path "$Root\.agents\plugins\marketplace.json")) {
  throw "marketplace.json não encontrado."
}

if (-not (Test-Path "$Root\plugins\project-continuity\.codex-plugin\plugin.json")) {
  throw "plugin.json não encontrado."
}

if (Get-Command python -ErrorAction SilentlyContinue) {
  python "$Root\plugins\project-continuity\scripts\validate_plugin.py" "$Root\plugins\project-continuity"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  py -3 "$Root\plugins\project-continuity\scripts\validate_plugin.py" "$Root\plugins\project-continuity"
} else {
  throw "Python 3 não encontrado no PATH."
}

codex plugin marketplace add "$Root"
codex plugin add project-continuity --marketplace rafaelscosta-plugins
codex plugin marketplace list

Write-Host ""
Write-Host "Marketplace local registrado. Reinicie o ChatGPT Desktop e abra uma conversa nova."
