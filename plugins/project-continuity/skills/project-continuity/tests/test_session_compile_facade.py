from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    """Load one sibling script under an isolated module name."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


facade = load_module("pcp_test_session_compile_facade", "session_compile.py")


def blocker(blocker_id: str, depends_on: list[str] | None = None) -> dict:
    """Build the minimal blocker shape needed by the facade guard."""
    return {
        "id": blocker_id,
        "title": blocker_id,
        "priority": "high",
        "acceptance_criteria": [f"Resolve {blocker_id}"],
        "depends_on": list(depends_on or []),
    }


def decision(
    decision_id: str,
    supersedes: list[str] | None = None,
) -> dict:
    """Build a Session Compilation decision for cross-record guard tests."""
    return {
        "id": decision_id,
        "statement": decision_id,
        "status": "accepted",
        "confidence": "reported",
        "origin": {"kind": "current_user", "ref": "session:test"},
        "supersedes": list(supersedes or []),
    }


def planning_item(
    item_id: str,
    supersedes: list[str] | None = None,
) -> dict:
    """Build a Session Compilation planning item for supersession tests."""
    return {
        "id": item_id,
        "kind": "story",
        "title": item_id,
        "status": "accepted",
        "parent_id": None,
        "priority": "high",
        "depends_on": [],
        "acceptance_criteria": [f"Complete {item_id}"],
        "origin": {"kind": "conversation", "ref": "session:test"},
        "supersedes": list(supersedes or []),
        "evidence_refs": [],
        "repository_refs": [],
    }


def valid_prior_planning() -> dict:
    """Build a canonically digested prior planning snapshot."""
    snapshot = {
        "format": "pcp-planning/1",
        "planning_id": "planning-20260901-abcdef12",
        "created_at": "2026-09-01T12:00:00Z",
        "project_id": "git-demo-project",
        "source_checkpoint": None,
        "vision": "Preserve project continuity.",
        "items": [],
        "decisions": [],
        "unresolved_questions": [],
        "content_digest": None,
    }
    snapshot["content_digest"] = facade.COMPILER.BUNDLE.compute_planning_digest(
        snapshot
    )
    return snapshot


class BlockerDependencyGuardTests(unittest.TestCase):
    """Cross-record blocker dependency semantics that JSON Schema cannot express."""

    def test_valid_blocker_chain_is_preserved(self):
        """Known acyclic blocker dependencies pass validation."""
        source = {
            "blockers": [
                blocker("blocker-a"),
                blocker("blocker-b", ["blocker-a"]),
                blocker("blocker-c", ["blocker-b"]),
            ]
        }
        facade.validate_blocker_dependencies(source)

    def test_unknown_blocker_dependency_fails_closed(self):
        """Unknown blocker IDs cannot be silently dropped during PCP mapping."""
        source = {
            "blockers": [
                blocker("blocker-a", ["missing-blocker"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("references unknown depends_on", str(ctx.exception))

    def test_direct_blocker_cycle_fails_closed(self):
        """A two-node blocker cycle is rejected before PCP conversion."""
        source = {
            "blockers": [
                blocker("blocker-a", ["blocker-b"]),
                blocker("blocker-b", ["blocker-a"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("Blocker depends_on cycle", str(ctx.exception))

    def test_self_dependency_fails_closed(self):
        """A blocker cannot depend on itself."""
        source = {
            "blockers": [
                blocker("blocker-a", ["blocker-a"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("cannot reference itself", str(ctx.exception))


class PriorPlanningIntegrityTests(unittest.TestCase):
    """Incremental mode must trust only canonically intact prior planning."""

    def test_valid_prior_planning_digest_passes(self):
        """An intact planning snapshot is accepted for incremental merge."""
        facade.validate_prior_planning_integrity(valid_prior_planning())

    def test_missing_prior_planning_digest_fails_closed(self):
        """Incremental mode refuses an undigested prior snapshot."""
        prior = valid_prior_planning()
        prior["content_digest"] = None
        with self.assertRaises(facade.MERGE.PlanningMergeError) as ctx:
            facade.validate_prior_planning_integrity(prior)
        self.assertIn("must carry a canonical content_digest", str(ctx.exception))

    def test_tampered_prior_planning_fails_closed(self):
        """A structurally valid but modified prior snapshot cannot be merged."""
        prior = valid_prior_planning()
        prior["vision"] = "Tampered after digest"
        with self.assertRaises(facade.MERGE.PlanningMergeError) as ctx:
            facade.validate_prior_planning_integrity(prior)
        self.assertIn("does not match its canonical bytes", str(ctx.exception))


class SupersessionGuardTests(unittest.TestCase):
    """Supersession edges must remain resolvable through compilation."""

    def test_known_decision_supersession_passes(self):
        """A current decision may supersede another known decision."""
        source = {
            "decisions": [
                decision("decision-v1"),
                decision("decision-v2", ["decision-v1"]),
            ],
            "planning": {"items": []},
        }
        facade.validate_supersession_references(source)

    def test_unknown_decision_supersession_fails_closed(self):
        """Decision supersession cannot point to an absent decision ID."""
        source = {
            "decisions": [decision("decision-v2", ["missing-decision"])],
            "planning": {"items": []},
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_supersession_references(source)
        self.assertIn("references unknown supersedes", str(ctx.exception))

    def test_decision_supersession_cycle_fails_closed(self):
        """Decision supersession cannot form a cycle."""
        source = {
            "decisions": [
                decision("decision-v1", ["decision-v2"]),
                decision("decision-v2", ["decision-v1"]),
            ],
            "planning": {"items": []},
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_supersession_references(source)
        self.assertIn("Decision supersedes cycle", str(ctx.exception))

    def test_unknown_planning_supersession_fails_closed(self):
        """Planning supersession cannot point to an absent planning item."""
        source = {
            "decisions": [],
            "planning": {
                "items": [planning_item("story-v2", ["missing-story"])]
            },
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_supersession_references(source)
        self.assertIn("references unknown supersedes", str(ctx.exception))

    def test_decision_supersedes_is_mapped_to_pcp_claim_ids(self):
        """IR decision IDs become the emitted PCP claim IDs in claim lineage."""
        source = {
            "decisions": [
                decision("decision-v1"),
                decision("decision-v2", ["decision-v1"]),
            ]
        }
        checkpoint = {
            "claims": [
                {"id": "SC-D-001", "supersedes": []},
                {"id": "SC-D-002", "supersedes": ["decision-v1"]},
            ]
        }
        facade.normalize_pcp_decision_supersedes(checkpoint, source)
        self.assertEqual(checkpoint["claims"][0]["supersedes"], [])
        self.assertEqual(
            checkpoint["claims"][1]["supersedes"],
            ["SC-D-001"],
        )


if __name__ == "__main__":
    unittest.main()
