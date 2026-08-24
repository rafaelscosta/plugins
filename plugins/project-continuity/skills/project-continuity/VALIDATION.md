# Validation Report — Project Continuity Skill v1.0.0

**Protocol:** PCP/1  
**Date:** 2026-08-21  
**Release scope:** ChatGPT ↔ Codex continuity, local/file/portable verification, safe external checkpoint consumption, Git/file evidence, drift classification, lineage, and local concurrency protection.

## Result

**PASS within the tested PCP/1 scope.**

The package is functionally ready for installation/testing as v1.0.0. This statement does **not** claim digital authenticity, distributed consensus, perfect secret detection, or formal security verification.

## Agent Skills conformance

Validated against the current Agent Skills structural requirements represented by the bundled local validator:

- directory name matches `name: project-continuity`;
- `SKILL.md` has valid supported frontmatter fields;
- name/description/compatibility length and naming constraints pass;
- metadata values are strings;
- `SKILL.md` is 408 lines, below the Agent Skills recommendation to keep the main file under 500 lines;
- referenced local files exist;
- JSON schema files parse successfully;
- package follows progressive disclosure using `scripts/`, `references/`, and `assets/`.

Command:

```bash
python scripts/validate_skill.py .
```

Result: **PASS**.

### Official validator limitation

The official `skills-ref validate` command was **not executed** because `skills-ref` is not installed in this runtime and the runtime cannot install it from the network. The bundled validator is explicitly an equivalent local structural check, not a claim that the official validator was run.

Before publishing the skill to a managed catalog, run:

```bash
skills-ref validate ./project-continuity
```

## Automated tests

Command:

```bash
python -m unittest discover -s tests -v
```

Result: **35/35 tests passed**.

Coverage includes:

- completion claims require hard evidence;
- exact checkpoint verification;
- digest tamper detection;
- dirty worktree drift;
- legitimate forward advancement;
- diverged Git history;
- compare-and-swap rejection of parallel writers;
- detached checkpoint diagnosis;
- continuity-only commits do not create false advancement;
- stale test evidence is rejected;
- failing test evidence cannot prove completion;
- evidence-log tampering is rejected;
- stored commands are never auto-executed by verification;
- portable/no-repository checkpoints remain unverifiable;
- external completion claims are downgraded during consumption;
- imported command/test evidence is not copied as executable proof;
- project-ID mismatches are rejected unless explicitly mapped;
- Git remote identity is stable across SSH/HTTPS transport and display-name changes;
- repositories without a first commit degrade safely;
- tracked `..` path escapes are rejected;
- tracked symlink escapes are rejected;
- drafts cannot be deleted outside `.continuity/drafts/`;
- rendered output cannot escape the project root;
- malicious checkpoint IDs cannot traverse filesystem paths;
- symlinked `.continuity`, `checkpoints`, and `evidence` write paths are rejected;
- common credential patterns are redacted from captured logs;
- `handoff-out` copies sealed HEAD bytes to an interchange file;
- `handoff-in` consumes that file as a reconciliation draft;
- missing interchange files and symlink destinations are rejected.

## JSON Schema validation

Using `jsonschema` Draft 2020-12 in the validation runtime:

- `state.schema.json` is a valid schema;
- `checkpoint.schema.json` is a valid schema;
- a generated `state.json` validates;
- a real sealed checkpoint validates;
- `assets/templates/portable-checkpoint.json` validates.

Result: **PASS**.

## Bidirectional handoff smoke test

Executed an isolated end-to-end flow:

```text
ChatGPT-like PORTABLE producer
  ↓ sealed portable checkpoint
Codex-like FULL repository
  ↓ consume → reconciliation draft → seal/promote
ChatGPT-like receiver without repository
```

Observed results:

- portable producer: `unverifiable` + integrity valid;
- Codex consumer: `reconciliation-required`;
- Codex after local seal: `exact` + integrity valid;
- continuity doctor: healthy;
- return to repository-less ChatGPT surface: `unverifiable` + integrity valid.

Result: **PASS**.

This confirms the intended semantic distinction: checkpoint integrity can travel between surfaces, while repository truth is never fabricated on a surface that cannot inspect the repository.

## Static safety checks

Python AST scan of bundled scripts found none of:

- `eval`;
- `exec`;
- `os.system`;
- `os.popen`;
- `subprocess(..., shell=True)`.

Python compilation also passed for the CLI, validator, and tests.

Result: **PASS**.

`bandit` and `ruff` were not installed in the validation runtime, so no claim is made that those external analyzers were run.

## Known limitations

1. **Tamper-evident, not authenticated.** SHA-256 detects mutation but does not prove author identity. Signed attestations are a future extension.
2. **Local CAS, not distributed consensus.** Parallel-head protection applies to the continuity state visible in the current shared filesystem/repository; PCP/1 is not a remote consensus protocol.
3. **Secret redaction is defense-in-depth.** Common token/password/header patterns are scrubbed, but arbitrary secrets cannot be guaranteed to be recognized. Avoid capturing sensitive commands/logs.
4. **Ignored Git files are outside the default Git snapshot.** Critical ignored artifacts should be explicitly tracked with `--track` when their bytes matter to a claim.
5. **Portable mode cannot prove implementation.** Chat-only checkpoints intentionally carry reported state until a FILE/FULL consumer reconciles them.
6. **No automatic execution of historical commands.** This is intentional; a current agent/operator must independently choose every validation command.
7. **Exotic Git remote formats may require `--project-id`.** Common SSH/HTTPS/scp-like forms are normalized; explicit IDs remain the portability escape hatch.
8. **No formal security audit.** Adversarial unit tests and static checks were run, but they are not a substitute for third-party review in high-assurance environments.

## Release gate

For v1.0.0, the release gate is satisfied by the evidence above with two explicit external-validation caveats:

- run official `skills-ref validate` in an environment where it is installed;
- optionally run `ruff`/`bandit` or equivalent organization-standard static analyzers before high-assurance deployment.
