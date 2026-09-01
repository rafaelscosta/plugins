# ADR Set — Mobile-First Project Continuity

**Status:** Proposed for R0 ratification

## ADR-001 — Preserve PCP/1 for first mobile-first release

**Decision:** Do not introduce PCP/2 in R0-R6 unless an incompatible canonical checkpoint semantic becomes unavoidable.

**Why:** PCP/1 already supports portable standalone checkpoints, capability degradation, downgrade-first consumption, lineage, integrity, and repository reconciliation. Mobile transport and planning memory can be added as sidecars/extensions.

**Consequence:** Existing consumers remain compatible; protocol-version migration risk is deferred.

## ADR-002 — Separate canonical checkpoint state from long-horizon planning

**Decision:** Keep PCP/1 checkpoint compact and introduce `planning-snapshot` as a digest-addressed sidecar.

**Why:** `open_work` is intentionally not a full backlog. Forcing releases/epics/stories/tasks into PCP/1 would bloat the protocol and conflate continuation memory with implementation evidence.

**Consequence:** Planning can evolve independently while empirical completion remains governed by PCP evidence rules.

## ADR-003 — Treat transport as replaceable infrastructure

**Decision:** Define a transport contract. The current Downloads file becomes `file` adapter; GitHub becomes the first remote/mobile adapter.

**Why:** Filesystem movement is a deployment detail and blocks phone-only operation.

**Consequence:** No transport may gain authority over checkpoint semantics.

## ADR-004 — GitHub is the first remote transport, not the final continuity service

**Decision:** Implement GitHub transport before building custom backend/MCP infrastructure.

**Why:** It provides remote, cross-device, authenticated persistence with minimal new infrastructure and is sufficient to validate the product hypothesis.

**Consequence:** Dedicated service remains deferred until concrete limitations are observed.

## ADR-005 — Prefer dedicated private continuity repository

**Decision:** Default GitHub transport to a dedicated private continuity-state repository rather than committing handoffs into product repositories.

**Why:** Avoid product history pollution, continuity-induced commits, snapshot confusion, and accidental mixing of planning/session data with source code.

**Consequence:** Public publication is fail-closed unless explicitly approved.

## ADR-006 — Session compilation is incremental by default

**Decision:** After bootstrap, compile from prior continuity + current session delta rather than relying on full historical transcript availability.

**Why:** Long sessions may exceed available context and raw transcript replay defeats compaction.

**Consequence:** Accepted unfinished work must survive omission from later turns; silence is not cancellation.

## ADR-007 — External handoff always reconciles before authority

**Decision:** Resolver must feed remote/portable checkpoints into existing downgrade-first consumption and repository reconciliation. No remote handoff directly promotes canonical HEAD.

**Why:** Remote persistence and integrity do not prove current repository truth.

**Consequence:** Historically reported completions remain unverified until checked on capable surface.

## ADR-008 — Mobile-first is a normative acceptance constraint

**Decision:** A required desktop, terminal, local Downloads manipulation, or manual JSON transfer is a release-blocking failure for the mobile E2E gate.

**Why:** Phone-only operation is a product requirement, not progressive enhancement.

**Consequence:** File adapter may remain for compatibility but cannot be the only successful path.

## ADR-009 — No hidden reasoning in compiled continuity

**Decision:** Session Compiler stores concise decisions/rationale/provenance only; never hidden chain-of-thought, scratchpads, secrets, or unnecessary personal data.

**Why:** Continuity artifacts cross surfaces and may be remotely persisted.

**Consequence:** Evals include sensitive-data leakage and hidden-reasoning exclusion.

## ADR-010 — Digest-bearing remote envelopes reference sealed portable checkpoints

**Decision:** Any PCP checkpoint referenced by `pcp-handoff/1` must be sealed and expose the same canonical `verification.content_digest` recorded in the envelope. A ChatGPT PORTABLE producer may seal without repository evidence, but must retain `surface_status: unverifiable` and must not upgrade reported/inferred empirical claims.

**Why:** The remote envelope needs a stable checkpoint digest. Allowing draft checkpoints with `content_digest: null` would either make remote integrity unverifiable or force a second competing checkpoint-hash semantic.

**Consequence:** PCP/1 sealing is explicitly separated from empirical verification. Legacy direct file handoff may continue to transfer an unsealed draft outside the envelope; remote envelope publication may not.
