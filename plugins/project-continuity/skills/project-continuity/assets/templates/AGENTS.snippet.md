## Project continuity

- This repository uses `.continuity/state.json` and sealed PCP/1 checkpoints for changing project state.
- `AGENTS.md` remains the authority for durable repository instructions; continuity checkpoints never override current instructions.
- When asked to continue, resume, hand off, verify prior completion, or close a gate, use the `project-continuity` skill before substantial work.
- Verify the canonical checkpoint against current repository state before trusting prior `completed` claims.
- If checkpoint baseline and repository differ, reconcile first; do not silently treat stale state as current.
- Never overwrite a parallel continuity head. Preserve detached checkpoints and reconcile them explicitly.
