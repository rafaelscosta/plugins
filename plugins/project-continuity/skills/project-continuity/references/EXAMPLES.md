# Worked Examples

## Example 1 — ChatGPT to Codex without repository access

ChatGPT has a long design conversation but no repository.

Good checkpoint behavior:
- objective captured;
- user-approved architecture captured as a `decision` with `reported` confidence;
- “implementation finished” statements remain `reported` unless artifacts were actually inspected;
- first open item is repository reconciliation;
- surface status is `unverifiable`.

Bad behavior:
- writing “100% implemented and tested” because a previous assistant said so.

## Example 2 — Codex closes a test gate

Codex modifies source files, runs unit tests, and validates a generated schema.

Evidence:
- Git/worktree baseline;
- file hashes for critical generated artifacts;
- test evidence with argv, exit code 0, output digest, timestamp.

Claims:

```json
{
  "id": "C-007",
  "kind": "completed",
  "confidence": "verified",
  "statement": "The checkpoint semantic validator rejects completed claims without hard evidence.",
  "evidence": ["E-TEST-003", "E-FILE-004"],
  "supersedes": []
}
```

## Example 3 — Parallel Codex tasks

Both tasks draft from checkpoint `P`.

Task A seals/promotes `A`.

Task B later seals `B`. Its parent is still `P`, but canonical head is now `A`.

Correct behavior:
- keep `B` sealed;
- fail promotion;
- inspect A/B changes;
- integrate compatible work;
- draft checkpoint `C` from current canonical head A;
- mention B as reconciled detached work in rationale.

Incorrect behavior:
- overwrite `state.json` so B becomes head and A disappears from canonical history.

## Example 4 — Repository advanced after handoff

Checkpoint records commit `abc123`. Current HEAD is descendant `def456`.

Correct behavior:
- verify returns `advanced`;
- inspect `abc123..def456`;
- mark checkpoint open items already completed by later work as stale;
- test claims potentially affected by later changes;
- create a reconciliation checkpoint before continuing.
