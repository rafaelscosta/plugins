from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    """Load one skill runtime module for direct behavior tests."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


resume = load_module("pcp_resume_resolver_test", "resume_resolver.py")
PCP = resume.PCP
BUNDLE = resume.BUNDLE


class FakeGitHubClient:
    """Minimal private GitHub binding used by R5 resolve tests."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], str] = {}

    def get_repository(self, owner: str, repository: str) -> dict:
        return {
            "owner": owner,
            "name": repository,
            "visibility": "private",
            "private": True,
        }

    def read_text_file(self, owner: str, repository: str, path: str) -> str | None:
        return self.files.get((owner, repository, path))

    def create_text_file(
        self,
        owner: str,
        repository: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        key = (owner, repository, path)
        if key in self.files:
            raise AssertionError(f"overwrite attempted: {path}")
        self.files[key] = content


def checkpoint(
    *,
    project_id: str = "git-demo-project",
    sealed: bool = True,
    include_completed: bool = False,
) -> dict:
    """Build one valid portable PCP checkpoint."""
    claims = [
        {
            "id": "C-DECISION-001",
            "kind": "decision",
            "confidence": "reported",
            "statement": "Keep GitHub as the mobile transport.",
            "evidence": [],
            "supersedes": [],
        }
    ]
    evidence = []
    if include_completed:
        evidence.append(
            {
                "id": "E-ART-001",
                "type": "artifact",
                "label": "Historical artifact evidence",
                "observed_at": "2026-09-01T15:00:00Z",
                "path": "historical.txt",
                "sha256": "sha256:" + ("1" * 64),
            }
        )
        claims.append(
            {
                "id": "C-COMPLETE-001",
                "kind": "completed",
                "confidence": "verified",
                "statement": "Historical implementation was complete at source time.",
                "evidence": ["E-ART-001"],
                "supersedes": [],
            }
        )
    value = {
        "protocol_version": "pcp/1",
        "checkpoint_id": "pcp-20260901T150000Z-resume01",
        "created_at": "2026-09-01T15:00:00Z",
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": "session:r5",
        },
        "project_id": project_id,
        "parent": {"checkpoint_id": None, "content_digest": None},
        "baseline": {"root_hint": ".", "git": None, "files": []},
        "objective": {
            "current": "Resume mobile continuity implementation",
            "definition_of_done": ["Codex resumes without blind repetition."],
        },
        "claims": claims,
        "evidence": evidence,
        "open_work": [
            {
                "id": "W-BLOCKED-001",
                "title": "Resolve an explicit historical blocker",
                "status": "blocked",
                "priority": "medium",
                "acceptance_criteria": ["Blocker is reconciled."],
                "depends_on": [],
            }
        ],
        "next_action": {
            "work_item_id": "W-BLOCKED-001",
            "instruction": "Reconcile current project state.",
            "acceptance_criteria": ["Current repository is inspected."],
        },
        "risks": [],
        "verification": {
            "status": "draft",
            "sealed_at": None,
            "content_digest": None,
            "policy": "evidence-required-v1",
            "surface_status": "unverifiable",
        },
    }
    if sealed:
        value["verification"] = {
            "status": "sealed",
            "sealed_at": "2026-09-01T15:00:01Z",
            "content_digest": None,
            "policy": "evidence-required-v1",
            "surface_status": "unverifiable",
        }
        value["verification"]["content_digest"] = PCP.compute_content_digest(value)
        errors = PCP.validate_checkpoint(value, expect_sealed=True)
    else:
        errors = PCP.validate_checkpoint(value, expect_sealed=False)
    assert not errors, errors
    return value


def planning(
    *,
    project_id: str = "git-demo-project",
    status: str = "accepted",
    item_id: str = "story-001",
) -> dict:
    """Build one single-leaf planning snapshot."""
    value = {
        "format": "pcp-planning/1",
        "planning_id": "planning-resume-r5-001",
        "created_at": "2026-09-01T15:00:00Z",
        "project_id": project_id,
        "source_checkpoint": None,
        "vision": "Mobile continuity",
        "items": [
            {
                "id": item_id,
                "kind": "story",
                "title": "Implement the resumed story",
                "status": status,
                "parent_id": None,
                "priority": "high",
                "depends_on": [],
                "acceptance_criteria": ["Current repository state decides truth."],
                "origin": {
                    "kind": "session_compiler",
                    "ref": "session:r5",
                    "observed_at": "2026-09-01T15:00:00Z",
                },
                "supersedes": [],
                "evidence_refs": (
                    ["E-HIST-001"] if status == "verified_done" else []
                ),
                "repository_refs": [],
            }
        ],
        "decisions": [],
        "unresolved_questions": [],
        "content_digest": None,
    }
    value["content_digest"] = BUNDLE.compute_planning_digest(value)
    errors = BUNDLE.validate_planning_snapshot(value)
    assert not errors, errors
    return value


def reconciliation_request(
    plan: dict,
    *,
    operation: str,
    item_id: str = "story-001",
) -> dict:
    """Build one current FILE/FULL observation transaction."""
    needs_evidence = operation in {
        "verify_complete",
        "verify_incomplete",
        "invalidate_verification",
    }
    return {
        "format": "pcp-planning-reconciliation/1",
        "reconciliation_id": "reconcile-r5-0001",
        "created_at": "2026-09-01T15:05:00Z",
        "project_id": plan["project_id"],
        "planning_id": plan["planning_id"],
        "planning_digest": plan["content_digest"],
        "observations": [
            {
                "item_id": item_id,
                "operation": operation,
                "evidence_refs": ["E-CURRENT-001"] if needs_evidence else [],
                "repository_refs": ["git:HEAD"],
                "reason": "Observed current repository state.",
            }
        ],
    }


def init_local(root: pathlib.Path, *, project_id: str = "git-demo-project") -> None:
    """Initialize local PCP state with a deterministic project ID."""
    args = argparse.Namespace(
        root=str(root),
        project_name="Demo",
        project_id=project_id,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        rc = PCP.cmd_init(args)
    assert rc == 0


class ResumeResolverTests(unittest.TestCase):
    """R5 resolver + downgrade-first + planning-reconciliation contract."""

    def make_root(self, *, project_id: str = "git-demo-project") -> pathlib.Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        init_local(root, project_id=project_id)
        return root

    def test_standalone_file_draft_resolves_and_never_promotes_head(self):
        root = self.make_root()
        cp = checkpoint(sealed=False)
        handoff = root / "handoff.json"
        handoff.write_text(json.dumps(cp), encoding="utf-8")
        transport = resume.TRANSPORTS.FileTransport(allowed_root=root)
        reference = str(transport.reference_for_path(handoff))
        before = json.loads((root / ".continuity" / "state.json").read_text())

        resolved = resume.resolve_reference(reference, file_allowed_root=root)
        result = resume.prepare_resume(
            root,
            resolved,
            resolved_at="2026-09-01T15:06:00Z",
        )
        after = json.loads((root / ".continuity" / "state.json").read_text())

        self.assertEqual(resolved["verification"]["checkpoint_integrity"], "unsealed-reported")
        self.assertEqual(result["planning"]["status"], "absent")
        self.assertFalse(result["pcp"]["external_promoted"])
        self.assertEqual(before["head"], after["head"])
        self.assertTrue(pathlib.Path(result["pcp"]["reconciliation_draft"]).is_file())

    def test_tampered_sealed_standalone_file_is_rejected(self):
        root = self.make_root()
        cp = checkpoint()
        cp["objective"]["current"] = "tampered"
        handoff = root / "handoff.json"
        handoff.write_text(json.dumps(cp), encoding="utf-8")
        transport = resume.TRANSPORTS.FileTransport(allowed_root=root)
        reference = str(transport.reference_for_path(handoff))
        with self.assertRaises(resume.ResumeResolutionError):
            resume.resolve_reference(reference, file_allowed_root=root)

    def test_file_envelope_resolves_checkpoint_and_planning(self):
        root = self.make_root()
        cp = checkpoint()
        plan = planning()
        cp_path = root / "checkpoint.json"
        plan_path = root / "planning.json"
        cp_path.write_text(json.dumps(cp), encoding="utf-8")
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        envelope = {
            "format": "pcp-handoff/1",
            "handoff_id": "handoff-file-r5-0001",
            "created_at": "2026-09-01T15:01:00Z",
            "project": {"id": cp["project_id"], "repository": None},
            "checkpoint": {
                "protocol": "pcp/1",
                "id": cp["checkpoint_id"],
                "digest": cp["verification"]["content_digest"],
                "location": "checkpoint.json",
            },
            "planning_snapshot": {
                "id": plan["planning_id"],
                "digest": plan["content_digest"],
                "location": "planning.json",
            },
            "transport": {"kind": "file"},
        }
        env_path = root / "envelope.json"
        env_path.write_text(json.dumps(envelope), encoding="utf-8")
        transport = resume.TRANSPORTS.FileTransport(allowed_root=root)
        reference = str(transport.reference_for_path(env_path))

        resolved = resume.resolve_reference(reference, file_allowed_root=root)
        self.assertEqual(resolved["checkpoint"]["checkpoint_id"], cp["checkpoint_id"])
        self.assertEqual(
            resolved["planning_snapshot"]["planning_id"], plan["planning_id"]
        )
        self.assertTrue(resolved["verification"]["valid"])

    def test_github_reference_requires_authorized_client(self):
        with self.assertRaises(resume.ResumeResolutionError):
            resume.resolve_reference(
                "pcp+github://owner/repo/projects/0123456789abcdef01234567/"
                "handoffs/handoff-abcdefgh.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.json"
            )

    def test_github_round_trip_feeds_same_downgrade_first_resume(self):
        root = self.make_root()
        client = FakeGitHubClient()
        cp = checkpoint(include_completed=True)
        plan = planning()
        receipt = resume.GITHUB.publish_bundle(
            client,
            cp,
            plan,
            owner="rafaelscosta",
            repository="project-continuity-state",
            created_at="2026-09-01T15:01:00Z",
        )
        resolved = resume.resolve_reference(
            receipt["reference"], github_client=client
        )
        result = resume.prepare_resume(
            root,
            resolved,
            resolved_at="2026-09-01T15:06:00Z",
        )
        self.assertEqual(result["transport"], "github")
        self.assertEqual(result["planning"]["status"], "reconciliation-required")
        self.assertIsNone(result["resume_brief"]["candidate_frontier"])
        self.assertEqual(
            result["pcp"]["historical_completion_claims"][0]["status"],
            "requires-reverification",
        )
        draft = json.loads(
            pathlib.Path(result["pcp"]["reconciliation_draft"]).read_text()
        )
        imported_completion = [
            claim for claim in draft["claims"]
            if "Historical completion claim requiring current re-verification" in claim["statement"]
        ]
        self.assertTrue(imported_completion)
        self.assertTrue(all(claim["confidence"] == "reported" for claim in imported_completion))

    def test_unreconciled_planning_never_exposes_candidate_frontier(self):
        root = self.make_root()
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": planning(status="accepted"),
        }
        result = resume.prepare_resume(
            root,
            resolved,
            resolved_at="2026-09-01T15:06:00Z",
        )
        self.assertTrue(result["execution_gate"]["planning_reconciliation_required"])
        self.assertFalse(result["execution_gate"]["candidate_frontier_available"])
        self.assertIsNone(result["resume_brief"]["candidate_frontier"])

    def test_stale_accepted_work_already_implemented_is_not_repeated(self):
        root = self.make_root()
        plan = planning(status="accepted")
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": plan,
        }
        result = resume.prepare_resume(
            root,
            resolved,
            planning_reconciliation=reconciliation_request(
                plan, operation="verify_complete"
            ),
            resolved_at="2026-09-01T15:06:00Z",
        )
        self.assertEqual(result["planning"]["status"], "reconciled")
        self.assertEqual(
            result["planning"]["transitions"][0]["classification"], "stale-plan"
        )
        self.assertIsNone(result["resume_brief"]["candidate_frontier"])

    def test_reported_done_absent_from_repo_reopens_as_frontier(self):
        root = self.make_root()
        plan = planning(status="reported_done")
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": plan,
        }
        result = resume.prepare_resume(
            root,
            resolved,
            planning_reconciliation=reconciliation_request(
                plan, operation="verify_incomplete"
            ),
            resolved_at="2026-09-01T15:06:00Z",
        )
        transition = result["planning"]["transitions"][0]
        self.assertEqual(transition["classification"], "incomplete-implementation")
        self.assertEqual(transition["to_status"], "ready")
        self.assertEqual(
            result["resume_brief"]["candidate_frontier"]["item_id"], "story-001"
        )

    def test_external_decisions_are_reported_in_resume_brief(self):
        root = self.make_root()
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": None,
        }
        result = resume.prepare_resume(
            root,
            resolved,
            resolved_at="2026-09-01T15:06:00Z",
        )
        decision = result["resume_brief"]["surviving_decisions"][0]
        self.assertEqual(decision["confidence"], "reported")
        self.assertEqual(result["resume_brief"]["objective"]["confidence"], "reported")

    def test_explicit_checkpoint_blockers_survive_resume_brief(self):
        root = self.make_root()
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": None,
        }
        result = resume.prepare_resume(
            root,
            resolved,
            resolved_at="2026-09-01T15:06:00Z",
        )
        self.assertTrue(
            any(
                blocker["id"] == "W-BLOCKED-001"
                for blocker in result["resume_brief"]["blockers"]
            )
        )

    def test_project_mismatch_is_hard_stop_without_explicit_mapping(self):
        root = self.make_root(project_id="local-project")
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(project_id="external-project"),
            "planning_snapshot": None,
        }
        with self.assertRaises(resume.ResumeResolutionError):
            resume.prepare_resume(
                root,
                resolved,
                resolved_at="2026-09-01T15:06:00Z",
            )

    def test_explicit_project_mapping_allows_downgrade_first_draft_only(self):
        root = self.make_root(project_id="local-project")
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(project_id="external-project"),
            "planning_snapshot": None,
        }
        result = resume.prepare_resume(
            root,
            resolved,
            confirm_project_mapping=True,
            resolved_at="2026-09-01T15:06:00Z",
        )
        self.assertFalse(result["pcp"]["external_promoted"])
        self.assertTrue(pathlib.Path(result["pcp"]["reconciliation_draft"]).exists())

    def test_reconciliation_without_planning_is_rejected(self):
        root = self.make_root()
        resolved = {
            "reference": "pcp+file://local/example",
            "transport": "file",
            "envelope": None,
            "checkpoint": checkpoint(),
            "planning_snapshot": None,
        }
        dummy = {
            "format": "pcp-planning-reconciliation/1",
            "reconciliation_id": "reconcile-r5-0001",
            "created_at": "2026-09-01T15:05:00Z",
            "project_id": "git-demo-project",
            "planning_id": "planning-missing-001",
            "planning_digest": "sha256:" + ("0" * 64),
            "observations": [],
        }
        with self.assertRaises(resume.ResumeResolutionError):
            resume.prepare_resume(
                root,
                resolved,
                planning_reconciliation=dummy,
                resolved_at="2026-09-01T15:06:00Z",
            )


if __name__ == "__main__":
    unittest.main()
