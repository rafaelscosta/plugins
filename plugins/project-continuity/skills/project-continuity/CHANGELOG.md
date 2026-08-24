# Changelog

## Unreleased

- Added `handoff-out` and `handoff-in` interchange commands (`~/Downloads/pcp-handoff.json`).
- Added short **Handoff to Codex** and **Handoff in** prompts to the skill.

## 1.0.0 — 2026-08-21

- Introduced PCP/1 checkpoint protocol.
- Added evidence-required completion invariant.
- Added canonical SHA-256 checkpoint sealing.
- Added Git/worktree and file baseline capture.
- Added exact/advanced/drift/diverged/unverifiable verification states.
- Added compare-and-swap head promotion and detached checkpoint handling.
- Added ChatGPT, Codex, security, and eval references.
- Added standard-library continuity CLI and tests.
- Added safe external checkpoint consumption with project-identity enforcement and downgrade-on-import semantics.
- Added effective project snapshots that exclude continuity metadata to prevent self-induced drift.
- Added normalized Git-origin project identity for cross-clone SSH/HTTPS portability.
- Added project-mismatch verification and explicit project-mapping guard.
- Added filesystem-boundary protections for drafts, rendered outputs, checkpoint IDs, and internal symlink paths.
- Expanded adversarial validation to 30 automated tests plus bidirectional handoff smoke testing.
