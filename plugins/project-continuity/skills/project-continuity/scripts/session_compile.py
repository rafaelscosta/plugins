#!/usr/bin/env python3
"""Supported CLI facade for bootstrap and incremental Session Compiler workflows.

Semantic extraction produces ``pcp-session-compilation/1`` IR. This facade is
the supported compiler entrypoint: it merges prior planning when present,
performs cross-record validations that JSON Schema cannot express, and only then
delegates deterministic PCP/planning compilation to ``session_compiler.py``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
from typing import Any


def _load(name: str, filename: str):
    """Load one sibling compiler module without requiring package installation."""
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


COMPILER = _load("pcp_session_compile_core", "session_compiler.py")
MERGE = _load("pcp_session_compile_merge", "planning_merge.py")


def validate_blocker_dependencies(source: dict[str, Any]) -> None:
    """Reject unknown or cyclic blocker dependencies before PCP conversion.

    ``blockers[].depends_on`` is intentionally a blocker-to-blocker graph. The
    low-level compiler maps those stable blocker IDs into PCP ``open_work`` IDs;
    allowing an unknown dependency would otherwise lose information silently.
    """
    blockers = source.get("blockers")
    if not isinstance(blockers, list):
        return

    blocker_ids = {
        blocker.get("id")
        for blocker in blockers
        if isinstance(blocker, dict) and isinstance(blocker.get("id"), str)
    }
    graph: dict[str, list[str]] = {}
    for blocker in blockers:
        if not isinstance(blocker, dict) or not isinstance(blocker.get("id"), str):
            continue
        blocker_id = blocker["id"]
        dependencies = blocker.get("depends_on")
        if not isinstance(dependencies, list):
            continue
        unknown = [
            dependency
            for dependency in dependencies
            if isinstance(dependency, str) and dependency not in blocker_ids
        ]
        if unknown:
            raise COMPILER.SessionCompilationError(
                f"Blocker {blocker_id!r} references unknown blocker dependencies: "
                + ", ".join(sorted(unknown))
            )
        graph[blocker_id] = [
            dependency
            for dependency in dependencies
            if isinstance(dependency, str)
        ]

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        """Depth-first cycle check for the blocker dependency graph."""
        if node in visited:
            return
        if node in visiting:
            if node in trail:
                start = trail.index(node)
                cycle = trail[start:] + [node]
            else:
                cycle = trail + [node]
            raise COMPILER.SessionCompilationError(
                "Blocker dependency cycle: " + " -> ".join(cycle)
            )
        visiting.add(node)
        for dependency in graph.get(node, []):
            visit(dependency, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for blocker_id in sorted(graph):
        visit(blocker_id, [])


def build_parser() -> argparse.ArgumentParser:
    """Build the supported Session Compiler CLI parser."""
    parser = argparse.ArgumentParser(
        description="Compile bootstrap or incremental Session Compilation IR into PCP portable state"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Current pcp-session-compilation/1 JSON",
    )
    parser.add_argument(
        "--prior-planning",
        help="Optional prior pcp-planning/1 snapshot. When supplied, omitted prior work is preserved.",
    )
    parser.add_argument("--checkpoint-out", required=True)
    parser.add_argument("--planning-out", required=True)
    parser.add_argument("--seal-portable", action="store_true")
    parser.add_argument(
        "--sealed-at",
        help="Optional RFC3339 seal time for deterministic tests",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Compile one bootstrap or incremental continuity session."""
    args = build_parser().parse_args(argv)
    try:
        source = COMPILER.read_json(pathlib.Path(args.input))
        mode = "bootstrap"
        if args.prior_planning:
            prior = COMPILER.read_json(pathlib.Path(args.prior_planning))
            source = MERGE.merge_compilation_with_prior(source, prior)
            mode = "incremental"
        validate_blocker_dependencies(source)
        checkpoint, planning = COMPILER.compile_session(
            source,
            seal_portable=bool(args.seal_portable),
            sealed_at=args.sealed_at,
        )
        COMPILER.atomic_write_json(
            pathlib.Path(args.checkpoint_out),
            checkpoint,
        )
        COMPILER.atomic_write_json(
            pathlib.Path(args.planning_out),
            planning,
        )
        print(
            json.dumps(
                {
                    "status": "compiled",
                    "mode": mode,
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "checkpoint_status": checkpoint["verification"]["status"],
                    "checkpoint_digest": checkpoint["verification"]["content_digest"],
                    "planning_id": planning["planning_id"],
                    "planning_digest": planning["content_digest"],
                    "planning_items": len(planning["items"]),
                    "decisions": len(planning["decisions"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (
        COMPILER.SessionCompilationError,
        MERGE.PlanningMergeError,
        RuntimeError,
    ) as exc:
        print(f"session-compile: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
