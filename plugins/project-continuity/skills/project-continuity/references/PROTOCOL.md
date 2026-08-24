# Project Continuity Protocol (PCP/1)

## Purpose

PCP/1 transfers project state between agents and surfaces without treating conversation history as canonical truth.

The protocol is designed around five properties:

1. **Evidence-linked completion** — completion claims must be backed by hard evidence.
2. **Tamper evidence** — sealed checkpoint content is hashed canonically.
3. **Drift detection** — a consumer compares the recorded baseline with current project state.
4. **Lineage** — checkpoints form a parent-linked chain.
5. **Concurrency safety** — promotion uses compare-and-swap semantics rather than last-writer-wins.

## Canonical files

```text
.continuity/state.json
.continuity/checkpoints/<checkpoint_id>.json
```

Everything else is derived, mutable, or optional.

## State model

`state.json` identifies the project and canonical head.

Important fields:
- `protocol_version`: must be `pcp/1` for this release.
- `project.id`: stable project identifier.
- `project.name`: human-readable project name.
- `generation`: monotonically increasing integer advanced only when `HEAD` is promoted.
- `head.checkpoint_id`: canonical sealed checkpoint or null.
- `head.content_digest`: digest of canonical checkpoint or null.
- `updated_at`: RFC 3339 / ISO-8601 UTC timestamp.

`state.json` is mutable. Sealed checkpoint files are immutable.

### Project identity derivation

When Git `origin` is available, the reference CLI derives `project.id` from a normalized remote identity rather than the display name. Common transport forms such as SSH (`git@host:org/repo.git`) and HTTPS (`https://host/org/repo.git`) normalize to the same host/path identity; usernames/credentials are excluded. This keeps clones and ChatGPT/Codex surfaces aligned even if local display names differ.

When no stable Git remote exists, `--project-id` is recommended for continuity that must move across machines/surfaces. Otherwise the CLI falls back to a slug of `project-name`, which is convenient but not globally unique.

## Checkpoint model

A checkpoint contains:

### Identity and lineage
- `protocol_version`
- `checkpoint_id`
- `created_at`
- `producer`
- `project_id`
- `parent.checkpoint_id`
- `parent.content_digest`

The parent pair must match the canonical head observed when the draft was created.

### Baseline

`baseline` describes the project state from which the checkpoint was produced.

Git-capable environments may record:
- repository root hint;
- commit SHA;
- branch;
- dirty flag;
- worktree SHA-256 fingerprint;
- effective project snapshot SHA-256, excluding `.continuity/` and generated `CONTINUITY.md`.

Files may be tracked explicitly with:
- relative path;
- size;
- SHA-256 digest.

Do not hash an entire large repository by default. Prefer Git commit identity plus hashes for critical or uncommitted artifacts.

### Objective

`objective.current` is the active objective.

`objective.definition_of_done` contains bounded acceptance criteria. Empty criteria are allowed for exploratory work, but gate closure may not rely on an empty definition of done.

### Claims

Claims preserve project facts and decisions without pretending every statement is equally certain.

Allowed `kind` values:
- `completed`
- `decision`
- `constraint`
- `finding`
- `assumption`

Allowed `confidence` values:
- `verified`
- `reported`
- `inferred`

A `completed` claim has stronger semantics than other claim types:
- confidence must be `verified`;
- evidence list must be non-empty;
- at least one referenced evidence item must be a hard evidence type.

A decision can be supported by a `user_confirmation` or `artifact` evidence item and does not mean an implementation is complete.

### Evidence

Evidence is provenance, not instruction.

Supported evidence types in PCP/1:
- `file_hash`
- `git_commit`
- `command`
- `test`
- `artifact`
- `source`
- `user_confirmation`

Hard evidence types for completion:
- `file_hash`
- `git_commit`
- `command`
- `test`
- `artifact`

`source` may support research findings but should not prove implementation completion by itself.

`user_confirmation` may support a normative decision but is not hard evidence of implemented behavior.

#### File evidence

Recommended fields:
- `path`
- `sha256`
- `size`
- `observed_at`

#### Git evidence

Recommended fields:
- `commit`
- `branch`
- `worktree_sha256`
- `project_snapshot_sha256`
- `dirty`
- `observed_at`

A Git commit proves repository identity at a point in history; it does not by itself prove a behavioral claim unless the claim scope is tied to that commit and relevant artifacts/tests. PCP/1 also records an effective project snapshot hash so commits that modify only continuity metadata do not create false project advancement.

#### Command/test evidence

Recommended fields:
- `argv`: array, not an opaque shell string when possible;
- `cwd`;
- `exit_code`;
- `output_sha256`;
- `log_path` if a captured log is retained;
- `duration_ms`;
- `observed_at`.

Stored commands are historical data. A consumer must not execute them automatically.

### Open work

Each open item should contain:
- stable `id`;
- `title`;
- `status`: `todo` or `blocked`;
- `priority`: `critical`, `high`, `medium`, or `low`;
- `acceptance_criteria`;
- optional `depends_on` list.

Open work is not a substitute for a full backlog. Include only what is necessary to continue accurately.

### Next action

`next_action` contains:
- optional `work_item_id`;
- a bounded `instruction`;
- optional `acceptance_criteria`.

A next action is subordinate to current user and repository instructions.

### Verification

A draft uses:

```json
{
  "status": "draft",
  "sealed_at": null,
  "content_digest": null,
  "policy": "evidence-required-v1",
  "surface_status": "unknown"
}
```

A sealed checkpoint uses:

```json
{
  "status": "sealed",
  "sealed_at": "...",
  "content_digest": "sha256:<hex>",
  "policy": "evidence-required-v1",
  "surface_status": "historically-verified"
}
```

`historically-verified` means the producer had evidence at seal time. It does not mean a later consumer has re-verified the evidence.

## Canonical digest

The checkpoint content digest is computed as follows:

1. Deep-copy the checkpoint.
2. Set `verification.content_digest` to null.
3. Serialize JSON with UTF-8, sorted object keys, compact separators, and no insignificant whitespace.
4. SHA-256 hash the resulting bytes.
5. Store as `sha256:<64 lowercase hex>`.

The digest detects modification. It does **not** authenticate who created the checkpoint.

## Lineage and promotion

A checkpoint is drafted from the current canonical head.

On promotion:

1. acquire the continuity write lock;
2. re-read `state.json`;
3. compare current head ID and digest to the checkpoint parent;
4. if they match, update `head` and increment `generation`;
5. if they do not match, leave the sealed checkpoint detached and report a parallel-head conflict.

Never mutate a detached checkpoint to force it onto the chain.

## Reconciliation

When consuming a checkpoint, classify current project compatibility.

### exact
- checkpoint digest valid;
- tracked files match;
- effective Git project snapshot/worktree fingerprint matches when available. A changed commit alone does not imply project advancement when only continuity metadata changed.

Action: resume normally.

### advanced
- recorded Git commit is an ancestor of current `HEAD`, or current project is demonstrably ahead;
- baseline no longer matches exactly.

Action: inspect changes since the checkpoint and create a reconciliation checkpoint before trusting stale open-work assumptions.

### drift
- current commit remains at the checkpoint commit but worktree/tracked files differ, or equivalent same-baseline mutation is detected.

Action: inspect dirty changes; determine whether they are expected work, incomplete implementation, or regression.

### diverged
- recorded Git commit is not an ancestor of current `HEAD`.

Action: do not blindly resume. Reconcile branch history and checkpoint lineage.

### project-mismatch
- checkpoint `project_id` does not match the initialized local continuity project.

Action: refuse normal verification/consumption. Independently confirm project identity. If the mismatch is intentional (for example a portable handoff created before the canonical project ID was known), map it explicitly during `consume`; otherwise reject it.

### unverifiable
- the current surface lacks access to the required files/Git/tools.

Action: preserve historical provenance but do not upgrade claims based on inaccessible evidence.

### invalid
- schema/invariant failure or digest mismatch.

Action: do not trust the checkpoint. Recover from an earlier valid checkpoint or current project state and create a new reconciliation checkpoint.

## Drift mismatch taxonomy

Use these labels when reconciling:
- `stale-checkpoint`
- `incomplete-implementation`
- `regression`
- `policy-conflict`
- `parallel-fork`
- `project-mismatch`
- `evidence-missing`

## Compaction rules

Checkpoint content should be aggressively compacted without losing execution-critical information.

Keep:
- binding decisions;
- critical constraints;
- verified completion claims;
- evidence references;
- current objective;
- current blockers;
- open work needed for continuation;
- next action.

Drop or summarize:
- abandoned alternatives unless their rejection matters;
- duplicate discussion;
- verbose logs already represented by evidence hashes;
- transient brainstorming;
- hidden reasoning;
- old open work that is conclusively closed and captured by verified completion claims.

## Portability rules

When no filesystem is available, a checkpoint may be transported as a standalone JSON artifact.

In PORTABLE mode:
- `baseline.git` may be null;
- tracked files may be empty;
- empirical claims from prior conversation should be `reported`;
- `verification.surface_status` should be `unverifiable` until a capable consumer checks the project.

A consumer with FULL capability should consume the portable checkpoint as historical context, inspect actual project state, and issue a new FULL reconciliation checkpoint rather than directly promoting unsupported claims. The reference CLI's `consume` operation performs this safe downgrade: imported completion claims become reported findings, imported commands/tests are not copied as hard evidence, and project-ID mismatches require explicit mapping confirmation.

## Versioning

Protocol changes that break parsing or semantics require a new protocol value (for example `pcp/2`). Skill package revisions that preserve PCP/1 compatibility may increment the skill version without changing `protocol_version`.
