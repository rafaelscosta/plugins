# Handoff Envelope Contract

**Status:** R0 ratification candidate  
**Format:** `pcp-handoff/1`

## Purpose

The handoff envelope binds a PCP checkpoint and optional planning snapshot to transport metadata and expected digests. It is deliberately small and transport-oriented.

The envelope is not canonical project state and MUST NOT be used to elevate claim confidence or bypass PCP consumption/reconciliation.

## Required fields

```json
{
  "format": "pcp-handoff/1",
  "handoff_id": "handoff-...",
  "created_at": "...",
  "project": {
    "id": "...",
    "repository": "github:owner/repo"
  },
  "checkpoint": {
    "protocol": "pcp/1",
    "id": "pcp-...",
    "digest": "sha256:...",
    "location": "..."
  },
  "planning_snapshot": {
    "id": "planning-...",
    "digest": "sha256:...",
    "location": "..."
  },
  "transport": {
    "kind": "github"
  }
}
```

`planning_snapshot` MAY be null when the handoff has no long-horizon planning sidecar.

## Checkpoint sealing rule

Any checkpoint referenced by a digest-bearing `pcp-handoff/1` envelope MUST be a **sealed PCP/1 checkpoint** whose `verification.content_digest` equals `checkpoint.digest`.

For a PORTABLE ChatGPT producer, sealing is an integrity operation only:

- empirical claims without current hard evidence remain `reported` or `inferred`;
- `verification.surface_status` remains `unverifiable` when the surface cannot verify project reality;
- sealing MUST NOT create a PCP `completed` claim or otherwise upgrade confidence;
- the receiving FULL consumer still uses downgrade-first consumption and repository reconciliation.

The legacy direct file flow MAY continue to transfer a PCP draft outside a handoff envelope. That backward-compatible draft flow has no envelope digest and remains explicitly unsealed/reported until consumed.

## Integrity rules

1. Checkpoint digest MUST equal the canonical PCP digest recorded by the sealed checkpoint.
2. Planning snapshot digest MUST be SHA-256 of canonical JSON bytes using sorted keys and compact separators, with its own `content_digest` set to null during hashing if that field is present.
3. Envelope location fields are locators only; fetched bytes must be verified against the recorded digest.
4. Envelope mutation is detectable only if the envelope itself is transported through a mechanism with its own immutable identity/content hash. PCP/1 checkpoint integrity does not authenticate the envelope.
5. A draft checkpoint with `verification.content_digest = null` MUST NOT be published through a digest-bearing `pcp-handoff/1` envelope.

## Project identity

`project.id` must use the same identity as the target PCP project where known. `project.repository` is an optional normalized human/debug hint and MUST NOT override a mismatching project ID.

A portable ChatGPT handoff created before canonical project identity is known may use a provisional project ID only if the receiving consumer requires explicit project mapping before reconciliation.

## Location rules

- Location values are opaque strings interpreted by the selected transport.
- A consumer MUST NOT infer a different transport from the location when `transport.kind` is present.
- Unknown fields are rejected in v1 schemas to avoid silent semantic drift.

## Security

Envelope fields MUST NOT contain credentials, access tokens, cookies, signed URLs with embedded secrets, private reasoning, or unnecessary personal data.
