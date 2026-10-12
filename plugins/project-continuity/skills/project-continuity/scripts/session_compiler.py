#!/usr/bin/env python3
"""Deterministic compiler from Session Compilation IR to PCP/1 portable state.

Semantic extraction is performed by the agent. This module owns the mechanical
boundary: validate the extracted IR, preserve accepted long-horizon work, emit a
PCP/1 PORTABLE checkpoint plus pcp-planning/1 sidecar, and optionally seal the
portable checkpoint for digest-bearing remote transport.

The compiler deliberately imports PCP validation/digest logic from continuity.py
and planning validation/digest logic from handoff_bundle.py. It does not create a
second evidence or canonical-hash implementation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

FORMAT = "pcp-session-compilation/1"
PLANNING_FORMAT = "pcp-planning/1"
EXECUTABLE_STATUSES = {"accepted", "ready", "in_progress"}
PLANNING_STATUSES = {
    "proposed",
    "accepted",
    "ready",
    "in_progress",
    "blocked",
    "reported_done",
    "verified_done",
    "superseded",
    "cancelled",
}
PLANNING_KINDS = {"release", "epic", "story", "task"}
PRIORITIES = {"critical", "high", "medium", "low"}
DECISION_STATUSES = {"accepted", "superseded"}
CONFIDENCE = {"reported", "inferred"}
ORIGIN_KINDS = {
    "current_user",
    "conversation",
    "prior_checkpoint",
    "repository_evidence",
    "artifact",
    "inference",
    "unknown",
}
COMPILATION_ID_RE = re.compile(r"^compilation-[A-Za-z0-9._-]{8,}$")
CHECKPOINT_ID_RE = re.compile(r"^pcp-[A-Za-z0-9._-]{8,}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
SECRET_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


class SessionCompilationError(Exception):
    pass


def _load_sibling(name: str, filename: str):
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SessionCompilationError(f"Unable to load required sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


PCP = _load_sibling("pcp_session_compiler_core", "continuity.py")
BUNDLE = _load_sibling("pcp_session_compiler_bundle", "handoff_bundle.py")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_array(value: Any, where: str, *, unique: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, list):
        return [f"{where} must be an array"]
    kept: list[str] = []
    for i, item in enumerate(value):
        if not _nonempty(item):
            errors.append(f"{where}[{i}] must be a non-empty string")
        else:
            kept.append(item)
    if unique and len(kept) != len(set(kept)):
        errors.append(f"{where} must contain unique values")
    return errors


def _exact_keys(value: dict[str, Any], expected: set[str], where: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        errors.append(f"{where} missing required fields: {', '.join(missing)}")
    if extra:
        errors.append(f"{where} contains unknown fields: {', '.join(extra)}")
    return errors


def _valid_time(value: Any) -> bool:
    if not isinstance(value, str) or RFC3339_RE.fullmatch(value) is None:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _secret_paths(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            findings.extend(_secret_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            findings.extend(_secret_paths(child, f"{path}[{i}]"))
    elif isinstance(value, str):
        if any(pattern.search(value) for pattern in SECRET_PATTERNS):
            findings.append(path)
    return findings


def _validate_origin(value: Any, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where} must be an object"]
    errors = _exact_keys(value, {"kind", "ref"}, where)
    if value.get("kind") not in ORIGIN_KINDS:
        errors.append(f"{where}.kind is invalid")
    if value.get("ref") is not None and not _nonempty(value.get("ref")):
        errors.append(f"{where}.ref must be null or non-empty")
    return errors


def _dependency_cycles(items: list[dict[str, Any]]) -> list[str]:
    graph = {
        str(item["id"]): [str(dep) for dep in item.get("depends_on", [])]
        for item in items
        if isinstance(item, dict) and _nonempty(item.get("id"))
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[str] = []

    def visit(node: str, trail: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            try:
                start = trail.index(node)
                cycle = trail[start:] + [node]
            except ValueError:
                cycle = trail + [node]
            cycles.append(" -> ".join(cycle))
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, trail + [node])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])
    return cycles


def validate_compilation(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["session compilation must be an object"]
    expected = {
        "format",
        "compilation_id",
        "created_at",
        "project",
        "producer",
        "prior_checkpoint",
        "objective",
        "decisions",
        "findings",
        "planning",
        "blockers",
        "risks",
        "uncertainties",
        "next_frontier",
    }
    errors.extend(_exact_keys(data, expected, "compilation"))
    if data.get("format") != FORMAT:
        errors.append(f"compilation.format must be {FORMAT}")
    if not isinstance(data.get("compilation_id"), str) or COMPILATION_ID_RE.fullmatch(str(data.get("compilation_id"))) is None:
        errors.append("compilation.compilation_id has invalid format")
    if not _valid_time(data.get("created_at")):
        errors.append("compilation.created_at must be RFC3339 date-time with timezone")

    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("compilation.project must be an object")
    else:
        errors.extend(_exact_keys(project, {"id", "name", "repository"}, "compilation.project"))
        if not _nonempty(project.get("id")):
            errors.append("compilation.project.id must be non-empty")
        if not _nonempty(project.get("name")):
            errors.append("compilation.project.name must be non-empty")
        if project.get("repository") is not None and not _nonempty(project.get("repository")):
            errors.append("compilation.project.repository must be null or non-empty")

    producer = data.get("producer")
    if not isinstance(producer, dict):
        errors.append("compilation.producer must be an object")
    else:
        errors.extend(_exact_keys(producer, {"surface", "model", "session_ref"}, "compilation.producer"))
        if not _nonempty(producer.get("surface")):
            errors.append("compilation.producer.surface must be non-empty")
        for field in ("model", "session_ref"):
            if producer.get(field) is not None and not _nonempty(producer.get(field)):
                errors.append(f"compilation.producer.{field} must be null or non-empty")

    prior = data.get("prior_checkpoint")
    if prior is not None:
        if not isinstance(prior, dict):
            errors.append("compilation.prior_checkpoint must be null or object")
        else:
            errors.extend(_exact_keys(prior, {"id", "digest"}, "compilation.prior_checkpoint"))
            if not isinstance(prior.get("id"), str) or CHECKPOINT_ID_RE.fullmatch(str(prior.get("id"))) is None:
                errors.append("compilation.prior_checkpoint.id has invalid format")
            if not isinstance(prior.get("digest"), str) or SHA256_RE.fullmatch(str(prior.get("digest"))) is None:
                errors.append("compilation.prior_checkpoint.digest has invalid format")

    objective = data.get("objective")
    if not isinstance(objective, dict):
        errors.append("compilation.objective must be an object")
    else:
        errors.extend(_exact_keys(objective, {"current", "definition_of_done"}, "compilation.objective"))
        if not _nonempty(objective.get("current")):
            errors.append("compilation.objective.current must be non-empty")
        errors.extend(_string_array(objective.get("definition_of_done"), "compilation.objective.definition_of_done"))

    decisions = data.get("decisions")
    decision_ids: set[str] = set()
    if not isinstance(decisions, list):
        errors.append("compilation.decisions must be an array")
    else:
        for i, decision in enumerate(decisions):
            where = f"compilation.decisions[{i}]"
            if not isinstance(decision, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(_exact_keys(decision, {"id", "statement", "status", "confidence", "origin", "supersedes"}, where))
            did = decision.get("id")
            if not _nonempty(did):
                errors.append(f"{where}.id must be non-empty")
            elif did in decision_ids:
                errors.append(f"duplicate decision id: {did}")
            else:
                decision_ids.add(did)
            if not _nonempty(decision.get("statement")):
                errors.append(f"{where}.statement must be non-empty")
            if decision.get("status") not in DECISION_STATUSES:
                errors.append(f"{where}.status is invalid")
            if decision.get("confidence") not in CONFIDENCE:
                errors.append(f"{where}.confidence is invalid")
            errors.extend(_validate_origin(decision.get("origin"), f"{where}.origin"))
            errors.extend(_string_array(decision.get("supersedes"), f"{where}.supersedes", unique=True))

    findings = data.get("findings")
    finding_ids: set[str] = set()
    if not isinstance(findings, list):
        errors.append("compilation.findings must be an array")
    else:
        for i, finding in enumerate(findings):
            where = f"compilation.findings[{i}]"
            if not isinstance(finding, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(_exact_keys(finding, {"id", "statement", "confidence", "origin"}, where))
            fid = finding.get("id")
            if not _nonempty(fid):
                errors.append(f"{where}.id must be non-empty")
            elif fid in finding_ids:
                errors.append(f"duplicate finding id: {fid}")
            else:
                finding_ids.add(fid)
            if not _nonempty(finding.get("statement")):
                errors.append(f"{where}.statement must be non-empty")
            if finding.get("confidence") not in CONFIDENCE:
                errors.append(f"{where}.confidence is invalid")
            errors.extend(_validate_origin(finding.get("origin"), f"{where}.origin"))

    planning = data.get("planning")
    planning_items: list[dict[str, Any]] = []
    item_ids: set[str] = set()
    if not isinstance(planning, dict):
        errors.append("compilation.planning must be an object")
    else:
        errors.extend(_exact_keys(planning, {"vision", "items"}, "compilation.planning"))
        if planning.get("vision") is not None and not isinstance(planning.get("vision"), str):
            errors.append("compilation.planning.vision must be string or null")
        raw_items = planning.get("items")
        if not isinstance(raw_items, list):
            errors.append("compilation.planning.items must be an array")
        else:
            planning_items = [item for item in raw_items if isinstance(item, dict)]
            for i, item in enumerate(raw_items):
                where = f"compilation.planning.items[{i}]"
                if not isinstance(item, dict):
                    errors.append(f"{where} must be an object")
                    continue
                expected_item = {
                    "id", "kind", "title", "status", "parent_id", "priority",
                    "depends_on", "acceptance_criteria", "origin", "supersedes",
                    "evidence_refs", "repository_refs",
                }
                errors.extend(_exact_keys(item, expected_item, where))
                iid = item.get("id")
                if not _nonempty(iid):
                    errors.append(f"{where}.id must be non-empty")
                elif iid in item_ids:
                    errors.append(f"duplicate planning item id: {iid}")
                else:
                    item_ids.add(iid)
                if item.get("kind") not in PLANNING_KINDS:
                    errors.append(f"{where}.kind is invalid")
                if not _nonempty(item.get("title")):
                    errors.append(f"{where}.title must be non-empty")
                if item.get("status") not in PLANNING_STATUSES:
                    errors.append(f"{where}.status is invalid")
                if item.get("parent_id") is not None and not _nonempty(item.get("parent_id")):
                    errors.append(f"{where}.parent_id must be null or non-empty")
                if item.get("priority") not in PRIORITIES:
                    errors.append(f"{where}.priority is invalid")
                for field in ("depends_on", "supersedes", "evidence_refs", "repository_refs"):
                    errors.extend(_string_array(item.get(field), f"{where}.{field}", unique=True))
                errors.extend(_string_array(item.get("acceptance_criteria"), f"{where}.acceptance_criteria"))
                errors.extend(_validate_origin(item.get("origin"), f"{where}.origin"))
                if item.get("status") == "verified_done" and isinstance(item.get("evidence_refs"), list) and not item.get("evidence_refs"):
                    errors.append(f"{where}.verified_done requires evidence_refs")

    for i, item in enumerate(planning_items):
        where = f"compilation.planning.items[{i}]"
        parent = item.get("parent_id")
        if parent is not None and parent not in item_ids:
            errors.append(f"{where}.parent_id references unknown planning item: {parent}")
        for dep in item.get("depends_on", []) if isinstance(item.get("depends_on"), list) else []:
            if dep not in item_ids:
                errors.append(f"{where}.depends_on references unknown planning item: {dep}")
    for cycle in _dependency_cycles(planning_items):
        errors.append(f"planning dependency cycle: {cycle}")

    blockers = data.get("blockers")
    blocker_ids: set[str] = set()
    if not isinstance(blockers, list):
        errors.append("compilation.blockers must be an array")
    else:
        for i, blocker in enumerate(blockers):
            where = f"compilation.blockers[{i}]"
            if not isinstance(blocker, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(_exact_keys(blocker, {"id", "title", "priority", "acceptance_criteria", "depends_on"}, where))
            bid = blocker.get("id")
            if not _nonempty(bid):
                errors.append(f"{where}.id must be non-empty")
            elif bid in blocker_ids:
                errors.append(f"duplicate blocker id: {bid}")
            else:
                blocker_ids.add(bid)
            if not _nonempty(blocker.get("title")):
                errors.append(f"{where}.title must be non-empty")
            if blocker.get("priority") not in PRIORITIES:
                errors.append(f"{where}.priority is invalid")
            errors.extend(_string_array(blocker.get("acceptance_criteria"), f"{where}.acceptance_criteria"))
            errors.extend(_string_array(blocker.get("depends_on"), f"{where}.depends_on", unique=True))

    risks = data.get("risks")
    risk_ids: set[str] = set()
    if not isinstance(risks, list):
        errors.append("compilation.risks must be an array")
    else:
        for i, risk in enumerate(risks):
            where = f"compilation.risks[{i}]"
            if not isinstance(risk, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(_exact_keys(risk, {"id", "description", "severity", "mitigation"}, where))
            rid = risk.get("id")
            if not _nonempty(rid):
                errors.append(f"{where}.id must be non-empty")
            elif rid in risk_ids:
                errors.append(f"duplicate risk id: {rid}")
            else:
                risk_ids.add(rid)
            if not _nonempty(risk.get("description")):
                errors.append(f"{where}.description must be non-empty")
            if risk.get("severity") not in PRIORITIES:
                errors.append(f"{where}.severity is invalid")
            if not isinstance(risk.get("mitigation"), str):
                errors.append(f"{where}.mitigation must be a string")

    errors.extend(_string_array(data.get("uncertainties"), "compilation.uncertainties"))

    frontier = data.get("next_frontier")
    if frontier is not None:
        if not isinstance(frontier, dict):
            errors.append("compilation.next_frontier must be null or object")
        else:
            errors.extend(_exact_keys(frontier, {"planning_item_id", "instruction", "acceptance_criteria"}, "compilation.next_frontier"))
            frontier_id = frontier.get("planning_item_id")
            if frontier_id not in item_ids:
                errors.append(f"compilation.next_frontier references unknown planning item: {frontier_id}")
            else:
                item = next((candidate for candidate in planning_items if candidate.get("id") == frontier_id), None)
                if item is not None:
                    if item.get("status") not in EXECUTABLE_STATUSES:
                        errors.append(
                            f"compilation.next_frontier item status must be one of {sorted(EXECUTABLE_STATUSES)}, found {item.get('status')}"
                        )
                    unsatisfied = [
                        dep for dep in item.get("depends_on", [])
                        if next((candidate for candidate in planning_items if candidate.get("id") == dep), {}).get("status") != "verified_done"
                    ]
                    if unsatisfied:
                        errors.append(
                            "compilation.next_frontier has unsatisfied dependencies: " + ", ".join(unsatisfied)
                        )
            if not _nonempty(frontier.get("instruction")):
                errors.append("compilation.next_frontier.instruction must be non-empty")
            ac_errors = _string_array(frontier.get("acceptance_criteria"), "compilation.next_frontier.acceptance_criteria")
            errors.extend(ac_errors)
            if isinstance(frontier.get("acceptance_criteria"), list) and not frontier.get("acceptance_criteria"):
                errors.append("compilation.next_frontier.acceptance_criteria must not be empty")

    secret_paths = _secret_paths(data)
    if secret_paths:
        errors.append("secret-like content detected at: " + ", ".join(secret_paths))
    return errors


def _origin_for_planning(origin: dict[str, Any], observed_at: str) -> dict[str, Any]:
    mapping = {
        "current_user": "user_decision",
        "conversation": "session_compiler",
        "prior_checkpoint": "sealed_checkpoint",
        "repository_evidence": "repository_reconciliation",
        "artifact": "artifact",
        "inference": "session_compiler",
        "unknown": "unknown",
    }
    return {
        "kind": mapping.get(origin.get("kind"), "unknown"),
        "ref": origin.get("ref"),
        "observed_at": observed_at,
    }


def _compilation_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def _source_evidence(data: dict[str, Any]) -> dict[str, Any]:
    producer = data["producer"]
    return {
        "id": "E-SESSION-001",
        "type": "source",
        "label": "Session Compiler source context",
        "observed_at": data["created_at"],
        "source_kind": "conversation",
        "session_ref": producer.get("session_ref"),
        "compilation_id": data["compilation_id"],
    }


def compile_session(data: dict[str, Any], *, seal_portable: bool = False, sealed_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    errors = validate_compilation(data)
    if errors:
        raise SessionCompilationError("Invalid session compilation:\n- " + "\n- ".join(errors))

    digest_seed = _compilation_hash(data)[:20]
    checkpoint_id = f"pcp-session-{digest_seed}"
    planning_id = f"planning-session-{digest_seed}"
    source_evidence = _source_evidence(data)

    claims: list[dict[str, Any]] = []
    for i, decision in enumerate(data["decisions"], start=1):
        prefix = "Superseded decision" if decision["status"] == "superseded" else "Accepted decision"
        claims.append(
            {
                "id": f"SC-D-{i:03d}",
                "kind": "decision",
                "confidence": decision["confidence"],
                "statement": f"{prefix} [{decision['id']}]: {decision['statement']}",
                "evidence": [source_evidence["id"]],
                "supersedes": list(decision["supersedes"]),
            }
        )
    for i, finding in enumerate(data["findings"], start=1):
        claims.append(
            {
                "id": f"SC-F-{i:03d}",
                "kind": "finding",
                "confidence": finding["confidence"],
                "statement": f"Session finding [{finding['id']}]: {finding['statement']}",
                "evidence": [source_evidence["id"]],
                "supersedes": [],
            }
        )
    completion_like = [
        item for item in data["planning"]["items"]
        if item["status"] in {"reported_done", "verified_done"}
    ]
    for i, item in enumerate(completion_like, start=1):
        status_label = "reported completion" if item["status"] == "reported_done" else "historically verified planning status"
        claims.append(
            {
                "id": f"SC-H-{i:03d}",
                "kind": "finding",
                "confidence": "reported",
                "statement": (
                    f"Historical {status_label} [{item['id']}] requiring current repository reconciliation: {item['title']}"
                ),
                "evidence": [source_evidence["id"]],
                "supersedes": [],
            }
        )

    reconciliation_id = "W-RECONCILE-001"
    reconciliation_criteria = [
        "Project identity is confirmed against the authoritative repository or files.",
        "Historical implementation claims are rechecked against current project reality.",
        "No completion claim is promoted without current hard evidence.",
        "The planning snapshot is reconciled before executing the proposed frontier.",
    ]
    open_work: list[dict[str, Any]] = [
        {
            "id": reconciliation_id,
            "title": "Reconcile compiled session continuity with current project state",
            "status": "todo",
            "priority": "critical",
            "acceptance_criteria": reconciliation_criteria,
            "depends_on": [],
        }
    ]

    blocker_id_map: dict[str, str] = {}
    for i, blocker in enumerate(data["blockers"], start=1):
        blocker_id_map[blocker["id"]] = f"W-BLOCK-{i:03d}"
    for i, blocker in enumerate(data["blockers"], start=1):
        open_work.append(
            {
                "id": blocker_id_map[blocker["id"]],
                "title": blocker["title"],
                "status": "blocked",
                "priority": blocker["priority"],
                "acceptance_criteria": list(blocker["acceptance_criteria"]),
                "depends_on": [
                    blocker_id_map[dep] for dep in blocker["depends_on"] if dep in blocker_id_map
                ],
            }
        )

    frontier = data["next_frontier"]
    if frontier is not None:
        item_by_id = {item["id"]: item for item in data["planning"]["items"]}
        frontier_item = item_by_id[frontier["planning_item_id"]]
        open_work.append(
            {
                "id": "W-FRONTIER-001",
                "title": f"Proposed next frontier: {frontier_item['title']}",
                "status": "todo",
                "priority": frontier_item["priority"],
                "acceptance_criteria": list(frontier["acceptance_criteria"]),
                "depends_on": [reconciliation_id],
            }
        )

    risks = [dict(risk) for risk in data["risks"]]
    for i, uncertainty in enumerate(data["uncertainties"], start=1):
        risks.append(
            {
                "id": f"R-UNCERTAINTY-{i:03d}",
                "description": uncertainty,
                "severity": "medium",
                "mitigation": "Resolve during authoritative project reconciliation; do not guess missing state.",
            }
        )

    prior = data["prior_checkpoint"]
    checkpoint: dict[str, Any] = {
        "protocol_version": PCP.PROTOCOL,
        "checkpoint_id": checkpoint_id,
        "created_at": data["created_at"],
        "producer": {
            "surface": data["producer"]["surface"],
            "model": data["producer"]["model"],
            "session_ref": data["producer"]["session_ref"],
        },
        "project_id": data["project"]["id"],
        "parent": {
            "checkpoint_id": prior["id"] if prior else None,
            "content_digest": prior["digest"] if prior else None,
        },
        "baseline": {"root_hint": ".", "git": None, "files": []},
        "objective": {
            "current": data["objective"]["current"],
            "definition_of_done": list(data["objective"]["definition_of_done"]),
        },
        "claims": claims,
        "evidence": [source_evidence],
        "open_work": open_work,
        "next_action": {
            "work_item_id": reconciliation_id,
            "instruction": "Verify and reconcile this compiled portable state against the authoritative project before implementation work.",
            "acceptance_criteria": reconciliation_criteria,
        },
        "risks": risks,
        "verification": {
            "status": "draft",
            "sealed_at": None,
            "content_digest": None,
            "policy": PCP.POLICY,
            "surface_status": "unverifiable",
        },
    }

    draft_errors = PCP.validate_checkpoint(checkpoint, expect_sealed=False)
    if draft_errors:
        raise SessionCompilationError("Compiler emitted invalid PCP/1 draft:\n- " + "\n- ".join(draft_errors))

    if seal_portable:
        seal_time = sealed_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if not _valid_time(seal_time):
            raise SessionCompilationError("sealed_at must be RFC3339 date-time with timezone")
        if any(claim.get("kind") == "completed" for claim in checkpoint["claims"]):
            raise SessionCompilationError("Session Compiler portable sealing must not emit completed claims")
        checkpoint["verification"] = {
            "status": "sealed",
            "sealed_at": seal_time,
            "content_digest": None,
            "policy": PCP.POLICY,
            "surface_status": "unverifiable",
        }
        checkpoint["verification"]["content_digest"] = PCP.compute_content_digest(checkpoint)
        sealed_errors = PCP.validate_checkpoint(checkpoint, expect_sealed=True)
        if sealed_errors:
            raise SessionCompilationError("Compiler emitted invalid sealed PCP/1 checkpoint:\n- " + "\n- ".join(sealed_errors))

    planning_items = []
    for item in data["planning"]["items"]:
        planning_items.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "title": item["title"],
                "status": item["status"],
                "parent_id": item["parent_id"],
                "priority": item["priority"],
                "depends_on": list(item["depends_on"]),
                "acceptance_criteria": list(item["acceptance_criteria"]),
                "origin": _origin_for_planning(item["origin"], data["created_at"]),
                "supersedes": list(item["supersedes"]),
                "evidence_refs": list(item["evidence_refs"]),
                "repository_refs": list(item["repository_refs"]),
            }
        )
    planning_decisions = [
        {
            "id": decision["id"],
            "statement": decision["statement"],
            "status": decision["status"],
            "origin": _origin_for_planning(decision["origin"], data["created_at"]),
            "supersedes": list(decision["supersedes"]),
        }
        for decision in data["decisions"]
    ]
    source_checkpoint = None
    if checkpoint["verification"]["status"] == "sealed":
        source_checkpoint = {
            "id": checkpoint["checkpoint_id"],
            "digest": checkpoint["verification"]["content_digest"],
        }
    planning_snapshot: dict[str, Any] = {
        "format": PLANNING_FORMAT,
        "planning_id": planning_id,
        "created_at": data["created_at"],
        "project_id": data["project"]["id"],
        "source_checkpoint": source_checkpoint,
        "vision": data["planning"]["vision"],
        "items": planning_items,
        "decisions": planning_decisions,
        "unresolved_questions": list(data["uncertainties"]),
        "content_digest": None,
    }
    planning_errors = BUNDLE.validate_planning_snapshot(planning_snapshot)
    if planning_errors:
        raise SessionCompilationError("Compiler emitted invalid planning snapshot:\n- " + "\n- ".join(planning_errors))
    planning_snapshot["content_digest"] = BUNDLE.compute_planning_digest(planning_snapshot)
    return checkpoint, planning_snapshot


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SessionCompilationError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SessionCompilationError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SessionCompilationError(f"Expected JSON object in {path}")
    return value


def atomic_write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(raw, encoding="utf-8")
    temp.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile Session Compilation IR into portable PCP continuity state")
    parser.add_argument("--input", required=True, help="pcp-session-compilation/1 JSON input")
    parser.add_argument("--checkpoint-out", required=True)
    parser.add_argument("--planning-out", required=True)
    parser.add_argument("--seal-portable", action="store_true")
    parser.add_argument("--sealed-at", help="Optional RFC3339 seal time for deterministic tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = read_json(pathlib.Path(args.input))
        checkpoint, planning = compile_session(
            source,
            seal_portable=bool(args.seal_portable),
            sealed_at=args.sealed_at,
        )
        atomic_write_json(pathlib.Path(args.checkpoint_out), checkpoint)
        atomic_write_json(pathlib.Path(args.planning_out), planning)
        print(
            json.dumps(
                {
                    "status": "compiled",
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "checkpoint_status": checkpoint["verification"]["status"],
                    "checkpoint_digest": checkpoint["verification"]["content_digest"],
                    "planning_id": planning["planning_id"],
                    "planning_digest": planning["content_digest"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except SessionCompilationError as exc:
        print(f"session-compiler: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
