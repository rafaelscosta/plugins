# Session Compiler Contract

**Status:** R2 implementation contract  
**IR:** `pcp-session-compilation/1`  
**Outputs:** PCP/1 PORTABLE checkpoint + `pcp-planning/1` snapshot

## Purpose

The Session Compiler converts available ChatGPT/Codex conversation context into compact, execution-critical project state without treating the transcript as canonical truth.

It is deliberately split into two layers:

1. **Semantic extraction by the agent** produces a strict `pcp-session-compilation/1` intermediate representation (IR).
2. **Deterministic compilation** validates/merges that IR and emits PCP/1 PORTABLE state plus a planning sidecar using the existing PCP/planning validators and digest rules.

The LLM determines meaning; deterministic code owns state vocabulary, cross-record invariants, preservation rules, output shape, and sealing mechanics.

## Supported entrypoint

Use `scripts/session_compile.py` as the supported compiler entrypoint. `scripts/session_compiler.py` is the low-level deterministic library used by that facade.

Bootstrap:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <session-compilation.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

Incremental:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <current-session-delta.json> \
  --prior-planning <prior-planning.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

For digest-bearing remote transport, add `--seal-portable`.

The IR schema is `assets/schemas/session-compilation.schema.json`; start from `assets/templates/session-compilation.json`.

## Inputs

The semantic extraction layer may use:

- current conversation context available to the surface;
- optional prior PCP checkpoint or handoff reference;
- optional prior `pcp-planning/1` snapshot;
- optional current project/repository evidence when the surface has FILE/FULL capability.

The compiler MUST NOT assume inaccessible older turns are available. Incremental compilation is the normal long-running mode after bootstrap.

## Session Compilation IR

The IR contains:

- project identity/name/repository hint;
- producer surface/model/session reference;
- optional prior checkpoint ID/digest;
- active objective and definition of done;
- accepted/superseded decisions;
- reported/inferred findings;
- planning vision and release/epic/story/task graph;
- blockers and blocker dependencies;
- risks;
- explicit uncertainties caused by incomplete context;
- one candidate next frontier.

Unknown fields are rejected. Missing history is represented in `uncertainties`, never invented.

## Extraction pipeline

```text
identify project
-> recover active objective / definition of done
-> extract decisions and constraints
-> extract architecture and accepted design
-> recover releases / epics / stories / tasks
-> classify implementation state
-> recover open loops, blockers, risks
-> build dependency graphs
-> detect supersession/conflict
-> select candidate frontier
-> emit strict IR
-> deterministic validation/merge
-> compile PCP + planning
```

## Required semantic distinctions

Planning items use:

- `proposed`: discussed but not accepted;
- `accepted`: explicitly adopted and still active;
- `ready`: accepted and dependency-ready;
- `in_progress`: current work is underway;
- `blocked`: cannot progress until a dependency/decision is resolved;
- `reported_done`: conversation/prior agent says done but current hard evidence is absent;
- `verified_done`: evidence references exist for a prior/current verified planning status;
- `superseded`: explicitly replaced;
- `cancelled`: explicitly abandoned.

`reported_done` MUST NEVER be serialized as a PCP `completed` claim.

Even an inherited planning `verified_done` does not become a fresh PORTABLE PCP `completed` claim. The Session Compiler emits historical reported findings that force current repository reconciliation before authority.

## Deterministic validation rules

Before output, the supported entrypoint must fail closed on at least:

- invalid project/producer/objective shape;
- duplicate decision/finding/planning/blocker/risk IDs;
- invalid RFC3339 timestamp;
- unknown planning parent/dependency IDs;
- planning dependency cycles;
- `verified_done` without evidence references;
- a candidate frontier that is blocked/superseded/cancelled/reported_done/verified_done;
- a candidate frontier with any dependency not `verified_done`;
- project mismatch against prior planning;
- conflicting explicit prior checkpoint identity;
- secret-like content detected in handoff state;
- blocker dependency references to unknown blocker IDs;
- blocker dependency cycles.

`blockers[].depends_on` is a blocker-to-blocker graph. Planning dependencies belong on planning items. The supported facade validates this distinction before blocker IDs are mapped into PCP `open_work` IDs, preventing silent dependency loss.

## Bootstrap mode

Use when no trustworthy prior planning snapshot exists.

- extract only context currently available;
- mark historical empirical claims reported unless verified now;
- create stable IDs for material long-horizon plan items;
- explicitly record uncertainty caused by unavailable history;
- do not manufacture parent checkpoint lineage;
- make authoritative project reconciliation the first PCP next action.

Bootstrap produces a draft PORTABLE checkpoint by default.

## Incremental mode

Use when a prior `pcp-planning/1` snapshot exists.

```text
prior planning snapshot
+ current session delta
= merged compilation
```

Deterministic merge semantics:

- same-ID current planning items replace the prior version;
- new IDs append;
- prior items omitted from the current session remain preserved;
- current `supersedes` marks omitted predecessor items superseded instead of deleting them;
- decisions follow the same ID/supersession behavior;
- prior decision confidence becomes historical `reported` on import;
- current `planning.vision = null` inherits the prior vision;
- prior source-checkpoint lineage is inherited when the delta does not specify a parent;
- conflicting explicit parent identity is a hard stop;
- project-ID mismatch is a hard stop.

**Silence is not cancellation.** Accepted post-MVP work does not disappear merely because a later conversation stopped mentioning it.

## PCP output rules

The compiler emits a PCP/1 PORTABLE checkpoint with:

- `baseline.git = null` and no invented file evidence when repository truth is unavailable;
- decisions/findings as reported/inferred PCP claims;
- historical `reported_done`/`verified_done` planning items represented as reported findings requiring reconciliation;
- no narrative-derived PCP `completed` claims;
- one critical `W-RECONCILE-001` open-work item;
- any candidate frontier retained as dependent work after reconciliation;
- uncertainties preserved as risks rather than guessed away;
- `verification.surface_status = unverifiable` when authoritative project reality is unavailable.

This means the portable checkpoint tells Codex what to inspect next without pretending the conversation proved code state.

## Planning output rules

The compiler emits the entire relevant long-horizon planning graph into `pcp-planning/1`, including:

- stable IDs;
- parent/dependency edges;
- statuses;
- priority;
- acceptance criteria;
- origins;
- supersession edges;
- evidence references;
- repository references;
- unresolved questions.

The planning snapshot gets its own canonical digest. It is authoritative memory of the accepted plan at handoff time, not evidence that implementation exists.

## Frontier selection

The semantic layer may nominate one next frontier, but deterministic validation accepts it only when:

- its ID exists;
- its status is `accepted`, `ready`, or `in_progress`;
- every declared planning dependency is `verified_done`;
- it has a bounded instruction and non-empty acceptance criteria.

The PORTABLE PCP checkpoint does not execute that frontier immediately. `W-RECONCILE-001` remains the first next action, and the proposed frontier depends on successful reconciliation.

## Remote publication boundary

When output will be referenced by `pcp-handoff/1`:

1. validate the merged Session Compilation IR;
2. compile a valid PCP/1 PORTABLE draft and planning snapshot;
3. ensure no unsupported PCP `completed` claim exists;
4. set the checkpoint to `verification.status: sealed`;
5. keep `verification.surface_status: unverifiable` when project reality is unavailable;
6. compute `verification.content_digest` using the existing PCP/1 canonical digest implementation;
7. bind that digest plus the planning digest into the handoff envelope.

Sealing is integrity/tamper evidence. It MUST NOT be interpreted as evidence that implementation exists, tests pass, or repository state matches the conversation.

A legacy direct file handoff may remain an unsealed PCP draft outside a digest-bearing envelope.

## Compaction invariants

Keep:

- active objective and DoD;
- binding decisions/constraints;
- architecture required for continuation;
- all accepted unfinished long-horizon items;
- inherited verified planning statuses with evidence references;
- reported completion that still requires verification;
- blockers/risks/uncertainties;
- dependency edges needed to order work;
- candidate next frontier.

Drop or summarize:

- duplicate discussion;
- transient brainstorming;
- rejected alternatives whose rejection is no longer operationally relevant;
- verbose rationale already represented by a concise decision;
- private reasoning/scratchpads;
- secrets and unnecessary personal data.

## Acceptance scenarios

A conforming compiler must correctly handle at least:

1. proposal A rejected, B accepted;
2. B1-B10 accepted, B1-B3 evidenced, B4 merely claimed done;
3. later user supersedes an earlier architecture decision;
4. multiple epics with dependency edges;
5. session stops at MVP while accepted post-MVP stories remain;
6. newer repository state implemented work still marked accepted/ready in old planning;
7. contradictory completion claims from parallel agents;
8. unavailable historical context without inventing missing state;
9. sensitive material that must not enter handoff artifacts;
10. PORTABLE remote seal without empirical confidence upgrade;
11. incremental delta omits prior accepted work;
12. same-ID delta updates without duplication;
13. explicit item/decision supersession;
14. project mismatch / conflicting parent;
15. invalid planning dependency cycles;
16. unknown or cyclic blocker dependencies;
17. proposed frontier whose dependency is not verified.

Expected semantics for the partial-completion case: evidenced work may remain `verified_done` in planning with evidence references; unevidenced completion is `reported_done`; accepted later work remains preserved and MUST NOT disappear. The PCP PORTABLE checkpoint itself still requires reconciliation before implementation authority.
