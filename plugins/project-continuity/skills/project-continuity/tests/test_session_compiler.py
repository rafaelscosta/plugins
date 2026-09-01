from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compiler = load_module("pcp_test_session_compiler", "session_compiler.py")
merge = load_module("pcp_test_planning_merge", "planning_merge.py")


def origin(kind: str = "conversation", ref: str | None = "session:test") -> dict:
    return {"kind": kind, "ref": ref}


def item(
    item_id: str,
    *,
    title: str | None = None,
    kind: str = "story",
    status: str = "accepted",
    parent_id: str | None = None,
    priority: str = "high",
    depends_on: list[str] | None = None,
    supersedes: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "title": title or item_id,
        "status": status,
        "parent_id": parent_id,
        "priority": priority,
        "depends_on": list(depends_on or []),
        "acceptance_criteria": [f"{item_id} acceptance"],
        "origin": origin(),
        "supersedes": list(supersedes or []),
        "evidence_refs": list(evidence_refs or []),
        "repository_refs": [],
    }


def compilation() -> dict:
    return {
        "format": "pcp-session-compilation/1",
        "compilation_id": "compilation-20260901-abcdef12",
        "created_at": "2026-09-01T12:00:00Z",
        "project": {
            "id": "git-demo-project",
            "name": "Demo Project",
            "repository": "github:owner/demo",
        },
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": "chat:test",
        },
        "prior_checkpoint": None,
        "objective": {
            "current": "Continue the accepted implementation plan.",
            "definition_of_done": ["All accepted stories are reconciled and implemented."],
        },
        "decisions": [
            {
                "id": "decision-architecture",
                "statement": "Preserve PCP/1 canonical semantics.",
                "status": "accepted",
                "confidence": "reported",
                "origin": origin("current_user"),
                "supersedes": [],
            }
        ],
        "findings": [
            {
                "id": "finding-transport",
                "statement": "The file-only handoff blocks a phone-only workflow.",
                "confidence": "reported",
                "origin": origin(),
            }
        ],
        "planning": {
            "vision": "Phone-only ChatGPT to Codex continuity.",
            "items": [
                item("story-r1", status="verified_done", evidence_refs=["evidence:r1"]),
                item("story-r2", status="ready", depends_on=["story-r1"]),
                item("story-r3", status="accepted", depends_on=["story-r2"]),
            ],
        },
        "blockers": [],
        "risks": [],
        "uncertainties": ["Repository reality must be checked by Codex."],
        "next_frontier": {
            "planning_item_id": "story-r2",
            "instruction": "Implement and validate the Session Compiler.",
            "acceptance_criteria": ["Compiler preserves accepted unresolved work."],
        },
    }


def prior_planning() -> dict:
    base = compilation()
    checkpoint, planning = compiler.compile_session(
        base,
        seal_portable=True,
        sealed_at="2026-09-01T12:05:00Z",
    )
    assert checkpoint["verification"]["status"] == "sealed"
    return planning


class SessionCompilerTests(unittest.TestCase):
    def test_bootstrap_compiles_valid_portable_draft_without_completed_claims(self):
        checkpoint, planning = compiler.compile_session(compilation())
        self.assertEqual(checkpoint["verification"]["status"], "draft")
        self.assertEqual(checkpoint["verification"]["surface_status"], "unverifiable")
        self.assertFalse(any(claim["kind"] == "completed" for claim in checkpoint["claims"]))
        self.assertEqual(checkpoint["next_action"]["work_item_id"], "W-RECONCILE-001")
        self.assertEqual(len(planning["items"]), 3)
        self.assertFalse(compiler.PCP.validate_checkpoint(checkpoint, expect_sealed=False))
        self.assertFalse(compiler.BUNDLE.validate_planning_snapshot(planning))

    def test_sealed_portable_is_tamper_evident_but_still_unverifiable(self):
        checkpoint, planning = compiler.compile_session(
            compilation(),
            seal_portable=True,
            sealed_at="2026-09-01T12:10:00Z",
        )
        self.assertEqual(checkpoint["verification"]["status"], "sealed")
        self.assertEqual(checkpoint["verification"]["surface_status"], "unverifiable")
        self.assertEqual(
            checkpoint["verification"]["content_digest"],
            compiler.PCP.compute_content_digest(checkpoint),
        )
        self.assertFalse(any(claim["kind"] == "completed" for claim in checkpoint["claims"]))
        self.assertEqual(planning["source_checkpoint"]["id"], checkpoint["checkpoint_id"])
        self.assertEqual(
            planning["source_checkpoint"]["digest"],
            checkpoint["verification"]["content_digest"],
        )

    def test_reported_done_becomes_reported_finding_not_completion(self):
        data = compilation()
        data["planning"]["items"][1]["status"] = "reported_done"
        data["next_frontier"] = None
        checkpoint, planning = compiler.compile_session(data)
        historical = [claim for claim in checkpoint["claims"] if claim["id"].startswith("SC-H-")]
        self.assertEqual(len(historical), 2)
        self.assertTrue(all(claim["confidence"] == "reported" for claim in historical))
        self.assertFalse(any(claim["kind"] == "completed" for claim in checkpoint["claims"]))
        self.assertEqual(planning["items"][1]["status"], "reported_done")

    def test_verified_done_requires_evidence_reference(self):
        data = compilation()
        data["planning"]["items"][0]["evidence_refs"] = []
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("verified_done requires evidence_refs" in error for error in errors))

    def test_secret_like_content_is_rejected(self):
        data = compilation()
        data["findings"][0]["statement"] = "authorization: Bearer abcdefghijklmnopqrstuvwxyz"
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("secret-like content detected" in error for error in errors))

    def test_created_at_must_be_rfc3339_with_timezone(self):
        data = compilation()
        data["created_at"] = "2026-09-01 12:00:00"
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("RFC3339" in error for error in errors))

    def test_dependency_cycle_is_rejected(self):
        data = compilation()
        data["planning"]["items"][0]["status"] = "accepted"
        data["planning"]["items"][0]["depends_on"] = ["story-r3"]
        data["next_frontier"] = None
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("dependency cycle" in error for error in errors))

    def test_blocked_frontier_is_rejected(self):
        data = compilation()
        data["planning"]["items"][1]["status"] = "blocked"
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("item status" in error for error in errors))

    def test_frontier_with_unsatisfied_dependency_is_rejected(self):
        data = compilation()
        data["planning"]["items"][0]["status"] = "accepted"
        errors = compiler.validate_compilation(data)
        self.assertTrue(any("unsatisfied dependencies" in error for error in errors))

    def test_frontier_with_verified_dependency_is_accepted(self):
        errors = compiler.validate_compilation(compilation())
        self.assertEqual(errors, [])

    def test_frontier_is_secondary_to_reconciliation_in_portable_checkpoint(self):
        checkpoint, _ = compiler.compile_session(compilation())
        frontier_work = next(item for item in checkpoint["open_work"] if item["id"] == "W-FRONTIER-001")
        self.assertEqual(frontier_work["depends_on"], ["W-RECONCILE-001"])
        self.assertEqual(checkpoint["next_action"]["work_item_id"], "W-RECONCILE-001")

    def test_uncertainty_is_preserved_as_risk_without_guessing(self):
        checkpoint, planning = compiler.compile_session(compilation())
        uncertainty_risks = [risk for risk in checkpoint["risks"] if risk["id"].startswith("R-UNCERTAINTY-")]
        self.assertEqual(len(uncertainty_risks), 1)
        self.assertEqual(planning["unresolved_questions"], compilation()["uncertainties"])


class IncrementalMergeTests(unittest.TestCase):
    def test_silence_does_not_delete_accepted_post_mvp_work(self):
        prior = prior_planning()
        delta = compilation()
        delta["planning"]["items"] = [
            item("story-r2", status="in_progress", depends_on=["story-r1"])
        ]
        delta["decisions"] = []
        merged = merge.merge_compilation_with_prior(delta, prior)
        ids = [entry["id"] for entry in merged["planning"]["items"]]
        self.assertEqual(ids, ["story-r1", "story-r2", "story-r3"])
        story_r3 = next(entry for entry in merged["planning"]["items"] if entry["id"] == "story-r3")
        self.assertEqual(story_r3["status"], "accepted")
        self.assertEqual(len(merged["decisions"]), 1)

    def test_same_id_current_delta_updates_without_duplicating(self):
        prior = prior_planning()
        delta = compilation()
        delta["planning"]["items"] = [item("story-r3", status="ready", depends_on=[])]
        delta["next_frontier"] = {
            "planning_item_id": "story-r3",
            "instruction": "Advance R3.",
            "acceptance_criteria": ["R3 advances."],
        }
        merged = merge.merge_compilation_with_prior(delta, prior)
        matches = [entry for entry in merged["planning"]["items"] if entry["id"] == "story-r3"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["status"], "ready")

    def test_explicit_supersedes_marks_omitted_prior_item_superseded(self):
        prior = prior_planning()
        delta = compilation()
        delta["planning"]["items"] = [
            item("story-r2b", status="ready", supersedes=["story-r2"])
        ]
        delta["next_frontier"] = {
            "planning_item_id": "story-r2b",
            "instruction": "Implement the replacement story.",
            "acceptance_criteria": ["Replacement story is implemented."],
        }
        merged = merge.merge_compilation_with_prior(delta, prior)
        old = next(entry for entry in merged["planning"]["items"] if entry["id"] == "story-r2")
        new = next(entry for entry in merged["planning"]["items"] if entry["id"] == "story-r2b")
        self.assertEqual(old["status"], "superseded")
        self.assertEqual(new["status"], "ready")

    def test_explicit_decision_supersession_marks_prior_decision(self):
        prior = prior_planning()
        delta = compilation()
        delta["decisions"] = [
            {
                "id": "decision-architecture-v2",
                "statement": "Adopt revised compatible architecture.",
                "status": "accepted",
                "confidence": "reported",
                "origin": origin("current_user"),
                "supersedes": ["decision-architecture"],
            }
        ]
        merged = merge.merge_compilation_with_prior(delta, prior)
        old = next(entry for entry in merged["decisions"] if entry["id"] == "decision-architecture")
        self.assertEqual(old["status"], "superseded")

    def test_project_mismatch_is_hard_failure(self):
        prior = prior_planning()
        delta = compilation()
        delta["project"]["id"] = "different-project"
        with self.assertRaises(merge.PlanningMergeError):
            merge.merge_compilation_with_prior(delta, prior)

    def test_prior_checkpoint_is_inherited_from_sealed_prior_planning(self):
        prior = prior_planning()
        delta = compilation()
        self.assertIsNone(delta["prior_checkpoint"])
        merged = merge.merge_compilation_with_prior(delta, prior)
        self.assertEqual(merged["prior_checkpoint"], prior["source_checkpoint"])

    def test_conflicting_explicit_prior_checkpoint_fails(self):
        prior = prior_planning()
        delta = compilation()
        delta["prior_checkpoint"] = {
            "id": "pcp-conflicting-parent",
            "digest": "sha256:" + ("0" * 64),
        }
        with self.assertRaises(merge.PlanningMergeError):
            merge.merge_compilation_with_prior(delta, prior)

    def test_incremental_merge_can_compile_to_valid_outputs(self):
        prior = prior_planning()
        delta = compilation()
        delta["planning"]["items"] = [
            item("story-r2", status="in_progress", depends_on=["story-r1"])
        ]
        merged = merge.merge_compilation_with_prior(delta, prior)
        checkpoint, planning = compiler.compile_session(merged)
        self.assertFalse(compiler.PCP.validate_checkpoint(checkpoint, expect_sealed=False))
        self.assertFalse(compiler.BUNDLE.validate_planning_snapshot(planning))
        self.assertEqual(len(planning["items"]), 3)


if __name__ == "__main__":
    unittest.main()
