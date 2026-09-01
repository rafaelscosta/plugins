#!/usr/bin/env python3
"""Transport primitives for Project Continuity mobile-first handoffs.

This module is deliberately independent from PCP checkpoint semantics. A
transport moves bytes and resolves locators; it never upgrades claims, promotes
continuity HEAD, or interprets commands embedded in transported content.
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
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class HandoffReference:
    """Parsed transport reference.

    References identify how to locate a handoff envelope. They contain routing
    information only and must never contain credentials, query tokens, or
    fragments.
    """

    kind: str
    authority: str
    path: str

    def to_uri(self) -> str:
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
        return self.to_uri()


def _reject_unsafe_reference_text(value: str) -> None:
    if not value or len(value) > MAX_REFERENCE_LENGTH:
        raise TransportError("reference-invalid", "Handoff reference is empty or too long")
    if value != value.strip():
        raise TransportError("reference-invalid", "Handoff reference must not contain leading or trailing whitespace")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise TransportError("reference-invalid", "Handoff reference contains control characters")


def parse_reference(value: str) -> HandoffReference:
    """Parse an explicit pcp+<transport> URI without guessing transport."""

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
        raise TransportError("reference-invalid", "pcp+file references may only use the local authority")
    if kind == "github":
        segments = [part for part in path.split("/") if part]
        if not authority or not segments:
            raise TransportError(
                "reference-invalid",
                "pcp+github references require owner authority and repository path",
            )

    return HandoffReference(kind=kind, authority=authority, path=path)


class TransportRegistry:
    """Explicit transport registry. Unknown kinds fail closed."""

    def __init__(self) -> None:
        self._transports: dict[str, Any] = {}

    def register(self, transport: Any, *, replace: bool = False) -> None:
        kind = getattr(transport, "kind", None)
        if not isinstance(kind, str) or not TRANSPORT_KIND_RE.fullmatch(kind):
            raise TransportError("transport-unavailable", "Transport must expose a valid lowercase kind")
        if kind in self._transports and not replace:
            raise TransportError("transport-unavailable", f"Transport already registered: {kind}")
        self._transports[kind] = transport

    def get(self, kind: str) -> Any:
        transport = self._transports.get(kind)
        if transport is None:
            raise TransportError("unsupported-transport", f"Unsupported handoff transport: {kind}")
        return transport

    def resolve(self, value: str) -> tuple[Any, HandoffReference]:
        ref = parse_reference(value)
        return self.get(ref.kind), ref


@dataclass(frozen=True)
class FileDescriptor:
    path: pathlib.Path
    reference: HandoffReference


class FileTransport:
    """Legacy-compatible local file transport.

    The adapter copies and fetches opaque bytes. It intentionally does not parse
    PCP checkpoints or envelopes.
    """

    kind = "file"

    @staticmethod
    def default_path() -> pathlib.Path:
        return pathlib.Path.home() / "Downloads" / HANDOFF_FILENAME

    @staticmethod
    def _path(value: str | os.PathLike[str]) -> pathlib.Path:
        return pathlib.Path(value).expanduser().absolute()

    @classmethod
    def reference_for_path(cls, value: str | os.PathLike[str]) -> HandoffReference:
        path = cls._path(value)
        return HandoffReference(kind="file", authority="local", path=path.as_posix())

    @classmethod
    def resolve(cls, ref: str | HandoffReference) -> FileDescriptor:
        parsed = parse_reference(ref) if isinstance(ref, str) else ref
        if parsed.kind != cls.kind:
            raise TransportError("unsupported-transport", f"File transport cannot resolve {parsed.kind!r}")
        if parsed.authority not in {"", "local"}:
            raise TransportError("reference-invalid", "File reference authority must be local")
        path = cls._path(parsed.path)
        return FileDescriptor(path=path, reference=parsed)

    @staticmethod
    def _reject_symlink(path: pathlib.Path, *, label: str) -> None:
        if path.is_symlink():
            raise TransportError("transport-unavailable", f"{label} must not be a symlink: {path}")

    @classmethod
    def publish_file(
        cls,
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str] | None = None,
    ) -> FileDescriptor:
        src = cls._path(source)
        cls._reject_symlink(src, label="Source handoff artifact")
        if not src.is_file():
            raise TransportError("remote-not-found", f"Source handoff artifact not found: {src}")

        dest = cls._path(destination) if destination is not None else cls.default_path().absolute()
        cls._reject_symlink(dest, label="Handoff destination")
        if dest.exists() and dest.is_dir():
            raise TransportError("transport-unavailable", f"Handoff destination is a directory: {dest}")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
            tmp = pathlib.Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, dest)
            finally:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
        except PermissionError as exc:
            raise TransportError("permission-denied", f"Permission denied publishing handoff to {dest}") from exc
        except OSError as exc:
            raise TransportError("transport-unavailable", f"Unable to publish handoff to {dest}: {exc}") from exc

        return FileDescriptor(path=dest, reference=cls.reference_for_path(dest))

    @classmethod
    def fetch(cls, ref: str | HandoffReference | FileDescriptor) -> bytes:
        descriptor = ref if isinstance(ref, FileDescriptor) else cls.resolve(ref)
        path = descriptor.path
        cls._reject_symlink(path, label="Handoff artifact")
        if not path.is_file():
            raise TransportError("remote-not-found", f"Handoff artifact not found: {path}")
        try:
            return path.read_bytes()
        except PermissionError as exc:
            raise TransportError("permission-denied", f"Permission denied reading handoff artifact: {path}") from exc
        except OSError as exc:
            raise TransportError("transport-unavailable", f"Unable to read handoff artifact {path}: {exc}") from exc

    @staticmethod
    def verify(data: bytes, expected_sha256: str) -> dict[str, Any]:
        if not SHA256_RE.fullmatch(expected_sha256):
            raise TransportError("integrity-failed", "Expected digest must be sha256:<64 lowercase hex>")
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != expected_sha256:
            raise TransportError(
                "integrity-failed",
                f"Transport byte digest mismatch: expected {expected_sha256}, computed {actual}",
            )
        return {"valid": True, "expected": expected_sha256, "actual": actual}

    @classmethod
    def describe(cls, ref: str | HandoffReference | FileDescriptor) -> dict[str, str]:
        descriptor = ref if isinstance(ref, FileDescriptor) else cls.resolve(ref)
        return {
            "kind": cls.kind,
            "reference": str(descriptor.reference),
            "path": str(descriptor.path),
        }


def default_registry() -> TransportRegistry:
    registry = TransportRegistry()
    registry.register(FileTransport())
    return registry
