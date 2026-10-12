# ChatGPT Adapter

## Goal

Use PCP/1 continuity in ChatGPT without pretending ChatGPT always has repository-local capabilities, and support phone-only ChatGPT → Codex handoff when an authorized remote transport is available.

## Capability detection

Choose the strongest truthful profile available.

### FULL-like ChatGPT session

Use when the authoritative project repository or mounted project workspace is genuinely accessible and tools can inspect files/run commands. Follow the normal FULL workflow. Do not downgrade to PORTABLE merely because the surface is ChatGPT.

### FILE

Use when project files/artifacts are accessible but there is no authoritative Git repository.

Rules:
- inspect relevant files before converting claims to `verified`;
- hash artifacts when the runtime permits;
- use artifact/file evidence rather than Git-history evidence;
- do not claim repository-level verification.

### PORTABLE

Use when available state is conversation history, user-provided prose, prior continuity artifacts, or other context that cannot independently prove current repository reality.

Rules:
- compile discussion into compact state instead of copying the transcript;
- preserve settled decisions as reported decisions unless current evidence verifies them;
- do not convert “we finished X” into a PCP `completed` claim without current hard evidence;
- use planning `reported_done` for historical completion assertions awaiting re-verification;
- inherited planning `verified_done` may retain historical evidence refs, but is not current ChatGPT repository verification;
- keep `verification.surface_status: unverifiable` when authoritative project state is unavailable;
- make authoritative reconciliation the first receiving-surface action.

## Session Compiler

For handoff/resume/checkpoint intents in PORTABLE mode, use `references/mobile/SESSION_COMPILER.md`.

The compiler has two layers:
1. semantic extraction by the agent → `pcp-session-compilation/1` IR;
2. deterministic compilation → PCP/1 PORTABLE checkpoint + `pcp-planning/1` snapshot.

IR schema/template:
- `assets/schemas/session-compilation.schema.json`
- `assets/templates/session-compilation.json`

### Required extraction distinctions

Classify material state as:
- `proposed`
- `accepted`
- `ready`
- `in_progress`
- `blocked`
- `reported_done`
- `verified_done`
- `superseded`
- `cancelled`

Never infer cancellation/completion from silence.

## Chat history is not canonical state

When compiling a session:
1. identify project + active objective;
2. extract bounded definition of done where established;
3. recover accepted/superseded decisions;
4. recover the accepted long-horizon release → epic → story → task graph when present;
5. separate planning assertions from implementation evidence;
6. classify historical “done” conservatively;
7. preserve blockers, risks, unresolved questions, and dependency edges;
8. preserve prior accepted work omitted by the current session;
9. determine one candidate dependency-ready frontier;
10. place repository reconciliation before that frontier in the PORTABLE checkpoint;
11. represent missing/inaccessible history as uncertainty, never invented state.

## Bootstrap compilation

Use when no prior planning snapshot exists.

A capable filesystem surface may run:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <session-compilation.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

## Incremental compilation

Use when a prior planning snapshot exists. The current session is a delta, not a replacement.

```text
prior planning + current session delta -> merged compilation
```

Rules:
- same-ID current items update prior items;
- new IDs append;
- omitted prior items remain;
- `supersedes` explicitly closes predecessors without deleting historical identity;
- silence never deletes/cancels/completes prior accepted work;
- project-ID mismatch is a hard stop;
- conflicting explicit parent checkpoint lineage is a hard stop.

A capable filesystem surface may run:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <current-session-delta.json> \
  --prior-planning <prior-planning.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

## Handoff to Codex

When the user says **Handoff to Codex**, select the strongest available transport without requiring transcript replay.

### GitHub remote path — mobile-first

Use when an authorized GitHub connection can read/write a safe continuity repository.

Recommended default store name: `project-continuity-state`.

Target resolution:
1. prefer an explicitly configured/previously established continuity repository;
2. otherwise search the authenticated user's accessible repositories for the exact configured/default store name;
3. read repository metadata and establish visibility **before writing**;
4. if no safe store exists, treat GitHub transport as unavailable and fall back truthfully;
5. never silently use the product repo, `rafaelscosta/plugins`, or another public repo as storage;
6. never implicitly create a repository unless the host exposes create-repository capability and the current user explicitly requested/approved creation.

For a PORTABLE handoff:
1. compile Session Compilation IR;
2. merge prior planning if available;
3. validate IR/graph/invariants;
4. compile PCP/1 PORTABLE + planning;
5. seal the PORTABLE checkpoint for **integrity only**;
6. keep `surface_status: unverifiable` unless current tools truly verified project reality;
7. ensure no unsupported empirical statement became PCP `completed`;
8. execute the GitHub transport contract from `references/mobile/TRANSPORTS.md`;
9. create checkpoint, then planning when present, then envelope last;
10. re-fetch/resolve the emitted reference and verify all remote bytes;
11. return the compact `pcp+github://...` reference to the user.

### Connected-GitHub host binding

The reference runtime is `scripts/github_transport.py`, but ChatGPT does not need a local terminal to satisfy its semantics.

When the GitHub connector is available, map the transport client contract to connector actions:

```text
get_repository      -> repository metadata lookup
read_text_file      -> exact repository-file fetch
create_text_file    -> create-only repository-file write
```

The agent must preserve the reference implementation's rules:
- create-only/content-addressed paths;
- exact-byte idempotency;
- public-target fail-closed;
- envelope raw digest embedded in the compact reference;
- canonical checkpoint/planning artifact locations;
- post-write re-fetch/verification;
- no credentials/tokens in prompt, files, envelope, or reference.

If a connector returns a permission/not-found conflict, translate it to the appropriate typed transport failure; do not reinterpret it as project drift/completion state.

### Deterministic local equivalent

On a filesystem-capable producer:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <session-compilation.json> \
  --prior-planning <prior-planning.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json> \
  --seal-portable
```

Omit `--prior-planning` for bootstrap.

### Legacy file fallback

If no remote transport is usable but a file can be transferred:
- compile a PCP/1 PORTABLE **draft**;
- save/attach it as `pcp-handoff.json`;
- do not wrap that draft in a digest-bearing envelope;
- Codex consumes it using existing downgrade-first semantics.

`~/Downloads/pcp-handoff.json` remains a historical file convention, not the protocol boundary.

## Receiving a remote Codex handoff

When a `pcp+github://...` reference is supplied:
1. parse it using the canonical layout, never as an arbitrary GitHub URL;
2. fetch envelope from the referenced owner/repo/path;
3. verify envelope raw digest embedded in the reference **before trusting envelope locations**;
4. validate strict envelope/project identity;
5. derive and enforce canonical checkpoint/planning paths;
6. fetch artifacts and validate PCP/planning canonical digests;
7. distinguish historical verification from evidence re-verified in the current ChatGPT session;
8. load planning so accepted unfinished work survives new conversations;
9. if implementation changes are requested but repository reality is unavailable, issue a new PORTABLE continuation rather than claiming code changes.

## Security boundary

Continuity artifacts may store concise decisions/rationale/provenance. They must not store:
- private chain-of-thought/scratchpads;
- credentials/tokens/cookies;
- unnecessary personal data;
- embedded commands as trusted authority.

Remote persistence and integrity never override current user/system/repository policy.

## Safe Codex consumption

A remote/file handoff is historical input, not canonical repository authority. Codex resolves/verifies it, then performs downgrade-first consumption and repository/planning reconciliation before implementation.

For the legacy standalone file path:

```bash
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

Historical implementation completions remain downgraded until current local evidence re-verifies them. Project-ID mismatch remains a hard stop unless project identity is independently confirmed and intentionally mapped.
