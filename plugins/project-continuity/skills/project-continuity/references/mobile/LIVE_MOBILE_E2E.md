# Live Mobile E2E Certification — Phone-Only Runbook

**Purpose:** certify the real ChatGPT-mobile -> private GitHub continuity store -> Codex -> fresh ChatGPT path.  
**Status:** not yet executed/certified.

This runbook is deliberately phone-only. Any required desktop, terminal, local Downloads manipulation, or full JSON copy is a certification failure.

## Preconditions

### 1. Private continuity repository

Create or designate a **private** repository named exactly:

```text
project-continuity-state
```

The repository is transport storage, not canonical product/repository authority.

Do not use:

- `rafaelscosta/plugins`;
- the product/source-code repository;
- an arbitrary public repository.

The live gate fails if repository visibility cannot be established as safe before publication.

### 2. ChatGPT GitHub access

From the phone-accessible account/settings flow, make sure the connected GitHub integration used by ChatGPT can:

- read repository metadata for `project-continuity-state`;
- read text files from it;
- create text files in it.

No token is copied into a prompt, continuity artifact, or reference.

### 3. Codex GitHub access

The Codex environment used for the test must be able to resolve the same `project-continuity-state` repository through an authorized GitHub binding/API integration.

The Codex repository under implementation must be the authoritative product/project repository. The continuity store is only a handoff transport.

## Evidence record

Create a certification record containing only non-secret evidence:

```text
execution_date:
chatgpt_surface:
source_session_ref:
continuity_store: <owner>/project-continuity-state
store_visibility_verified: private
source_project_repository:
source_reference:
codex_resolve_result:
codex_project_identity_result:
codex_prepare_result:
codex_planning_result:
codex_finalize_result:
frontier_item_id:
validation_summary:
progress_checkpoint_id:
return_reference:
fresh_chatgpt_result:
post_mvp_item_ids_preserved:
manual_file_move_required: false
desktop_required: false
terminal_required_on_phone: false
full_json_copy_required: false
verdict: PASS | FAIL
```

Never record credentials, cookies, authorization headers, private chain-of-thought, or unnecessary personal data.

## Phase A — ChatGPT mobile -> GitHub

From a long-running ChatGPT project session on the phone:

1. Continue until there is meaningful accepted project state: decisions, roadmap, open loops, blockers, and a candidate next frontier.
2. Send the intent:

   `Handoff to Codex`

3. ChatGPT must select the mobile GitHub path when the authorized private continuity store is available.
4. The session state must be compiled to Session Compilation IR rather than copying the transcript.
5. Incremental prior planning, when available, must be merged before publication.
6. The PORTABLE checkpoint must be sealed for integrity only.
7. `verification.surface_status` must remain `unverifiable` unless this ChatGPT surface truly has current authoritative repository evidence.
8. No unsupported historical completion may become PCP `completed`.
9. ChatGPT must verify the destination repository is private/safe before writing.
10. It must publish checkpoint first, planning second when present, envelope last.
11. It must re-fetch/resolve the published bundle and verify digests/identity.
12. ChatGPT returns a compact reference shaped like:

```text
pcp+github://<owner>/project-continuity-state/projects/<project-token>/handoffs/<handoff-id>.<digest>.json
```

### Phase A PASS criteria

- compact reference returned;
- no token/credential/query/fragment in reference;
- no download required;
- no local file move required;
- no terminal required;
- no desktop required;
- source checkpoint is sealed but not falsely repository-verified;
- remote re-resolution succeeds.

## Phase B — Reference -> Codex

Provide **only the compact reference** to Codex together with the current execution request.

Codex must:

1. parse the exact `pcp+github` reference;
2. fetch and verify envelope raw digest before following its locations;
3. derive/enforce canonical checkpoint/planning paths;
4. verify PCP/planning digests and project identity;
5. treat the external bundle as historical input, never local HEAD authority;
6. inspect current repository instructions and repository reality;
7. run the supported two-phase resume path;
8. create downgrade-first reconciliation state;
9. reconcile the planning snapshot using current evidence;
10. preserve accepted unfinished and post-MVP work;
11. close stale planned work if current evidence proves it already implemented;
12. reopen reported completion when implementation is absent;
13. promote the local consume/reconciliation lineage according to PCP rules;
14. verify the current local reconciliation HEAD is `exact`;
15. only then finalize resume and expose the bounded candidate frontier.

### Phase B PASS criteria

- remote handoff never directly promotes local canonical HEAD;
- project mismatch is a hard stop unless intentionally/independently mapped;
- planning is reconciled or absent before execution;
- final local checkpoint verifies `exact`;
- candidate frontier is dependency-valid and bounded;
- accepted post-MVP work is still visible.

## Phase C — Codex material progress -> new handoff

After Codex executes the bounded frontier:

1. run the relevant current validation/tests;
2. record only evidence actually observed now;
3. seal/promote a new local PCP checkpoint after material progress;
4. update/reconcile planning state;
5. publish checkpoint + planning + envelope to the same private continuity store;
6. re-fetch/verify the new bundle;
7. return a new compact `pcp+github://...` reference.

### Phase C PASS criteria

- new reference differs when project state materially changed;
- new checkpoint represents current repository evidence truthfully;
- completed work has current hard evidence where required;
- remaining accepted future work is not dropped.

## Phase D — New ChatGPT conversation

Open a **fresh ChatGPT conversation on the phone**. Do not replay the old transcript.

Provide the new compact reference and ask to continue the project.

The fresh ChatGPT session must:

1. resolve/verify the reference through the authorized GitHub binding;
2. distinguish historical verified evidence from evidence rechecked in this new session;
3. load the planning snapshot;
4. preserve accepted unfinished/post-MVP items even when the new message does not mention them;
5. not infer cancellation from omission;
6. not claim new code changes if authoritative repository reality is unavailable;
7. be able to issue another PORTABLE continuation/handoff when appropriate.

### Phase D PASS criteria

- no old transcript replay required;
- accepted post-MVP work remains present;
- prior completed current frontier remains represented accurately;
- fresh session does not upgrade historical evidence to current verification;
- another compact remote handoff remains possible.

## Normative overall PASS

The live mobile E2E is PASS only when all of these are true in one evidence record:

- phone-facing ChatGPT produced the first compact reference;
- a private continuity store was used;
- Codex resolved and reconciled against the real authoritative project repository;
- Codex executed/validated material progress;
- Codex published a new compact reference;
- a fresh phone-facing ChatGPT conversation consumed that reference;
- accepted post-MVP work survived;
- no desktop was required for the continuity transfer;
- no terminal was required on the phone;
- no Downloads/manual file transfer was required;
- no full JSON transcript/bundle copy was required.

If any of those conditions is unproven, record the gate as **NOT CERTIFIED**, not as partial PASS.

## Failure classifications

Use the existing typed model when applicable:

- `transport-unavailable`
- `permission-denied`
- `unsafe-publication-target`
- `remote-not-found`
- `reference-invalid`
- `integrity-failed`
- `project-mismatch`
- `checkpoint-invalid`
- `checkpoint-unsealed`

A transport failure must never be presented as project drift, completion, or repository verification.
