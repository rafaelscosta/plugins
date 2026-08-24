# Project Continuity Plugin

**Version:** 1.0.0  
**Protocol:** PCP/1  
**Surfaces:** ChatGPT and Codex

Project Continuity packages the `project-continuity` skill as a skills-only OpenAI plugin. It transfers compact, tamper-evident project state instead of raw chat history and requires evidence before treating implementation claims as complete.

## What it does

- creates FILE, FULL, or PORTABLE continuity checkpoints;
- distinguishes verified, reported, and inferred claims;
- seals checkpoints with canonical SHA-256 digests;
- detects exact state, advancement, drift, divergence, mismatch, or unverifiable state;
- safely consumes external ChatGPT or Codex checkpoints into reconciliation drafts;
- moves state through `~/Downloads/pcp-handoff.json` via `handoff-out` / `handoff-in`;
- prevents silent last-writer-wins promotion through parent-aware compare-and-swap semantics;
- preserves the rule that current repository reality outranks historical narrative.

## Package shape

```text
project-continuity/
├── .codex-plugin/plugin.json
├── assets/
├── skills/project-continuity/
├── scripts/validate_plugin.py
├── submission/
└── tests/
```

This release is intentionally **skills-only**. It does not contain `.app.json`, `.mcp.json`, `mcpServers`, lifecycle hooks, or fabricated external-service configuration. A future MCP-backed release can add remote checkpoint storage or signed attestations after a real server is implemented, registered, deployed, and reviewed.

## Validate

```bash
python3 scripts/validate_plugin.py .
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/project-continuity/tests -v
```

See `INSTALL.pt-BR.md`, `VALIDATION.md`, and `submission/` for local testing and public-submission preparation.
