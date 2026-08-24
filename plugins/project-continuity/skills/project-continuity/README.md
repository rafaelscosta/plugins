# Project Continuity Skill

A portable Agent Skill for moving **verified project state** between ChatGPT, Codex, and other Agent Skills-compatible clients.

## Why it exists

Long conversations and long-running coding sessions blur three different things:

1. what was discussed;
2. what was decided;
3. what was actually implemented and verified.

This skill makes that distinction explicit. It creates parent-linked PCP/1 checkpoints where completion claims require evidence and consumers must reconcile checkpoints against current project state.

## Main capabilities

- ChatGPT → Codex handoff without transcript dumping.
- Codex → ChatGPT state transfer.
- Tamper-evident sealed checkpoints.
- Git/worktree and file-hash baselines.
- Recorded test/command evidence.
- Exact/advanced/drift/diverged/project-mismatch/unverifiable classifications.
- Compare-and-swap head promotion for parallel-agent safety.
- Gate closure that refuses unsupported “100% done” claims.
- Portable fallback when repository access is unavailable.
- Stable cross-surface project identity via normalized Git origin, with explicit `--project-id` fallback.

## Install

Upload or install the `project-continuity/` directory as an Agent Skill in each surface where you want to use it.

ChatGPT personal Skills and Codex installations may need to be installed separately even though the same Agent Skills package is portable.

## Quick start in a repository

```bash
python3 scripts/continuity.py init --root . --project-name "My Project"
python3 scripts/continuity.py draft --root . --surface codex --model gpt-5.6-sol --objective "Ship the next validated release"
# edit the generated draft
python3 scripts/continuity.py seal --root . --draft .continuity/drafts/<id>.json --promote
python3 scripts/continuity.py verify --root . --json
python3 scripts/continuity.py render --root .
```

## Handoff between ChatGPT and Codex

One interchange file: `~/Downloads/pcp-handoff.json`.

```bash
python3 scripts/continuity.py handoff-out --root .
python3 scripts/continuity.py handoff-in --root .
```

ChatGPT prompt: **Handoff to Codex** — emit only the portable template JSON and save it as that file. Codex prompt: **Handoff in** — consume it. Do not promote unsupported claims.

`consume --checkpoint <file>` remains available when the file is not in the default path. Cross-project IDs are rejected unless identity is independently confirmed and explicitly mapped.

## Test the bundled CLI

```bash
python3 -m unittest discover -s tests -v
```

The CLI uses only the Python standard library plus Git when Git evidence is available.

## Protocol

See `references/DESIGN.md`, `references/PROTOCOL.md`, and JSON Schemas under `assets/schemas/`.

## Validation

See `VALIDATION.md` for the 30-test adversarial suite, JSON Schema smoke test, bidirectional ChatGPT ↔ Codex smoke test, security checks, and explicit limitations.
