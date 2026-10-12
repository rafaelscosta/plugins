# Planning Continuity Contract

**Status:** R0 ratification candidate

## Purpose

PCP/1 `open_work` is intentionally compact and is not a complete backlog. Planning Continuity preserves accepted long-horizon work so a project cannot silently stop at MVP while later releases/epics/stories disappear.

The planning snapshot is a sidecar. It carries planning memory, not implementation authority.

## Graph model

```text
Vision
  -> Release
    -> Epic
      -> Story
        -> Task
```

Items may additionally declare `depends_on` edges across siblings/levels when needed.

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
- only an explicit decision or reconciled evidence may close/remove accepted work.

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
- imported session compiler result;
- repository reconciliation;
- issue/PR/artifact reference.

## Reconciliation rules

Planning state must be reconciled against current repository state before execution when a capable consumer exists.

Examples:
- plan says `accepted` or `ready`, repository proves implementation exists -> classify stale planning state and re-verify before `verified_done`;
- plan says `reported_done`, implementation absent -> classify incomplete implementation and reopen work;
- plan says `verified_done`, relevant implementation changed -> invalidate stale verification and re-test/reconcile;
- dependency completed by later work -> unblock dependents;
- accepted post-MVP stories remain preserved even if the previous session stopped at the MVP milestone.

## Compaction

Planning snapshots may compact closed history but must never lose:
- accepted unfinished items;
- dependency edges required to order remaining work;
- binding decisions/constraints affecting future execution;
- supersession records necessary to prevent regressions;
- definition of done / acceptance criteria for remaining work.

## Canonicality

The snapshot is canonical for **remembering the accepted plan at handoff time**, but not canonical evidence that code exists or behavior works. Current repository/tool state remains authoritative for empirical implementation claims.
