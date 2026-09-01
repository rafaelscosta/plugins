#!/usr/bin/env python3
"""Supported CLI facade for bootstrap and incremental Session Compiler workflows.

Semantic extraction produces ``pcp-session-compilation/1`` IR. This facade is
the supported compiler entrypoint: it verifies inherited planning integrity,
merges prior planning when present, enforces cross-record invariants that JSON
Schema cannot express, and only then delegates deterministic PCP/planning
compilation to ``session_compiler.py``.
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


def validate_prior_planning_integrity(prior: dict[str, Any]) -> None:
    """Verify prior planning structure and canonical digest before incremental merge."""
    errors = COMPILER.BUNDLE.validate_planning_snapshot(prior)
    if errors:
        raise MERGE.PlanningMergeError(
            "Invalid prior planning snapshot:\n- " + "\n- ".join(errors)
        )
    recorded_digest = prior.get("content_digest")
    if not isinstance(recorded_digest, str) or not recorded_digest:
        raise MERGE.PlanningMergeError(
            "Prior planning snapshot must carry a canonical content_digest"
        )
    computed_digest = COMPILER.BUNDLE.compute_planning_digest(prior)
    if recorded_digest != computed_digest:
        raise MERGE.PlanningMergeError(
            "Prior planning snapshot content_digest does not match its canonical bytes"
        )


def _validate_reference_graph(
    records: list[dict[str, Any]],
    *,
    id_field: str,
    edge_field: str,
    label: str,
) -> None:
    """Reject unknown, self-referential, or cyclic ID edges in one record set."""
    ids = {
        record.get(id_field)
        for record in records
        if isinstance(record, dict) and isinstance(record.get(id_field), str)
    }
    graph: dict[str, list[str]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get(id_field), str):
            continue
        record_id = record[id_field]
        raw_edges = record.get(edge_field)
        if not isinstance(raw_edges, list):
            continue
        edges = [edge for edge in raw_edges if isinstance(edge, str)]
        unknown = [edge for edge in edges if edge not in ids]
        if unknown:
            raise COMPILER.SessionCompilationError(
                f"{label} {record_id!r} references unknown {edge_field}: "
                + ", ".join(sorted(unknown))
            )
        if record_id in edges:
            raise COMPILER.SessionCompilationError(
                f"{label} {record_id!r} cannot reference itself via {edge_field}"
            )
        graph[record_id] = edges

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, trail: list[str]) -> None:
        """Depth-first cycle check for one ID reference graph."""
        if node in visited:
            return
        if node in visiting:
            if node in trail:
                start = trail.index(node)
                cycle = trail[start:] + [node]
            else:
                cycle = trail + [node]
            raise COMPILER.SessionCompilationError(
                f"{label} {edge_field} cycle: " + " -> ".join(cycle)
            )
        visiting.add(node)
        for dependency in graph.get(node, []):
            visit(dependency, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for record_id in sorted(graph):
        visit(record_id, [])


def validate_blocker_dependencies(source: dict[str, Any]) -> None:
    """Reject unknown or cyclic blocker dependencies before PCP conversion.

    ``blockers[].depends_on`` is intentionally a blocker-to-blocker graph. The
    low-level compiler maps those stable blocker IDs into PCP ``open_work`` IDs;
    allowing an unknown dependency would otherwise lose information silently.
    """
    blockers = source.get("blockers")
    if not isinstance(blockers, list):
        return
    _validate_reference_graph(
        blockers,
        id_field="id",
        edge_field="depends_on",
        label="Blocker",
    )


def validate_supersession_references(source: dict[str, Any]) -> None:
    """Ensure decision/planning supersession edges point to known current state."""
    decisions = source.get("decisions")
    if isinstance(decisions, list):
        _validate_reference_graph(
            decisions,
            id_field="id",
            edge_field="supersedes",
            label="Decision",
        )

    planning = source.get("planning")
    if isinstance(planning, dict):
        items = planning.get("items")
        if isinstance(items, list):
            _validate_reference_graph(
                items,
                id_field="id",
                edge_field="supersedes",
                label="Planning item",
            )


def normalize_pcp_decision_supersedes(
    checkpoint: dict[str, Any],
    source: dict[str, Any],
) -> None:
    """Translate IR decision IDs to the PCP claim IDs emitted for those decisions."""
    decisions = source.get("decisions")
    if not isinstance(decisions, list):
        return
    claim_id_by_decision_id = {
        decision["id"]: f"SC-D-{index:03d}"
        for index, decision in enumerate(decisions, start=1)
        if isinstance(decision, dict) and isinstance(decision.get("id"), str)
    }
    claims = checkpoint.get("claims")
    if not isinstance(claims, list):
        return
    for index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            continue
        target_claim_id = f"SC-D-{index:03d}"
        claim = next(
            (
                candidate
                for candidate in claims
                if isinstance(candidate, dict)
                and candidate.get("id") == target_claim_id
            ),
            None,
        )
        if claim is None:
            raise COMPILER.SessionCompilationError(
                f"Compiler did not emit expected PCP decision claim {target_claim_id}"
            )
        supersedes = decision.get("supersedes")
        if not isinstance(supersedes, list):
            continue
        claim["supersedes"] = [
            claim_id_by_decision_id[decision_id]
            for decision_id in supersedes
        ]


def refresh_digests_after_normalization(
    checkpoint: dict[str, Any],
    planning: dict[str, Any],
) -> None:
    """Refresh canonical digests after deterministic post-compilation normalization."""
    verification = checkpoint.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "sealed":
        return

    verification["content_digest"] = None
    verification["content_digest"] = COMPILER.PCP.compute_content_digest(checkpoint)
    checkpoint_errors = COMPILER.PCP.validate_checkpoint(
        checkpoint,
        expect_sealed=True,
    )
    if checkpoint_errors:
        raise COMPILER.SessionCompilationError(
            "Normalized sealed checkpoint is invalid:\n- "
            + "\n- ".join(checkpoint_errors)
        )

    planning["source_checkpoint"] = {
        "id": checkpoint["checkpoint_id"],
        "digest": verification["content_digest"],
    }
    planning["content_digest"] = None
    planning_errors = COMPILER.BUNDLE.validate_planning_snapshot(planning)
    if planning_errors:
        raise COMPILER.SessionCompilationError(
            "Normalized planning snapshot is invalid:\n- "
            + "\n- ".join(planning_errors)
        )
    planning["content_digest"] = COMPILER.BUNDLE.compute_planning_digest(planning)


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
            validate_prior_planning_integrity(prior)
            source = MERGE.merge_compilation_with_prior(source, prior)
            mode = "incremental"

        validate_blocker_dependencies(source)
        validate_supersession_references(source)

        checkpoint, planning = COMPILER.compile_session(
            source,
            seal_portable=bool(args.seal_portable),
            sealed_at=args.sealed_at,
        )
        normalize_pcp_decision_supersedes(checkpoint, source)
        refresh_digests_after_normalization(checkpoint, planning)

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
