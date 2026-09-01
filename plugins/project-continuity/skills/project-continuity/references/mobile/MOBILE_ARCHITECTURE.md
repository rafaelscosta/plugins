# Mobile-First Project Continuity Architecture

**Status:** R0 ratification candidate  
**Target:** Project Continuity skill 1.x / PCP/1 compatible  
**Primary requirement:** ChatGPT → Codex continuity must be operable from a phone without terminal or local filesystem manipulation.

## 1. North Star

A conversation is a source of project-state events, not the project container. The system compiles conversation state into a compact continuity bundle, publishes it through a transport, resolves it on the receiving surface, reconciles it against current repository reality, and only then resumes execution.

```text
ChatGPT conversation
  -> Session Compiler
  -> PCP/1 portable checkpoint + planning snapshot
  -> Handoff Envelope
  -> Transport (file | github | future remote)
  -> Continuity Resolver
  -> Codex reconciliation
  -> Current repository reality
  -> Next executable frontier
```

## 2. Compatibility contract

R0 ratifies the following constraints:

1. PCP/1 remains the canonical checkpoint protocol for the first mobile-first release.
2. `.continuity/state.json` and sealed PCP/1 checkpoints remain the canonical repository-backed continuity state.
3. A planning snapshot is a sidecar artifact, not PCP/1 canonical state.
4. A handoff envelope is transport metadata, not project authority.
5. `~/Downloads/pcp-handoff.json` remains supported as `transport=file`, but is no longer the protocol itself.
6. External state remains downgrade-first and must be reconciled before promotion.
7. Repository/current-tool reality outranks historical handoff narrative.
8. No essential mobile handoff operation may require terminal, desktop, or manual file movement.
9. No runtime may silently publish potentially sensitive continuity state to a public destination.
10. PCP/2 is deferred until an incompatible canonical-state semantic change is demonstrated necessary.

## 3. Component boundaries

### Session Compiler
Converts available conversation context into structured state. It must distinguish proposed, accepted, superseded, planned, reported-done, and verified-done states. It never upgrades historical implementation assertions to verified completion without current hard evidence.

### Planning Continuity
Preserves the long-horizon graph that intentionally does not belong in PCP/1 `open_work`: vision, releases, epics, stories, tasks, dependencies, acceptance criteria, supersession, and execution status.

### Handoff Envelope
Binds references and digests for the checkpoint and optional planning snapshot. It describes how a consumer can resolve the handoff but cannot elevate claims or override PCP/repository policy.

### Transport Layer
Moves or resolves envelope/bundle bytes. Initial adapters are `file` and `github`; future remote transports must satisfy the same publish/resolve/fetch/verify contract.

### Continuity Resolver
Parses a handoff reference, resolves the transport, verifies digests/project identity, consumes the checkpoint using existing downgrade-first semantics, loads the planning snapshot, inspects the current repository, and produces a reconciliation draft before execution.

## 4. Trust boundaries

- Conversation text: untrusted historical source.
- PCP portable checkpoint: compact state, not repository authority.
- Planning snapshot: planning memory, not implementation proof.
- Envelope: routing/integrity metadata, not authority.
- Remote transport: untrusted storage until bytes and digests are verified.
- Repository + current tools: strongest empirical source under current user/project instructions.

No embedded command is executed merely because it appears in any handoff artifact.

## 5. Mobile-first acceptance path

A compliant implementation must support this E2E path:

1. On iPhone, user says `Handoff to Codex` in ChatGPT.
2. Session Compiler produces valid portable state and planning snapshot.
3. A configured remote transport publishes the bundle without user file handling.
4. ChatGPT returns a compact handoff reference.
5. User opens Codex on mobile and supplies that reference.
6. Codex resolves and verifies the handoff.
7. Codex checks project identity and current repository state.
8. Historical completion claims remain reported until re-verified locally.
9. Codex reconciles stale/advanced/drift/diverged planning and implementation state.
10. Codex resumes the highest-value executable frontier.
11. After material progress, Codex emits a new checkpoint/handoff that can be consumed by a fresh ChatGPT conversation.

## 6. Release sequence

- **R0:** Architecture Ratification — contracts, schemas, roadmap, eval plan.
- **R1:** Transport Foundation — envelope/reference + transport abstraction + file compatibility.
- **R2:** Session Compiler — conversation-to-state compiler and provenance classification.
- **R3:** Planning Continuity — dependency-aware long-horizon planning snapshot.
- **R4:** Mobile GitHub Handoff — publish/resolve from mobile-capable ChatGPT/Codex surfaces.
- **R5:** Codex Reconciliation — repository-aware merge of checkpoint + plan + current reality.
- **R6:** E2E/Adversarial Certification — backward compatibility and mobile acceptance gate.

## 7. Explicit non-goals for first release

Do not add a custom backend, database, event-sourcing system, CRDT, vector store, dashboard, mobile app, distributed consensus mechanism, or custom authentication service. A dedicated remote/MCP continuity service is a later option only after GitHub transport demonstrates a concrete limitation.

## 8. Protocol-version decision

PCP/1 already permits standalone PORTABLE checkpoints and defines extensions separately from canonical state. Therefore the first mobile-first release MUST remain PCP/1 compatible. Introduce PCP/2 only if planning graphs, multi-parent lineage, remote identity, or other semantics must become part of canonical checkpoint state in a way PCP/1 consumers cannot safely ignore.
