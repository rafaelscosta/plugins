#!/usr/bin/env python3
"""Deterministic repository-aware reconciliation for pcp-planning/1 snapshots.

The reconciler consumes a sealed/digest-addressed planning snapshot plus a
small observation record produced by a FILE/FULL-capable consumer. It never
executes commands, never invents evidence, and never treats a repository
reference as proof by itself. Evidence/reference IDs are provenance supplied by
the current capable surface; this module only enforces deterministic state
transitions and planning-graph invariants.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

FORMAT = "pcp-planning-reconciliation/1"
REPORT_FORMAT = "pcp-planning-reconciliation-report/1"
RECONCILIATION_ID_RE = re.compile(r"^reconcile-[A-Za-z0-9._-]{8,}$")
PLANNING_ID_RE = re.compile(r"^planning-[A-Za-z0-9._-]{8,}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
OPERATIONS = {
    "verify_complete",
    "verify_incomplete",
    "invalidate_verification",
    "start_progress",
    "set_blocked",
    "recheck_dependencies",
}
EVIDENCE_REQUIRED_OPERATIONS = {
    "verify_complete",
    "verify_incomplete",
    "invalidate_verification",
}
PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
STATUS_RANK = {"in_progress": 0, "ready": 1, "accepted": 2}
KIND_RANK = {"task": 0, "story": 1, "epic": 2, "release": 3}
EXECUTABLE_STATUSES = set(STATUS_RANK)
TERMINAL_CHILD_STATUSES = {"verified_done", "superseded", "cancelled"}
PARENT_KIND = {"epic": "release", "story": "epic", "task": "story"}
SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


class PlanningReconciliationError(Exception):
    """Fail-closed planning reconciliation error."""


def _load_bundle():
    """Load the existing planning validator/digest implementation."""
    path = pathlib.Path(__file__).resolve().with_name("handoff_bundle.py")
    spec = importlib.util.spec_from_file_location("pcp_planning_reconcile_bundle", path)
    if spec is None or spec.loader is None:
        raise PlanningReconciliationError("Unable to load handoff_bundle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pcp_planning_reconcile_bundle", module)
    spec.loader.exec_module(module)
    return module


BUNDLE = _load_bundle()


def canonical_bytes(value: Any) -> bytes:
    """Return stable canonical JSON bytes for deterministic IDs."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _valid_time(value: Any) -> bool:
    """Return whether a value is a timezone-aware RFC3339 date-time."""
    if not isinstance(value, str) or RFC3339_RE.fullmatch(value) is None:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _nonempty(value: Any) -> bool:
    """Return whether a value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def _exact_keys(value: dict[str, Any], expected: set[str], where: str) -> list[str]:
    """Validate a strict object field set."""
    errors: list[str] = []
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        errors.append(f"{where} missing required fields: {', '.join(missing)}")
    if extra:
        errors.append(f"{where} contains unknown fields: {', '.join(extra)}")
    return errors


def _string_array(value: Any, where: str) -> list[str]:
    """Validate a unique array of non-empty strings."""
    if not isinstance(value, list):
        return [f"{where} must be an array"]
    errors: list[str] = []
    kept: list[str] = []
    for index, item in enumerate(value):
        if not _nonempty(item):
            errors.append(f"{where}[{index}] must be a non-empty string")
        else:
            kept.append(item)
    if len(kept) != len(set(kept)):
        errors.append(f"{where} must contain unique values")
    return errors


def _secret_paths(value: Any, path: str = "$") -> list[str]:
    """Find obvious secret-like values before they enter durable planning state."""
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            findings.extend(_secret_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_secret_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            findings.append(path)
    return findings


def validate_request(request: dict[str, Any], planning: dict[str, Any]) -> list[str]:
    """Validate the reconciliation request against one exact planning snapshot."""
    errors: list[str] = []
    if not isinstance(request, dict):
        return ["reconciliation request must be an object"]
    errors.extend(
        _exact_keys(
            request,
            {
                "format",
                "reconciliation_id",
                "created_at",
                "project_id",
                "planning_id",
                "planning_digest",
                "observations",
            },
            "reconciliation",
        )
    )
    if request.get("format") != FORMAT:
        errors.append(f"reconciliation.format must be {FORMAT}")
    if not isinstance(request.get("reconciliation_id"), str) or RECONCILIATION_ID_RE.fullmatch(
        str(request.get("reconciliation_id"))
    ) is None:
        errors.append("reconciliation.reconciliation_id has invalid format")
    if not _valid_time(request.get("created_at")):
        errors.append("reconciliation.created_at must be RFC3339 date-time with timezone")
    if not _nonempty(request.get("project_id")):
        errors.append("reconciliation.project_id must be non-empty")
    if not isinstance(request.get("planning_id"), str) or PLANNING_ID_RE.fullmatch(
        str(request.get("planning_id"))
    ) is None:
        errors.append("reconciliation.planning_id has invalid format")
    if not isinstance(request.get("planning_digest"), str) or SHA256_RE.fullmatch(
        str(request.get("planning_digest"))
    ) is None:
        errors.append("reconciliation.planning_digest has invalid format")

    if request.get("project_id") != planning.get("project_id"):
        errors.append("reconciliation.project_id does not match planning.project_id")
    if request.get("planning_id") != planning.get("planning_id"):
        errors.append("reconciliation.planning_id does not match planning.planning_id")
    if request.get("planning_digest") != planning.get("content_digest"):
        errors.append("reconciliation.planning_digest does not match planning.content_digest")

    item_ids = {
        item.get("id")
        for item in planning.get("items", [])
        if isinstance(item, dict) and _nonempty(item.get("id"))
    }
    observations = request.get("observations")
    seen: set[str] = set()
    if not isinstance(observations, list):
        errors.append("reconciliation.observations must be an array")
    else:
        for index, observation in enumerate(observations):
            where = f"reconciliation.observations[{index}]"
            if not isinstance(observation, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(
                _exact_keys(
                    observation,
                    {"item_id", "operation", "evidence_refs", "repository_refs", "reason"},
                    where,
                )
            )
            item_id = observation.get("item_id")
            if not _nonempty(item_id):
                errors.append(f"{where}.item_id must be non-empty")
            elif item_id not in item_ids:
                errors.append(f"{where}.item_id references unknown planning item: {item_id}")
            elif item_id in seen:
                errors.append(f"duplicate reconciliation observation for item: {item_id}")
            else:
                seen.add(item_id)
            operation = observation.get("operation")
            if operation not in OPERATIONS:
                errors.append(f"{where}.operation is invalid")
            errors.extend(_string_array(observation.get("evidence_refs"), f"{where}.evidence_refs"))
            errors.extend(_string_array(observation.get("repository_refs"), f"{where}.repository_refs"))
            if operation in EVIDENCE_REQUIRED_OPERATIONS and isinstance(
                observation.get("evidence_refs"), list
            ) and not observation.get("evidence_refs"):
                errors.append(f"{where}.{operation} requires at least one evidence_refs entry")
            if not _nonempty(observation.get("reason")):
                errors.append(f"{where}.reason must be non-empty")

    secret_paths = _secret_paths(request)
    if secret_paths:
        errors.append("secret-like content detected at: " + ", ".join(secret_paths))
    return errors


def _cycle_errors(graph: dict[str, list[str]], label: str) -> list[str]:
    """Return deterministic cycle findings for a directed graph."""
    visiting: set[str] = set()
    visited: set[str] = set()
    errors: list[str] = []

    def visit(node: str, trail: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            start = trail.index(node) if node in trail else 0
            errors.append(f"{label} cycle: " + " -> ".join(trail[start:] + [node]))
            return
        visiting.add(node)
        for target in graph.get(node, []):
            if target in graph:
                visit(target, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return errors


def validate_planning_graph(planning: dict[str, Any]) -> list[str]:
    """Validate hierarchy and dependency invariants not expressed by the schema."""
    errors: list[str] = []
    items = [item for item in planning.get("items", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in items if _nonempty(item.get("id"))}
    parent_graph: dict[str, list[str]] = {}
    dependency_graph: dict[str, list[str]] = {}
    for item in items:
        item_id = str(item.get("id"))
        parent_id = item.get("parent_id")
        if parent_id is not None:
            parent = by_id.get(str(parent_id))
            if parent is None:
                errors.append(f"planning item {item_id!r} has unknown parent_id {parent_id!r}")
            else:
                expected_parent = PARENT_KIND.get(str(item.get("kind")))
                if expected_parent is None:
                    errors.append(f"release item {item_id!r} must not have a parent")
                elif parent.get("kind") != expected_parent:
                    errors.append(
                        f"planning item {item_id!r} kind={item.get('kind')} requires parent kind={expected_parent}, found {parent.get('kind')}"
                    )
                parent_graph[item_id] = [str(parent_id)]
        elif item.get("kind") != "release":
            errors.append(f"planning item {item_id!r} kind={item.get('kind')} requires a parent_id")

        dependencies = [str(dep) for dep in item.get("depends_on", []) if isinstance(dep, str)]
        if item_id in dependencies:
            errors.append(f"planning item {item_id!r} cannot depend on itself")
        unknown = [dep for dep in dependencies if dep not in by_id]
        if unknown:
            errors.append(
                f"planning item {item_id!r} depends_on unknown items: " + ", ".join(sorted(unknown))
            )
        dependency_graph[item_id] = [dep for dep in dependencies if dep in by_id]

    errors.extend(_cycle_errors(parent_graph, "planning parent"))
    errors.extend(_cycle_errors(dependency_graph, "planning dependency"))
    return errors


def _merge_unique(current: list[str], added: list[str]) -> list[str]:
    """Append provenance references without duplicates."""
    result = list(current)
    for value in added:
        if value not in result:
            result.append(value)
    return result


def _dependencies_ready(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    """Return whether every declared dependency is currently verified_done."""
    return all(by_id[dep].get("status") == "verified_done" for dep in item.get("depends_on", []))


def _ready_or_blocked(item: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    """Return ready when dependencies are proven, otherwise blocked."""
    return "ready" if _dependencies_ready(item, by_id) else "blocked"


def _transition(
    *,
    item_id: str,
    from_status: str,
    to_status: str,
    classification: str,
    evidence_refs: list[str],
    repository_refs: list[str],
    reason: str,
) -> dict[str, Any]:
    """Build one report transition record."""
    return {
        "item_id": item_id,
        "from_status": from_status,
        "to_status": to_status,
        "classification": classification,
        "evidence_refs": list(evidence_refs),
        "repository_refs": list(repository_refs),
        "reason": reason,
    }


def _apply_origin(item: dict[str, Any], request: dict[str, Any]) -> None:
    """Mark a changed planning item as repository-reconciled state."""
    item["origin"] = {
        "kind": "repository_reconciliation",
        "ref": request["reconciliation_id"],
        "observed_at": request["created_at"],
    }


def _frontier(planning: dict[str, Any]) -> dict[str, Any] | None:
    """Select the highest-priority dependency-ready executable leaf."""
    items = [item for item in planning.get("items", []) if isinstance(item, dict)]
    by_id = {item["id"]: item for item in items}
    active_children: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        parent_id = item.get("parent_id")
        if parent_id is not None and item.get("status") not in TERMINAL_CHILD_STATUSES:
            active_children.setdefault(parent_id, []).append(item)

    candidates: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for index, item in enumerate(items):
        if item.get("status") not in EXECUTABLE_STATUSES:
            continue
        if active_children.get(item["id"]):
            continue
        if not _dependencies_ready(item, by_id):
            continue
        rank = (
            PRIORITY_RANK[item["priority"]],
            STATUS_RANK[item["status"]],
            KIND_RANK[item["kind"]],
            index,
        )
        candidates.append((rank, item))
    if not candidates:
        return None
    item = min(candidates, key=lambda pair: pair[0])[1]
    return {
        "item_id": item["id"],
        "title": item["title"],
        "kind": item["kind"],
        "status": item["status"],
        "priority": item["priority"],
    }


def reconcile(
    planning: dict[str, Any],
    request: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one deterministic reconciliation transaction to a planning snapshot."""
    planning_errors = BUNDLE.validate_planning_snapshot(planning)
    if planning_errors:
        raise PlanningReconciliationError(
            "Invalid planning snapshot:\n- " + "\n- ".join(planning_errors)
        )
    recorded_digest = planning.get("content_digest")
    if not isinstance(recorded_digest, str) or not recorded_digest:
        raise PlanningReconciliationError("Planning snapshot requires content_digest")
    computed_digest = BUNDLE.compute_planning_digest(planning)
    if recorded_digest != computed_digest:
        raise PlanningReconciliationError(
            "Planning snapshot content_digest does not match canonical bytes"
        )
    graph_errors = validate_planning_graph(planning)
    if graph_errors:
        raise PlanningReconciliationError(
            "Invalid planning graph:\n- " + "\n- ".join(graph_errors)
        )
    request_errors = validate_request(request, planning)
    if request_errors:
        raise PlanningReconciliationError(
            "Invalid planning reconciliation:\n- " + "\n- ".join(request_errors)
        )

    result = copy.deepcopy(planning)
    items = [item for item in result["items"] if isinstance(item, dict)]
    by_id = {item["id"]: item for item in items}
    prior_by_id = {
        item["id"]: copy.deepcopy(item)
        for item in planning["items"]
        if isinstance(item, dict)
    }
    observations = {obs["item_id"]: obs for obs in request["observations"]}
    transition_by_id: dict[str, dict[str, Any]] = {}
    deferred_readiness: dict[str, tuple[str, str]] = {}

    # Phase 1: establish completion truth first so later dependency decisions are
    # independent of observation order.
    for item_id, observation in observations.items():
        item = by_id[item_id]
        prior_status = prior_by_id[item_id]["status"]
        operation = observation["operation"]
        if operation == "verify_complete":
            allowed = {"accepted", "ready", "in_progress", "blocked", "reported_done", "verified_done"}
            if prior_status not in allowed:
                raise PlanningReconciliationError(
                    f"verify_complete is not valid from status {prior_status!r} for {item_id}"
                )
            item["status"] = "verified_done"
            item["evidence_refs"] = list(observation["evidence_refs"])
            item["repository_refs"] = _merge_unique(
                item.get("repository_refs", []), observation["repository_refs"]
            )
            _apply_origin(item, request)
            classification = (
                "verification-refreshed"
                if prior_status in {"reported_done", "verified_done"}
                else "stale-plan"
            )
            transition_by_id[item_id] = _transition(
                item_id=item_id,
                from_status=prior_status,
                to_status="verified_done",
                classification=classification,
                evidence_refs=observation["evidence_refs"],
                repository_refs=observation["repository_refs"],
                reason=observation["reason"],
            )
        elif operation == "verify_incomplete":
            if prior_status not in {"reported_done", "verified_done"}:
                raise PlanningReconciliationError(
                    f"verify_incomplete requires reported_done or verified_done for {item_id}"
                )
            item["status"] = "accepted"  # provisional until dependencies are evaluated
            item["evidence_refs"] = list(observation["evidence_refs"])
            item["repository_refs"] = _merge_unique(
                item.get("repository_refs", []), observation["repository_refs"]
            )
            _apply_origin(item, request)
            deferred_readiness[item_id] = ("incomplete-implementation", observation["reason"])
        elif operation == "invalidate_verification":
            if prior_status != "verified_done":
                raise PlanningReconciliationError(
                    f"invalidate_verification requires verified_done for {item_id}"
                )
            item["status"] = "accepted"  # provisional until dependencies are evaluated
            item["evidence_refs"] = list(observation["evidence_refs"])
            item["repository_refs"] = _merge_unique(
                item.get("repository_refs", []), observation["repository_refs"]
            )
            _apply_origin(item, request)
            deferred_readiness[item_id] = ("invalidated-verification", observation["reason"])

    # Phase 2: resolve provisional re-opened states using the final completion
    # truth from phase 1.
    for item_id, (classification, reason) in deferred_readiness.items():
        observation = observations[item_id]
        item = by_id[item_id]
        target = _ready_or_blocked(item, by_id)
        item["status"] = target
        transition_by_id[item_id] = _transition(
            item_id=item_id,
            from_status=prior_by_id[item_id]["status"],
            to_status=target,
            classification=classification,
            evidence_refs=observation["evidence_refs"],
            repository_refs=observation["repository_refs"],
            reason=reason,
        )

    # Phase 3: explicit progress/blocking operations.
    for item_id, observation in observations.items():
        operation = observation["operation"]
        if operation not in {"start_progress", "set_blocked"}:
            continue
        item = by_id[item_id]
        prior_status = prior_by_id[item_id]["status"]
        if operation == "start_progress":
            if prior_status not in {"accepted", "ready", "in_progress"}:
                raise PlanningReconciliationError(
                    f"start_progress is not valid from status {prior_status!r} for {item_id}"
                )
            if not _dependencies_ready(item, by_id):
                raise PlanningReconciliationError(
                    f"start_progress requires all dependencies verified_done for {item_id}"
                )
            target = "in_progress"
            classification = "no-change" if prior_status == target else "progress-started"
        else:
            if prior_status not in {"accepted", "ready", "in_progress", "blocked"}:
                raise PlanningReconciliationError(
                    f"set_blocked is not valid from status {prior_status!r} for {item_id}"
                )
            target = "blocked"
            classification = "no-change" if prior_status == target else "blocked"
        item["status"] = target
        item["repository_refs"] = _merge_unique(
            item.get("repository_refs", []), observation["repository_refs"]
        )
        if observation["evidence_refs"]:
            item["evidence_refs"] = _merge_unique(
                item.get("evidence_refs", []), observation["evidence_refs"]
            )
        if target != prior_status:
            _apply_origin(item, request)
        transition_by_id[item_id] = _transition(
            item_id=item_id,
            from_status=prior_status,
            to_status=target,
            classification=classification,
            evidence_refs=observation["evidence_refs"],
            repository_refs=observation["repository_refs"],
            reason=observation["reason"],
        )

    # Phase 4: dependency rechecks happen after all completion/progress changes.
    for item_id, observation in observations.items():
        if observation["operation"] != "recheck_dependencies":
            continue
        item = by_id[item_id]
        prior_status = prior_by_id[item_id]["status"]
        if prior_status not in {"accepted", "ready", "in_progress", "blocked"}:
            raise PlanningReconciliationError(
                f"recheck_dependencies is not valid from status {prior_status!r} for {item_id}"
            )
        dependencies = item.get("depends_on", [])
        if prior_status == "blocked" and not dependencies:
            raise PlanningReconciliationError(
                f"blocked item {item_id} has no dependency blocker to recheck"
            )
        ready = _dependencies_ready(item, by_id)
        if ready:
            if prior_status == "blocked":
                target, classification = "ready", "dependency-unblocked"
            elif prior_status == "accepted":
                target, classification = "ready", "dependency-ready"
            elif prior_status == "ready":
                target, classification = "ready", "no-change"
            else:
                target, classification = "in_progress", "no-change"
        else:
            target = "blocked"
            classification = (
                "dependency-invalidated"
                if prior_status in {"ready", "in_progress"}
                else "dependency-still-blocked"
            )
        item["status"] = target
        item["repository_refs"] = _merge_unique(
            item.get("repository_refs", []), observation["repository_refs"]
        )
        if observation["evidence_refs"]:
            item["evidence_refs"] = _merge_unique(
                item.get("evidence_refs", []), observation["evidence_refs"]
            )
        if target != prior_status:
            _apply_origin(item, request)
        transition_by_id[item_id] = _transition(
            item_id=item_id,
            from_status=prior_status,
            to_status=target,
            classification=classification,
            evidence_refs=observation["evidence_refs"],
            repository_refs=observation["repository_refs"],
            reason=observation["reason"],
        )

    # A ready/in-progress item can never remain executable after one of its
    # dependencies lost verified completion, even when the caller omitted an
    # explicit dependency recheck for that item.
    for item in items:
        item_id = item["id"]
        if item_id in observations:
            continue
        if item.get("status") not in {"ready", "in_progress"}:
            continue
        if _dependencies_ready(item, by_id):
            continue
        prior_status = prior_by_id[item_id]["status"]
        item["status"] = "blocked"
        _apply_origin(item, request)
        transition_by_id[item_id] = _transition(
            item_id=item_id,
            from_status=prior_status,
            to_status="blocked",
            classification="dependency-invalidated",
            evidence_refs=[],
            repository_refs=[],
            reason="A dependency is no longer verified_done after reconciliation.",
        )

    # Verified aggregate parents cannot remain verified when an active child is
    # reopened. Propagate invalidation upward until hierarchy state is coherent.
    changed = True
    while changed:
        changed = False
        children: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if item.get("parent_id") is not None:
                children.setdefault(item["parent_id"], []).append(item)
        for item in items:
            if item.get("status") != "verified_done":
                continue
            active = [
                child
                for child in children.get(item["id"], [])
                if child.get("status") not in TERMINAL_CHILD_STATUSES
            ]
            if not active:
                continue
            item_id = item["id"]
            prior_status = prior_by_id[item_id]["status"]
            target = _ready_or_blocked(item, by_id)
            item["status"] = target
            _apply_origin(item, request)
            child_transitions = [
                transition_by_id.get(child["id"])
                for child in active
                if transition_by_id.get(child["id"]) is not None
            ]
            evidence = []
            repositories = []
            for transition in child_transitions:
                evidence = _merge_unique(evidence, transition["evidence_refs"])
                repositories = _merge_unique(repositories, transition["repository_refs"])
            transition_by_id[item_id] = _transition(
                item_id=item_id,
                from_status=prior_status,
                to_status=target,
                classification="invalidated-verification",
                evidence_refs=evidence,
                repository_refs=repositories,
                reason="Verified aggregate parent contains a child reopened by reconciliation.",
            )
            changed = True

    # Revalidate the graph/result before assigning a fresh digest.
    result["planning_id"] = "planning-reconciled-" + hashlib.sha256(
        canonical_bytes(
            {
                "prior_id": planning["planning_id"],
                "prior_digest": recorded_digest,
                "request": request,
            }
        )
    ).hexdigest()[:20]
    result["created_at"] = request["created_at"]
    result["content_digest"] = None
    result_errors = BUNDLE.validate_planning_snapshot(result)
    if result_errors:
        raise PlanningReconciliationError(
            "Reconciliation emitted invalid planning snapshot:\n- "
            + "\n- ".join(result_errors)
        )
    result_graph_errors = validate_planning_graph(result)
    if result_graph_errors:
        raise PlanningReconciliationError(
            "Reconciliation emitted invalid planning graph:\n- "
            + "\n- ".join(result_graph_errors)
        )
    result["content_digest"] = BUNDLE.compute_planning_digest(result)

    transitions = [
        transition_by_id[item["id"]]
        for item in items
        if item["id"] in transition_by_id
    ]
    report = {
        "format": REPORT_FORMAT,
        "reconciliation_id": request["reconciliation_id"],
        "created_at": request["created_at"],
        "project_id": request["project_id"],
        "prior_planning": {
            "id": planning["planning_id"],
            "digest": recorded_digest,
        },
        "result_planning": {
            "id": result["planning_id"],
            "digest": result["content_digest"],
        },
        "transitions": transitions,
        "frontier": _frontier(result),
    }
    return result, report


def read_json(path: pathlib.Path) -> dict[str, Any]:
    """Read one JSON object with stable errors."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanningReconciliationError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PlanningReconciliationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PlanningReconciliationError(f"Expected JSON object in {path}")
    return value


def atomic_write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    """Write JSON using a sibling temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temp = path.with_name(f".{path.name}.{hashlib.sha256(raw.encode()).hexdigest()[:12]}.tmp")
    try:
        temp.write_text(raw, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the supported planning reconciliation CLI."""
    parser = argparse.ArgumentParser(
        description="Reconcile pcp-planning/1 against current repository observations"
    )
    parser.add_argument("--planning", required=True, help="Prior pcp-planning/1 JSON")
    parser.add_argument("--input", required=True, help="pcp-planning-reconciliation/1 JSON")
    parser.add_argument("--planning-out", required=True)
    parser.add_argument("--report-out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one deterministic planning reconciliation transaction."""
    args = build_parser().parse_args(argv)
    try:
        planning = read_json(pathlib.Path(args.planning))
        request = read_json(pathlib.Path(args.input))
        result, report = reconcile(planning, request)
        atomic_write_json(pathlib.Path(args.planning_out), result)
        atomic_write_json(pathlib.Path(args.report_out), report)
        print(
            json.dumps(
                {
                    "status": "reconciled",
                    "reconciliation_id": report["reconciliation_id"],
                    "prior_planning_id": report["prior_planning"]["id"],
                    "result_planning_id": report["result_planning"]["id"],
                    "result_planning_digest": report["result_planning"]["digest"],
                    "transitions": len(report["transitions"]),
                    "frontier": report["frontier"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except PlanningReconciliationError as exc:
        print(f"planning-reconcile: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
