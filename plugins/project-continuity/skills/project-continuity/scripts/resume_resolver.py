#!/usr/bin/env python3
"""Codex-side handoff resolver and reconciliation orchestrator for PCP mobile continuity.

This module composes existing primitives rather than redefining them:

- transports.py parses explicit file/GitHub references;
- github_transport.py verifies content-addressed remote bundles;
- continuity.py performs downgrade-first PCP consumption and repository-baseline comparison;
- planning_reconcile.py applies current FILE/FULL planning observations.

External handoffs never promote local continuity HEAD. A planning frontier is
reported only after the supplied planning snapshot has been reconciled through
the deterministic R3 reconciler.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
from typing import Any


class ResumeResolutionError(Exception):
    """Fail-closed R5 orchestration error."""


def _load(name: str, filename: str):
    """Load one sibling runtime module without requiring package installation."""
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ResumeResolutionError(f"Unable to load required sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


PCP = _load("pcp_resume_core", "continuity.py")
TRANSPORTS = _load("pcp_resume_transports", "transports.py")
BUNDLE = _load("pcp_resume_bundle", "handoff_bundle.py")
GITHUB = _load("pcp_resume_github", "github_transport.py")
PLANNING = _load("pcp_resume_planning", "planning_reconcile.py")

TransportError = TRANSPORTS.TransportError


def now_utc() -> str:
    """Return a stable RFC3339 UTC timestamp."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _json_object(text: str, label: str) -> dict[str, Any]:
    """Parse one UTF-8 JSON object with a stable error."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResumeResolutionError(f"Invalid JSON in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResumeResolutionError(f"{label} must be a JSON object")
    return value


def _file_transport_for_reference(
    reference_value: str,
    allowed_root: str | pathlib.Path | None,
):
    """Return a root-scoped file transport and parsed reference."""
    reference = TRANSPORTS.parse_reference(reference_value)
    if reference.kind != "file":
        raise ResumeResolutionError("Reference is not a file handoff")
    reference_path = pathlib.Path(reference.path).expanduser().absolute()
    root = pathlib.Path(allowed_root).expanduser().absolute() if allowed_root else reference_path.parent
    return TRANSPORTS.FileTransport(allowed_root=root), reference


def _file_artifact_reference(
    transport: Any,
    envelope_path: pathlib.Path,
    location: str,
):
    """Resolve one envelope locator within the file transport's authorized root."""
    location_path = pathlib.Path(location).expanduser()
    if not location_path.is_absolute():
        location_path = envelope_path.parent / location_path
    return transport.reference_for_path(location_path)


def resolve_file_reference(
    reference_value: str,
    *,
    allowed_root: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Resolve a legacy checkpoint or strict file-envelope handoff."""
    transport, reference = _file_transport_for_reference(reference_value, allowed_root)
    descriptor = transport.resolve(reference)
    raw = transport.fetch(descriptor)
    payload = _json_object(raw.decode("utf-8"), "file handoff")

    # Legacy standalone PCP checkpoint: preserve compatibility with handoff-in.
    if payload.get("protocol_version") == PCP.PROTOCOL:
        status = payload.get("verification", {}).get("status")
        if status == "sealed":
            errors = PCP.validate_checkpoint(payload, expect_sealed=True)
            if not errors:
                expected = payload["verification"].get("content_digest")
                actual = PCP.compute_content_digest(payload)
                if expected != actual:
                    errors.append(
                        f"content digest mismatch: expected {expected}, computed {actual}"
                    )
            if errors:
                raise ResumeResolutionError(
                    "Invalid sealed standalone checkpoint: " + "; ".join(errors)
                )
            integrity = "sealed-valid"
        elif status == "draft":
            errors = PCP.validate_checkpoint(payload, expect_sealed=False)
            if errors:
                raise ResumeResolutionError(
                    "Invalid standalone checkpoint draft: " + "; ".join(errors)
                )
            integrity = "unsealed-reported"
        else:
            raise ResumeResolutionError(
                "Standalone checkpoint verification.status must be draft or sealed"
            )
        return {
            "status": "resolved",
            "reference": reference_value,
            "transport": "file",
            "envelope": None,
            "checkpoint": payload,
            "planning_snapshot": None,
            "verification": {
                "valid": True,
                "legacy_standalone": True,
                "checkpoint_integrity": integrity,
            },
        }

    if payload.get("format") != BUNDLE.HANDOFF_FORMAT:
        raise ResumeResolutionError(
            "File handoff must contain a PCP/1 checkpoint or pcp-handoff/1 envelope"
        )
    envelope_errors = BUNDLE.validate_handoff_envelope(payload)
    if envelope_errors:
        raise ResumeResolutionError(
            "Invalid file handoff envelope: " + "; ".join(envelope_errors)
        )
    if payload["transport"]["kind"] != "file":
        raise ResumeResolutionError(
            "File reference cannot resolve an envelope whose transport.kind is not file"
        )

    checkpoint_ref = _file_artifact_reference(
        transport, descriptor.path, payload["checkpoint"]["location"]
    )
    checkpoint = _json_object(
        transport.fetch(checkpoint_ref).decode("utf-8"), "file checkpoint"
    )

    planning: dict[str, Any] | None = None
    planning_meta = payload.get("planning_snapshot")
    if planning_meta is not None:
        planning_ref = _file_artifact_reference(
            transport, descriptor.path, planning_meta["location"]
        )
        planning = _json_object(
            transport.fetch(planning_ref).decode("utf-8"), "file planning snapshot"
        )

    try:
        verification = BUNDLE.verify_handoff_bundle(
            payload,
            checkpoint,
            planning,
            checkpoint_validator=lambda cp: PCP.validate_checkpoint(
                cp, expect_sealed=True
            ),
            checkpoint_digest=PCP.compute_content_digest,
        )
    except BUNDLE.HandoffBundleError as exc:
        raise ResumeResolutionError(
            f"File handoff bundle verification failed ({exc.code}): {exc.message}"
        ) from exc

    return {
        "status": "resolved",
        "reference": reference_value,
        "transport": "file",
        "envelope": payload,
        "checkpoint": checkpoint,
        "planning_snapshot": planning,
        "verification": verification,
    }


def resolve_reference(
    reference_value: str,
    *,
    github_client: Any | None = None,
    file_allowed_root: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    """Resolve one explicit handoff reference without guessing transport."""
    reference = TRANSPORTS.parse_reference(reference_value)
    try:
        if reference.kind == "github":
            if github_client is None:
                raise ResumeResolutionError(
                    "GitHub handoff resolution requires an authorized GitHub client binding"
                )
            resolved = GITHUB.resolve_bundle(github_client, reference_value)
            return {**resolved, "transport": "github"}
        if reference.kind == "file":
            return resolve_file_reference(
                reference_value, allowed_root=file_allowed_root
            )
        raise ResumeResolutionError(
            f"Unsupported handoff transport for R5 resume: {reference.kind}"
        )
    except TransportError as exc:
        raise ResumeResolutionError(
            f"Handoff resolution failed ({exc.code}): {exc.message}"
        ) from exc


def _compatibility_for_external(
    root: pathlib.Path,
    checkpoint: dict[str, Any],
    local_project_id: str,
) -> dict[str, Any]:
    """Classify source baseline against current project without promoting it."""
    status = checkpoint.get("verification", {}).get("status")
    if status == "sealed":
        return PCP.verify_checkpoint(
            root,
            checkpoint,
            expected_project_id=local_project_id,
        )
    errors = PCP.validate_checkpoint(checkpoint, expect_sealed=False)
    if errors:
        return {
            "status": "invalid",
            "integrity": {"valid": False, "errors": errors},
            "compatibility": None,
        }
    if checkpoint.get("project_id") != local_project_id:
        return {
            "status": "project-mismatch",
            "integrity": {"valid": True, "errors": []},
            "compatibility": {
                "status": "project-mismatch",
                "expected_project_id": local_project_id,
                "checkpoint_project_id": checkpoint.get("project_id"),
            },
        }
    baseline = PCP.compare_baseline(root, checkpoint)
    return {
        "status": baseline["status"],
        "integrity": {
            "valid": True,
            "errors": [],
            "unsealed": True,
        },
        "compatibility": baseline,
    }


def _consume_external_checkpoint(
    root: pathlib.Path,
    checkpoint: dict[str, Any],
    *,
    surface: str,
    model: str | None,
    confirm_project_mapping: bool,
) -> dict[str, Any]:
    """Reuse the canonical downgrade-first PCP consume implementation."""
    temp_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as handle:
            json.dump(checkpoint, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            temp_path = pathlib.Path(handle.name)

        namespace = argparse.Namespace(
            root=str(root),
            checkpoint=str(temp_path),
            surface=surface,
            model=model,
            confirm_project_mapping=confirm_project_mapping,
        )
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            PCP.cmd_consume(namespace)
        text = stdout.getvalue().strip()
        result = _json_object(text, "PCP consume result")
        if result.get("status") != "reconciliation-required":
            raise ResumeResolutionError(
                f"Unexpected PCP consume status: {result.get('status')!r}"
            )
        return result
    except PCP.ContinuityError as exc:
        raise ResumeResolutionError(f"PCP downgrade-first consume failed: {exc}") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _historical_decisions(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    """Return external decisions explicitly downgraded for resume display."""
    decisions: list[dict[str, Any]] = []
    for claim in checkpoint.get("claims", []) or []:
        if not isinstance(claim, dict) or claim.get("kind") != "decision":
            continue
        decisions.append(
            {
                "id": claim.get("id"),
                "statement": claim.get("statement"),
                "confidence": "reported",
            }
        )
    return decisions


def _completion_claims(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    """List historical completion claims requiring current local re-verification."""
    claims: list[dict[str, Any]] = []
    for claim in checkpoint.get("claims", []) or []:
        if not isinstance(claim, dict) or claim.get("kind") != "completed":
            continue
        claims.append(
            {
                "id": claim.get("id"),
                "statement": claim.get("statement"),
                "status": "requires-reverification",
            }
        )
    return claims


def _blocked_items(
    checkpoint: dict[str, Any],
    planning: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Collect explicit blocked work from checkpoint and planning history."""
    blocked: list[dict[str, Any]] = []
    for item in checkpoint.get("open_work", []) or []:
        if isinstance(item, dict) and item.get("status") == "blocked":
            blocked.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "source": "checkpoint",
                }
            )
    if planning is not None:
        for item in planning.get("items", []) or []:
            if isinstance(item, dict) and item.get("status") == "blocked":
                blocked.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "source": "planning",
                    }
                )
    return blocked


def prepare_resume(
    root: str | pathlib.Path,
    resolved: dict[str, Any],
    *,
    surface: str = "codex",
    model: str | None = None,
    confirm_project_mapping: bool = False,
    planning_reconciliation: dict[str, Any] | None = None,
    resolved_at: str | None = None,
) -> dict[str, Any]:
    """Consume external PCP state and optionally reconcile its planning sidecar."""
    project_root = pathlib.Path(root).resolve()
    _, state = PCP.load_state(project_root)
    local_project_id = state["project"]["id"]
    checkpoint = resolved.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise ResumeResolutionError("Resolved handoff has no checkpoint object")

    compatibility = _compatibility_for_external(
        project_root, checkpoint, local_project_id
    )
    if (
        compatibility["status"] == "project-mismatch"
        and not confirm_project_mapping
    ):
        raise ResumeResolutionError(
            "External handoff project_id does not match local project; "
            "independently verify identity before explicit mapping"
        )

    consume_result = _consume_external_checkpoint(
        project_root,
        checkpoint,
        surface=surface,
        model=model,
        confirm_project_mapping=confirm_project_mapping,
    )

    planning = resolved.get("planning_snapshot")
    planning_state: dict[str, Any]
    effective_planning: dict[str, Any] | None = (
        planning if isinstance(planning, dict) else None
    )
    if effective_planning is None:
        if planning_reconciliation is not None:
            raise ResumeResolutionError(
                "Planning reconciliation was supplied but the handoff has no planning snapshot"
            )
        planning_state = {
            "status": "absent",
            "prior": None,
            "result": None,
            "transitions": [],
            "frontier": None,
        }
    elif planning_reconciliation is None:
        planning_state = {
            "status": "reconciliation-required",
            "prior": {
                "id": effective_planning["planning_id"],
                "digest": effective_planning["content_digest"],
            },
            "result": None,
            "transitions": [],
            "frontier": None,
        }
    else:
        try:
            reconciled, report = PLANNING.reconcile(
                effective_planning, planning_reconciliation
            )
        except PLANNING.PlanningReconciliationError as exc:
            raise ResumeResolutionError(
                f"Planning reconciliation failed: {exc}"
            ) from exc
        effective_planning = reconciled
        planning_state = {
            "status": "reconciled",
            "prior": report["prior_planning"],
            "result": report["result_planning"],
            "transitions": report["transitions"],
            "frontier": report["frontier"],
        }

    historical_objective = checkpoint.get("objective", {}).get("current")
    return {
        "format": "pcp-resume-resolution/1",
        "created_at": resolved_at or now_utc(),
        "reference": resolved.get("reference"),
        "transport": resolved.get("transport"),
        "local_project": {
            "id": local_project_id,
            "name": state["project"]["name"],
        },
        "source": {
            "project_id": checkpoint.get("project_id"),
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "checkpoint_digest": checkpoint.get("verification", {}).get(
                "content_digest"
            ),
            "checkpoint_status": checkpoint.get("verification", {}).get("status"),
            "surface_status": checkpoint.get("verification", {}).get(
                "surface_status"
            ),
            "handoff_id": (
                resolved.get("envelope", {}).get("handoff_id")
                if isinstance(resolved.get("envelope"), dict)
                else None
            ),
        },
        "pcp": {
            "compatibility": compatibility["status"],
            "compatibility_detail": compatibility.get("compatibility"),
            "reconciliation_draft": consume_result["draft"],
            "external_promoted": False,
            "historical_completion_claims": _completion_claims(checkpoint),
        },
        "planning": planning_state,
        "resume_brief": {
            "objective": {
                "text": historical_objective,
                "confidence": "reported",
                "instruction": (
                    "Confirm against current user/repository instructions before material execution."
                ),
            },
            "surviving_decisions": _historical_decisions(checkpoint),
            "blockers": _blocked_items(checkpoint, effective_planning),
            "candidate_frontier": planning_state["frontier"],
        },
        "execution_gate": {
            "repository_reconciliation_required": True,
            "planning_reconciliation_required": (
                planning_state["status"] == "reconciliation-required"
            ),
            "candidate_frontier_available": planning_state["frontier"] is not None,
            "external_head_promotion_allowed": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the file-reference CLI. GitHub host bindings call the library API."""
    parser = argparse.ArgumentParser(
        description="Resolve a file handoff and prepare downgrade-first Codex resume state"
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
    """Resolve a local file reference; GitHub resolution uses host-injected clients."""
    args = build_parser().parse_args(argv)
    try:
        parsed = TRANSPORTS.parse_reference(args.reference)
        if parsed.kind == "github":
            raise ResumeResolutionError(
                "CLI GitHub resolution requires a host binding; call resolve_reference() "
                "with an authorized GitHub client"
            )
        planning_request = None
        if args.planning_reconciliation:
            planning_request = PLANNING.read_json(
                pathlib.Path(args.planning_reconciliation)
            )
        resolved = resolve_reference(
            args.reference,
            file_allowed_root=args.file_root,
        )
        result = prepare_resume(
            args.root,
            resolved,
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
        ResumeResolutionError,
        TransportError,
        PLANNING.PlanningReconciliationError,
    ) as exc:
        print(f"resume-resolver: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
