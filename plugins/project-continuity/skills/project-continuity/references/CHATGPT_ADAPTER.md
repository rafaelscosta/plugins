# ChatGPT Adapter

## Goal

Use the same PCP/1 skill in ChatGPT without pretending ChatGPT always has repository-local capabilities.

## Capability detection

Choose the strongest truthful profile available:

### FULL-like ChatGPT session

Use when the project repository or a mounted project workspace is genuinely accessible and tools can inspect files/run commands. Follow the normal FULL workflow.

### FILE

Use when the user has attached project files, artifacts, or a file workspace but there is no authoritative Git repository.

Rules:
- inspect the relevant files before converting claims to `verified`;
- hash artifacts when the runtime permits;
- use artifact/file evidence rather than Git evidence;
- say repository verification is unavailable.

### PORTABLE

Use when the only source is the chat history or user-provided prose.

Rules:
- convert discussion into compact state;
- preserve settled decisions as `reported` decisions unless current evidence verifies them;
- do not convert “we finished X” into a verified completion claim without evidence;
- mark `verification.surface_status` as `unverifiable`;
- produce a bootstrap instruction for the next FULL-capability consumer.

## Chat history is not canonical state

A long thread contains:
- superseded ideas;
- proposed work that may never have been executed;
- duplicated assertions;
- model overclaims;
- stale assumptions.

Therefore, when making a checkpoint from chat:

1. extract current objective;
2. identify decisions explicitly settled by the user or artifacts;
3. separate proposals from performed actions;
4. downgrade implementation claims lacking evidence to `reported`;
5. list unresolved gaps;
6. make repository verification the first next action when appropriate.

## Transferring to Codex

When the user says **Handoff to Codex**, emit one valid PCP/1 portable checkpoint:

1. start from `assets/templates/portable-checkpoint.json`;
2. fill required fields only;
3. mark unverified claims `reported`;
4. set `verification.status` to `draft`;
5. make the last message that JSON object only — no prose, no markdown fence unless the host can only download a file.

Save or download it as `~/Downloads/pcp-handoff.json`. If the skill is already installed in Codex, the operator runs:

```bash
python3 <skill-root>/scripts/continuity.py handoff-in --root <project>
```

If files from the actual project are attached, include the minimum set needed to disambiguate project identity and critical artifacts.

## Receiving from Codex

When a Codex-produced sealed checkpoint is supplied:

1. verify its canonical digest if you can access the file bytes;
2. distinguish `historically-verified` from evidence re-verified in the current ChatGPT session;
3. use the checkpoint to answer planning/architecture questions without reopening settled decisions unnecessarily;
4. if asked to modify implementation but the repository is unavailable, produce a new PORTABLE continuation checkpoint rather than claiming implementation changes.

## Do not store hidden reasoning

A continuity checkpoint may contain concise rationale such as:

```text
Decision: keep state.json canonical and CONTINUITY.md derived.
Rationale: prevents prose drift and enables deterministic validation.
```

It must not contain private chain-of-thought, hidden scratchpads, or internal deliberation transcripts.

## Safe Codex consumption command

When the checkpoint arrives as a standalone file, Codex should not copy its claims directly into canonical state. Prefer:

```bash
python3 <skill-root>/scripts/continuity.py handoff-in --root .
```

This reads `~/Downloads/pcp-handoff.json` unless `--checkpoint` is supplied. The result is a **draft reconciliation checkpoint** parented to the current local head. Historical implementation-completion claims are downgraded until re-verified locally. A project-ID mismatch is a hard stop unless project identity is independently confirmed and `--confirm-project-mapping` is intentionally supplied.
