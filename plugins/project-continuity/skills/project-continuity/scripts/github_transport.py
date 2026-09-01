#!/usr/bin/env python3
"""Content-addressed GitHub transport for Project Continuity handoffs.

The module owns remote layout, publication safety, immutable/create-only object
semantics, and reference resolution. Network/authentication are deliberately
injected through a tiny client interface so the same contract can be bound to a
ChatGPT GitHub connector, a Codex host integration, or a test double without
persisting credentials in handoff references or plugin configuration.
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
HANDOFF_FILENAME_RE = re.compile(
    r"^(handoff-[A-Za-z0-9._-]{8,})\.([0-9a-f]{64})\.json$"
)
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_CONTINUITY_REPOSITORY = "project-continuity-state"


class GitHubTransportError(Exception):
    """Internal load/configuration failure before typed transport handling exists."""


def _load_sibling(name: str, filename: str):
    """Load a sibling module without requiring package installation."""
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise GitHubTransportError(f"Unable to load required sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


PCP = _load_sibling("pcp_github_transport_core", "continuity.py")
BUNDLE = _load_sibling("pcp_github_transport_bundle", "handoff_bundle.py")
TRANSPORTS = _load_sibling("pcp_github_transport_primitives", "transports.py")
TransportError = TRANSPORTS.TransportError
HandoffReference = TRANSPORTS.HandoffReference


def canonical_bytes(value: Any) -> bytes:
    """Serialize one JSON-compatible value using the transport canonical form."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a lower-case sha256:<hex> digest."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def now_utc() -> str:
    """Return an RFC3339 UTC timestamp without fractional seconds."""
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _hex(digest: str) -> str:
    """Extract the hex body of one canonical SHA-256 digest."""
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise TransportError("integrity-failed", "Expected sha256:<hex> digest")
    value = digest[7:]
    if HEX_DIGEST_RE.fullmatch(value) is None:
        raise TransportError("integrity-failed", "Expected sha256:<64 lowercase hex> digest")
    return value


def _validate_owner_repo(owner: str, repository: str) -> None:
    """Reject malformed GitHub owner/repository locators."""
    if OWNER_RE.fullmatch(owner or "") is None:
        raise TransportError("reference-invalid", f"Invalid GitHub owner: {owner!r}")
    if REPO_RE.fullmatch(repository or "") is None or repository in {".", ".."}:
        raise TransportError("reference-invalid", f"Invalid GitHub repository: {repository!r}")


def project_token(project_id: str) -> str:
    """Map an arbitrary PCP project ID to a path-safe stable token."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise TransportError("project-mismatch", "project_id must be a non-empty string")
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:24]


def checkpoint_path(project_id: str, checkpoint: dict[str, Any]) -> str:
    """Return the canonical immutable GitHub path for a sealed checkpoint."""
    checkpoint_id = checkpoint.get("checkpoint_id")
    digest = checkpoint.get("verification", {}).get("content_digest")
    if not isinstance(checkpoint_id, str):
        raise TransportError("checkpoint-invalid", "Checkpoint ID is missing")
    return (
        f"projects/{project_token(project_id)}/checkpoints/"
        f"{checkpoint_id}.{_hex(digest)}.json"
    )


def planning_path(project_id: str, planning: dict[str, Any]) -> str:
    """Return the canonical immutable GitHub path for a planning snapshot."""
    planning_id = planning.get("planning_id")
    digest = planning.get("content_digest")
    if not isinstance(planning_id, str):
        raise TransportError("integrity-failed", "Planning ID is missing")
    return (
        f"projects/{project_token(project_id)}/planning/"
        f"{planning_id}.{_hex(digest)}.json"
    )


def _handoff_id(
    *,
    project_id: str,
    checkpoint_digest: str,
    planning_digest: str | None,
    owner: str,
    repository: str,
) -> str:
    """Derive a stable handoff ID from exact bundle identity and store target."""
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
    """Return a content-addressed envelope path embedding the raw envelope digest."""
    envelope_hex = hashlib.sha256(envelope_bytes).hexdigest()
    return (
        f"projects/{project_token(project_id)}/handoffs/"
        f"{handoff_id}.{envelope_hex}.json"
    )


def build_envelope(
    checkpoint: dict[str, Any],
    planning: dict[str, Any] | None,
    *,
    owner: str,
    repository: str,
    created_at: str | None = None,
    project_repository: str | None = None,
) -> tuple[dict[str, Any], bytes, HandoffReference]:
    """Build a validated GitHub envelope and compact content-addressed reference."""
    _validate_owner_repo(owner, repository)
    checkpoint_errors = PCP.validate_checkpoint(checkpoint, expect_sealed=True)
    if checkpoint_errors:
        raise TransportError(
            "checkpoint-invalid",
            "Invalid sealed checkpoint: " + "; ".join(checkpoint_errors),
        )
    checkpoint_digest = checkpoint["verification"]["content_digest"]
    computed_checkpoint = PCP.compute_content_digest(checkpoint)
    if checkpoint_digest != computed_checkpoint:
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
            raise TransportError(
                "project-mismatch",
                "Planning project_id does not match checkpoint project_id",
            )
        planning_digest = planning.get("content_digest")
        if planning_digest != BUNDLE.compute_planning_digest(planning):
            raise TransportError("integrity-failed", "Planning canonical digest mismatch")
        planning_meta = {
            "id": planning["planning_id"],
            "digest": planning_digest,
            "location": planning_path(project_id, planning),
        }

    handoff_id = _handoff_id(
        project_id=project_id,
        checkpoint_digest=checkpoint_digest,
        planning_digest=planning_digest,
        owner=owner,
        repository=repository,
    )
    envelope = {
        "format": BUNDLE.HANDOFF_FORMAT,
        "handoff_id": handoff_id,
        "created_at": created_at or now_utc(),
        "project": {
            "id": project_id,
            "repository": project_repository,
        },
        "checkpoint": {
            "protocol": PCP.PROTOCOL,
            "id": checkpoint["checkpoint_id"],
            "digest": checkpoint_digest,
            "location": checkpoint_path(project_id, checkpoint),
        },
        "planning_snapshot": planning_meta,
        "transport": {"kind": "github"},
    }
    envelope_errors = BUNDLE.validate_handoff_envelope(envelope)
    if envelope_errors:
        raise TransportError(
            "integrity-failed",
            "Generated GitHub envelope is invalid: " + "; ".join(envelope_errors),
        )
    envelope_bytes = canonical_bytes(envelope)
    path = handoff_path(project_id, handoff_id, envelope_bytes)
    reference = HandoffReference(
        kind="github",
        authority=owner,
        path=f"/{repository}/{path}",
    )
    return envelope, envelope_bytes, reference


def _repo_is_public(info: dict[str, Any]) -> bool:
    """Classify a repository as public without treating internal as public."""
    visibility = str(info.get("visibility") or "").lower()
    if visibility == "public":
        return True
    if visibility in {"private", "internal"}:
        return False
    private = info.get("private")
    return private is False


def _client_read(client: Any, owner: str, repository: str, path: str) -> str | None:
    """Read one UTF-8 file through the injected client contract."""
    method = getattr(client, "read_text_file", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks read_text_file")
    value = method(owner, repository, path)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TransportError("transport-unavailable", "GitHub client returned non-text artifact")
    return value


def _client_create(
    client: Any,
    owner: str,
    repository: str,
    path: str,
    content: str,
    message: str,
) -> None:
    """Create one immutable UTF-8 object through the injected client contract."""
    method = getattr(client, "create_text_file", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks create_text_file")
    method(owner, repository, path, content, message)


def _ensure_immutable_object(
    client: Any,
    owner: str,
    repository: str,
    path: str,
    content: str,
    *,
    message: str,
) -> None:
    """Create an object once or accept an exact idempotent existing copy."""
    existing = _client_read(client, owner, repository, path)
    if existing is None:
        _client_create(client, owner, repository, path, content, message)
        existing = _client_read(client, owner, repository, path)
        if existing is None:
            raise TransportError(
                "remote-not-found",
                f"GitHub object was not readable after create: {path}",
            )
    if existing.encode("utf-8") != content.encode("utf-8"):
        raise TransportError(
            "integrity-failed",
            f"Immutable GitHub object path already contains different bytes: {path}",
        )


def _assert_safe_target(client: Any, owner: str, repository: str, *, allow_public: bool) -> dict[str, Any]:
    """Fail closed on a public repository unless current-user approval is explicit."""
    method = getattr(client, "get_repository", None)
    if not callable(method):
        raise TransportError("transport-unavailable", "GitHub client lacks get_repository")
    info = method(owner, repository)
    if not isinstance(info, dict):
        raise TransportError("transport-unavailable", "GitHub repository metadata is unavailable")
    if _repo_is_public(info) and not allow_public:
        raise TransportError(
            "unsafe-publication-target",
            f"Refusing to publish continuity state to public repository {owner}/{repository}",
        )
    return info


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
    """Publish checkpoint/planning/envelope create-only, then re-fetch and verify."""
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
    project_id = checkpoint["project_id"]
    checkpoint_bytes = canonical_bytes(checkpoint)
    checkpoint_location = envelope["checkpoint"]["location"]
    _ensure_immutable_object(
        client,
        owner,
        repository,
        checkpoint_location,
        checkpoint_bytes.decode("utf-8"),
        message=f"pcp: publish checkpoint {checkpoint['checkpoint_id']}",
    )

    planning_location: str | None = None
    if planning is not None:
        planning_location = envelope["planning_snapshot"]["location"]
        _ensure_immutable_object(
            client,
            owner,
            repository,
            planning_location,
            canonical_bytes(planning).decode("utf-8"),
            message=f"pcp: publish planning {planning['planning_id']}",
        )

    parsed_reference = parse_github_reference(str(reference))
    _ensure_immutable_object(
        client,
        owner,
        repository,
        parsed_reference["path"],
        envelope_bytes.decode("utf-8"),
        message=f"pcp: publish handoff {envelope['handoff_id']}",
    )

    resolved = resolve_bundle(client, str(reference))
    return {
        "status": "published",
        "reference": str(reference),
        "owner": owner,
        "repository": repository,
        "project_id": project_id,
        "checkpoint_id": checkpoint["checkpoint_id"],
        "checkpoint_digest": checkpoint["verification"]["content_digest"],
        "planning_id": planning.get("planning_id") if planning else None,
        "planning_digest": planning.get("content_digest") if planning else None,
        "envelope_digest": sha256_bytes(envelope_bytes),
        "paths": {
            "checkpoint": checkpoint_location,
            "planning": planning_location,
            "handoff": parsed_reference["path"],
        },
        "verification": resolved["verification"],
    }


def parse_github_reference(value: str) -> dict[str, str]:
    """Parse one canonical content-addressed pcp+github reference."""
    reference = TRANSPORTS.parse_reference(value)
    if reference.kind != "github":
        raise TransportError("unsupported-transport", "Reference is not a GitHub handoff")
    owner = reference.authority
    segments = [part for part in reference.path.split("/") if part]
    if len(segments) < 6:
        raise TransportError("reference-invalid", "GitHub handoff reference path is incomplete")
    repository = segments[0]
    _validate_owner_repo(owner, repository)
    relative = "/".join(segments[1:])
    if segments[1] != "projects" or segments[3] != "handoffs":
        raise TransportError("reference-invalid", "GitHub handoff reference has non-canonical layout")
    project_part = segments[2]
    if re.fullmatch(r"[0-9a-f]{24}", project_part) is None:
        raise TransportError("reference-invalid", "GitHub handoff project token is invalid")
    match = HANDOFF_FILENAME_RE.fullmatch(segments[4]) if len(segments) == 5 else None
    if match is None:
        # Expected path after repository: projects/<token>/handoffs/<file>.
        if len(segments) != 5:
            raise TransportError("reference-invalid", "GitHub handoff reference contains unexpected path segments")
        match = HANDOFF_FILENAME_RE.fullmatch(segments[4])
    if match is None:
        raise TransportError("reference-invalid", "GitHub handoff filename is invalid")
    return {
        "owner": owner,
        "repository": repository,
        "path": relative,
        "project_token": project_part,
        "handoff_id": match.group(1),
        "envelope_hex": match.group(2),
    }


def _read_json_object(text: str, *, label: str) -> dict[str, Any]:
    """Parse one remote JSON object with typed failure semantics."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TransportError("integrity-failed", f"Invalid JSON in remote {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransportError("integrity-failed", f"Remote {label} must be a JSON object")
    return value


def _expected_artifact_path(
    project_id: str,
    meta: dict[str, Any],
    *,
    kind: str,
) -> str:
    """Derive the only accepted content-addressed artifact location."""
    token = project_token(project_id)
    if kind == "checkpoint":
        return f"projects/{token}/checkpoints/{meta['id']}.{_hex(meta['digest'])}.json"
    if kind == "planning":
        return f"projects/{token}/planning/{meta['id']}.{_hex(meta['digest'])}.json"
    raise AssertionError(kind)


def resolve_bundle(client: Any, reference_value: str) -> dict[str, Any]:
    """Resolve, content-verify, and semantically verify one GitHub handoff bundle."""
    parsed = parse_github_reference(reference_value)
    owner = parsed["owner"]
    repository = parsed["repository"]
    envelope_text = _client_read(client, owner, repository, parsed["path"])
    if envelope_text is None:
        raise TransportError("remote-not-found", "GitHub handoff envelope was not found")
    envelope_bytes = envelope_text.encode("utf-8")
    actual_envelope_hex = hashlib.sha256(envelope_bytes).hexdigest()
    if actual_envelope_hex != parsed["envelope_hex"]:
        raise TransportError(
            "integrity-failed",
            "GitHub handoff envelope bytes do not match digest embedded in reference",
        )
    envelope = _read_json_object(envelope_text, label="handoff envelope")
    envelope_errors = BUNDLE.validate_handoff_envelope(envelope)
    if envelope_errors:
        raise TransportError(
            "integrity-failed",
            "Remote handoff envelope is invalid: " + "; ".join(envelope_errors),
        )
    if envelope["transport"]["kind"] != "github":
        raise TransportError("integrity-failed", "Remote envelope transport.kind is not github")
    if envelope["handoff_id"] != parsed["handoff_id"]:
        raise TransportError("integrity-failed", "Reference handoff ID does not match envelope")
    if project_token(envelope["project"]["id"]) != parsed["project_token"]:
        raise TransportError("project-mismatch", "Reference project token does not match envelope project")

    expected_checkpoint_path = _expected_artifact_path(
        envelope["project"]["id"],
        envelope["checkpoint"],
        kind="checkpoint",
    )
    if envelope["checkpoint"]["location"] != expected_checkpoint_path:
        raise TransportError("integrity-failed", "Checkpoint location is not canonical/content-addressed")
    checkpoint_text = _client_read(client, owner, repository, expected_checkpoint_path)
    if checkpoint_text is None:
        raise TransportError("remote-not-found", "GitHub checkpoint artifact was not found")
    checkpoint = _read_json_object(checkpoint_text, label="checkpoint")

    planning: dict[str, Any] | None = None
    planning_meta = envelope.get("planning_snapshot")
    if planning_meta is not None:
        expected_planning_path = _expected_artifact_path(
            envelope["project"]["id"],
            planning_meta,
            kind="planning",
        )
        if planning_meta["location"] != expected_planning_path:
            raise TransportError("integrity-failed", "Planning location is not canonical/content-addressed")
        planning_text = _client_read(client, owner, repository, expected_planning_path)
        if planning_text is None:
            raise TransportError("remote-not-found", "GitHub planning artifact was not found")
        planning = _read_json_object(planning_text, label="planning snapshot")

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
