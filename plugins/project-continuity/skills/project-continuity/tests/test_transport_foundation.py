from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    """Load one sibling script as a test module."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


transports = load_module("pcp_transports", "transports.py")
bundle = load_module("pcp_handoff_bundle", "handoff_bundle.py")


def pcp_digest(checkpoint: dict) -> str:
    """Compute the minimal test PCP canonical digest."""
    clone = copy.deepcopy(checkpoint)
    clone["verification"]["content_digest"] = None
    raw = json.dumps(
        clone,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def checkpoint_validator(checkpoint: dict) -> list[str]:
    """Validate the minimal checkpoint shape needed by bundle tests."""
    required = {"protocol_version", "checkpoint_id", "project_id", "verification"}
    missing = required - set(checkpoint)
    return [f"missing {name}" for name in sorted(missing)]


def sealed_checkpoint() -> dict:
    """Return a sealed but surface-unverifiable test checkpoint."""
    checkpoint = {
        "protocol_version": "pcp/1",
        "checkpoint_id": "pcp-20260901-abcdef12",
        "project_id": "git-demo-project",
        "claims": [
            {
                "id": "C-1",
                "kind": "finding",
                "confidence": "reported",
                "statement": "Historical implementation claim remains reported.",
            }
        ],
        "verification": {
            "status": "sealed",
            "sealed_at": "2026-09-01T12:00:00Z",
            "content_digest": None,
            "policy": "evidence-required-v1",
            "surface_status": "unverifiable",
        },
    }
    checkpoint["verification"]["content_digest"] = pcp_digest(checkpoint)
    return checkpoint


def valid_planning() -> dict:
    """Return a valid planning sidecar fixture."""
    snapshot = {
        "format": "pcp-planning/1",
        "planning_id": "planning-20260901-abcdef12",
        "created_at": "2026-09-01T12:00:00Z",
        "project_id": "git-demo-project",
        "source_checkpoint": None,
        "vision": "Mobile continuity",
        "items": [
            {
                "id": "story-001",
                "kind": "story",
                "title": "Implement transport foundation",
                "status": "accepted",
                "parent_id": None,
                "priority": "high",
                "depends_on": [],
                "acceptance_criteria": ["Transport is explicit and typed."],
                "origin": {
                    "kind": "user_decision",
                    "ref": "session:R0",
                    "observed_at": "2026-09-01T12:00:00Z",
                },
                "supersedes": [],
                "evidence_refs": [],
                "repository_refs": [],
            }
        ],
        "decisions": [],
        "unresolved_questions": [],
        "content_digest": None,
    }
    snapshot["content_digest"] = bundle.compute_planning_digest(snapshot)
    return snapshot


def envelope_for(
    checkpoint: dict,
    planning: dict | None = None,
    *,
    kind: str = "file",
) -> dict:
    """Build a digest-bearing envelope for test artifacts."""
    planning_meta = None
    if planning is not None:
        planning_meta = {
            "id": planning["planning_id"],
            "digest": bundle.compute_planning_digest(planning),
            "location": "planning.json",
        }
    return {
        "format": "pcp-handoff/1",
        "handoff_id": "handoff-20260901-abcdef12",
        "created_at": "2026-09-01T12:00:00Z",
        "project": {
            "id": checkpoint["project_id"],
            "repository": "github:owner/repo",
        },
        "checkpoint": {
            "protocol": "pcp/1",
            "id": checkpoint["checkpoint_id"],
            "digest": checkpoint["verification"]["content_digest"],
            "location": "checkpoint.json",
        },
        "planning_snapshot": planning_meta,
        "transport": {"kind": kind},
    }


class ReferenceTests(unittest.TestCase):
    """Reference parsing and registry failure-mode coverage."""

    def test_file_reference_round_trip(self):
        """File references round-trip without transport guessing."""
        ref = transports.HandoffReference(
            "file",
            "local",
            "/tmp/pcp handoff.json",
        )
        parsed = transports.parse_reference(str(ref))
        self.assertEqual(parsed.kind, "file")
        self.assertEqual(parsed.authority, "local")
        self.assertEqual(parsed.path, "/tmp/pcp handoff.json")

    def test_github_reference_is_explicit(self):
        """GitHub references encode the transport explicitly."""
        parsed = transports.parse_reference(
            "pcp+github://owner/repo/projects/demo/handoffs/handoff-1.json"
        )
        self.assertEqual(parsed.kind, "github")
        self.assertEqual(parsed.authority, "owner")
        self.assertEqual(
            parsed.path,
            "/repo/projects/demo/handoffs/handoff-1.json",
        )

    def test_reference_rejects_implicit_path(self):
        """A raw filesystem path is not silently treated as a transport ref."""
        with self.assertRaises(transports.TransportError) as ctx:
            transports.parse_reference("/tmp/pcp-handoff.json")
        self.assertEqual(ctx.exception.code, "reference-invalid")

    def test_reference_rejects_credentials_query_and_fragment(self):
        """References reject common secret/routing smuggling surfaces."""
        bad = [
            "pcp+github://user:token@owner/repo/handoff.json",
            "pcp+github://owner/repo/handoff.json?token=secret",
            "pcp+github://owner/repo/handoff.json#fragment",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(
                transports.TransportError
            ) as ctx:
                transports.parse_reference(value)
            self.assertEqual(ctx.exception.code, "reference-invalid")

    def test_registry_rejects_unknown_transport(self):
        """Unknown transport kinds fail closed."""
        registry = transports.default_registry()
        with self.assertRaises(transports.TransportError) as ctx:
            registry.resolve("pcp+github://owner/repo/handoff.json")
        self.assertEqual(ctx.exception.code, "unsupported-transport")

    def test_registry_rejects_duplicate_registration(self):
        """Duplicate registration requires an explicit replacement decision."""
        registry = transports.default_registry()
        with self.assertRaises(transports.TransportError) as ctx:
            registry.register(transports.FileTransport())
        self.assertEqual(ctx.exception.code, "transport-unavailable")


class FileTransportTests(unittest.TestCase):
    """Authorized-root and byte-preservation coverage for local transport."""

    def test_publish_fetch_preserves_exact_bytes(self):
        """Publishing and fetching preserve artifact bytes exactly."""
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            source = root / "source.json"
            dest = root / "nested" / "pcp-handoff.json"
            payload = b'{"hello":"world"}\n'
            source.write_bytes(payload)
            transport = transports.FileTransport(allowed_root=root)

            descriptor = transport.publish_file(source, dest)
            self.assertEqual(dest.read_bytes(), payload)
            self.assertEqual(transport.fetch(descriptor), payload)
            self.assertEqual(
                transports.parse_reference(
                    str(descriptor.reference)
                ).kind,
                "file",
            )

    def test_publish_bytes_preserves_exact_bytes(self):
        """In-memory publication avoids arbitrary source-file reads."""
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            dest = root / "pcp-handoff.json"
            payload = b"opaque bytes\n"
            transport = transports.FileTransport(allowed_root=root)
            descriptor = transport.publish_bytes(payload, dest)
            self.assertEqual(descriptor.path.read_bytes(), payload)

    def test_verify_raw_transport_digest(self):
        """Raw transport byte digests fail closed on mutation."""
        payload = b"opaque handoff bytes"
        expected = "sha256:" + hashlib.sha256(payload).hexdigest()
        result = transports.FileTransport.verify(payload, expected)
        self.assertTrue(result["valid"])
        with self.assertRaises(transports.TransportError) as ctx:
            transports.FileTransport.verify(payload + b"x", expected)
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_fetch_missing_is_typed(self):
        """Missing authorized artifacts return a stable typed error."""
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            transport = transports.FileTransport(allowed_root=root)
            ref = transport.reference_for_path(root / "missing.json")
            with self.assertRaises(transports.TransportError) as ctx:
                transport.fetch(ref)
            self.assertEqual(ctx.exception.code, "remote-not-found")

    def test_publish_rejects_direct_symlink_destination(self):
        """A destination artifact cannot itself be a symlink."""
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            source = root / "source.json"
            target = root / "target.json"
            link = root / "link.json"
            source.write_text("{}\n", encoding="utf-8")
            target.write_text("unchanged\n", encoding="utf-8")
            transport = transports.FileTransport(allowed_root=root)
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaises(transports.TransportError) as ctx:
                transport.publish_file(source, link)
            self.assertEqual(ctx.exception.code, "transport-unavailable")
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged\n")

    def test_publish_rejects_destination_outside_authorized_root(self):
        """Caller-selected destinations cannot escape the authorized root."""
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            root = base / "authorized"
            outside = base / "outside" / "pcp-handoff.json"
            transport = transports.FileTransport(allowed_root=root)
            with self.assertRaises(transports.TransportError) as ctx:
                transport.publish_bytes(b"secret", outside)
            self.assertEqual(ctx.exception.code, "permission-denied")
            self.assertFalse(outside.exists())

    def test_publish_rejects_source_outside_authorized_root(self):
        """Caller-selected source files cannot be read outside the root."""
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            root = base / "authorized"
            root.mkdir()
            outside = base / "outside.json"
            outside.write_bytes(b"do not read")
            transport = transports.FileTransport(allowed_root=root)
            with self.assertRaises(transports.TransportError) as ctx:
                transport.publish_file(
                    outside,
                    root / "pcp-handoff.json",
                )
            self.assertEqual(ctx.exception.code, "permission-denied")

    def test_parent_symlink_escape_is_rejected(self):
        """A parent-directory symlink cannot redirect writes outside the root."""
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            root = base / "authorized"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            link_parent = root / "redirect"
            try:
                link_parent.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            transport = transports.FileTransport(allowed_root=root)
            with self.assertRaises(transports.TransportError) as ctx:
                transport.publish_bytes(
                    b"must stay inside",
                    link_parent / "pcp-handoff.json",
                )
            self.assertEqual(ctx.exception.code, "permission-denied")
            self.assertFalse((outside / "pcp-handoff.json").exists())


class BundleTests(unittest.TestCase):
    """Envelope/checkpoint/planning integrity coverage."""

    def test_sealed_portable_checkpoint_is_integrity_valid_but_unverifiable(self):
        """Sealed portable state can be integral while empirically unverified."""
        checkpoint = sealed_checkpoint()
        envelope = envelope_for(checkpoint)
        result = bundle.verify_handoff_bundle(
            envelope,
            checkpoint,
            checkpoint_validator=checkpoint_validator,
            checkpoint_digest=pcp_digest,
        )
        self.assertTrue(result["valid"])
        self.assertEqual(
            result["checkpoint"]["surface_status"],
            "unverifiable",
        )
        self.assertEqual(
            checkpoint["claims"][0]["confidence"],
            "reported",
        )

    def test_digest_bearing_envelope_rejects_draft_checkpoint(self):
        """Remote-style digest envelopes cannot point at unsealed drafts."""
        checkpoint = sealed_checkpoint()
        checkpoint["verification"]["status"] = "draft"
        checkpoint["verification"]["sealed_at"] = None
        checkpoint["verification"]["content_digest"] = None
        envelope = envelope_for(sealed_checkpoint())
        envelope["checkpoint"]["id"] = checkpoint["checkpoint_id"]
        with self.assertRaises(bundle.HandoffBundleError) as ctx:
            bundle.verify_handoff_bundle(
                envelope,
                checkpoint,
                checkpoint_validator=checkpoint_validator,
                checkpoint_digest=pcp_digest,
            )
        self.assertEqual(ctx.exception.code, "checkpoint-unsealed")

    def test_checkpoint_digest_mismatch_fails_closed(self):
        """Checkpoint envelope mutation fails canonical digest validation."""
        checkpoint = sealed_checkpoint()
        envelope = envelope_for(checkpoint)
        envelope["checkpoint"]["digest"] = "sha256:" + ("0" * 64)
        with self.assertRaises(bundle.HandoffBundleError) as ctx:
            bundle.verify_handoff_bundle(
                envelope,
                checkpoint,
                checkpoint_validator=checkpoint_validator,
                checkpoint_digest=pcp_digest,
            )
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_planning_snapshot_digest_and_project_are_verified(self):
        """Planning bytes are bound to project identity and canonical digest."""
        checkpoint = sealed_checkpoint()
        planning = valid_planning()
        envelope = envelope_for(checkpoint, planning)
        result = bundle.verify_handoff_bundle(
            envelope,
            checkpoint,
            planning,
            checkpoint_validator=checkpoint_validator,
            checkpoint_digest=pcp_digest,
        )
        self.assertTrue(result["planning_snapshot"]["valid"])

        tampered = copy.deepcopy(planning)
        tampered["vision"] = "tampered"
        with self.assertRaises(bundle.HandoffBundleError) as ctx:
            bundle.verify_handoff_bundle(
                envelope,
                checkpoint,
                tampered,
                checkpoint_validator=checkpoint_validator,
                checkpoint_digest=pcp_digest,
            )
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_verified_done_without_evidence_is_invalid(self):
        """Planning cannot claim verified completion without evidence refs."""
        planning = valid_planning()
        planning["items"][0]["status"] = "verified_done"
        planning["items"][0]["evidence_refs"] = []
        errors = bundle.validate_planning_snapshot(planning)
        self.assertTrue(
            any("verified_done requires" in error for error in errors)
        )

    def test_unknown_envelope_fields_are_rejected(self):
        """Unknown envelope fields fail closed to prevent semantic drift."""
        checkpoint = sealed_checkpoint()
        envelope = envelope_for(checkpoint)
        envelope["authority"] = "nope"
        errors = bundle.validate_handoff_envelope(envelope)
        self.assertTrue(
            any("unknown fields" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
