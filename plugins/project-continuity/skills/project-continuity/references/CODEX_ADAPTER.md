# Codex Adapter

## Goal

Use PCP/1 as a repository-backed continuity layer for long-running/multi-agent Codex work and consume mobile ChatGPT handoffs without requiring a local Downloads transfer when a remote transport is available.

## Relationship to AGENTS.md

`AGENTS.md` and PCP solve different problems:
- `AGENTS.md`: durable project instructions/working agreements;
- `.continuity/`: changing project state, verified claims, lineage, and next work;
- `pcp-planning/1`: accepted long-horizon roadmap memory;
- remote handoff: portable historical input, never repository authority.

Do not copy a full checkpoint/planning snapshot into `AGENTS.md`.

## Start-of-task precedence

When continuing/resuming:
1. current system/developer/user instructions;
2. current repository instructions such as `AGENTS.md`;
3. current repository/files/tool reality;
4. current canonical local PCP state;
5. verified remote handoff integrity/history;
6. older conversation narrative.

## Receiving a `pcp+github` handoff

If an authorized GitHub binding is available:
1. parse the exact canonical reference from `references/mobile/TRANSPORTS.md`;
2. fetch the envelope using the referenced owner/repository/path;
3. verify raw envelope SHA-256 embedded in the filename before trusting its locations;
4. validate strict envelope schema, handoff ID, and project token;
5. derive the canonical checkpoint/planning paths from project ID + artifact IDs/digests;
6. reject non-canonical locations rather than following arbitrary paths;
7. fetch and verify checkpoint/planning canonical digests;
8. treat `sealed + unverifiable` as integrity/history, not current repository verification;
9. feed the external PCP checkpoint into downgrade-first consumption/reconciliation;
10. reconcile planning with the current repository before choosing implementation work.

A Codex host may implement the injected GitHub transport binding using its authorized GitHub API/connector. It must not put access tokens into the reference/artifacts.

If the GitHub transport is unavailable, do not claim the reference was resolved. Use a supported fallback artifact only when actually supplied/accessible.

## Downgrade-first checkpoint consumption

An external checkpoint never directly becomes canonical local HEAD.

Imported `completed` claims are historical input and remain downgraded until fresh local hard evidence re-verifies them. Imported historical command/test records are not auto-executed and do not become current proof.

If project IDs differ, stop. Intentional mapping requires independent project-identity confirmation before explicit mapping.

## Planning reconciliation

If a planning snapshot accompanies the handoff:
1. validate its structure and canonical digest;
2. preserve all accepted unfinished work, including post-MVP items omitted from the newest session;
3. inspect current repository state/evidence;
4. express bounded observations through `pcp-planning-reconciliation/1`;
5. run/apply deterministic reconciliation semantics from `scripts/planning_reconcile.py`;
6. use the resulting leaf/dependency-ready frontier, not an unreconciled historical next action.

The reconciler can:
- verify stale planned work already implemented;
- reopen false/historical completion claims;
- invalidate stale verification after code changed;
- unblock or re-block dependency-derived work;
- cascade invalidation upward when a child reopens;
- preserve unrelated accepted post-MVP work.

## Recommended start-of-task sequence

When a local `.continuity/state.json` exists or an external handoff is supplied:
1. load Project Continuity instructions;
2. inspect `AGENTS.md`/repository policy;
3. resolve/verify external handoff if supplied;
4. read local canonical state if initialized;
5. consume external checkpoint downgrade-first into a reconciliation draft;
6. inspect current Git/files/tests;
7. classify PCP compatibility (`exact`, `advanced`, `drift`, `diverged`, `project-mismatch`, etc.);
8. reconcile planning snapshot when present;
9. produce a concise resume brief: objective, surviving decisions, invalidated claims, blockers, exact next frontier;
10. execute only current-user/repository-approved work;
11. run relevant validation;
12. seal/promote a new local checkpoint after material progress;
13. emit/publish a new handoff when cross-surface continuation is needed.

## Git evidence

Prefer a clean commit as the strongest compact repository baseline.

If worktree is dirty:
- keep actual commit;
- include worktree/project snapshot fingerprint;
- hash critical changed/untracked artifacts explicitly where relevant.

Do not create commits solely to satisfy continuity unless repository/user workflow calls for commits.

## Tests and validation

Historical test evidence proves only what was observed at checkpoint time.

Rerun/reinspect when:
- relevant code changed;
- a gate requires current evidence;
- PCP status is advanced/drift/diverged;
- planning `verified_done` evidence is stale for the requested claim.

Never execute a stored historical command just because the handoff contains it.

## Parallel work

PCP/1 local state still uses parent-aware CAS/no-last-writer-wins.

If parallel Codex tasks produce competing results:
- preserve detached checkpoints;
- reconcile code + continuity state explicitly;
- create a new checkpoint from current canonical HEAD;
- do not let remote GitHub storage order determine local canonical project state.

Remote GitHub handoff objects are immutable/content-addressed transport artifacts, not distributed consensus.

## Publishing back to ChatGPT

When a GitHub store is authorized and safe:
1. seal the current PCP checkpoint;
2. pair it with the current planning snapshot when relevant;
3. build/publish content-addressed GitHub objects;
4. write envelope last;
5. re-fetch/verify the resulting reference;
6. return the compact `pcp+github://...` reference.

For FILE/FULL output, `surface_status` and claims reflect evidence actually available at seal time. A later ChatGPT session still distinguishes historical verification from evidence rechecked in that session.

## Legacy file fallback

The historical commands remain valid when a local file transfer is appropriate:

```bash
python3 <skill-root>/scripts/continuity.py handoff-out --root .
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

Default legacy interchange path remains `~/Downloads/pcp-handoff.json`, but file transport is no longer the only protocol path.

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

Whether `.continuity/evidence/` belongs in Git depends on repository policy/log sensitivity. Checkpoints/handoffs must never contain secrets even if both source and continuity repositories are private.
