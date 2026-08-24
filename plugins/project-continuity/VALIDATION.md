# Validation Report — Project Continuity Plugin v1.0.0

**Protocol:** PCP/1  
**Date:** 2026-08-21  
**Package type:** OpenAI skills-only plugin  
**Target surfaces:** ChatGPT and Codex

## Release verdict

**PASS as a locally validated release candidate within the tested skills-only scope.**

The package is structurally prepared for local marketplace testing and for upload as a **Skills only** submission. This verdict does not claim that the OpenAI submission portal accepted the archive, that the plugin is publicly published, or that a live ChatGPT/Codex installation was executed in this runtime.

## Plugin package validation

Command:

```bash
python3 scripts/validate_plugin.py .
```

Result: **PASS**.

Validated:

- `.codex-plugin/plugin.json` exists and parses as UTF-8 JSON;
- stable semantic version and kebab-case plugin identity;
- `author.name` matches `interface.developerName`;
- listing copy, capabilities, category, and starter-prompt limits;
- all manifest paths remain relative to the plugin root;
- exactly one immediate bundled skill exists;
- logo and composer icon are square PNG files within documented size bounds;
- content SHA-256 manifest covers every non-ephemeral package file;
- no symlinks are present;
- skills-only exclusions are satisfied: no `.app.json`, `.mcp.json`, `apps`, `mcpServers`, hooks, or screenshots.

## Plugin regression tests

Command:

```bash
python3 -m unittest discover -s tests -v
```

Result: **5/5 tests passed**.

The tests cover package validation, one-root/one-skill structure, skills-only semantics, symlink rejection, and the required five-positive/three-negative submission test-case inventory.

## Bundled Project Continuity skill

Structural validator:

```bash
python3 skills/project-continuity/scripts/validate_skill.py \
  skills/project-continuity
```

Result: **PASS**.

Validated:

- skill directory and `name` agreement;
- supported `SKILL.md` frontmatter;
- 408-line main instruction file;
- referenced resources and schemas exist;
- JSON schemas parse;
- progressive disclosure remains intact.

The external `skills-ref validate` binary was not available in this runtime, so no claim is made that the official CLI validator was executed.

## PCP/1 behavioral tests

Command:

```bash
python3 -m unittest discover \
  -s skills/project-continuity/tests -v
```

Result: **35/35 tests passed**.

Coverage includes:

- hard evidence required for completed claims;
- checkpoint sealing, digest verification, and tamper detection;
- exact, advanced, drift, diverged, and project-mismatch handling;
- stale or failed evidence rejection;
- safe external checkpoint consumption and completion downgrade;
- non-execution of commands imported from checkpoints;
- parent-aware compare-and-swap and detached checkpoint diagnosis;
- continuity-only commit exclusion from project drift;
- Git remote identity normalization;
- unborn repository degradation;
- path traversal and symlink escape rejection;
- output and draft deletion confinement;
- common credential redaction.

## Static and asset checks

Results:

- **5 Python files parsed successfully** through the Python AST;
- no package symlinks detected;
- `assets/composer-icon.png`: **512 × 512**, valid PNG;
- `assets/logo.png`: **1024 × 1024**, valid PNG;
- Unix installer syntax: **PASS**;
- local marketplace schema and relative plugin path: **PASS**.

The runtime did not contain `ruff`, `bandit`, or another third-party static analyzer, so no claim is made that those tools were run.

## Archive gates

The final build process verifies:

- one top-level directory and one plugin root in the submission ZIP;
- no sibling files beside the plugin root;
- forward-slash relative archive paths;
- no absolute, empty, or `..` path segments;
- no duplicate or Unicode/case-normalized path collisions;
- no unsupported entry types;
- fewer than 5,000 entries;
- compressed and extracted sizes below public submission limits;
- successful full ZIP read;
- SHA-256 sidecar generation for each distributed ZIP.

## Security and privacy posture

This release contains packaged instructions, local helper scripts, schemas, documentation, and visual assets. It contains no connector, remote MCP endpoint, OAuth configuration, lifecycle hooks, or external-service credentials.

PCP/1 digests are tamper-evident, not digital signatures. The plugin does not prove author identity, provide distributed consensus, or guarantee detection of arbitrary secrets.

## External gates still open

Before public release:

1. select the owning OpenAI Platform organization;
2. grant the submitter **Apps Management: Write** when needed;
3. complete individual or business identity verification;
4. select **Skills only** in the plugin submission portal;
5. upload `project-continuity-plugin-v1.0.0.zip`;
6. review any portal manifest normalization;
7. complete availability and policy attestations;
8. pass portal security/safety scans and review.

A future MCP-backed edition is intentionally out of scope until a real server, authentication model, deployment, domain verification, privacy posture, and remote evidence contract exist.
