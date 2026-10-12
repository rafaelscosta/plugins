#!/usr/bin/env python3
"""Supported Codex resume facade for Project Continuity mobile handoffs.

Phase 1 (`prepare_from_reference`) resolves remote/file history, creates the
canonical downgrade-first PCP reconciliation draft, optionally reconciles the
planning sidecar, and returns a bounded candidate frontier.

Phase 2 (`finalize_resume`) releases execution only after the local continuity
HEAD has advanced through the imported handoff's consume lineage, verifies
`exact` against current repository state, and any supplied planning snapshot has
been reconciled. Remote history never directly becomes execution authority.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import pathlib
import sys
from typing import Any

FORMAT = "pcp-codex-resume/1"


class CodexResumeError(Exception):
    """Fail-closed error for the supported R5 resume facade."""


def _load(name: str, filename: str):
    """Load a sibling runtime module without package installation."""
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CodexResumeError(f"Unable to load required sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


RESOLVER = _load("pcp_codex_resume_resolver", "resume_resolver.py")
PCP = RESOLVER.PCP
PLANNING = RESOLVER.PLANNING


def _accepted_planning_decisions(planning: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return active planning decisions as historical/reportable resume context."""
    if planning is None:
        return []
    decisions: list[dict[str, Any]] = []
    for decision in planning.get("decisions", []) or []:
        if not isinstance(decision, dict) or decision.get("status") != "accepted":
            continue
        decisions.append(
            {
                "id": decision.get("id"),
                "statement": decision.get("statement"),
                "confidence": "reported",
                "source": "planning",
            }
        )
    return decisions


def _dedupe_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep stable first occurrence while avoiding duplicate decision IDs/statements."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for decision in decisions:
        key = (decision.get("id"), decision.get("statement"))
        if key in seen:
            continue
        seen.add(key)
        result.append(decision)
    return result


def _frontier_details(
    planning: dict[str, Any] | None,
    frontier: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Enrich the reconciler frontier with acceptance/dependency information."""
    if planning is None or frontier is None:
        return None
    item_id = frontier.get("item_id")
    item = next(
        (
            candidate
            for candidate in planning.get("items", []) or []
            if isinstance(candidate, dict) and candidate.get("id") == item_id
        ),
        None,
    )
    if item is None:
        raise CodexResumeError(
            f"Planning reconciliation frontier references unknown item: {item_id!r}"
        )
    return {
        **frontier,
        "acceptance_criteria": list(item.get("acceptance_criteria", []) or []),
        "depends_on": list(item.get("depends_on", []) or []),
    }


def _effective_planning(
    resolved: dict[str, Any],
    reconciliation: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Compute the exact planning result used to enrich the resume brief."""
    planning = resolved.get("planning_snapshot")
    if not isinstance(planning, dict):
        return None, None
    if reconciliation is None:
        return planning, None
    try:
        result, report = PLANNING.reconcile(planning, reconciliation)
    except PLANNING.PlanningReconciliationError as exc:
        raise CodexResumeError(f"Planning reconciliation failed: {exc}") from exc
    return result, report


def prepare_from_reference(
    root: str | pathlib.Path,
    reference: str,
    *,
    github_client: Any | None = None,
    file_allowed_root: str | pathlib.Path | None = None,
    surface: str = "codex",
    model: str | None = None,
    confirm_project_mapping: bool = False,
    planning_reconciliation: dict[str, Any] | None = None,
    resolved_at: str | None = None,
) -> dict[str, Any]:
    """Resolve one handoff and prepare a non-executable local reconciliation state."""
    project_root = pathlib.Path(root).resolve()
    _, before_state = PCP.load_state(project_root)
    before_head = copy.deepcopy(before_state["head"])
    before_generation = before_state["generation"]

    resolved = RESOLVER.resolve_reference(
        reference,
        github_client=github_client,
        file_allowed_root=file_allowed_root,
    )
    effective_planning, expected_report = _effective_planning(
        resolved, planning_reconciliation
    )
    prepared = RESOLVER.prepare_resume(
        project_root,
        resolved,
        surface=surface,
        model=model,
        confirm_project_mapping=confirm_project_mapping,
        planning_reconciliation=planning_reconciliation,
        resolved_at=resolved_at,
    )

    # The planning reconcile operation is deterministic. If both layers ran it,
    # assert their reports agree before surfacing a frontier.
    if expected_report is not None:
        actual = prepared["planning"]
        if actual.get("result") != expected_report.get("result_planning"):
            raise CodexResumeError("Planning reconciliation result drifted across resolver layers")
        if actual.get("transitions") != expected_report.get("transitions"):
            raise CodexResumeError("Planning reconciliation transitions drifted across resolver layers")

    checkpoint = resolved["checkpoint"]
    source_checkpoint_id = checkpoint.get("checkpoint_id")
    planning_status = prepared["planning"]["status"]
    enriched_frontier = _frontier_details(
        effective_planning if planning_status == "reconciled" else None,
        prepared["planning"].get("frontier"),
    )

    checkpoint_decisions = []
    for decision in prepared["resume_brief"].get("surviving_decisions", []):
        checkpoint_decisions.append({**decision, "source": "checkpoint"})
    planning_decisions = _accepted_planning_decisions(effective_planning)

    prepared["format"] = FORMAT
    prepared["local_project"]["head_at_prepare"] = before_head
    prepared["local_project"]["generation_at_prepare"] = before_generation
    prepared["resume_brief"]["surviving_decisions"] = _dedupe_decisions(
        checkpoint_decisions + planning_decisions
    )
    prepared["resume_brief"]["candidate_frontier"] = enriched_frontier
    prepared["execution_gate"] = {
        "repository_reconciliation_required": True,
        "planning_reconciliation_required": planning_status == "reconciliation-required",
        "candidate_frontier_available": enriched_frontier is not None,
        "execution_ready": False,
        "external_head_promotion_allowed": False,
        "next_required_action": (
            "reconcile-planning"
            if planning_status == "reconciliation-required"
            else "seal-local-reconciliation"
        ),
        "required_consume_session_ref": f"consume:{source_checkpoint_id}",
    }
    return prepared


def _lineage_contains_consume(
    root: pathlib.Path,
    *,
    head_id: str,
    stop_id: str | None,
    required_session_ref: str,
) -> bool:
    """Check that new local lineage contains the external consume reconciliation checkpoint."""
    current: str | None = head_id
    visited: set[str] = set()
    while current is not None and current != stop_id:
        if current in visited:
            raise CodexResumeError("Local continuity lineage cycle detected during resume finalization")
        visited.add(current)
        checkpoint = PCP.read_json(PCP.checkpoint_path(root, current))
        if checkpoint.get("producer", {}).get("session_ref") == required_session_ref:
            return True
        current = checkpoint.get("parent", {}).get("checkpoint_id")
    return False


def finalize_resume(
    root: str | pathlib.Path,
    prepared: dict[str, Any],
    *,
    finalized_at: str | None = None,
) -> dict[str, Any]:
    """Release execution only after local PCP reconciliation is promoted and exact."""
    if not isinstance(prepared, dict) or prepared.get("format") != FORMAT:
        raise CodexResumeError(f"Prepared resume must use {FORMAT}")
    project_root = pathlib.Path(root).resolve()
    _, state = PCP.load_state(project_root)
    if state["project"]["id"] != prepared.get("local_project", {}).get("id"):
        raise CodexResumeError("Prepared resume local project no longer matches current continuity state")

    prior_head = prepared.get("local_project", {}).get("head_at_prepare", {}) or {}
    prior_head_id = prior_head.get("checkpoint_id")
    prior_generation = prepared.get("local_project", {}).get("generation_at_prepare")
    current_head_id = state["head"].get("checkpoint_id")
    if current_head_id is None:
        raise CodexResumeError("Local continuity HEAD is still empty; reconciliation draft was not promoted")
    if state["generation"] <= prior_generation or current_head_id == prior_head_id:
        raise CodexResumeError("Local continuity HEAD did not advance after resume preparation")

    required_session_ref = prepared.get("execution_gate", {}).get(
        "required_consume_session_ref"
    )
    if not isinstance(required_session_ref, str) or not required_session_ref:
        raise CodexResumeError("Prepared resume is missing required consume lineage identity")
    if not _lineage_contains_consume(
        project_root,
        head_id=current_head_id,
        stop_id=prior_head_id,
        required_session_ref=required_session_ref,
    ):
        raise CodexResumeError(
            "Current local HEAD did not advance through the prepared external consume reconciliation"
        )

    current_checkpoint = PCP.read_json(PCP.checkpoint_path(project_root, current_head_id))
    verification = PCP.verify_checkpoint(
        project_root,
        current_checkpoint,
        expected_project_id=state["project"]["id"],
    )
    if verification["status"] != "exact":
        raise CodexResumeError(
            "Local reconciliation HEAD must verify exact before execution; "
            f"current status={verification['status']}"
        )

    planning_status = prepared.get("planning", {}).get("status")
    if planning_status == "reconciliation-required":
        raise CodexResumeError("Planning reconciliation is still required before execution")
    if planning_status not in {"reconciled", "absent"}:
        raise CodexResumeError(f"Unexpected planning status: {planning_status!r}")

    result = copy.deepcopy(prepared)
    frontier = result.get("resume_brief", {}).get("candidate_frontier")
    result["finalized_at"] = finalized_at or RESOLVER.now_utc()
    result["pcp"]["local_reconciliation_head"] = {
        "checkpoint_id": current_head_id,
        "content_digest": current_checkpoint["verification"]["content_digest"],
        "verification_status": verification["status"],
    }
    result["execution_gate"].update(
        {
            "repository_reconciliation_required": False,
            "planning_reconciliation_required": False,
            "execution_ready": frontier is not None,
            "next_required_action": (
                "execute-candidate-frontier"
                if frontier is not None
                else "no-executable-frontier"
            ),
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the file-reference prepare CLI; GitHub host bindings use library API."""
    parser = argparse.ArgumentParser(
        description="Prepare a downgrade-first Codex resume from an explicit handoff reference"
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--file-root")
    parser.add_argument("--surface", default="codex")
    parser.add_argument("--model")
    parser.add_argument("--confirm-project-mapping", action="store_true")
    parser.add_argument("--planning-reconciliation")
    parser.add_argument("--out")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Prepare a local/file resume; GitHub clients call prepare_from_reference directly."""
    args = build_parser().parse_args(argv)
    try:
        parsed = RESOLVER.TRANSPORTS.parse_reference(args.reference)
        if parsed.kind == "github":
            raise CodexResumeError(
                "CLI GitHub resolution requires a host binding; call prepare_from_reference() "
                "with an authorized GitHub client"
            )
        planning_request = None
        if args.planning_reconciliation:
            planning_request = PLANNING.read_json(pathlib.Path(args.planning_reconciliation))
        result = prepare_from_reference(
            args.root,
            args.reference,
            file_allowed_root=args.file_root,
            surface=args.surface,
            model=args.model,
            confirm_project_mapping=bool(args.confirm_project_mapping),
            planning_reconciliation=planning_request,
        )
        text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
        if args.out:
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    except (
        CodexResumeError,
        RESOLVER.ResumeResolutionError,
        RESOLVER.TransportError,
        PLANNING.PlanningReconciliationError,
    ) as exc:
        print(f"codex-resume: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
