# Planning Continuity Contract

**Status:** R3 implementation contract

## Purpose

PCP/1 `open_work` is intentionally compact and is not a complete backlog. Planning Continuity preserves accepted long-horizon work so a project cannot silently stop at MVP while later releases/epics/stories disappear.

The planning snapshot is a sidecar. It carries planning memory, not implementation authority. Repository/tool evidence can change planning status only through an explicit reconciliation transaction.

## Graph model

```text
Vision
  -> Release
    -> Epic
      -> Story
        -> Task
```

Items may additionally declare `depends_on` edges across siblings/levels when needed.

Hierarchy is strict for R3:
- releases have no parent;
- epics have a release parent;
- stories have an epic parent;
- tasks have a story parent;
- unknown parents/dependencies, self-dependencies, parent cycles, and dependency cycles fail closed.

## Stable identity

Every item must have a persistent ID independent of title wording. IDs must not be recycled after supersession/cancellation.

Recommended prefixes:
- `rel-`
- `epic-`
- `story-`
- `task-`
- `decision-`

## Status model

Allowed planning statuses:

- `proposed`
- `accepted`
- `ready`
- `in_progress`
- `blocked`
- `reported_done`
- `verified_done`
- `superseded`
- `cancelled`

Semantics:
- `reported_done` means historical/user/agent assertion without current hard evidence;
- `verified_done` requires at least one bounded evidence reference and later semantic validation that the referenced evidence is sufficient for the claim;
- silence in a later session does not change an accepted unfinished item to cancelled/superseded;
- only an explicit decision or reconciled evidence may close/remove accepted work;
- `ready` and `in_progress` require every declared dependency to remain `verified_done`.

## Minimum item fields

Each executable item contains:
- `id`
- `kind`
- `title`
- `status`
- `parent_id` where applicable
- `priority`
- `depends_on`
- `acceptance_criteria`
- `origin`
- `supersedes`
- `evidence_refs`
- `repository_refs`

Arrays may be empty when no dependency/evidence/repository reference exists. `evidence_refs` MUST be non-empty for `verified_done`.

## Origin/provenance

`origin` identifies the source category without storing transcript dumps. Examples:
- current user decision;
- prior sealed checkpoint;
- imported Session Compiler result;
- repository reconciliation;
- issue/PR/artifact reference.

A changed item emitted by R3 receives `origin.kind: repository_reconciliation`, the reconciliation ID, and the observation timestamp.

## Reconciliation transaction

Use `pcp-planning-reconciliation/1` only from a FILE/FULL-capable surface that has independently inspected current project reality.

The request is bound to one exact snapshot by:
- `project_id`;
- `planning_id`;
- canonical `planning_digest`.

The runtime recomputes the prior planning digest before applying anything. Stale/tampered/mismatched input fails closed.

Supported operations:

| Operation | Purpose |
| --- | --- |
| `verify_complete` | Current hard evidence proves implementation complete. |
| `verify_incomplete` | A historical `reported_done`/`verified_done` claim is not actually complete. |
| `invalidate_verification` | Previously verified work changed/regressed and must be reopened. |
| `start_progress` | Move accepted/ready dependency-satisfied work to `in_progress`. |
| `set_blocked` | Explicitly block accepted/ready/in-progress work. |
| `recheck_dependencies` | Recompute dependency-derived ready/blocked state. |

`verify_complete`, `verify_incomplete`, and `invalidate_verification` require at least one current evidence reference. The reconciler never executes or manufactures the evidence itself.

Run:

```bash
python3 <skill-root>/scripts/planning_reconcile.py \
  --planning <prior-planning.json> \
  --input <planning-reconciliation.json> \
  --planning-out <reconciled-planning.json> \
  --report-out <reconciliation-report.json>
```

Start from `assets/templates/planning-reconciliation.json` when a file template is useful.

## Deterministic transitions

R3 applies completion truth before dependency rechecks so request ordering cannot change results.

Core transitions:
- `accepted|ready|in_progress|blocked` + `verify_complete` -> `verified_done` / `stale-plan`;
- `reported_done|verified_done` + `verify_complete` -> `verified_done` / `verification-refreshed`;
- `reported_done|verified_done` + `verify_incomplete` -> `ready` or `blocked` / `incomplete-implementation`;
- `verified_done` + `invalidate_verification` -> `ready` or `blocked` / `invalidated-verification`;
- `accepted|ready` + dependency-ready `start_progress` -> `in_progress` / `progress-started`;
- explicit blocking -> `blocked` / `blocked`;
- dependency-blocked -> dependency-ready `recheck_dependencies` -> `ready` / `dependency-unblocked`;
- `ready|in_progress` whose dependency loses verification -> `blocked` / `dependency-invalidated` automatically.

A blocked item with no declared dependency cannot be unblocked using `recheck_dependencies`; that prevents dependency logic from erasing an unrelated external blocker.

## Aggregate invalidation

Hierarchy completion propagates upward conservatively.

If a child is reopened while an aggregate parent is still `verified_done`, R3 automatically invalidates the parent and continues upward until the hierarchy is coherent. This prevents a Release/Epic/Story from remaining certified complete while an active descendant is incomplete.

## Frontier selection

After reconciliation, the runtime emits one optional frontier in `pcp-planning-reconciliation-report/1`.

A frontier candidate must:
- be `accepted`, `ready`, or `in_progress`;
- have every dependency `verified_done`;
- be an executable **leaf** with no active unfinished child.

Ranking is deterministic:
1. priority: critical -> high -> medium -> low;
2. status: in_progress -> ready -> accepted;
3. kind: task -> story -> epic -> release;
4. original stable planning order.

This prevents the runtime from choosing a high-level Release/Epic when a concrete unfinished Story/Task exists underneath it.

## Reconciliation report

Each transaction emits `pcp-planning-reconciliation-report/1` containing:
- exact prior planning ID/digest;
- exact result planning ID/digest;
- every explicit or automatically derived status transition;
- classification and provenance refs for each transition;
- the resulting frontier, if one exists.

The result receives a new deterministic planning ID and canonical digest. The prior snapshot is never mutated in place.

## MVP-abandonment invariant

Reconciliation updates statuses; it does not compact away unrelated accepted work.

Therefore:
- accepted post-MVP releases/epics/stories/tasks omitted from the observation set survive byte-for-byte except for globally derived consistency transitions;
- only explicit update/supersession/cancellation or deterministic dependency/aggregate invalidation changes state;
- reaching an MVP is not equivalent to completing the accepted roadmap.

## Compaction

Planning snapshots may compact closed history but must never lose:
- accepted unfinished items;
- dependency edges required to order remaining work;
- binding decisions/constraints affecting future execution;
- supersession records necessary to prevent regressions;
- definition of done / acceptance criteria for remaining work.

## Canonicality

The snapshot is canonical for **remembering the accepted plan at handoff time**, but not canonical evidence that code exists or behavior works. Current repository/tool state remains authoritative for empirical implementation claims. Reconciliation is the deterministic bridge between those two layers.
