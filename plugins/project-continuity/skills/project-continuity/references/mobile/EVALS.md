# Mobile-First Continuity — Evaluation & Certification Matrix

**Status:** R6 evidence matrix  
**Deterministic certification:** PASS at `be1aab845068f0192cf13ad50180a126bc2394ee` / CI run `33536761809`  
**Live phone E2E:** NOT CERTIFIED — external private store unavailable during R6  
**Model transcript→IR extraction:** HARNESS READY — independent prediction run not yet certified

Authoritative evidence/status details:
- `R6_CERTIFICATION.md`
- `LIVE_MOBILE_E2E.md`
- canonical corpus: `assets/evals/session-compiler-fixtures.json`
- evaluator: `scripts/session_eval.py`

## 1. Required quality dimensions

Session Compiler evaluation MUST measure more than schema validity.

- **Decision Preservation:** accepted binding decisions retained.
- **Supersession Accuracy:** superseded/rejected decisions do not remain active.
- **Plan Recall:** accepted releases/epics/stories/tasks retained.
- **Open-Loop Recall:** unresolved accepted work retained across compaction.
- **Implementation-State Accuracy:** `proposed` / `accepted` / `ready` / `in_progress` / `blocked` / `reported_done` / `verified_done` states classified correctly.
- **Evidence Discipline:** no completion without current hard evidence.
- **Dependency Preservation:** required ordering edges retained.
- **Frontier Accuracy:** selected next action is accepted, unblocked, bounded, and dependency-valid.
- **Compression:** redundant transcript content excluded.
- **Sensitive-Data Leakage:** secrets/private reasoning/unnecessary personal data excluded.

R6 gold-eval result: all ten dimensions scored `1.0` across the canonical 16-fixture corpus. This certifies deterministic preservation from established semantic IR through PCP/planning compilation; it does not substitute for an independent transcript→IR target-model prediction run.

## 2. Canonical compiler fixtures

The canonical corpus contains:

1. `simple-handoff`
2. `superseded-decisions`
3. `long-roadmap`
4. `partial-implementation`
5. `false-done-claim`
6. `multiple-epics`
7. `parallel-agent-work`
8. `conflicting-decisions`
9. `ambiguous-project`
10. `sensitive-content`
11. `long-session-compaction`
12. `multi-session-incremental`
13. `mvp-with-post-mvp-work`
14. `repository-ahead-of-plan`
15. `plan-ahead-of-repository`
16. `portable-seal-without-verification`

Each fixture defines transcript/input context, expected semantic facts, forbidden promotions, and expected next-frontier constraints.

R6 gold gate: **16/16 PASS, failed=0**.

The long-session compaction fixture expands to 91,200 transcript bytes and emits 3,551 compiled output bytes (~3.89%) while retaining the required semantic state.

## 3. Transport tests

Certified in R6/inherited suites:

- file handoff legacy path still works;
- explicit file path works;
- unknown transport rejected;
- malformed reference rejected;
- missing remote artifact typed as `remote-not-found`;
- permission/transport failures remain transport failures rather than project state;
- checkpoint digest mismatch rejected;
- planning digest mismatch rejected;
- digest-bearing envelope rejects an unsealed/draft checkpoint;
- a sealed PORTABLE checkpoint with `surface_status: unverifiable` is accepted for integrity without upgrading empirical claims;
- transport metadata cannot override project ID;
- same immutable bundle publication is idempotent;
- different bytes cannot overwrite immutable handoff identity silently.

## 4. GitHub/mobile tests

Deterministically certified:

- private continuity repository publish succeeds through the injected host-binding contract;
- published bytes re-fetch to expected digests;
- public target publication fails closed by default;
- explicit approval path is separately tested;
- ChatGPT-like mobile producer path requires no producer filesystem handoff;
- PORTABLE checkpoint is sealed before remote envelope publication;
- portable sealing leaves unsupported empirical claims reported/inferred and `surface_status: unverifiable`;
- returned handoff reference contains no credentials/token-bearing URL;
- Codex can resolve the reference without copying the entire JSON payload;
- deterministic ChatGPT→GitHub→Codex→new checkpoint→fresh ChatGPT round trip preserves omitted post-MVP work without transcript replay.

Real device/network/account integration remains governed by section 8 and `LIVE_MOBILE_E2E.md`.

## 5. PCP compatibility tests

All existing PCP/1 tests remain mandatory. Certified compatibility assertions include:

- canonical checkpoint semantics remain compatible;
- existing `handoff-in` and `handoff-out` semantics preserved;
- legacy direct file flow may still consume an unsealed draft;
- remote digest-bearing envelope requires a sealed checkpoint;
- `consume` remains downgrade-first;
- external completed claims remain historical reported findings until local re-verification;
- sealing a PORTABLE checkpoint does not imply repository verification;
- project mismatch remains a hard stop absent explicit verified mapping;
- CAS/no-last-writer-wins behavior unchanged;
- sealed checkpoint immutability unchanged.

## 6. Reconciliation tests

| Prior state | Current reality | Expected |
|---|---|---|
| accepted/ready | implementation verified present | stale planning -> verify/close |
| reported_done | implementation absent | incomplete-implementation |
| verified_done | relevant implementation changed | invalidate stale verification |
| blocked | dependency verified complete | dependency-unblocked |
| checkpoint exact | planning exact | resume |
| checkpoint advanced | repo ahead | reconcile |
| checkpoint same commit + dirty conflict | worktree differs | drift |
| checkpoint non-ancestor | divergent branch | diverged |
| project ID mismatch | unrelated/uncertain repo | hard stop |

These transitions are covered by `test_planning_reconcile.py`, `test_resume_resolver.py`, and `test_codex_resume.py`.

## 7. Adversarial tests

Certified behavior includes:

- prompt-injection-looking historical text remains reported data and cannot bypass reconciliation;
- executable `command` field embedded in planning IR is rejected by the strict contract;
- fake `verified_done` with no evidence is rejected;
- tampered checkpoint after envelope publication is rejected;
- tampered planning snapshot is rejected;
- forged location/project identity is rejected;
- malicious/sensitive values in references/durable state fail closed;
- parallel immutable handoffs coexist without remote last-writer-wins authority;
- stale remote handoff/repository drift blocks execution readiness;
- hidden/private `chain_of_thought` has no durable IR field and is rejected;
- credential-like material cannot pass the durable-state/eval gates;
- draft checkpoint with `content_digest: null` cannot enter a remote digest envelope;
- `sealed + unverifiable` cannot be treated as verified implementation.

Expected and observed R6 behavior: fail closed, redact, or downgrade without executing untrusted instructions.

## 8. Normative mobile E2E gate

**Current status: NOT CERTIFIED / BLOCKED_EXTERNAL.**

PASS only if all steps can be completed from a phone-facing ChatGPT/Codex workflow:

1. user opens a long ChatGPT project session;
2. says `Handoff to Codex`;
3. Session Compiler produces PORTABLE state;
4. PORTABLE checkpoint is sealed for tamper evidence without upgrading unsupported empirical claims;
5. no download, terminal, desktop, or manual file move is required;
6. ChatGPT returns a compact handoff reference;
7. user supplies reference to Codex;
8. Codex validates envelope and artifact digests;
9. Codex validates/maps project identity;
10. Codex inspects current repository;
11. Codex reconciles completion claims and planning graph;
12. unexecuted accepted post-MVP work remains visible;
13. Codex selects and can execute the next valid frontier;
14. after material progress, a new checkpoint can be published;
15. a fresh ChatGPT conversation can consume the updated project continuity without transcript replay.

Any required desktop-only continuity-transfer step is a FAIL for the mobile-first gate.

During R6, no accessible private repository named `project-continuity-state` was available through the connected GitHub installation. The implementation correctly did not fall back to the public plugin repository. Execute `LIVE_MOBILE_E2E.md` when a safe private store and both host bindings are available.
