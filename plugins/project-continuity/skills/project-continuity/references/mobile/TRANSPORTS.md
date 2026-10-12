# Transport Architecture

**Status:** R0 ratification candidate

## Goal

Decouple continuity semantics from how handoff bytes move between surfaces. `~/Downloads/pcp-handoff.json` becomes one adapter (`file`), not the protocol boundary.

## Transport contract

A transport implementation exposes equivalent semantics for:

- `publish(bundle) -> reference`
- `resolve(reference) -> descriptor`
- `fetch(descriptor) -> bytes/artifacts`
- `verify(descriptor, bytes) -> integrity result`
- `describe(reference) -> safe human summary`

A transport MUST NOT:
- promote a checkpoint;
- upgrade claim confidence;
- execute embedded commands;
- bypass project-identity checks;
- mutate PCP lineage semantics.

## Reference model

A handoff reference is a compact locator plus expected integrity metadata. It is not authority.

Suggested URI forms:

```text
pcp+file://local/pcp-handoff.json
pcp+github://owner/repo/projects/<project-id>/handoffs/<handoff-id>.json
```

Consumers MUST treat unknown schemes as unsupported rather than guessing.

## Adapter: file

Purpose: backward compatibility and offline/local use.

- continue to support `~/Downloads/pcp-handoff.json` as the conventional default;
- `handoff-in` / `handoff-out` remain valid aliases over the file transport;
- file transport is not required for mobile-first E2E success.

## Adapter: github

Purpose: first remote/mobile transport.

Recommended storage target is a dedicated **private** continuity repository rather than commits to the product repository.

Recommended layout:

```text
projects/<project-id>/
  checkpoints/<checkpoint-id>.json
  planning/<planning-id>.json
  handoffs/<handoff-id>.json
```

Publishing to a public repository MUST be blocked by default when the payload can contain non-public project context. Explicit current-user consent is required to override that safety policy.

### GitHub publish sequence

1. validate checkpoint/planning/envelope locally on the producing surface;
2. redact forbidden/sensitive fields;
3. derive content digests before publication;
4. create immutable/versioned remote objects; avoid silent overwrite;
5. fetch the published bytes back when capability permits;
6. verify remote bytes match expected digests;
7. return the compact reference.

### GitHub resolve sequence

1. parse reference;
2. fetch envelope;
3. validate envelope schema;
4. resolve referenced checkpoint/planning artifacts;
5. validate digests;
6. validate project identity mapping;
7. pass verified bytes to the normal PCP consumer/reconciliation flow.

## Failure model

Required typed failures:

- `unsupported-transport`
- `reference-invalid`
- `remote-not-found`
- `permission-denied`
- `integrity-mismatch`
- `project-mismatch`
- `unsafe-publication-target`
- `transport-unavailable`

Transport failures MUST NOT be misclassified as project completion/drift states.

## Idempotency

Publishing the same immutable bundle MAY return the same content-addressed target/reference. A different payload MUST NOT silently overwrite an existing immutable handoff ID.

## Future transports

Possible later adapters: remote continuity service, MCP-backed storage, object store, signed attestation store. They must implement the same trust boundary: remote storage preserves bytes but does not grant project authority.
