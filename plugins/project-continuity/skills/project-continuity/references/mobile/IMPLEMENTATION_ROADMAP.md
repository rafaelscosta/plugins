# Mobile-First Continuity — Implementation Roadmap

**Status:** R0 execution plan  
**Program ID:** `PCP-MOBILE`

## Definition of Done

The program is complete when a user can, from a phone, hand off a long ChatGPT project session to Codex and later resume it in a fresh ChatGPT conversation without terminal, desktop, manual file movement, transcript dumping, loss of accepted future work, or false promotion of unverified implementation claims.

## Epic E00 — Architecture Ratification (R0)

### S00.1 Ratify compatibility boundary
- Preserve PCP/1 canonical semantics.
- Declare planning snapshot and envelope as sidecars.
- Downgrade `~/Downloads` from protocol assumption to file transport convention.
- Record explicit PCP/2 trigger criteria.

Acceptance:
- architecture, transport, compiler, planning, envelope contracts exist;
- no runtime behavior changed;
- current PCP/1 schema remains untouched.

### S00.2 Define machine contracts
- Add handoff-envelope JSON Schema.
- Add planning-snapshot JSON Schema.

Acceptance:
- Draft 2020-12 valid schemas;
- unknown fields rejected in v1;
- digest/project identity fields constrained.

### S00.3 Define certification matrix
- Add E2E, adversarial, compatibility, privacy, and compiler-state scenarios.
- Define measurable compiler quality dimensions.

Acceptance:
- each future release maps to explicit gates;
- mobile E2E acceptance scenario is normative.

## Epic E01 — Transport Foundation (R1)

### S01.1 Transport registry and reference parser
Implement transport-neutral interfaces/registry and typed references.

Acceptance:
- unsupported scheme fails closed;
- parser never guesses transport;
- references contain no secrets.

### S01.2 File adapter compatibility
Wrap current handoff-in/out behavior as file transport without breaking aliases.

Acceptance:
- existing PCP/1 tests remain green;
- default Downloads path still works;
- direct `--checkpoint` continues to work.

### S01.3 Envelope validation and digest verification

Acceptance:
- invalid schema rejected;
- checkpoint/planning digest mismatch rejected;
- transport cannot promote or upgrade claims.

## Epic E02 — Session Compiler (R2)

### S02.1 Compiler semantic model
Implement/encode proposed, accepted, superseded, ready, in-progress, blocked, reported-done, verified-done distinctions.

### S02.2 Bootstrap compilation
Create first portable continuity bundle from available conversation context.

### S02.3 Incremental compilation
Merge new session delta with prior continuity without dropping accepted unresolved work.

### S02.4 Frontier selection
Select one bounded highest-value executable frontier from accepted dependency-ready work.

Acceptance for E02:
- no reported completion becomes PCP completed;
- superseded decisions resolve deterministically;
- unmentioned accepted post-MVP work survives incremental compaction;
- unavailable history is represented as uncertainty, never invented.

## Epic E03 — Planning Continuity (R3)

### S03.1 Planning graph runtime
Support releases, epics, stories, tasks, parent/depends_on/supersedes edges.

### S03.2 Planning digest and validation
Canonicalize and hash planning snapshots.

### S03.3 Reconciliation transitions
Support stale-plan, incomplete-implementation, invalidated-verification, dependency-unblocked transitions.

Acceptance:
- stable IDs survive title edits;
- reported_done and verified_done remain distinct;
- accepted unfinished work cannot disappear by omission.

## Epic E04 — Mobile GitHub Handoff (R4)

### S04.1 GitHub transport publish
Publish immutable/versioned handoff artifacts to configured continuity repository.

### S04.2 GitHub transport resolve
Fetch envelope/checkpoint/planning and verify bytes/digests.

### S04.3 Publication safety
Detect public target and fail closed unless explicit current-user approval permits publication.

### S04.4 Mobile ChatGPT intent
`Handoff to Codex` performs compile -> validate -> publish -> verify -> return compact reference without local file handling.

Acceptance:
- iPhone flow requires no terminal/desktop/download;
- remote bytes are re-fetched/verified when possible;
- permission/not-found/integrity errors are typed and recoverable.

## Epic E05 — Codex Resolver & Reconciliation (R5)

### S05.1 Reference resolver
Resolve file/github references into validated handoff bundles.

### S05.2 PCP downgrade-first consume
Reuse existing consume semantics for imported checkpoint claims/evidence.

### S05.3 Repository reconciliation
Compare checkpoint + plan against current repository and classify exact/advanced/drift/diverged/project-mismatch plus planning mismatches.

### S05.4 Resume brief and execution frontier
Emit verified objective, surviving decisions, invalidated claims, blockers, and next action before material execution.

Acceptance:
- no external handoff directly promotes canonical HEAD;
- stale `accepted`/`ready` items already implemented are not blindly repeated;
- `reported_done` absent from repo reopens as incomplete implementation.

## Epic E06 — Certification & Release (R6)

### S06.1 Regression suite
All pre-mobile PCP/1 behavior remains green.

### S06.2 Session compiler eval suite
Measure decision preservation, plan recall, open-loop recall, supersession accuracy, implementation-state accuracy, evidence discipline, dependency preservation, frontier accuracy, compression, and sensitive-data leakage.

### S06.3 Mobile E2E certification
Run normative ChatGPT-mobile -> GitHub -> Codex -> repository -> new checkpoint -> fresh ChatGPT flow.

### S06.4 Adversarial certification
Cover tampering, project mismatch, public publication, injected commands, missing remote artifacts, parallel handoffs, stale verification, and divergent branches.

## Execution order

`E00 -> E01 -> E02 -> E03 -> E04 -> E05 -> E06`

Parallelism is permitted only within an epic when dependencies are explicit. Do not begin E04 by directly coupling ChatGPT to GitHub before E01 transport/envelope contracts and E02/E03 compiler outputs are stable.
