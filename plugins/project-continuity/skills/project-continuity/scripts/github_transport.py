#!/usr/bin/env python3
"""Content-addressed GitHub transport for Project Continuity handoffs.

Remote persistence and authentication are injected through a tiny client
interface. The transport itself owns deterministic paths, publication safety,
create-only/idempotent writes, compact references, and end-to-end integrity
verification. It never stores credentials and never promotes PCP state.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HANDOFF_FILE_RE = re.compile(r"^(handoff-[A-Za-z0-9._-]{8,})\.([0-9a-f]{64})\.json$")
DEFAULT_CONTINUITY_REPOSITORY = "project-continuity-state"


class GitHubTransportError(Exception):
    """Bootstrap failure before shared TransportError can be loaded."""


def _load_sibling(name: str, filename: str):
    """Load a sibling skill script without package installation."""
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GitHubTransportError(f"Unable to load sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


PCP = _load_sibling("pcp_github_core", "continuity.py")
BUNDLE = _load_sibling("pcp_github_bundle", "handoff_bundle.py")
TRANSPORTS = _load_sibling("pcp_github_transports", "transports.py")
TransportError = TRANSPORTS.TransportError
HandoffReference = TRANSPORTS.HandoffReference


def canonical_bytes(value: Any) -> bytes:
    """Serialize JSON using the remote transport canonical representation."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return canonical SHA-256 notation."""
    return "sha256:" + hashlib.sha256(value).hexdigest()


def now_utc() -> str:
    """Return a compact RFC3339 UTC timestamp."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _hex(digest: Any) -> str:
    """Extract and validate the lowercase hex body of a SHA-256 digest."""
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise TransportError("integrity-failed", "Expected sha256:<hex> digest")
    value = digest[7:]
    if HEX64_RE.fullmatch(value) is None:
        raise TransportError("integrity-failed", "Expected sha256:<64 lowercase hex> digest")
    return value


def _validate_owner_repo(owner: str, repository: str) -> None:
    """Validate a GitHub target without accepting path-like repository names."""
    if OWNER_RE.fullmatch(owner or "") is None:
        raise TransportError("reference-invalid", f"Invalid GitHub owner: {owner!r}")
    if REPO_RE.fullmatch(repository or "") is None or repository in {".", ".."}:
        raise TransportError("reference-invalid", f"Invalid GitHub repository: {repository!r}")


def project_token(project_id: str) -> str:
    """Derive a path-safe opaque token from the canonical PCP project ID."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise TransportError("project-mismatch", "project_id must be non-empty")
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:24]


def checkpoint_path(project_id: str, checkpoint: dict[str, Any]) -> str:
    """Return the immutable content-addressed checkpoint path."""
    checkpoint_id = checkpoint.get("checkpoint_id")
    if not isinstance(checkpoint_id, str):
        raise TransportError("checkpoint-invalid", "Checkpoint ID is missing")
    digest = _hex(checkpoint.get("verification", {}).get("content_digest"))
    return f"projects/{project_token(project_id)}/checkpoints/{checkpoint_id}.{digest}.json"


def planning_path(project_id: str, planning: dict[str, Any]) -> str:
    """Return the immutable content-addressed planning path."""
    planning_id = planning.get("planning_id")
    if not isinstance(planning_id, str):
        raise TransportError("integrity-failed", "Planning ID is missing")
    digest = _hex(planning.get("content_digest"))
    return f"projects/{project_token(project_id)}/planning/{planning_id}.{digest}.json"


def _handoff_id(
    project_id: str,
    checkpoint_digest: str,
    planning_digest: str | None,
    owner: str,
    repository: str,
) -> str:
    """Derive a stable handoff ID from exact bundle/store identity."""
    seed = canonical_bytes(
        {
            "project_id": project_id,
            "checkpoint_digest": checkpoint_digest,
            "planning_digest": planning_digest,
            "owner": owner.lower(),
            "repository": repository,
        }
    )
    return "handoff-" + hashlib.sha256(seed).hexdigest()[:24]


def handoff_path(project_id: str, handoff_id: str, envelope_bytes: bytes) -> str:
    """Return the envelope path with its raw-byte digest embedded in the filename."""
    digest = hashlib.sha256(envelope_bytes).hexdigest()
    return f"projects/{project_token(project_id)}/handoffs/{handoff_id}.{digest}.json"


def build_envelope(
    checkpoint: dict[str, Any],
    planning: dict[str, Any] | None,
    *,
    owner: str,
    repository: str,
    created_at: str | None = None,
    project_repository: str | None = None,
) -> tuple[dict[str, Any], bytes, HandoffReference]:
    """Build a valid handoff envelope and content-addressed GitHub reference."""
    _validate_owner_repo(owner, repository)
    checkpoint_errors = PCP.validate_checkpoint(checkpoint, expect_sealed=True)
    if checkpoint_errors:
        raise TransportError(
            "checkpoint-invalid",
            "Invalid sealed checkpoint: " + "; ".join(checkpoint_errors),
        )
    checkpoint_digest = checkpoint["verification"]["content_digest"]
    if checkpoint_digest != PCP.compute_content_digest(checkpoint):
        raise TransportError("integrity-failed", "Checkpoint canonical digest mismatch")

    project_id = checkpoint["project_id"]
    planning_digest: str | None = None
    planning_meta: dict[str, Any] | None = None
    if planning is not None:
        planning_errors = BUNDLE.validate_planning_snapshot(planning)
        if planning_errors:
            raise TransportError(
                "integrity-failed",
                "Invalid planning snapshot: " + "; ".join(planning_errors),
            )
        if planning.get("project_id") != project_id:
            raise TransportError("project-mismatch", "Planning/checkpoint project IDs differ")
        planning_digest = planning.get("content_digest")
        if planning_digest != BUNDLE.compute_planning_digest(planning):
            raise TransportError("integrity-failed", "Planning canonical digest mismatch")
        planning_meta = {
            "id": planning["planning_id"],
            "digest": planning_digest,
            "location": planning_path(project_id, planning),
        }

    handoff_id = _handoff_id(
        project_id,
        checkpoint_digest,
        planning_digest,
        owner,
        repository,
    )
    envelope = {
        "format": BUNDLE.HANDOFF_FORMAT,
        "handoff_id": handoff_id,
        "created_at": created_at or now_utc(),
        "project": {"id": project_id, "repository": project_repository},
        "checkpoint": {
            "protocol": PCP.PROTOCOL,
            "id": checkpoint["checkpoint_id"],
            "digest": checkpoint_digest,
            "location": checkpoint_path(project_id, checkpoint),
        },
        "planning_snapshot": planning_meta,
        "transport": {"kind": "github"},
    }
    errors = BUNDLE.validate_handoff_envelope(envelope)
    if errors:
        raise TransportError(
            "integrity-failed",
            "Generated GitHub envelope is invalid: " + "; ".join(errors),
        )
    envelope_bytes = canonical_bytes(envelope)
    relative = handoff_path(project_id, handoff_id, envelope_bytes)
    reference = HandoffReference(
        kind="github",
        authority=owner,
        path=f"/{repository}/{relative}",
    )
    return envelope, envelope_bytes, reference


def parse_github_reference(value: str) -> dict[str, str]:
    """Parse the one canonical GitHub handoff reference layout."""
    reference = TRANSPORTS.parse_reference(value)
    if reference.kind != "github":
        raise TransportError("unsupported-transport", "Reference is not a GitHub handoff")
    segments = [part for part in reference.path.split("/") if part]
    # <repo>/projects/<24hex>/handoffs/<handoff>.<64hex>.json
    if len(segments) != 5:
        raise TransportError("reference-invalid", "GitHub handoff reference path is non-canonical")
    repository, projects_literal, token, handoffs_literal, filename = segments
    owner = reference.authority
    _validate_owner_repo(owner, repository)
    if projects_literal != "projects" or handoffs_literal != "handoffs":
        raise TransportError("reference-invalid", "GitHub handoff reference path is non-canonical")
    if re.fullmatch(r"[0-9a-f]{24}", token) is None:
        raise TransportError("reference-invalid", "GitHub handoff project token is invalid")
    match = HANDOFF_FILE_RE.fullmatch(filename)
    if match is None:
        raise TransportError("reference-invalid", "GitHub handoff filename is invalid")
    return {
        "owner": owner,
        "repository": repository,
        "path": "/".join(segments[1:]),
        "project_token": token,
        "handoff_id": match.group(1),
        "envelope_hex": match.group(2),
    }


def _repo_is_public(info: dict[str, Any]) -> bool:
    """Return True only for a repository known to be public."""
    visibility = str(info.get("visibility") or "").lower()
    if visibility == "public":
        return True
    if visibility in {"private", "internal"}:
        return False
    return info.get("private") is False


def _client_repository(client: Any, owner: str, repository: str) -> dict[str, Any]:
    """Read repository metadata from the injected host binding."""
    method = getattr(client, "get_repository", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks get_repository")
    info = method(owner, repository)
    if not isinstance(info, dict):
        raise TransportError("transport-unavailable", "GitHub repository metadata unavailable")
    return info


def _client_read(client: Any, owner: str, repository: str, path: str) -> str | None:
    """Read one UTF-8 repository file; None means not found."""
    method = getattr(client, "read_text_file", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks read_text_file")
    value = method(owner, repository, path)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TransportError("transport-unavailable", "GitHub client returned non-text bytes")
    return value


def _client_create(
    client: Any,
    owner: str,
    repository: str,
    path: str,
    content: str,
    message: str,
) -> None:
    """Create one UTF-8 file through the injected host binding."""
    method = getattr(client, "create_text_file", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks create_text_file")
    method(owner, repository, path, content, message)


def _assert_safe_target(
    client: Any,
    owner: str,
    repository: str,
    *,
    allow_public: bool,
) -> dict[str, Any]:
    """Fail closed on a public destination unless this operation has explicit approval."""
    info = _client_repository(client, owner, repository)
    if _repo_is_public(info) and not allow_public:
        raise TransportError(
            "unsafe-publication-target",
            f"Refusing to publish continuity state to public repository {owner}/{repository}",
        )
    return info


def _ensure_object(
    client: Any,
    owner: str,
    repository: str,
    path: str,
    content: str,
    *,
    message: str,
) -> None:
    """Create once or accept a byte-identical existing object; never overwrite."""
    existing = _client_read(client, owner, repository, path)
    if existing is None:
        _client_create(client, owner, repository, path, content, message)
        existing = _client_read(client, owner, repository, path)
        if existing is None:
            raise TransportError("remote-not-found", f"Object unreadable after create: {path}")
    if existing.encode("utf-8") != content.encode("utf-8"):
        raise TransportError(
            "integrity-failed",
            f"Immutable GitHub path already contains different bytes: {path}",
        )


def publish_bundle(
    client: Any,
    checkpoint: dict[str, Any],
    planning: dict[str, Any] | None,
    *,
    owner: str,
    repository: str = DEFAULT_CONTINUITY_REPOSITORY,
    allow_public: bool = False,
    created_at: str | None = None,
    project_repository: str | None = None,
) -> dict[str, Any]:
    """Publish checkpoint/planning/envelope create-only and re-verify remote bytes."""
    _validate_owner_repo(owner, repository)
    _assert_safe_target(client, owner, repository, allow_public=allow_public)
    envelope, envelope_bytes, reference = build_envelope(
        checkpoint,
        planning,
        owner=owner,
        repository=repository,
        created_at=created_at,
        project_repository=project_repository,
    )
    checkpoint_location = envelope["checkpoint"]["location"]
    _ensure_object(
        client,
        owner,
        repository,
        checkpoint_location,
        canonical_bytes(checkpoint).decode("utf-8"),
        message=f"pcp: publish checkpoint {checkpoint['checkpoint_id']}",
    )
    planning_location: str | None = None
    if planning is not None:
        assert envelope["planning_snapshot"] is not None
        planning_location = envelope["planning_snapshot"]["location"]
        _ensure_object(
            client,
            owner,
            repository,
            planning_location,
            canonical_bytes(planning).decode("utf-8"),
            message=f"pcp: publish planning {planning['planning_id']}",
        )
    parsed = parse_github_reference(str(reference))
    _ensure_object(
        client,
        owner,
        repository,
        parsed["path"],
        envelope_bytes.decode("utf-8"),
        message=f"pcp: publish handoff {envelope['handoff_id']}",
    )
    resolved = resolve_bundle(client, str(reference))
    return {
        "status": "published",
        "reference": str(reference),
        "owner": owner,
        "repository": repository,
        "project_id": checkpoint["project_id"],
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_digest": checkpoint["verification"]["content_digest"],
        "planning_id": planning.get("planning_id") if planning else None,
        "planning_digest": planning.get("content_digest") if planning else None,
        "envelope_digest": sha256_bytes(envelope_bytes),
        "paths": {
            "checkpoint": checkpoint_location,
            "planning": planning_location,
            "handoff": parsed["path"],
        },
        "verification": resolved["verification"],
    }


def _read_json(text: str, label: str) -> dict[str, Any]:
    """Parse one remote JSON object."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TransportError("integrity-failed", f"Invalid JSON in remote {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransportError("integrity-failed", f"Remote {label} must be a JSON object")
    return value


def _artifact_path(project_id: str, meta: dict[str, Any], kind: str) -> str:
    """Derive the only accepted content-addressed location for an envelope artifact."""
    token = project_token(project_id)
    if kind == "checkpoint":
        return f"projects/{token}/checkpoints/{meta['id']}.{_hex(meta['digest'])}.json"
    if kind == "planning":
        return f"projects/{token}/planning/{meta['id']}.{_hex(meta['digest'])}.json"
    raise AssertionError(kind)


def resolve_bundle(client: Any, reference_value: str) -> dict[str, Any]:
    """Fetch and verify a GitHub handoff without granting it project authority."""
    parsed = parse_github_reference(reference_value)
    owner, repository = parsed["owner"], parsed["repository"]
    envelope_text = _client_read(client, owner, repository, parsed["path"])
    if envelope_text is None:
        raise TransportError("remote-not-found", "GitHub handoff envelope not found")
    envelope_bytes = envelope_text.encode("utf-8")
    if hashlib.sha256(envelope_bytes).hexdigest() != parsed["envelope_hex"]:
        raise TransportError(
            "integrity-failed",
            "Envelope bytes do not match digest embedded in GitHub reference",
        )
    envelope = _read_json(envelope_text, "handoff envelope")
    envelope_errors = BUNDLE.validate_handoff_envelope(envelope)
    if envelope_errors:
        raise TransportError(
            "integrity-failed",
            "Remote handoff envelope is invalid: " + "; ".join(envelope_errors),
        )
    if envelope["transport"]["kind"] != "github":
        raise TransportError("integrity-failed", "Envelope transport.kind is not github")
    if envelope["handoff_id"] != parsed["handoff_id"]:
        raise TransportError("integrity-failed", "Reference/envelope handoff IDs differ")
    project_id = envelope["project"]["id"]
    if project_token(project_id) != parsed["project_token"]:
        raise TransportError("project-mismatch", "Reference/envelope project identity differs")

    checkpoint_location = _artifact_path(project_id, envelope["checkpoint"], "checkpoint")
    if envelope["checkpoint"]["location"] != checkpoint_location:
        raise TransportError("integrity-failed", "Checkpoint location is non-canonical")
    checkpoint_text = _client_read(client, owner, repository, checkpoint_location)
    if checkpoint_text is None:
        raise TransportError("remote-not-found", "GitHub checkpoint artifact not found")
    checkpoint = _read_json(checkpoint_text, "checkpoint")

    planning: dict[str, Any] | None = None
    planning_meta = envelope.get("planning_snapshot")
    if planning_meta is not None:
        planning_location = _artifact_path(project_id, planning_meta, "planning")
        if planning_meta["location"] != planning_location:
            raise TransportError("integrity-failed", "Planning location is non-canonical")
        planning_text = _client_read(client, owner, repository, planning_location)
        if planning_text is None:
            raise TransportError("remote-not-found", "GitHub planning artifact not found")
        planning = _read_json(planning_text, "planning snapshot")

    try:
        verification = BUNDLE.verify_handoff_bundle(
            envelope,
            checkpoint,
            planning,
            checkpoint_validator=lambda cp: PCP.validate_checkpoint(cp, expect_sealed=True),
            checkpoint_digest=PCP.compute_content_digest,
        )
    except BUNDLE.HandoffBundleError as exc:
        code = exc.code if exc.code in {
            "invalid-envelope",
            "checkpoint-invalid",
            "checkpoint-unsealed",
            "integrity-failed",
            "project-mismatch",
        } else "integrity-failed"
        raise TransportError(code, exc.message) from exc
    return {
        "status": "resolved",
        "reference": reference_value,
        "envelope": envelope,
        "checkpoint": checkpoint,
        "planning_snapshot": planning,
        "verification": verification,
    }
