# Session Compiler Contract

**Status:** R0 ratification candidate

## Purpose

The Session Compiler converts available ChatGPT/Codex conversation context into compact, execution-critical project state without treating the transcript as canonical truth.

## Inputs

- current conversation context available to the surface;
- optional prior PCP checkpoint or handoff reference;
- optional planning snapshot;
- optional current project/repository evidence when the surface has FILE/FULL capability.

The compiler MUST NOT assume inaccessible older turns are available. Incremental compilation is the normal long-running mode.

## Output classes

The compiler emits:

1. a PCP/1-compatible portable/reconciliation checkpoint candidate;
2. an optional planning snapshot when long-horizon work exists;
3. provenance links between extracted items and their source category;
4. one bounded next frontier plus acceptance criteria.

Before a checkpoint is referenced by a digest-bearing remote handoff envelope, the producer seals that PORTABLE checkpoint according to PCP/1 canonical-digest rules. This seal is tamper evidence, not repository verification.

## Extraction pipeline

```text
identify project
-> recover active objective / definition of done
-> extract decisions and constraints
-> extract architecture and accepted design
-> recover releases / epics / stories / tasks
-> classify implementation state
-> recover open loops, blockers, risks
-> build dependency graph
-> detect supersession/conflict
-> select next executable frontier
-> compact
-> validate
```

## Required semantic distinctions

The compiler MUST distinguish:

- `proposed`: discussed but not accepted;
- `accepted`: explicitly adopted/ratified plan or decision;
- `superseded`: previously relevant but replaced;
- `ready`: accepted and unblocked;
- `in_progress`: evidence/report indicates active execution;
- `blocked`: cannot progress without dependency/decision;
- `reported_done`: conversation or prior agent says it is done, but current hard evidence is absent;
- `verified_done`: current hard evidence satisfies the bounded completion claim.

`reported_done` MUST NEVER be serialized as a PCP `completed` claim. PCP `completed` remains reserved for `verified` claims with hard evidence.

## Remote publication boundary

When the output will be referenced by `pcp-handoff/1`:

1. validate the PORTABLE checkpoint as a PCP/1 draft candidate;
2. ensure empirical statements that cannot be checked now remain `reported`/`inferred`;
3. ensure there are no unsupported PCP `completed` claims;
4. set `verification.status` to `sealed`;
5. set `verification.surface_status` to `unverifiable` when project reality is unavailable;
6. compute `verification.content_digest` with the normal PCP/1 canonical digest procedure;
7. include that exact digest in the handoff envelope.

Sealing MUST NOT be interpreted as evidence that implementation exists, tests pass, or the repository matches the conversation. A FULL consumer still performs downgrade-first import and reconciliation.

A legacy direct file handoff may remain an unsealed PCP draft outside the envelope for backward compatibility.

## Decision precedence

When multiple statements conflict, apply:

1. current system/developer/current-user instructions;
2. current repository/project instructions;
3. directly observed current project/tool state;
4. canonical sealed checkpoint;
5. later explicit user-ratified decision;
6. older accepted decision;
7. proposals/brainstorming.

Superseded alternatives should be compacted unless retaining the rejection prevents future regression.

## Bootstrap mode

Use when no trustworthy prior continuity state exists.

- extract only context currently available;
- mark historical empirical claims as reported unless verified now;
- create stable IDs for long-horizon plan items;
- explicitly record uncertainty caused by unavailable history;
- make repository reconciliation the first next action where relevant.

## Incremental mode

Use when a prior checkpoint/planning snapshot exists.

```text
prior canonical continuity
+ new conversation delta
+ current evidence available
= new continuity candidate
```

Incremental mode MUST preserve accepted unresolved work not mentioned in the newest conversation. Silence is not cancellation.

## Compaction invariants

Keep:
- active objective and DoD;
- binding decisions/constraints;
- architecture required for continuation;
- all accepted unfinished long-horizon items;
- verified completion claims and evidence refs;
- reported completion that still requires verification;
- blockers/risks;
- dependency edges needed to order work;
- next executable frontier.

Drop or summarize:
- duplicate discussion;
- transient brainstorming;
- rejected alternatives whose rejection is no longer operationally relevant;
- verbose rationale already represented by a concise decision;
- private reasoning/scratchpads;
- secrets and unnecessary personal data.

## Frontier selection

The compiler may recommend a next frontier only from accepted work whose dependencies are satisfied or whose immediate task is dependency resolution. Prefer the highest-value unblocked item using current project priorities. The recommendation remains subordinate to the current user/repository instructions.

## Acceptance tests

A conforming compiler must correctly handle at least:

1. proposal A rejected, B accepted;
2. B1-B10 accepted in the roadmap, B1-B3 executed, B4 claimed done without evidence;
3. later user supersedes an earlier architecture decision;
4. multiple epics with dependency edges;
5. a session ending at MVP while post-MVP accepted stories remain;
6. a newer repository state implementing work marked `accepted`/`ready` in the old plan;
7. contradictory completion claims from parallel agents;
8. unavailable historical context without inventing missing state;
9. sensitive material that must not be copied into handoff artifacts;
10. remote publication of a PORTABLE checkpoint that becomes sealed/tamper-evident without upgrading any unverified empirical claim.

Expected semantics for case 2: B1-B3 may be `verified_done` only with current hard evidence; B4 is `reported_done`; B5-B10 remain accepted unfinished work and MUST NOT disappear.
