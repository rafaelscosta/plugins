#!/usr/bin/env python3
"""Transport primitives for Project Continuity mobile-first handoffs.

This module is deliberately independent from PCP checkpoint semantics. A
transport moves bytes and resolves locators; it never upgrades claims, promotes
continuity HEAD, or interprets commands embedded in transported content.

The local file adapter is root-scoped by construction. Callers must explicitly
choose the authorized artifact root; the default registry is limited to
``~/Downloads`` for legacy compatibility.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import tempfile
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, unquote, urlsplit

HANDOFF_FILENAME = "pcp-handoff.json"
REFERENCE_PREFIX = "pcp+"
MAX_REFERENCE_LENGTH = 2048
TRANSPORT_KIND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class TransportError(Exception):
    """Typed transport failure suitable for stable CLI/agent handling."""

    def __init__(self, code: str, message: str):
        """Create a typed transport error."""
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        """Return a stable machine-readable error shape."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class HandoffReference:
    """Parsed transport reference with routing metadata only."""

    kind: str
    authority: str
    path: str

    def to_uri(self) -> str:
        """Serialize the reference without adding credentials or query data."""
        scheme = f"{REFERENCE_PREFIX}{self.kind}"
        authority = self.authority
        encoded_path = quote(self.path, safe="/-._~:")
        if authority:
            if not encoded_path.startswith("/"):
                encoded_path = "/" + encoded_path
            return f"{scheme}://{authority}{encoded_path}"
        if not encoded_path.startswith("/"):
            encoded_path = "/" + encoded_path
        return f"{scheme}://{encoded_path}"

    def __str__(self) -> str:
        """Return the canonical URI representation."""
        return self.to_uri()


def _reject_unsafe_reference_text(value: str) -> None:
    """Reject reference text that can hide or smuggle routing data."""
    if not value or len(value) > MAX_REFERENCE_LENGTH:
        raise TransportError("reference-invalid", "Handoff reference is empty or too long")
    if value != value.strip():
        raise TransportError(
            "reference-invalid",
            "Handoff reference must not contain leading or trailing whitespace",
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise TransportError("reference-invalid", "Handoff reference contains control characters")


def parse_reference(value: str) -> HandoffReference:
    """Parse an explicit ``pcp+<transport>`` URI without guessing transport."""
    _reject_unsafe_reference_text(value)
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if not scheme.startswith(REFERENCE_PREFIX):
        raise TransportError(
            "reference-invalid",
            f"Handoff reference must use an explicit {REFERENCE_PREFIX}<transport> scheme",
        )
    kind = scheme[len(REFERENCE_PREFIX):]
    if not TRANSPORT_KIND_RE.fullmatch(kind):
        raise TransportError("reference-invalid", f"Invalid transport kind in reference: {kind!r}")
    if parsed.query or parsed.fragment:
        raise TransportError(
            "reference-invalid",
            "Handoff references must not contain query strings or fragments",
        )
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise TransportError(
            "reference-invalid",
            "Handoff references must not contain embedded credentials",
        )

    authority = parsed.netloc
    path = unquote(parsed.path)
    if not path:
        raise TransportError("reference-invalid", "Handoff reference path is required")

    if kind == "file" and authority not in {"", "local"}:
        raise TransportError(
            "reference-invalid",
            "pcp+file references may only use the local authority",
        )
    if kind == "github":
        segments = [part for part in path.split("/") if part]
        if not authority or not segments:
            raise TransportError(
                "reference-invalid",
                "pcp+github references require owner authority and repository path",
            )

    return HandoffReference(kind=kind, authority=authority, path=path)


class TransportRegistry:
    """Explicit transport registry where unknown kinds fail closed."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._transports: dict[str, Any] = {}

    def register(self, transport: Any, *, replace: bool = False) -> None:
        """Register one explicit transport implementation."""
        kind = getattr(transport, "kind", None)
        if not isinstance(kind, str) or not TRANSPORT_KIND_RE.fullmatch(kind):
            raise TransportError(
                "transport-unavailable",
                "Transport must expose a valid lowercase kind",
            )
        if kind in self._transports and not replace:
            raise TransportError(
                "transport-unavailable",
                f"Transport already registered: {kind}",
            )
        self._transports[kind] = transport

    def get(self, kind: str) -> Any:
        """Return a registered transport or fail closed."""
        transport = self._transports.get(kind)
        if transport is None:
            raise TransportError(
                "unsupported-transport",
                f"Unsupported handoff transport: {kind}",
            )
        return transport

    def resolve(self, value: str) -> tuple[Any, HandoffReference]:
        """Parse a reference and return its explicitly registered transport."""
        ref = parse_reference(value)
        return self.get(ref.kind), ref


@dataclass(frozen=True)
class FileDescriptor:
    """Authorized local artifact descriptor."""

    path: pathlib.Path
    reference: HandoffReference


class FileTransport:
    """Root-scoped local file transport for opaque handoff bytes.

    The adapter never interprets artifact content. Every read/write is confined
    to ``allowed_root`` after resolving parent directories, which prevents a
    caller-selected path or parent symlink from escaping the authorized artifact
    root.
    """

    kind = "file"

    def __init__(self, allowed_root: str | os.PathLike[str] | None = None) -> None:
        """Create a file transport scoped to one authorized root."""
        root = allowed_root if allowed_root is not None else self.default_path().parent
        self.allowed_root = self._path(root)

    @staticmethod
    def default_path() -> pathlib.Path:
        """Return the historical Downloads interchange path."""
        return pathlib.Path.home() / "Downloads" / HANDOFF_FILENAME

    @staticmethod
    def _path(value: str | os.PathLike[str]) -> pathlib.Path:
        """Normalize a path lexically without following symlinks."""
        return pathlib.Path(
            os.path.abspath(os.path.expanduser(os.fspath(value)))
        )

    @staticmethod
    def _is_within(candidate: pathlib.Path, root: pathlib.Path) -> bool:
        """Return whether ``candidate`` is contained by ``root``."""
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _reject_symlink(path: pathlib.Path, *, label: str) -> None:
        """Reject a direct symlink artifact."""
        if path.is_symlink():
            raise TransportError(
                "transport-unavailable",
                f"{label} must not be a symlink: {path}",
            )

    def _resolved_root(self) -> pathlib.Path:
        """Create and resolve the authorized root, rejecting a symlink root."""
        try:
            self.allowed_root.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise TransportError(
                "permission-denied",
                f"Permission denied creating authorized file transport root: {self.allowed_root}",
            ) from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to create authorized file transport root {self.allowed_root}: {exc}",
            ) from exc
        self._reject_symlink(self.allowed_root, label="Authorized file transport root")
        return self.allowed_root.resolve(strict=True)

    def _authorize_existing(self, path: pathlib.Path, *, label: str) -> pathlib.Path:
        """Resolve an existing artifact and prove it remains under the root."""
        root = self._resolved_root()
        self._reject_symlink(path, label=label)
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise TransportError("remote-not-found", f"{label} not found: {path}") from exc
        except PermissionError as exc:
            raise TransportError("permission-denied", f"Permission denied reading {label}: {path}") from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to resolve {label} {path}: {exc}",
            ) from exc
        if not self._is_within(resolved, root):
            raise TransportError(
                "permission-denied",
                f"{label} is outside the authorized file transport root: {path}",
            )
        return resolved

    def _authorize_destination(self, path: pathlib.Path) -> pathlib.Path:
        """Resolve a destination parent and prevent parent-symlink root escape."""
        root = self._resolved_root()
        if not self._is_within(path, self.allowed_root):
            raise TransportError(
                "permission-denied",
                f"Handoff destination is outside the authorized file transport root: {path}",
            )
        self._reject_symlink(path, label="Handoff destination")
        if path.exists() and path.is_dir():
            raise TransportError(
                "transport-unavailable",
                f"Handoff destination is a directory: {path}",
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = path.parent.resolve(strict=True)
        except PermissionError as exc:
            raise TransportError(
                "permission-denied",
                f"Permission denied preparing handoff destination: {path}",
            ) from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to prepare handoff destination {path}: {exc}",
            ) from exc
        if not self._is_within(resolved_parent, root):
            raise TransportError(
                "permission-denied",
                f"Handoff destination parent escapes the authorized file transport root: {path}",
            )
        resolved = resolved_parent / path.name
        if resolved.exists():
            self._reject_symlink(resolved, label="Handoff destination")
            if resolved.is_dir():
                raise TransportError(
                    "transport-unavailable",
                    f"Handoff destination is a directory: {resolved}",
                )
        return resolved

    def reference_for_path(self, value: str | os.PathLike[str]) -> HandoffReference:
        """Create a canonical local reference for an authorized path."""
        path = self._path(value)
        if path.exists():
            authorized = self._authorize_existing(path, label="Handoff artifact")
        else:
            authorized = self._authorize_destination(path)
        return HandoffReference(
            kind="file",
            authority="local",
            path=authorized.as_posix(),
        )

    def resolve(self, ref: str | HandoffReference) -> FileDescriptor:
        """Parse a file reference without reading bytes."""
        parsed = parse_reference(ref) if isinstance(ref, str) else ref
        if parsed.kind != self.kind:
            raise TransportError(
                "unsupported-transport",
                f"File transport cannot resolve {parsed.kind!r}",
            )
        if parsed.authority not in {"", "local"}:
            raise TransportError(
                "reference-invalid",
                "File reference authority must be local",
            )
        path = self._path(parsed.path)
        return FileDescriptor(path=path, reference=parsed)

    def publish_bytes(
        self,
        data: bytes,
        destination: str | os.PathLike[str] | None = None,
    ) -> FileDescriptor:
        """Atomically publish opaque bytes inside the authorized root."""
        if not isinstance(data, (bytes, bytearray)):
            raise TransportError(
                "transport-unavailable",
                "File transport publish_bytes requires bytes",
            )
        dest = self._path(destination) if destination is not None else self.default_path()
        resolved_dest = self._authorize_destination(dest)
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{resolved_dest.name}.",
                suffix=".tmp",
                dir=str(resolved_dest.parent),
            )
            tmp = pathlib.Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(bytes(data))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, resolved_dest)
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
        except PermissionError as exc:
            raise TransportError(
                "permission-denied",
                f"Permission denied publishing handoff to {resolved_dest}",
            ) from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to publish handoff to {resolved_dest}: {exc}",
            ) from exc
        return FileDescriptor(
            path=resolved_dest,
            reference=HandoffReference(
                kind="file",
                authority="local",
                path=resolved_dest.as_posix(),
            ),
        )

    def publish_file(
        self,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str] | None = None,
    ) -> FileDescriptor:
        """Copy one authorized source artifact as opaque bytes."""
        src = self._path(source)
        resolved_src = self._authorize_existing(
            src,
            label="Source handoff artifact",
        )
        if not resolved_src.is_file():
            raise TransportError(
                "remote-not-found",
                f"Source handoff artifact is not a file: {resolved_src}",
            )
        try:
            data = resolved_src.read_bytes()
        except PermissionError as exc:
            raise TransportError(
                "permission-denied",
                f"Permission denied reading source handoff artifact: {resolved_src}",
            ) from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to read source handoff artifact {resolved_src}: {exc}",
            ) from exc
        return self.publish_bytes(data, destination)

    def fetch(self, ref: str | HandoffReference | FileDescriptor) -> bytes:
        """Fetch exact artifact bytes after authorized-root verification."""
        descriptor = ref if isinstance(ref, FileDescriptor) else self.resolve(ref)
        path = self._authorize_existing(
            descriptor.path,
            label="Handoff artifact",
        )
        if not path.is_file():
            raise TransportError(
                "remote-not-found",
                f"Handoff artifact is not a file: {path}",
            )
        try:
            return path.read_bytes()
        except PermissionError as exc:
            raise TransportError(
                "permission-denied",
                f"Permission denied reading handoff artifact: {path}",
            ) from exc
        except OSError as exc:
            raise TransportError(
                "transport-unavailable",
                f"Unable to read handoff artifact {path}: {exc}",
            ) from exc

    @staticmethod
    def verify(data: bytes, expected_sha256: str) -> dict[str, Any]:
        """Verify a caller-supplied SHA-256 digest for opaque bytes."""
        if not SHA256_RE.fullmatch(expected_sha256):
            raise TransportError(
                "integrity-failed",
                "Expected digest must be sha256:<64 lowercase hex>",
            )
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise TransportError(
                "integrity-failed",
                f"Transport byte digest mismatch: expected {expected_sha256}, computed {actual}",
            )
        return {"valid": True, "expected": expected_sha256, "actual": actual}

    def describe(
        self,
        ref: str | HandoffReference | FileDescriptor,
    ) -> dict[str, str]:
        """Describe an artifact only after proving it is authorized."""
        descriptor = ref if isinstance(ref, FileDescriptor) else self.resolve(ref)
        path = self._authorize_existing(
            descriptor.path,
            label="Handoff artifact",
        )
        canonical_ref = HandoffReference(
            kind=self.kind,
            authority="local",
            path=path.as_posix(),
        )
        return {
            "kind": self.kind,
            "reference": str(canonical_ref),
            "path": str(path),
            "allowed_root": str(self._resolved_root()),
        }


def default_registry() -> TransportRegistry:
    """Return the legacy-compatible registry scoped to ``~/Downloads``."""
    registry = TransportRegistry()
    registry.register(FileTransport())
    return registry
