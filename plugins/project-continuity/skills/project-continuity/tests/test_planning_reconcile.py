from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import unittest


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


reconcile = load_module("pcp_planning_reconcile_test", "planning_reconcile.py")
bundle = reconcile.BUNDLE


def origin() -> dict:
    """Return stable source provenance for test planning items."""
    return {
        "kind": "session_compiler",
        "ref": "session:test",
        "observed_at": "2026-09-01T12:00:00Z",
    }


def item(
    item_id: str,
    kind: str,
    title: str,
    status: str,
    *,
    parent_id: str | None,
    priority: str = "high",
    depends_on: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict:
    """Build one valid pcp-planning/1 item."""
    return {
        "id": item_id,
        "kind": kind,
        "title": title,
        "status": status,
        "parent_id": parent_id,
        "priority": priority,
        "depends_on": list(depends_on or []),
        "acceptance_criteria": [f"{title} acceptance"],
        "origin": origin(),
        "supersedes": [],
        "evidence_refs": list(evidence_refs or []),
        "repository_refs": [],
    }


def base_planning() -> dict:
    """Return a hierarchy with one completed dependency and one ready leaf."""
    planning = {
        "format": "pcp-planning/1",
        "planning_id": "planning-test-baseline-001",
        "created_at": "2026-09-01T12:00:00Z",
        "project_id": "git-demo-project",
        "source_checkpoint": None,
        "vision": "Mobile-first continuity",
        "items": [
            item("rel-001", "release", "Release", "accepted", parent_id=None),
            item("epic-001", "epic", "Epic", "accepted", parent_id="rel-001"),
            item("story-001", "story", "Story", "accepted", parent_id="epic-001"),
            item(
                "task-dep",
                "task",
                "Dependency",
                "verified_done",
                parent_id="story-001",
                evidence_refs=["E-DEP-001"],
            ),
            item(
                "task-main",
                "task",
                "Main task",
                "ready",
                parent_id="story-001",
                depends_on=["task-dep"],
                priority="critical",
            ),
        ],
        "decisions": [],
        "unresolved_questions": [],
        "content_digest": None,
    }
    planning["content_digest"] = bundle.compute_planning_digest(planning)
    return planning


def refresh(planning: dict) -> dict:
    """Refresh a planning fixture after intentional test mutation."""
    planning["content_digest"] = None
    planning["content_digest"] = bundle.compute_planning_digest(planning)
    return planning


def request_for(planning: dict, observations: list[dict]) -> dict:
    """Build a reconciliation request bound to exact planning bytes."""
    return {
        "format": "pcp-planning-reconciliation/1",
        "reconciliation_id": "reconcile-test-abcdef12",
        "created_at": "2026-09-01T13:00:00Z",
        "project_id": planning["project_id"],
        "planning_id": planning["planning_id"],
        "planning_digest": planning["content_digest"],
        "observations": observations,
    }


def observation(
    item_id: str,
    operation: str,
    *,
    evidence: list[str] | None = None,
    repositories: list[str] | None = None,
    reason: str = "Current repository evidence establishes this state.",
) -> dict:
    """Build one reconciliation observation."""
    return {
        "item_id": item_id,
        "operation": operation,
        "evidence_refs": list(evidence or []),
        "repository_refs": list(repositories or []),
        "reason": reason,
    }


def by_id(planning: dict, item_id: str) -> dict:
    """Return a planning item by stable ID."""
    return next(candidate for candidate in planning["items"] if candidate["id"] == item_id)


def transition(report: dict, item_id: str) -> dict:
    """Return a transition by stable item ID."""
    return next(candidate for candidate in report["transitions"] if candidate["item_id"] == item_id)


class PlanningReconciliationTests(unittest.TestCase):
    """R3 planning-state reconciliation contract coverage."""

    def test_verify_complete_closes_stale_plan_with_fresh_evidence(self):
        """Repository-proven implementation upgrades accepted work to verified_done."""
        planning = base_planning()
        target = by_id(planning, "task-main")
        target["status"] = "accepted"
        refresh(planning)
        request = request_for(
            planning,
            [
                observation(
                    "task-main",
                    "verify_complete",
                    evidence=["E-TEST-001"],
                    repositories=["commit:abc123"],
                )
            ],
        )
        result, report = reconcile.reconcile(planning, request)
        updated = by_id(result, "task-main")
        self.assertEqual(updated["status"], "verified_done")
        self.assertEqual(updated["evidence_refs"], ["E-TEST-001"])
        self.assertEqual(transition(report, "task-main")["classification"], "stale-plan")

    def test_reported_done_missing_implementation_reopens_work(self):
        """A historical done claim becomes ready work when implementation is absent."""
        planning = base_planning()
        target = by_id(planning, "task-main")
        target["status"] = "reported_done"
        target["depends_on"] = []
        refresh(planning)
        request = request_for(
            planning,
            [observation("task-main", "verify_incomplete", evidence=["E-ABSENT-001"])],
        )
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(by_id(result, "task-main")["status"], "ready")
        self.assertEqual(
            transition(report, "task-main")["classification"],
            "incomplete-implementation",
        )

    def test_invalidated_verification_reopens_verified_work(self):
        """Changed behavior invalidates old verified_done state without deleting history."""
        planning = base_planning()
        target = by_id(planning, "task-main")
        target["status"] = "verified_done"
        target["evidence_refs"] = ["E-OLD-001"]
        refresh(planning)
        request = request_for(
            planning,
            [
                observation(
                    "task-main",
                    "invalidate_verification",
                    evidence=["E-CHANGE-001"],
                )
            ],
        )
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(by_id(result, "task-main")["status"], "ready")
        self.assertEqual(
            transition(report, "task-main")["classification"],
            "invalidated-verification",
        )

    def test_dependency_can_be_verified_and_dependent_unblocked_same_transaction(self):
        """Completion truth is established before dependency rechecks regardless of request order."""
        planning = base_planning()
        dependency = by_id(planning, "task-dep")
        dependency["status"] = "reported_done"
        dependency["evidence_refs"] = []
        main = by_id(planning, "task-main")
        main["status"] = "blocked"
        refresh(planning)
        request = request_for(
            planning,
            [
                observation("task-main", "recheck_dependencies"),
                observation("task-dep", "verify_complete", evidence=["E-DEP-NEW"]),
            ],
        )
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(by_id(result, "task-dep")["status"], "verified_done")
        self.assertEqual(by_id(result, "task-main")["status"], "ready")
        self.assertEqual(
            transition(report, "task-main")["classification"],
            "dependency-unblocked",
        )

    def test_invalidated_dependency_auto_blocks_ready_dependent(self):
        """Readiness cannot silently survive loss of a verified dependency."""
        planning = base_planning()
        request = request_for(
            planning,
            [
                observation(
                    "task-dep",
                    "invalidate_verification",
                    evidence=["E-DEP-REGRESSION"],
                )
            ],
        )
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(by_id(result, "task-main")["status"], "blocked")
        self.assertEqual(
            transition(report, "task-main")["classification"],
            "dependency-invalidated",
        )

    def test_reopened_child_invalidates_verified_parent(self):
        """Aggregate completion cannot remain verified when a child reopens."""
        planning = base_planning()
        story = by_id(planning, "story-001")
        story["status"] = "verified_done"
        story["evidence_refs"] = ["E-STORY-OLD"]
        main = by_id(planning, "task-main")
        main["status"] = "verified_done"
        main["evidence_refs"] = ["E-MAIN-OLD"]
        refresh(planning)
        request = request_for(
            planning,
            [
                observation(
                    "task-main",
                    "invalidate_verification",
                    evidence=["E-MAIN-CHANGE"],
                )
            ],
        )
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(by_id(result, "story-001")["status"], "ready")
        self.assertEqual(
            transition(report, "story-001")["classification"],
            "invalidated-verification",
        )

    def test_frontier_prefers_executable_leaf_over_container(self):
        """A release/epic/story with active children is never selected over its task leaf."""
        planning = base_planning()
        request = request_for(planning, [])
        _, report = reconcile.reconcile(planning, request)
        self.assertIsNotNone(report["frontier"])
        self.assertEqual(report["frontier"]["item_id"], "task-main")

    def test_start_progress_requires_verified_dependencies(self):
        """A task cannot enter progress while a dependency is merely reported done."""
        planning = base_planning()
        dependency = by_id(planning, "task-dep")
        dependency["status"] = "reported_done"
        dependency["evidence_refs"] = []
        refresh(planning)
        request = request_for(
            planning,
            [observation("task-main", "start_progress")],
        )
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_blocked_item_without_dependency_cannot_be_dependency_unblocked(self):
        """Dependency recheck cannot erase an unrelated external blocker."""
        planning = base_planning()
        target = by_id(planning, "task-main")
        target["status"] = "blocked"
        target["depends_on"] = []
        refresh(planning)
        request = request_for(
            planning,
            [observation("task-main", "recheck_dependencies")],
        )
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_request_is_bound_to_exact_planning_digest_and_project(self):
        """Stale/mismatched reconciliation inputs fail closed."""
        planning = base_planning()
        request = request_for(planning, [])
        request["planning_digest"] = "sha256:" + ("0" * 64)
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

        request = request_for(planning, [])
        request["project_id"] = "other-project"
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_duplicate_observations_are_rejected(self):
        """One item may have only one explicit operation per reconciliation transaction."""
        planning = base_planning()
        request = request_for(
            planning,
            [
                observation("task-main", "set_blocked"),
                observation("task-main", "recheck_dependencies"),
            ],
        )
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_verification_operations_require_evidence(self):
        """No verified completion or invalidation can be asserted without evidence refs."""
        planning = base_planning()
        request = request_for(
            planning,
            [observation("task-main", "verify_complete")],
        )
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_invalid_hierarchy_fails_closed(self):
        """Task/story/epic hierarchy cannot silently drift from the canonical graph model."""
        planning = base_planning()
        by_id(planning, "task-main")["parent_id"] = "rel-001"
        refresh(planning)
        request = request_for(planning, [])
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)

    def test_accepted_post_mvp_work_survives_unrelated_reconciliation(self):
        """Reconciliation preserves accepted work omitted from the current observation set."""
        planning = base_planning()
        planning["items"].append(
            item(
                "story-post-mvp",
                "story",
                "Post-MVP story",
                "accepted",
                parent_id="epic-001",
                priority="medium",
            )
        )
        refresh(planning)
        request = request_for(
            planning,
            [observation("task-main", "verify_complete", evidence=["E-MAIN-DONE"])],
        )
        result, _ = reconcile.reconcile(planning, request)
        preserved = by_id(result, "story-post-mvp")
        self.assertEqual(preserved["status"], "accepted")
        self.assertEqual(preserved["title"], "Post-MVP story")

    def test_result_digest_is_canonical_and_report_binds_both_versions(self):
        """The report cryptographically binds prior and reconciled planning snapshots."""
        planning = base_planning()
        request = request_for(planning, [])
        result, report = reconcile.reconcile(planning, request)
        self.assertEqual(
            result["content_digest"],
            bundle.compute_planning_digest(result),
        )
        self.assertEqual(report["prior_planning"]["digest"], planning["content_digest"])
        self.assertEqual(report["result_planning"]["digest"], result["content_digest"])

    def test_secret_like_reconciliation_content_is_rejected(self):
        """Secrets cannot be persisted through reconciliation provenance fields."""
        planning = base_planning()
        request = request_for(
            planning,
            [
                observation(
                    "task-main",
                    "set_blocked",
                    reason="api_key=super-secret-value-that-must-not-persist",
                )
            ],
        )
        with self.assertRaises(reconcile.PlanningReconciliationError):
            reconcile.reconcile(planning, request)


if __name__ == "__main__":
    unittest.main()
