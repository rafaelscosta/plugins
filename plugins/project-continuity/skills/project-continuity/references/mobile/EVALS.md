# Mobile-First Continuity — Evaluation & Certification Matrix

**Status:** R0 ratification candidate

## 1. Required quality dimensions

Session Compiler evaluation MUST measure more than schema validity.

- **Decision Preservation:** accepted binding decisions retained.
- **Supersession Accuracy:** superseded/rejected decisions do not remain active.
- **Plan Recall:** accepted releases/epics/stories/tasks retained.
- **Open-Loop Recall:** unresolved accepted work retained across compaction.
- **Implementation-State Accuracy:** proposed/planned/reported/verified states classified correctly.
- **Evidence Discipline:** no completion without current hard evidence.
- **Dependency Preservation:** required ordering edges retained.
- **Frontier Accuracy:** selected next action is accepted, unblocked, bounded, and dependency-valid.
- **Compression:** redundant transcript content excluded.
- **Sensitive-Data Leakage:** secrets/private reasoning/unnecessary personal data excluded.

## 2. Canonical compiler fixtures

Create fixtures for:

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

Each fixture needs an input transcript/state, expected semantic facts, forbidden promotions, and expected next-frontier constraints.

## 3. Transport tests

- file handoff legacy path still works;
- explicit file path works;
- unknown transport rejected;
- malformed reference rejected;
- missing remote artifact typed as `remote-not-found`;
- permission failure typed as `permission-denied`;
- checkpoint digest mismatch rejected;
- planning digest mismatch rejected;
- transport metadata cannot override project ID;
- same immutable bundle publication is idempotent or safely duplicated;
- different bytes cannot overwrite immutable handoff identity silently.

## 4. GitHub/mobile tests

- private continuity repository publish succeeds;
- published bytes re-fetch to expected digests;
- public target publication fails closed by default;
- explicit approval path is separately tested;
- ChatGPT mobile flow does not require a filesystem path;
- returned handoff reference contains no credentials/token-bearing URL;
- Codex can resolve the reference without user copying the entire JSON payload.

## 5. PCP compatibility tests

All existing PCP/1 tests remain mandatory. Additional compatibility assertions:

- current checkpoint schema unchanged in R0/R1;
- existing `handoff-in` and `handoff-out` semantics preserved;
- `consume` remains downgrade-first;
- external completed claims remain historical reported findings until local re-verification;
- project mismatch remains a hard stop absent explicit verified mapping;
- CAS/no-last-writer-wins behavior unchanged;
- sealed checkpoint immutability unchanged.

## 6. Reconciliation tests

| Prior state | Current reality | Expected |
|---|---|---|
| todo | implementation verified present | stale planning -> verify/close |
| reported_done | implementation absent | incomplete-implementation |
| verified_done | relevant implementation changed | invalidate stale verification |
| blocked | dependency verified complete | dependency-unblocked |
| checkpoint exact | planning exact | resume |
| checkpoint advanced | repo ahead | reconcile |
| checkpoint same commit + dirty conflict | worktree differs | drift |
| checkpoint non-ancestor | divergent branch | diverged |
| project ID mismatch | unrelated/uncertain repo | hard stop |

## 7. Adversarial tests

- prompt-injection text embedded in a checkpoint;
- command embedded in planning item;
- fake `verified_done` with no evidence;
- tampered checkpoint after envelope publication;
- tampered planning snapshot;
- forged location pointing to different project;
- malicious/sensitive value placed in reference field;
- parallel handoffs from same canonical parent;
- stale remote handoff consumed after repository advanced;
- session compiler asked to preserve hidden/private chain-of-thought;
- transcript contains access token or credential-like material.

Expected: fail closed or redact/downgrade without executing untrusted instructions.

## 8. Normative mobile E2E gate

PASS only if all steps can be completed from a phone-facing ChatGPT/Codex workflow:

1. user opens a long ChatGPT project session;
2. says `Handoff to Codex`;
3. no download, terminal, desktop, or manual file move is required;
4. ChatGPT returns a compact handoff reference;
5. user supplies reference to Codex;
6. Codex validates envelope and artifact digests;
7. Codex validates/maps project identity;
8. Codex inspects current repository;
9. Codex reconciles completion claims and planning graph;
10. unexecuted accepted post-MVP work remains visible;
11. Codex selects and can execute the next valid frontier;
12. after material progress, a new checkpoint can be published;
13. a fresh ChatGPT conversation can consume the updated project continuity without transcript replay.

Any required desktop-only step is a FAIL for the mobile-first gate.
