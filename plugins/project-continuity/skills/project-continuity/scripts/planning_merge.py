#!/usr/bin/env python3
"""Deterministic incremental planning merge for Session Compiler.

Silence is not cancellation. A new conversation delta may update known planning
items or add new ones, but accepted prior work is preserved unless an explicit
current item supersedes/cancels/updates it.
"""

from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
from typing import Any


class PlanningMergeError(Exception):
    pass


def _load_bundle():
    path = pathlib.Path(__file__).resolve().with_name("handoff_bundle.py")
    spec = importlib.util.spec_from_file_location("pcp_planning_merge_bundle", path)
    if spec is None or spec.loader is None:
        raise PlanningMergeError("Unable to load handoff_bundle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pcp_planning_merge_bundle", module)
    spec.loader.exec_module(module)
    return module


BUNDLE = _load_bundle()


def _prior_ref(snapshot: dict[str, Any]) -> str:
    source = snapshot.get("source_checkpoint")
    if isinstance(source, dict) and source.get("id"):
        return str(source["id"])
    return str(snapshot.get("planning_id") or "prior-planning")


def _origin_from_prior(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "prior_checkpoint", "ref": _prior_ref(snapshot)}


def _ir_item_from_prior(item: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "status": item["status"],
        "parent_id": item.get("parent_id"),
        "priority": item["priority"],
        "depends_on": list(item.get("depends_on", [])),
        "acceptance_criteria": list(item.get("acceptance_criteria", [])),
        "origin": _origin_from_prior(snapshot),
        "supersedes": list(item.get("supersedes", [])),
        "evidence_refs": list(item.get("evidence_refs", [])),
        "repository_refs": list(item.get("repository_refs", [])),
    }


def _ir_decision_from_prior(decision: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": decision["id"],
        "statement": decision["statement"],
        "status": decision["status"],
        "confidence": "reported",
        "origin": _origin_from_prior(snapshot),
        "supersedes": list(decision.get("supersedes", [])),
    }


def merge_compilation_with_prior(
    compilation: dict[str, Any],
    prior_planning: dict[str, Any],
) -> dict[str, Any]:
    """Return a full compilation IR with prior planning preserved.

    The current compilation is treated as a delta for planning items/decisions.
    Same-ID current entries replace prior entries. New entries append. Prior
    entries omitted from the delta remain. Explicit `supersedes` references mark
    preserved prior entries superseded rather than deleting them.
    """

    if not isinstance(compilation, dict):
        raise PlanningMergeError("Compilation delta must be an object")
    if not isinstance(prior_planning, dict):
        raise PlanningMergeError("Prior planning snapshot must be an object")

    prior_errors = BUNDLE.validate_planning_snapshot(prior_planning)
    if prior_errors:
        raise PlanningMergeError("Invalid prior planning snapshot:\n- " + "\n- ".join(prior_errors))

    project = compilation.get("project")
    if not isinstance(project, dict) or project.get("id") != prior_planning.get("project_id"):
        raise PlanningMergeError(
            "Compilation project.id does not match prior planning project_id"
        )

    merged = copy.deepcopy(compilation)
    planning = merged.get("planning")
    if not isinstance(planning, dict):
        raise PlanningMergeError("Compilation delta planning must be an object")
    current_items = planning.get("items")
    if not isinstance(current_items, list):
        raise PlanningMergeError("Compilation delta planning.items must be an array")
    current_decisions = merged.get("decisions")
    if not isinstance(current_decisions, list):
        raise PlanningMergeError("Compilation delta decisions must be an array")

    prior_items = [_ir_item_from_prior(item, prior_planning) for item in prior_planning.get("items", [])]
    prior_decisions = [
        _ir_decision_from_prior(decision, prior_planning)
        for decision in prior_planning.get("decisions", [])
    ]

    item_order = [item["id"] for item in prior_items]
    items_by_id = {item["id"]: item for item in prior_items}
    current_item_ids: set[str] = set()
    for item in current_items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item.get("id"):
            raise PlanningMergeError("Every current planning delta item requires a non-empty id")
        item_id = item["id"]
        if item_id in current_item_ids:
            raise PlanningMergeError(f"Duplicate current planning delta item id: {item_id}")
        current_item_ids.add(item_id)
        if item_id not in items_by_id:
            item_order.append(item_id)
        items_by_id[item_id] = copy.deepcopy(item)

    explicitly_superseded_items = {
        target
        for item in current_items
        if isinstance(item, dict)
        for target in item.get("supersedes", []) or []
        if isinstance(target, str)
    }
    for target in explicitly_superseded_items:
        if target in items_by_id and target not in current_item_ids:
            items_by_id[target]["status"] = "superseded"

    decision_order = [decision["id"] for decision in prior_decisions]
    decisions_by_id = {decision["id"]: decision for decision in prior_decisions}
    current_decision_ids: set[str] = set()
    for decision in current_decisions:
        if not isinstance(decision, dict) or not isinstance(decision.get("id"), str) or not decision.get("id"):
            raise PlanningMergeError("Every current decision delta requires a non-empty id")
        decision_id = decision["id"]
        if decision_id in current_decision_ids:
            raise PlanningMergeError(f"Duplicate current decision delta id: {decision_id}")
        current_decision_ids.add(decision_id)
        if decision_id not in decisions_by_id:
            decision_order.append(decision_id)
        decisions_by_id[decision_id] = copy.deepcopy(decision)

    explicitly_superseded_decisions = {
        target
        for decision in current_decisions
        if isinstance(decision, dict)
        for target in decision.get("supersedes", []) or []
        if isinstance(target, str)
    }
    for target in explicitly_superseded_decisions:
        if target in decisions_by_id and target not in current_decision_ids:
            decisions_by_id[target]["status"] = "superseded"

    planning["items"] = [items_by_id[item_id] for item_id in item_order]
    if planning.get("vision") is None:
        planning["vision"] = prior_planning.get("vision")
    merged["decisions"] = [decisions_by_id[decision_id] for decision_id in decision_order]

    if merged.get("prior_checkpoint") is None:
        source = prior_planning.get("source_checkpoint")
        if isinstance(source, dict) and source.get("id") and source.get("digest"):
            merged["prior_checkpoint"] = {
                "id": source["id"],
                "digest": source["digest"],
            }
    else:
        source = prior_planning.get("source_checkpoint")
        if isinstance(source, dict):
            prior = merged["prior_checkpoint"]
            if prior.get("id") != source.get("id") or prior.get("digest") != source.get("digest"):
                raise PlanningMergeError(
                    "Compilation prior_checkpoint conflicts with prior planning source_checkpoint"
                )

    return merged
