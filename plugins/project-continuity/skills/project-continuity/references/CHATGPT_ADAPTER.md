# ChatGPT Adapter

## Goal

Use the same PCP/1 continuity model in ChatGPT without pretending ChatGPT always has repository-local capabilities, and make ChatGPT → Codex handoff compatible with phone-only operation when a remote transport is available.

## Capability detection

Choose the strongest truthful profile available.

### FULL-like ChatGPT session

Use when the authoritative project repository or a mounted project workspace is genuinely accessible and tools can inspect files/run commands. Follow the normal FULL workflow. Do not route through PORTABLE merely because the conversation is in ChatGPT.

### FILE

Use when the user has attached project files, artifacts, or a file workspace but there is no authoritative Git repository.

Rules:
- inspect relevant files before converting claims to `verified`;
- hash artifacts when the runtime permits;
- use artifact/file evidence rather than Git evidence;
- do not claim repository-level verification.

### PORTABLE

Use when the available source is conversation history, user-provided prose, prior continuity artifacts, or other context that cannot independently prove current repository reality.

Rules:
- compile discussion into compact state rather than copying the transcript;
- preserve settled decisions as reported decisions unless current evidence verifies them;
- do not convert “we finished X” into a PCP `completed` claim without current hard evidence;
- use planning status `reported_done` for historical completion assertions that require re-verification;
- preserve inherited `verified_done` planning items only when their evidence references are preserved from prior continuity; do not treat them as current verification;
- keep `verification.surface_status` as `unverifiable` when authoritative project state is unavailable;
- make authoritative reconciliation the first executable action on the receiving FULL surface.

## Session Compiler

For handoff/resume/checkpoint intents in PORTABLE mode, use the Session Compiler contract in `references/mobile/SESSION_COMPILER.md`.

The compiler has two layers:

1. **Semantic extraction by the agent** → `pcp-session-compilation/1` IR.
2. **Deterministic compilation** → PCP/1 PORTABLE checkpoint + `pcp-planning/1` snapshot.

The IR schema is `assets/schemas/session-compilation.schema.json` and its starter template is `assets/templates/session-compilation.json`.

### Required extraction distinctions

Classify material state as:
- `proposed` — discussed but not accepted;
- `accepted` — explicitly adopted and still active;
- `ready` — accepted and dependency-ready;
- `in_progress` — current work is underway;
- `blocked` — cannot advance until a dependency/decision is resolved;
- `reported_done` — conversation/prior agent says done but current hard evidence is absent;
- `verified_done` — inherited or currently evidenced completion with evidence references;
- `superseded` — replaced by an explicit later decision/item;
- `cancelled` — explicitly abandoned.

Never infer cancellation from silence.

## Chat history is not canonical state

A long thread contains superseded ideas, proposed work that may never have executed, duplicated assertions, stale assumptions, and model overclaims.

When compiling a session:

1. identify the project and active objective;
2. extract definition of done where established;
3. identify explicit accepted/superseded decisions;
4. recover the accepted long-horizon plan (release → epic → story → task when present);
5. separate planning from implementation evidence;
6. classify historical “done” assertions conservatively;
7. preserve blockers, risks, unresolved questions, and dependency edges;
8. determine one candidate next frontier from accepted dependency-ready work;
9. make repository reconciliation precede that frontier in the portable PCP checkpoint;
10. record missing/inaccessible history as uncertainty rather than inventing it.

## Bootstrap compilation

Use when no prior planning snapshot is available.

- Extract only state supported by the currently available context.
- Create stable planning IDs for material accepted work.
- Keep missing historical context in `uncertainties`.
- Do not manufacture parent lineage.
- Compile to a PCP/1 PORTABLE checkpoint candidate and planning snapshot.

A capable filesystem surface may run:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <session-compilation.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

## Incremental compilation

Use when a prior `pcp-planning/1` snapshot exists.

The current session is a **delta**, not a replacement for history.

```text
prior planning snapshot
+ current session delta
= merged compilation
```

Rules:
- same-ID current items update prior items;
- new IDs append;
- prior items omitted by the current session remain preserved;
- `supersedes` explicitly marks predecessor items/decisions superseded;
- silence never deletes, cancels, or completes prior accepted work;
- project-ID mismatch is a hard stop;
- a conflicting explicit parent checkpoint is a hard stop.

A capable filesystem surface may run:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <current-session-delta.json> \
  --prior-planning <prior-planning.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json>
```

## Transferring to Codex

When the user says **Handoff to Codex**, select the strongest available transport without requiring the user to replay the conversation.

### Remote-capable path (mobile-first target)

When a configured/authorized remote handoff transport is available:

1. compile the current session into Session Compilation IR;
2. merge prior planning when available;
3. validate the IR;
4. compile PCP/1 PORTABLE + planning snapshot;
5. seal the PORTABLE checkpoint for integrity only;
6. keep `surface_status: unverifiable` unless current tools actually verified project reality;
7. verify that no unsupported empirical claim became PCP `completed`;
8. create a digest-bearing `pcp-handoff/1` envelope;
9. publish through the selected transport;
10. return the compact handoff reference to the user.

Sealing a PORTABLE checkpoint is tamper evidence. It does **not** prove implementation state, test success, or repository compatibility.

The deterministic local equivalent is:

```bash
python3 <skill-root>/scripts/session_compile.py \
  --input <session-compilation.json> \
  --prior-planning <prior-planning.json> \
  --checkpoint-out <checkpoint.json> \
  --planning-out <planning.json> \
  --seal-portable
```

Omit `--prior-planning` for bootstrap mode.

### Legacy file fallback

If no remote transport is available but a file can be handed to Codex, the existing standalone file flow remains valid:

- compile a PCP/1 PORTABLE **draft**;
- save/attach it as `pcp-handoff.json`;
- do not wrap that draft in a digest-bearing `pcp-handoff/1` envelope;
- Codex consumes it into a reconciliation draft using existing downgrade-first semantics.

The historical default path remains `~/Downloads/pcp-handoff.json` when that filesystem convention exists, but it is a transport fallback, not the protocol boundary.

## Receiving from Codex

When a Codex-produced sealed checkpoint/handoff is supplied:

1. verify envelope/checkpoint/planning digests when bytes are accessible;
2. distinguish historical verification from evidence re-verified in the current ChatGPT session;
3. load the planning snapshot so accepted unfinished work survives across conversations;
4. use checkpoint/planning state to continue architecture/planning without unnecessarily reopening settled decisions;
5. if implementation changes are requested but repository reality is unavailable, produce a new PORTABLE continuation rather than claiming implementation changes.

## Do not store hidden reasoning

Continuity artifacts may store concise decisions and rationale, for example:

```text
Decision: keep state.json canonical and CONTINUITY.md derived.
Rationale: prevents prose drift and enables deterministic validation.
```

They must not contain private chain-of-thought, hidden scratchpads, secrets, credentials, or unnecessary personal data.

## Safe Codex consumption

A remote/file handoff is historical input, not canonical repository authority. Codex must resolve/verify it, then feed the checkpoint into downgrade-first consumption and repository reconciliation before implementation work.

For the legacy standalone file path:

```bash
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

The result is a **draft reconciliation checkpoint** parented to the current local head. Historical implementation-completion claims remain downgraded until re-verified locally. A project-ID mismatch is a hard stop unless project identity is independently confirmed and intentionally mapped.
