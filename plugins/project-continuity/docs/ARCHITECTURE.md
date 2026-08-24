# Plugin Architecture

## Release architecture

```text
Project Continuity Plugin
└── Project Continuity Skill
    ├── PCP/1 instructions
    ├── deterministic continuity CLI
    ├── schemas and templates
    ├── security boundaries
    └── evals and tests
```

The plugin is a distribution and discovery layer. The skill remains the workflow and protocol implementation. Repository truth remains in each project's `.continuity/` directory; the installed plugin is not the canonical project state.

## Why skills-only first

PCP/1 already supports repository-backed verification through the bundled local CLI when Codex has filesystem access. ChatGPT without repository access can still create portable checkpoints. A remote MCP service is not required for these core workflows and would introduce deployment, authentication, privacy, and trust obligations before it provides clear additional value.

## Future MCP frontier

An MCP-backed release should be considered only for capabilities that cannot be safely achieved by the packaged skill, such as:

- organization-wide checkpoint registries;
- signed checkpoint attestations;
- remote lineage queries across repositories;
- policy-controlled checkpoint publication;
- cross-device evidence retrieval.

Such a server must be real, registered, authenticated where necessary, deployed over production HTTPS, domain-verified, and separately reviewed. No placeholder MCP configuration belongs in this skills-only release.
