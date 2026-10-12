# R6 — Certification & Release Evidence

**Program:** PCP-MOBILE  
**Release:** R6 — Certification & Release  
**Status:** deterministic release-candidate certified; live-device certification pending  
**Certified implementation head:** `be1aab845068f0192cf13ad50180a126bc2394ee`  
**Certification CI run:** `33536761809`

## Certification vocabulary

R6 uses three statuses. They are intentionally not interchangeable.

### CERTIFIED

The behavior is implemented and has executable evidence in the repository/CI at the certified head.

### HARNESS_READY_NOT_MODEL_CERTIFIED

The evaluation contract/scorer exists, but an independent target-model prediction run has not been captured as release evidence. A deterministic gold fixture result is not presented as proof of model extraction quality.

### BLOCKED_EXTERNAL

The implementation/harness is ready, but a required real external environment is unavailable. This state must never be reported as PASS.

## Executive verdict

The deterministic Project Continuity mobile architecture is **CERTIFIED** through the full supported stack:

`PCP/1 -> transport foundation -> Session Compiler -> Planning Continuity -> GitHub handoff -> two-phase Codex resume -> deterministic mobile round trip -> adversarial gates`.

The certification run passed:

- authoritative package manifest comparison;
- all 9 Draft 2020-12 JSON Schemas;
- plugin package validator;
- plugin package tests;
- **154 Project Continuity skill tests**;
- explicit canonical Session Compiler gold eval.

The canonical Session Compiler eval result was:

- fixtures: **16**;
- passed: **16**;
- failed: **0**;
- aggregate PASS: **true**;
- all 10 required quality metrics: **1.0**.

Metrics:

- decision preservation: 1.0;
- supersession accuracy: 1.0;
- plan recall: 1.0;
- open-loop recall: 1.0;
- implementation-state accuracy: 1.0;
- evidence discipline: 1.0;
- dependency preservation: 1.0;
- frontier accuracy: 1.0;
- compression: 1.0;
- sensitive-data leakage gate: 1.0.

The long-session compaction fixture expanded to **91,200 transcript bytes** and compiled to **3,551 output bytes**, a ratio of approximately **3.89%**, while preserving the required semantic state and emitting zero PCP `completed` claims.

## Certified deterministic capabilities

### PCP/1 compatibility — CERTIFIED

- existing canonical PCP/1 checkpoint/state semantics remain in force;
- historical completion requires evidence and is downgrade-first when imported;
- CAS/no-last-writer-wins remains authoritative locally;
- external state never directly becomes canonical local HEAD;
- sealed PORTABLE means integrity, not repository verification;
- a PORTABLE checkpoint may be sealed while `surface_status: unverifiable`.

Evidence: inherited PCP test suite in the R6 certification run.

### Transport foundation — CERTIFIED

- explicit `pcp+file` / `pcp+github` references;
- unknown/implicit transports fail closed;
- references reject credentials, query strings, and fragments;
- root-scoped file transport rejects symlink/path escapes;
- handoff bundle digests/project identity are verified;
- draft checkpoints cannot enter a digest-bearing remote envelope.

Evidence: `test_transport_foundation.py` plus inherited PCP tests.

### Session Compiler deterministic layer — CERTIFIED

- `pcp-session-compilation/1` validates strict semantic IR;
- no narrative `reported_done` is promoted to PCP completion;
- incremental merge preserves omitted accepted work;
- decision/planning supersession is deterministic and cycle-guarded;
- blockers/dependencies are fail-closed;
- PORTABLE output reconciles before exposing a frontier as executable authority.

Evidence:

- `test_session_compiler.py`;
- `test_session_compile_facade.py`;
- `session_eval.py` gold corpus, 16/16 PASS.

### Session Compiler semantic extraction — HARNESS_READY_NOT_MODEL_CERTIFIED

The corpus and evaluator are ready to score externally/model-produced IR predictions:

```bash
python skills/project-continuity/scripts/session_eval.py \
  --predictions <prediction-directory>
```

Each prediction file is scored against the same 16 canonical scenarios and 10 dimensions before deterministic compilation.

This release does **not** claim that the 16/16 gold result proves transcript-to-IR quality of an arbitrary model. Gold mode certifies deterministic semantic preservation after the semantic state is established.

### Planning Continuity — CERTIFIED

- Release -> Epic -> Story -> Task hierarchy validated;
- stale accepted work can close with fresh evidence;
- `reported_done` can reopen as incomplete implementation;
- stale `verified_done` can be invalidated;
- dependency readiness/invalidation is deterministic;
- reopened children invalidate verified aggregate parents;
- accepted post-MVP work survives unrelated reconciliation;
- frontier selection is leaf/dependency aware.

Evidence: `test_planning_reconcile.py`.

### Mobile GitHub handoff semantics — CERTIFIED

- content-addressed checkpoint/planning/envelope layout;
- create-only/idempotent remote objects;
- envelope written last;
- raw envelope digest embedded in compact reference;
- remote bytes re-read and verified;
- public/unknown publication targets fail closed by default;
- no credentials/tokens are persisted in the reference;
- remote storage order never grants project authority.

Evidence:

- `test_github_transport.py`;
- `test_github_transport_visibility.py`;
- R6 round-trip/adversarial tests.

### Two-phase Codex resume — CERTIFIED

`codex_resume.py` enforces:

1. `prepare_from_reference`: resolve, verify, downgrade-first consume, optional planning reconciliation, no execution release;
2. local reconciliation draft promotion through PCP lineage;
3. current repository verification must be `exact`;
4. planning must be reconciled or absent;
5. `finalize_resume` then releases only the reconciled candidate frontier.

An unrelated local checkpoint cannot satisfy the gate. Repository mutation after reconciliation invalidates execution readiness.

Evidence: `test_codex_resume.py` and `test_resume_resolver.py`.

### Deterministic mobile round trip — CERTIFIED

`test_r6_e2e.py` proves the architecture without a producer-side Downloads/terminal dependency:

1. ChatGPT-like producer compiles Session IR in memory;
2. seals PORTABLE checkpoint for integrity while remaining `unverifiable`;
3. publishes checkpoint + planning + envelope through the injected private GitHub host binding;
4. receives compact `pcp+github://...` reference;
5. Codex resolves and verifies it against a real temporary Git repository;
6. planning is reconciled;
7. local consume lineage is promoted and verified `exact`;
8. candidate frontier is released;
9. material repository progress is committed;
10. a new checkpoint and planning snapshot are published;
11. a fresh ChatGPT-like session receives only the new reference plus a tiny delta;
12. omitted accepted post-MVP work survives without transcript replay.

Also certified:

- tampering after publication fails before project authority;
- compact reference contains no auth material.

### Adversarial behavior — CERTIFIED

R6 explicitly closes the remaining matrix gaps:

- prompt-injection-looking historical text remains `reported` data and cannot bypass reconciliation;
- an executable `command` field smuggled into planning IR is rejected by the strict contract;
- a `chain_of_thought` field has no durable schema surface and is rejected;
- two parallel immutable handoffs for the same project coexist independently; remote write order does not elect canonical state.

Inherited tests also cover:

- tampered checkpoint/planning/envelope;
- forged project identity/location;
- missing remote artifacts;
- public publication safety;
- secrets in durable state;
- draft checkpoint in remote envelope;
- sealed+unverifiable trust boundary;
- project mismatch;
- divergent/stale repository state;
- historical commands remaining inert data.

Evidence: `test_r6_adversarial.py` plus inherited suites.

## Live device gate — BLOCKED_EXTERNAL

The normative real-device path is **not yet certified**.

The connected GitHub installation was checked during R6 and no accessible repository named `project-continuity-state` was available. The implementation correctly refuses to fall back to the public `rafaelscosta/plugins` repository or another arbitrary project repository.

A live PASS requires:

- a real private continuity store accessible to the relevant ChatGPT GitHub binding;
- the Codex environment to resolve the same store/reference;
- a phone-facing ChatGPT session to complete the normative flow without Downloads, terminal, desktop, or manual JSON transfer.

Use `LIVE_MOBILE_E2E.md` for the exact certification procedure.

## R6 release decision

The deterministic implementation is a **release candidate** and can proceed through code review/stack integration.

Do not label the overall mobile program "live-device certified" until `LIVE_MOBILE_E2E.md` has a completed evidence record.

Do not label semantic transcript-to-IR extraction "model certified" until a target-model prediction corpus has been run through `session_eval.py --predictions` and its result has been recorded.
