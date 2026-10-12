#!/usr/bin/env python3
"""Transport-independent handoff bundle validation for Project Continuity.

The module validates the pcp-handoff/1 envelope and pcp-planning/1 sidecar.
Checkpoint semantics are injected by the PCP core so this module cannot create a
second implementation of evidence, sealing, or completion rules.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Callable

HANDOFF_FORMAT = "pcp-handoff/1"
PLANNING_FORMAT = "pcp-planning/1"
PCP_PROTOCOL = "pcp/1"
CHECKPOINT_ID_RE = re.compile(r"^pcp-[A-Za-z0-9._-]{8,}$")
HANDOFF_ID_RE = re.compile(r"^handoff-[A-Za-z0-9._-]{8,}$")
PLANNING_ID_RE = re.compile(r"^planning-[A-Za-z0-9._-]{8,}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
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
ORIGIN_KINDS = {
    "user_decision",
    "sealed_checkpoint",
    "session_compiler",
    "repository_reconciliation",
    "issue",
    "pull_request",
    "artifact",
    "unknown",
}
DECISION_STATUSES = {"accepted", "superseded"}


class HandoffBundleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def compute_planning_digest(snapshot: dict[str, Any]) -> str:
    clone = copy.deepcopy(snapshot)
    clone["content_digest"] = None
    return _sha256(canonical_bytes(clone))


def _exact_keys(value: dict[str, Any], required: set[str], *, where: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        errors.append(f"{where} missing required fields: {', '.join(missing)}")
    if extra:
        errors.append(f"{where} contains unknown fields: {', '.join(extra)}")
    return errors


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def validate_handoff_envelope(envelope: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(envelope, dict):
        return ["envelope must be an object"]
    errors.extend(
        _exact_keys(
            envelope,
            {"format", "handoff_id", "created_at", "project", "checkpoint", "planning_snapshot", "transport"},
            where="envelope",
        )
    )
    if envelope.get("format") != HANDOFF_FORMAT:
        errors.append(f"envelope.format must be {HANDOFF_FORMAT}")
    if not isinstance(envelope.get("handoff_id"), str) or HANDOFF_ID_RE.fullmatch(str(envelope.get("handoff_id"))) is None:
        errors.append("envelope.handoff_id has invalid format")
    if not _nonempty_string(envelope.get("created_at")):
        errors.append("envelope.created_at must be a non-empty string")

    project = envelope.get("project")
    if not isinstance(project, dict):
        errors.append("envelope.project must be an object")
    else:
        errors.extend(_exact_keys(project, {"id", "repository"}, where="envelope.project"))
        if not _nonempty_string(project.get("id")):
            errors.append("envelope.project.id must be non-empty")
        if project.get("repository") is not None and not _nonempty_string(project.get("repository")):
            errors.append("envelope.project.repository must be null or non-empty")

    checkpoint = envelope.get("checkpoint")
    if not isinstance(checkpoint, dict):
        errors.append("envelope.checkpoint must be an object")
    else:
        errors.extend(
            _exact_keys(checkpoint, {"protocol", "id", "digest", "location"}, where="envelope.checkpoint")
        )
        if checkpoint.get("protocol") != PCP_PROTOCOL:
            errors.append(f"envelope.checkpoint.protocol must be {PCP_PROTOCOL}")
        if not isinstance(checkpoint.get("id"), str) or CHECKPOINT_ID_RE.fullmatch(str(checkpoint.get("id"))) is None:
            errors.append("envelope.checkpoint.id has invalid format")
        if not _valid_digest(checkpoint.get("digest")):
            errors.append("envelope.checkpoint.digest has invalid format")
        if not _nonempty_string(checkpoint.get("location")):
            errors.append("envelope.checkpoint.location must be non-empty")

    planning = envelope.get("planning_snapshot")
    if planning is not None:
        if not isinstance(planning, dict):
            errors.append("envelope.planning_snapshot must be null or an object")
        else:
            errors.extend(
                _exact_keys(planning, {"id", "digest", "location"}, where="envelope.planning_snapshot")
            )
            if not isinstance(planning.get("id"), str) or PLANNING_ID_RE.fullmatch(str(planning.get("id"))) is None:
                errors.append("envelope.planning_snapshot.id has invalid format")
            if not _valid_digest(planning.get("digest")):
                errors.append("envelope.planning_snapshot.digest has invalid format")
            if not _nonempty_string(planning.get("location")):
                errors.append("envelope.planning_snapshot.location must be non-empty")

    transport = envelope.get("transport")
    if not isinstance(transport, dict):
        errors.append("envelope.transport must be an object")
    else:
        errors.extend(_exact_keys(transport, {"kind"}, where="envelope.transport"))
        if transport.get("kind") not in {"file", "github"}:
            errors.append("envelope.transport.kind must be file or github")

    return errors


def _validate_origin(origin: Any, *, where: str) -> list[str]:
    if not isinstance(origin, dict):
        return [f"{where} must be an object"]
    errors = _exact_keys(origin, {"kind", "ref", "observed_at"}, where=where)
    if origin.get("kind") not in ORIGIN_KINDS:
        errors.append(f"{where}.kind is invalid")
    if origin.get("ref") is not None and not _nonempty_string(origin.get("ref")):
        errors.append(f"{where}.ref must be null or non-empty")
    if origin.get("observed_at") is not None and not _nonempty_string(origin.get("observed_at")):
        errors.append(f"{where}.observed_at must be null or non-empty")
    return errors


def _validate_string_array(value: Any, *, where: str, unique: bool = False) -> list[str]:
    if not isinstance(value, list):
        return [f"{where} must be an array"]
    errors: list[str] = []
    normalized: list[str] = []
    for i, item in enumerate(value):
        if not _nonempty_string(item):
            errors.append(f"{where}[{i}] must be a non-empty string")
        else:
            normalized.append(item)
    if unique and len(normalized) != len(set(normalized)):
        errors.append(f"{where} must contain unique values")
    return errors


def validate_planning_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(snapshot, dict):
        return ["planning snapshot must be an object"]
    errors.extend(
        _exact_keys(
            snapshot,
            {
                "format",
                "planning_id",
                "created_at",
                "project_id",
                "source_checkpoint",
                "vision",
                "items",
                "decisions",
                "unresolved_questions",
                "content_digest",
            },
            where="planning",
        )
    )
    if snapshot.get("format") != PLANNING_FORMAT:
        errors.append(f"planning.format must be {PLANNING_FORMAT}")
    if not isinstance(snapshot.get("planning_id"), str) or PLANNING_ID_RE.fullmatch(str(snapshot.get("planning_id"))) is None:
        errors.append("planning.planning_id has invalid format")
    if not _nonempty_string(snapshot.get("created_at")):
        errors.append("planning.created_at must be non-empty")
    if not _nonempty_string(snapshot.get("project_id")):
        errors.append("planning.project_id must be non-empty")
    if snapshot.get("vision") is not None and not isinstance(snapshot.get("vision"), str):
        errors.append("planning.vision must be string or null")
    digest = snapshot.get("content_digest")
    if digest is not None and not _valid_digest(digest):
        errors.append("planning.content_digest has invalid format")

    source = snapshot.get("source_checkpoint")
    if source is not None:
        if not isinstance(source, dict):
            errors.append("planning.source_checkpoint must be null or object")
        else:
            errors.extend(_exact_keys(source, {"id", "digest"}, where="planning.source_checkpoint"))
            if not isinstance(source.get("id"), str) or CHECKPOINT_ID_RE.fullmatch(str(source.get("id"))) is None:
                errors.append("planning.source_checkpoint.id has invalid format")
            if not _valid_digest(source.get("digest")):
                errors.append("planning.source_checkpoint.digest has invalid format")

    items = snapshot.get("items")
    if not isinstance(items, list):
        errors.append("planning.items must be an array")
    else:
        seen_ids: set[str] = set()
        for i, item in enumerate(items):
            where = f"planning.items[{i}]"
            if not isinstance(item, dict):
                errors.append(f"{where} must be an object")
                continue
            required = {
                "id",
                "kind",
                "title",
                "status",
                "parent_id",
                "priority",
                "depends_on",
                "acceptance_criteria",
                "origin",
                "supersedes",
                "evidence_refs",
                "repository_refs",
            }
            errors.extend(_exact_keys(item, required, where=where))
            item_id = item.get("id")
            if not _nonempty_string(item_id):
                errors.append(f"{where}.id must be non-empty")
            elif item_id in seen_ids:
                errors.append(f"duplicate planning item id: {item_id}")
            else:
                seen_ids.add(item_id)
            if item.get("kind") not in PLANNING_KINDS:
                errors.append(f"{where}.kind is invalid")
            if not _nonempty_string(item.get("title")):
                errors.append(f"{where}.title must be non-empty")
            if item.get("status") not in PLANNING_STATUSES:
                errors.append(f"{where}.status is invalid")
            if item.get("parent_id") is not None and not _nonempty_string(item.get("parent_id")):
                errors.append(f"{where}.parent_id must be null or non-empty")
            if item.get("priority") not in PRIORITIES:
                errors.append(f"{where}.priority is invalid")
            for field in ("depends_on", "supersedes", "evidence_refs", "repository_refs"):
                errors.extend(_validate_string_array(item.get(field), where=f"{where}.{field}", unique=True))
            errors.extend(_validate_string_array(item.get("acceptance_criteria"), where=f"{where}.acceptance_criteria"))
            errors.extend(_validate_origin(item.get("origin"), where=f"{where}.origin"))
            if item.get("status") == "verified_done" and isinstance(item.get("evidence_refs"), list) and not item["evidence_refs"]:
                errors.append(f"{where}.verified_done requires at least one evidence_refs entry")

    decisions = snapshot.get("decisions")
    if not isinstance(decisions, list):
        errors.append("planning.decisions must be an array")
    else:
        seen_decisions: set[str] = set()
        for i, decision in enumerate(decisions):
            where = f"planning.decisions[{i}]"
            if not isinstance(decision, dict):
                errors.append(f"{where} must be an object")
                continue
            errors.extend(_exact_keys(decision, {"id", "statement", "status", "origin", "supersedes"}, where=where))
            did = decision.get("id")
            if not _nonempty_string(did):
                errors.append(f"{where}.id must be non-empty")
            elif did in seen_decisions:
                errors.append(f"duplicate decision id: {did}")
            else:
                seen_decisions.add(did)
            if not _nonempty_string(decision.get("statement")):
                errors.append(f"{where}.statement must be non-empty")
            if decision.get("status") not in DECISION_STATUSES:
                errors.append(f"{where}.status is invalid")
            errors.extend(_validate_origin(decision.get("origin"), where=f"{where}.origin"))
            errors.extend(_validate_string_array(decision.get("supersedes"), where=f"{where}.supersedes", unique=True))

    errors.extend(
        _validate_string_array(snapshot.get("unresolved_questions"), where="planning.unresolved_questions")
    )
    return errors


def verify_handoff_bundle(
    envelope: dict[str, Any],
    checkpoint: dict[str, Any],
    planning_snapshot: dict[str, Any] | None = None,
    *,
    checkpoint_validator: Callable[[dict[str, Any]], list[str]],
    checkpoint_digest: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Verify bundle integrity without mutating or promoting any project state."""

    envelope_errors = validate_handoff_envelope(envelope)
    if envelope_errors:
        raise HandoffBundleError("invalid-envelope", "; ".join(envelope_errors))

    checkpoint_errors = checkpoint_validator(checkpoint)
    if checkpoint_errors:
        raise HandoffBundleError("checkpoint-invalid", "; ".join(checkpoint_errors))

    verification = checkpoint.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "sealed":
        raise HandoffBundleError(
            "checkpoint-unsealed",
            "A digest-bearing handoff envelope may reference only a sealed PCP/1 checkpoint",
        )
    recorded_digest = verification.get("content_digest")
    if not _valid_digest(recorded_digest):
        raise HandoffBundleError("checkpoint-unsealed", "Sealed checkpoint requires a canonical content_digest")

    checkpoint_meta = envelope["checkpoint"]
    if checkpoint.get("protocol_version") != checkpoint_meta["protocol"]:
        raise HandoffBundleError("integrity-failed", "Checkpoint protocol does not match envelope")
    if checkpoint.get("checkpoint_id") != checkpoint_meta["id"]:
        raise HandoffBundleError("integrity-failed", "Checkpoint id does not match envelope")
    if checkpoint.get("project_id") != envelope["project"]["id"]:
        raise HandoffBundleError("project-mismatch", "Checkpoint project_id does not match envelope project.id")

    computed_checkpoint_digest = checkpoint_digest(checkpoint)
    if recorded_digest != checkpoint_meta["digest"] or computed_checkpoint_digest != checkpoint_meta["digest"]:
        raise HandoffBundleError(
            "integrity-failed",
            "Checkpoint canonical digest does not match the handoff envelope",
        )

    planning_meta = envelope.get("planning_snapshot")
    if planning_meta is None:
        if planning_snapshot is not None:
            raise HandoffBundleError(
                "integrity-failed",
                "Planning snapshot bytes were supplied but envelope declares no planning sidecar",
            )
        planning_result = None
    else:
        if planning_snapshot is None:
            raise HandoffBundleError("remote-not-found", "Envelope references a planning snapshot but none was supplied")
        planning_errors = validate_planning_snapshot(planning_snapshot)
        if planning_errors:
            raise HandoffBundleError("planning-invalid", "; ".join(planning_errors))
        if planning_snapshot.get("planning_id") != planning_meta["id"]:
            raise HandoffBundleError("integrity-failed", "Planning snapshot id does not match envelope")
        if planning_snapshot.get("project_id") != envelope["project"]["id"]:
            raise HandoffBundleError("project-mismatch", "Planning project_id does not match envelope project.id")
        computed_planning_digest = compute_planning_digest(planning_snapshot)
        recorded_planning_digest = planning_snapshot.get("content_digest")
        if recorded_planning_digest is not None and recorded_planning_digest != planning_meta["digest"]:
            raise HandoffBundleError("integrity-failed", "Planning snapshot recorded digest does not match envelope")
        if computed_planning_digest != planning_meta["digest"]:
            raise HandoffBundleError("integrity-failed", "Planning snapshot canonical digest does not match envelope")
        planning_result = {
            "id": planning_meta["id"],
            "digest": computed_planning_digest,
            "valid": True,
        }

    return {
        "valid": True,
        "project_id": envelope["project"]["id"],
        "checkpoint": {
            "id": checkpoint_meta["id"],
            "digest": computed_checkpoint_digest,
            "surface_status": verification.get("surface_status"),
            "valid": True,
        },
        "planning_snapshot": planning_result,
        "transport_kind": envelope["transport"]["kind"],
    }
