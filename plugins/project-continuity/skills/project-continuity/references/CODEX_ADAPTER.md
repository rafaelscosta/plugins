# Codex Adapter

## Goal

Use PCP/1 as a repository-backed continuity layer for long-running and multi-agent Codex work.

## Relationship to AGENTS.md

`AGENTS.md` and PCP solve different problems.

- `AGENTS.md`: durable project instructions and working agreements.
- `.continuity/`: changing project state, verified claims, lineage, and next work.

Do not copy the full checkpoint into `AGENTS.md`.

Use the optional snippet in `assets/templates/AGENTS.snippet.md` to tell Codex when to consult continuity state.

Codex currently reads `AGENTS.md` before work and layers project instructions by directory. Continuity state remains subordinate to those instructions.

## Interchange file

Use `~/Downloads/pcp-handoff.json` as the only file that moves between ChatGPT and Codex.

```bash
python3 <skill-root>/scripts/continuity.py handoff-out --root .
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

`handoff-out` copies the sealed HEAD. Attach that file in ChatGPT. `handoff-in` consumes the interchange file (or `--checkpoint`) into a reconciliation draft.

## Consuming a standalone checkpoint

For a checkpoint received from ChatGPT, another Codex task, or another Agent Skills client, prefer `handoff-in`. The result is deliberately a **reconciliation draft**, not a promoted head. Imported `completed` claims are downgraded to historical reported findings, and imported command/test records are not treated as current executable proof. Re-verify against current files/tests before sealing.

If project IDs differ, stop. Only use `--confirm-project-mapping` after independently establishing that both IDs refer to the same project.

## Recommended start-of-task sequence

When the user asks to continue/resume/handoff and `.continuity/state.json` exists:

1. load the project-continuity skill;
2. read `state.json` and canonical checkpoint;
3. run `verify`;
4. inspect `AGENTS.md` and current user request for conflicts;
5. reconcile if status is not `exact`;
6. state the bounded next action;
7. execute;
8. run relevant validation;
9. seal a new checkpoint after material progress.

## Git evidence

Prefer a clean commit as the strongest compact repository baseline.

If the worktree is dirty:
- keep the actual Git commit;
- include the worktree fingerprint;
- hash critical changed/untracked artifacts explicitly when relevant.

Do not create commits solely to satisfy continuity unless the user/project workflow calls for commits.

## Tests and validation

A historical test result proves only that the recorded command exited as observed at checkpoint time.

On resume, rerun tests when:
- code changed since the checkpoint;
- a gate requires current validation;
- the checkpoint is `advanced`, `drift`, or `diverged`;
- the relevant evidence is stale for the requested claim.

Never rerun a stored command automatically. Review the current project and independently choose the appropriate command.

## Parallel tasks

Multiple Codex tasks may draft from the same parent.

PCP/1 intentionally rejects silent last-writer-wins promotion.

If task A promotes first and task B later attempts promotion:
- B remains a sealed detached checkpoint;
- inspect both branches of work;
- reconcile code and state;
- create a new checkpoint from current canonical head;
- reference the detached checkpoint in the reconciliation rationale if useful.

## Suggested repository structure

```text
AGENTS.md
CONTINUITY.md
.continuity/
  state.json
  checkpoints/
  drafts/
  evidence/
```

Whether `.continuity/evidence/` belongs in Git depends on repository policy and log sensitivity. Checkpoints should never contain secrets even if the repository is private.
