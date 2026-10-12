from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    """Load one skill script for direct behavior tests."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


github = load_module("pcp_github_transport_test", "github_transport.py")
PCP = github.PCP
BUNDLE = github.BUNDLE


class FakeGitHubClient:
    """Minimal injected client matching the host-binding contract."""

    def __init__(self, *, visibility: str = "private") -> None:
        self.visibility = visibility
        self.files: dict[tuple[str, str, str], str] = {}
        self.create_calls: list[tuple[str, str, str]] = []

    def get_repository(self, owner: str, repository: str) -> dict:
        """Return repository visibility metadata."""
        return {
            "owner": owner,
            "name": repository,
            "visibility": self.visibility,
            "private": self.visibility == "private",
        }

    def read_text_file(self, owner: str, repository: str, path: str) -> str | None:
        """Return exact stored text or None when absent."""
        return self.files.get((owner, repository, path))

    def create_text_file(
        self,
        owner: str,
        repository: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        """Create one path once and reject overwrite semantics."""
        key = (owner, repository, path)
        if key in self.files:
            raise AssertionError(f"test client refuses overwrite: {path}")
        self.files[key] = content
        self.create_calls.append(key)


def sealed_checkpoint() -> dict:
    """Build one fully valid sealed PORTABLE PCP/1 checkpoint."""
    checkpoint = {
        "protocol_version": "pcp/1",
        "checkpoint_id": "pcp-20260901T150000Z-abcdef12",
        "created_at": "2026-09-01T15:00:00Z",
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": "session:test",
        },
        "project_id": "git-demo-project",
        "parent": {"checkpoint_id": None, "content_digest": None},
        "baseline": {"root_hint": ".", "git": None, "files": []},
        "objective": {
            "current": "Continue the mobile handoff project",
            "definition_of_done": ["Codex can reconcile the handoff."],
        },
        "claims": [
            {
                "id": "C-001",
                "kind": "decision",
                "confidence": "reported",
                "statement": "Use the GitHub mobile transport.",
                "evidence": [],
                "supersedes": [],
            }
        ],
        "evidence": [],
        "open_work": [],
        "next_action": {
            "work_item_id": None,
            "instruction": "Reconcile against the authoritative repository.",
            "acceptance_criteria": [],
        },
        "risks": [],
        "verification": {
            "status": "sealed",
            "sealed_at": "2026-09-01T15:00:00Z",
            "content_digest": None,
            "policy": "evidence-required-v1",
            "surface_status": "unverifiable",
        },
    }
    checkpoint["verification"]["content_digest"] = PCP.compute_content_digest(checkpoint)
    errors = PCP.validate_checkpoint(checkpoint, expect_sealed=True)
    assert not errors, errors
    return checkpoint


def planning_snapshot() -> dict:
    """Build one valid planning sidecar bound to the same project."""
    planning = {
        "format": "pcp-planning/1",
        "planning_id": "planning-mobile-github-001",
        "created_at": "2026-09-01T15:00:00Z",
        "project_id": "git-demo-project",
        "source_checkpoint": None,
        "vision": "Mobile-first continuity",
        "items": [
            {
                "id": "rel-001",
                "kind": "release",
                "title": "Mobile continuity",
                "status": "accepted",
                "parent_id": None,
                "priority": "high",
                "depends_on": [],
                "acceptance_criteria": ["Phone-only handoff works."],
                "origin": {
                    "kind": "session_compiler",
                    "ref": "session:test",
                    "observed_at": "2026-09-01T15:00:00Z",
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
    planning["content_digest"] = BUNDLE.compute_planning_digest(planning)
    errors = BUNDLE.validate_planning_snapshot(planning)
    assert not errors, errors
    return planning


class GitHubTransportTests(unittest.TestCase):
    """R4 content-addressed mobile GitHub transport contract."""

    def test_private_publish_and_resolve_round_trip(self):
        """A private store publishes all objects and resolves the same verified bundle."""
        client = FakeGitHubClient()
        checkpoint = sealed_checkpoint()
        planning = planning_snapshot()
        receipt = github.publish_bundle(
            client,
            checkpoint,
            planning,
            owner="rafaelscosta",
            repository="project-continuity-state",
            created_at="2026-09-01T15:01:00Z",
            project_repository="github:rafaelscosta/sinkra-hub-orb-dev",
        )
        self.assertEqual(receipt["status"], "published")
        self.assertTrue(receipt["reference"].startswith("pcp+github://rafaelscosta/"))
        self.assertNotIn("token", receipt["reference"].lower())
        self.assertEqual(len(client.create_calls), 3)

        resolved = github.resolve_bundle(client, receipt["reference"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(
            resolved["checkpoint"]["verification"]["content_digest"],
            checkpoint["verification"]["content_digest"],
        )
        self.assertEqual(
            resolved["planning_snapshot"]["content_digest"],
            planning["content_digest"],
        )
        self.assertTrue(resolved["verification"]["valid"])

    def test_reference_is_canonical_and_content_addressed(self):
        """The reference contains only owner/repo, project token, handoff ID, and envelope digest."""
        checkpoint = sealed_checkpoint()
        planning = planning_snapshot()
        _, envelope_bytes, reference = github.build_envelope(
            checkpoint,
            planning,
            owner="rafaelscosta",
            repository="project-continuity-state",
            created_at="2026-09-01T15:01:00Z",
        )
        parsed = github.parse_github_reference(str(reference))
        self.assertEqual(parsed["owner"], "rafaelscosta")
        self.assertEqual(parsed["repository"], "project-continuity-state")
        self.assertEqual(parsed["project_token"], github.project_token(checkpoint["project_id"]))
        self.assertEqual(parsed["envelope_hex"], __import__("hashlib").sha256(envelope_bytes).hexdigest())

    def test_public_destination_fails_closed(self):
        """A public continuity repository is rejected unless this publication has explicit approval."""
        client = FakeGitHubClient(visibility="public")
        with self.assertRaises(github.TransportError) as ctx:
            github.publish_bundle(
                client,
                sealed_checkpoint(),
                planning_snapshot(),
                owner="rafaelscosta",
                repository="plugins",
                created_at="2026-09-01T15:01:00Z",
            )
        self.assertEqual(ctx.exception.code, "unsafe-publication-target")
        self.assertFalse(client.create_calls)

    def test_explicit_public_override_is_narrow_to_current_call(self):
        """The caller may explicitly approve one public publication without changing defaults."""
        client = FakeGitHubClient(visibility="public")
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            None,
            owner="rafaelscosta",
            repository="plugins",
            allow_public=True,
            created_at="2026-09-01T15:01:00Z",
        )
        self.assertEqual(receipt["status"], "published")
        self.assertEqual(len(client.create_calls), 2)

    def test_republishing_identical_bundle_is_idempotent(self):
        """Content-addressed paths avoid duplicate writes for an identical handoff."""
        client = FakeGitHubClient()
        checkpoint = sealed_checkpoint()
        planning = planning_snapshot()
        first = github.publish_bundle(
            client,
            checkpoint,
            planning,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        calls = len(client.create_calls)
        second = github.publish_bundle(
            client,
            checkpoint,
            planning,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        self.assertEqual(first["reference"], second["reference"])
        self.assertEqual(len(client.create_calls), calls)

    def test_existing_different_bytes_at_immutable_path_fail(self):
        """A collision never degrades into last-writer-wins remote state."""
        client = FakeGitHubClient()
        checkpoint = sealed_checkpoint()
        path = github.checkpoint_path(checkpoint["project_id"], checkpoint)
        client.files[("rafaelscosta", "project-continuity-state", path)] = "{}"
        with self.assertRaises(github.TransportError) as ctx:
            github.publish_bundle(
                client,
                checkpoint,
                None,
                owner="rafaelscosta",
                created_at="2026-09-01T15:01:00Z",
            )
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_tampered_envelope_is_rejected_by_reference_digest(self):
        """Envelope mutation is detected before trusting its artifact locations."""
        client = FakeGitHubClient()
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            planning_snapshot(),
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        key = (
            "rafaelscosta",
            "project-continuity-state",
            receipt["paths"]["handoff"],
        )
        client.files[key] = client.files[key] + " "
        with self.assertRaises(github.TransportError) as ctx:
            github.resolve_bundle(client, receipt["reference"])
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_tampered_checkpoint_is_rejected_by_pcp_digest(self):
        """Checkpoint mutation is caught even when its GitHub path remains unchanged."""
        client = FakeGitHubClient()
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            None,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        key = (
            "rafaelscosta",
            "project-continuity-state",
            receipt["paths"]["checkpoint"],
        )
        original = client.files[key]
        client.files[key] = original.replace("Continue the mobile handoff project", "tampered objective")
        with self.assertRaises(github.TransportError) as ctx:
            github.resolve_bundle(client, receipt["reference"])
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_missing_remote_artifact_is_typed(self):
        """A deleted checkpoint fails as remote-not-found instead of stale project state."""
        client = FakeGitHubClient()
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            None,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        key = (
            "rafaelscosta",
            "project-continuity-state",
            receipt["paths"]["checkpoint"],
        )
        del client.files[key]
        with self.assertRaises(github.TransportError) as ctx:
            github.resolve_bundle(client, receipt["reference"])
        self.assertEqual(ctx.exception.code, "remote-not-found")

    def test_forged_project_token_is_rejected_after_envelope_integrity(self):
        """A valid envelope copied under another project-token reference cannot remap identity."""
        client = FakeGitHubClient()
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            None,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        parsed = github.parse_github_reference(receipt["reference"])
        forged_token = "0" * 24
        forged_path = parsed["path"].replace(parsed["project_token"], forged_token, 1)
        original_key = ("rafaelscosta", "project-continuity-state", parsed["path"])
        forged_key = ("rafaelscosta", "project-continuity-state", forged_path)
        client.files[forged_key] = client.files[original_key]
        forged_reference = receipt["reference"].replace(parsed["project_token"], forged_token, 1)
        with self.assertRaises(github.TransportError) as ctx:
            github.resolve_bundle(client, forged_reference)
        self.assertEqual(ctx.exception.code, "project-mismatch")

    def test_planning_is_optional(self):
        """A checkpoint-only handoff publishes and resolves without inventing a planning artifact."""
        client = FakeGitHubClient()
        receipt = github.publish_bundle(
            client,
            sealed_checkpoint(),
            None,
            owner="rafaelscosta",
            created_at="2026-09-01T15:01:00Z",
        )
        self.assertIsNone(receipt["paths"]["planning"])
        resolved = github.resolve_bundle(client, receipt["reference"])
        self.assertIsNone(resolved["planning_snapshot"])

    def test_noncanonical_reference_path_fails_closed(self):
        """Resolvers never guess layout from arbitrary GitHub paths."""
        with self.assertRaises(github.TransportError) as ctx:
            github.parse_github_reference(
                "pcp+github://rafaelscosta/project-continuity-state/handoff.json"
            )
        self.assertEqual(ctx.exception.code, "reference-invalid")


if __name__ == "__main__":
    unittest.main()
