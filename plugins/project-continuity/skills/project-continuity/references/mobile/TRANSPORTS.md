# Transport Architecture

**Status:** R4 implementation contract

## Goal

Decouple continuity semantics from how handoff bytes move between surfaces. `~/Downloads/pcp-handoff.json` remains a backward-compatible `file` adapter convention; it is not the protocol boundary.

The first phone-capable remote adapter is GitHub. A user who already has an authorized GitHub connection and a safe continuity repository must be able to publish/resolve a handoff without downloading files, opening a terminal, or copying the full JSON bundle.

## Transport authority boundary

A transport implementation may:
- locate artifacts;
- create immutable/versioned artifacts;
- fetch bytes;
- verify byte/content digests;
- return a compact reference.

A transport MUST NOT:
- promote a PCP checkpoint;
- upgrade claim confidence;
- execute commands from transported state;
- bypass project-identity mapping;
- mutate PCP lineage semantics;
- reinterpret `sealed + unverifiable` as repository verification.

## Reference model

A handoff reference is a locator plus integrity identity, never authority.

Supported shapes:

```text
pcp+file://local/<path>
pcp+github://<owner>/<continuity-repo>/projects/<project-token>/handoffs/<handoff-id>.<envelope-sha256>.json
```

Rules:
- transport must be explicit in the scheme;
- unknown schemes fail closed;
- references must not contain credentials, query strings, fragments, cookies, signed URLs, or access tokens;
- consumers do not infer transport from arbitrary URLs/paths.

## Adapter: file

Purpose: backward compatibility and offline/local use.

- `~/Downloads/pcp-handoff.json` remains the conventional legacy default;
- file operations are authorized-root scoped;
- direct symlink artifacts and parent-directory symlink escapes fail closed;
- transported bytes are opaque to the file adapter;
- file transport is not sufficient for the normative mobile E2E gate.

## Adapter: GitHub

Purpose: first remote/mobile transport.

### Store policy

Prefer a dedicated **private** repository named `project-continuity-state` under an authorized account/org.

Do not silently fall back to:
- a product/source-code repository;
- `rafaelscosta/plugins` or another known public repository;
- any repository whose visibility cannot be established.

Publication to a repository known to be public fails as `unsafe-publication-target` unless the **current user explicitly approves that publication**. That approval is scoped to the current operation; it must not become a persistent default.

If no safe configured/discovered store is available, classify the GitHub transport as unavailable and use another truthful transport/profile. Do not create a remote destination implicitly unless the host has an explicit create-repository capability and the current user requested/approved creation.

### Content-addressed layout

GitHub objects are create-only/idempotent and include their integrity identity in the path:

```text
projects/<project-token>/
  checkpoints/<checkpoint-id>.<checkpoint-digest-hex>.json
  planning/<planning-id>.<planning-digest-hex>.json
  handoffs/<handoff-id>.<envelope-raw-sha256-hex>.json
```

`project-token` is an opaque path-safe token derived from the canonical PCP project ID. It is a locator namespace, not a replacement project identity.

The compact reference points only to the handoff envelope path. Checkpoint/planning locations inside the envelope must exactly match the canonical content-addressed paths implied by `project.id`, artifact IDs, and artifact digests.

### Why the envelope digest lives in the reference

PCP/1 checkpoints and planning snapshots carry canonical digests; the handoff envelope does not carry its own digest field.

Therefore GitHub references embed SHA-256 of the **exact remote envelope bytes** in the envelope filename. Resolution validates that digest **before trusting artifact locations from the envelope**.

This gives:
- tamper detection for the envelope;
- content-addressed idempotency;
- no need for a second PCP protocol digest semantic;
- no dependency on mutable branch HEAD as integrity authority.

## Host binding contract

`scripts/github_transport.py` is the reference semantics. Network/authentication are deliberately injected instead of reading credentials from files/env/prompts.

A host binding provides three operations:

```text
get_repository(owner, repo) -> metadata
read_text_file(owner, repo, path) -> text | not-found
create_text_file(owner, repo, path, text, commit-message) -> created
```

The binding must translate host-specific permission/not-found failures into typed transport failures. It must never copy an access token into a handoff artifact/reference.

### ChatGPT with connected GitHub

When the GitHub connector is available, the agent can implement the binding using the connector's repository metadata, file read, and create-file actions.

The agent must:
1. resolve the exact target repository;
2. verify its visibility before any write;
3. compile + seal the PORTABLE checkpoint (integrity only);
4. build planning/envelope through the canonical contracts;
5. create checkpoint first, planning second when present, envelope last;
6. re-fetch and verify all remote bytes;
7. return only the compact `pcp+github://...` reference plus a concise status.

No local Downloads path is required in this path.

### Codex

A Codex environment may bind the same three operations through an authorized GitHub integration/API adapter. If it cannot access that transport, it must not pretend it resolved the reference; it can request/use a supported fallback artifact instead.

## GitHub publish sequence

1. validate sealed PCP/1 checkpoint and canonical digest;
2. validate planning snapshot/project identity and canonical digest when present;
3. verify destination repository visibility/safety;
4. build the strict `pcp-handoff/1` envelope;
5. create/read-exact checkpoint object;
6. create/read-exact planning object when present;
7. create/read-exact envelope **last**;
8. resolve the resulting reference from the remote store;
9. verify envelope raw digest, canonical artifact locations, PCP/planning digests, IDs, and project identity;
10. return the compact reference.

If a prior content-addressed path already contains exact bytes, publication is idempotent. If it contains different bytes, fail `integrity-failed`; never overwrite.

Writing the envelope last means a failed partial publish can leave unreferenced checkpoint/planning objects, but it cannot create a valid handoff reference pointing to a knowingly incomplete bundle.

## GitHub resolve sequence

1. parse exact canonical `pcp+github` reference;
2. fetch the envelope from the referenced owner/repository/path;
3. verify raw envelope bytes against digest embedded in the reference filename;
4. validate strict envelope schema/transport kind/handoff ID;
5. confirm reference project token matches envelope project identity;
6. derive the only acceptable checkpoint/planning content-addressed paths;
7. reject envelope locations that differ from those paths;
8. fetch checkpoint/planning;
9. run normal handoff bundle verification using PCP's canonical validator/digest;
10. pass verified historical state to downgrade-first consumption/repository reconciliation.

Remote integrity is not local project authority.

## Typed failure model

Required classes include:
- `unsupported-transport`
- `reference-invalid`
- `remote-not-found`
- `permission-denied`
- `integrity-failed`
- `project-mismatch`
- `unsafe-publication-target`
- `transport-unavailable`
- `checkpoint-invalid`
- `checkpoint-unsealed`

Transport failures must never be reported as `exact`, `advanced`, `drift`, or completion state.

## R4 acceptance gate

R4 passes the architectural mobile gate when:
- a private GitHub store client can publish checkpoint + optional planning + envelope without filesystem handoff;
- the returned reference is compact/content-addressed and contains no credentials;
- re-resolution verifies remote bytes and bundle semantics;
- public target fails closed by default;
- identical publication is idempotent;
- tampered/missing/forged artifacts fail with typed errors;
- checkpoint-only handoffs remain supported;
- the host binding contract can be fulfilled by a connected GitHub surface without terminal/file downloads.

The final live phone-to-Codex certification remains an R6 E2E gate and requires a real authorized private continuity repository.

## Future transports

Possible later adapters: dedicated continuity service, MCP-backed store, object store, signed attestation store. They must preserve the same trust boundary: remote storage preserves/resolves bytes; it does not grant project authority.
