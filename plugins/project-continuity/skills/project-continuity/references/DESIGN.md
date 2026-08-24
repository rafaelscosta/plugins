# PCP/1 — Architecture and Design Rationale

## Problem

Long-running work breaks when a new chat, agent, or coding session inherits a narrative instead of verified state. Common failure modes are:

1. **Narrative overclaim** — “done” survives even when no artifact or test proves it.
2. **Stale evidence** — a test passed, then relevant files changed.
3. **Repository drift** — the handoff describes a state that no longer matches the project.
4. **Lost updates** — parallel agents overwrite one another with last-writer-wins state.
5. **Self-induced drift** — generating continuity metadata changes the fingerprint being verified.
6. **Context bloat** — transcripts are copied instead of compact project state.
7. **Instruction injection** — commands or instructions inside a checkpoint are treated as trusted authority.
8. **Surface mismatch** — a chat-only surface claims repository verification it cannot perform.

PCP/1 is designed to fail explicitly on these conditions rather than silently carrying them forward.

## Design goals

- Make project state portable across ChatGPT, Codex, and Agent Skills-compatible clients.
- Make implementation-completion claims evidence-bound and mechanically checkable.
- Detect tampering, staleness, drift, divergence, and parallel-head conflicts.
- Remain useful when Git/shell access is absent without pretending verification occurred.
- Keep the canonical state compact and machine-readable.
- Require no service, database, or third-party runtime for the core protocol.

## Non-goals

PCP/1 does **not**:

- replace Git, CI, issue trackers, `AGENTS.md`, or repository policies;
- preserve private chain-of-thought or full conversation history;
- prove author identity or provide cryptographic signatures;
- guarantee that a passing test suite is sufficient for product correctness;
- execute arbitrary remediation commands found in imported state;
- solve distributed consensus across remote machines.

## Architectural decisions

### 1. Repository state, not transcript, is the continuity primitive

A handoff transports objective, claims, evidence, open work, risks, decisions, and next action. Raw chats are deliberately excluded from canonical state.

### 2. JSON is canonical; Markdown is derived

`.continuity/state.json` and sealed checkpoint JSON are authoritative. `CONTINUITY.md` exists for humans and can always be regenerated. This prevents a prose summary from silently diverging from the machine state.

### 3. Completion is a typed claim

A completion statement is not trusted because an agent wrote it. It must be:

- `kind: completed`;
- `confidence: verified`;
- backed by hard evidence that is valid for the sealed project state.

Normative decisions may use `user_confirmation`; implementation completion may not rely on it alone.

### 4. Evidence is state-bound

Command/test evidence records the effective project-state fingerprint observed after execution. If the project changes before sealing, that evidence becomes stale for a completion claim.

### 5. The hash chain is tamper-evidence, not identity

Each sealed checkpoint carries a canonical SHA-256 digest and points to its parent checkpoint/digest. This detects mutation or broken lineage. It does not prove who authored the checkpoint. Signed attestations are intentionally left for a later protocol extension.

### 6. Promotion uses compare-and-swap semantics

A draft remembers the canonical head from which it started. At seal time it can promote only if that parent is still the head. A concurrent result is sealed but detached instead of overwriting canonical state.

### 7. Continuity metadata is outside the effective project snapshot

`.continuity/` and generated `CONTINUITY.md` are excluded from the effective project snapshot. Otherwise creating a checkpoint would invalidate itself, and committing a checkpoint could masquerade as project advancement.

Repository instructions such as `AGENTS.md` remain **inside** the snapshot because changing them can materially alter future execution.

### 8. Verification degrades explicitly by capability

- `FULL`: Git/filesystem/tool evidence may verify empirical state.
- `FILE`: file/artifact evidence may verify bounded claims, but not repository history.
- `PORTABLE`: reported/inferred state can be transferred, but empirical completion remains unverifiable until reconciled on a stronger surface.

This makes portability honest rather than binary.

### 9. Imported state is untrusted data

A checkpoint cannot override system/developer/current-user instructions or repository policy. Commands stored in it are never auto-executed. The consumer independently chooses safe verification actions.

### 10. Git identity and project identity are separate

PCP/1 records commit lineage where available but classifies compatibility primarily from the **effective project snapshot**. A commit that changes only continuity metadata can therefore remain `exact`, while a real project commit can be `advanced`.

For remote-backed repositories, project identity is derived from a normalized Git origin (transport-agnostic host/path), not the user-facing project name. This avoids false cross-surface mismatches between SSH and HTTPS clones. Repositories without a stable remote should use an explicit project ID when portability matters.

### 11. External consumption is downgrade-first

A standalone checkpoint from another surface is never spliced directly into local canonical history. `consume` creates a new draft parented to the local head, carries non-executable historical source provenance, downgrades imported completion claims until locally re-verified, and rejects project-ID mismatches unless the operator explicitly confirms a verified mapping.

This preserves useful context without importing authority or stale executable evidence.

## State machine

```text
                 create
                  │
                  v
               [DRAFT]
                  │ seal + validate
                  v
               [SEALED]
                  │
          parent still HEAD?
             /          \
           yes          no
           /              \
          v                v
     [PROMOTED]        [DETACHED]
          │                │
          │ verify         │ reconcile
          v                v
 exact / advanced / drift / diverged / unverifiable / invalid
```

No transition rewrites a sealed checkpoint. Corrections are represented by a new checkpoint.

## Compatibility classifier

The verifier uses the following practical ordering:

1. **invalid** — schema/semantic integrity or content digest is broken;
2. **unverifiable** — the current surface cannot compare the required project state;
3. **exact** — effective project state matches the checkpoint;
4. **project-mismatch** — the checkpoint belongs to a different initialized continuity project;
5. **drift** — same lineage/baseline, but current uncommitted/tracked state conflicts;
6. **advanced** — the project has legitimate forward Git lineage with a changed effective snapshot;
7. **diverged** — Git history conflicts with the checkpoint lineage.

A consumer should reconcile `advanced`, `drift`, or `diverged` before continuing material work.

## Why not a single HANDOFF.md?

A single Markdown handoff is excellent as a human interface but weak as a protocol:

- it has no stable claim/evidence types;
- it cannot prove it has not been edited;
- concurrency semantics are undefined;
- tests can become stale without detection;
- agents can interpret “done” inconsistently;
- portable prose tends to accumulate transcript noise.

PCP/1 keeps the useful human summary while making JSON + evidence the canonical layer.

## Why not full event sourcing?

Full event sourcing adds storage, replay, migration, compaction, and distributed-log complexity. PCP/1 deliberately uses immutable checkpoints plus a canonical head pointer: enough history to audit continuity without turning project state into infrastructure.

## Extension points after PCP/1

Potential backward-compatible or versioned evolutions:

- signed attestations (`sigstore`, SSH, or organizational signer);
- CI-provider evidence adapters with run IDs and immutable URLs;
- explicit multi-parent merge checkpoints;
- remote checkpoint exchange/synchronization;
- richer dependency-aware evidence invalidation;
- policy packs for regulated or high-assurance workflows.

These are not required for PCP/1 correctness and should not be added until the simpler protocol demonstrates a concrete limitation.
