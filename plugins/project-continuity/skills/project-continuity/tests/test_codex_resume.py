from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import subprocess
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


resume = load_module("pcp_codex_resume_test", "codex_resume.py")
PCP = resume.PCP
GITHUB = resume.RESOLVER.GITHUB
BUNDLE = resume.RESOLVER.BUNDLE


def git(root: pathlib.Path, *args: str) -> str:
    """Run one deterministic Git command in the temporary project."""
    cp = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if cp.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {cp.stdout}")
    return cp.stdout.strip()


class FakeGitHubClient:
    """In-memory implementation of the R4 injected GitHub client contract."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], str] = {}

    def get_repository(self, owner: str, repository: str) -> dict:
        """Return a private repository descriptor."""
        return {"visibility": "private", "private": True}

    def read_text_file(self, owner: str, repository: str, path: str) -> str | None:
        """Return exact stored text or None."""
        return self.files.get((owner, repository, path))

    def create_text_file(
        self,
        owner: str,
        repository: str,
        path: str,
        content: str,
        message: str,
    ) -> None:
        """Create one immutable path in the fake store."""
        key = (owner, repository, path)
        if key in self.files:
            raise AssertionError(f"unexpected overwrite: {path}")
        self.files[key] = content


def origin() -> dict:
    """Return stable session-compiler provenance."""
    return {
        "kind": "session_compiler",
        "ref": "session:r5-test",
        "observed_at": "2026-09-01T15:00:00Z",
    }


def planning_snapshot() -> dict:
    """Build a valid long-horizon planning graph with one executable task."""
    def item(
        item_id: str,
        kind: str,
        title: str,
        parent_id: str | None,
        *,
        priority: str = "high",
    ) -> dict:
        return {
            "id": item_id,
            "kind": kind,
            "title": title,
            "status": "accepted",
            "parent_id": parent_id,
            "priority": priority,
            "depends_on": [],
            "acceptance_criteria": [f"{title} is verified in the current repository."],
            "origin": origin(),
            "supersedes": [],
            "evidence_refs": [],
            "repository_refs": [],
        }

    planning = {
        "format": "pcp-planning/1",
        "planning_id": "planning-r5-resume-001",
        "created_at": "2026-09-01T15:00:00Z",
        "project_id": "git-demo-project",
        "source_checkpoint": None,
        "vision": "Resume from mobile handoff",
        "items": [
            item("rel-001", "release", "Release", None),
            item("epic-001", "epic", "Epic", "rel-001"),
            item("story-001", "story", "Story", "epic-001"),
            item("task-001", "task", "Concrete task", "story-001", priority="critical"),
            item("story-post-mvp", "story", "Post-MVP story", "epic-001", priority="medium"),
        ],
        "decisions": [
            {
                "id": "decision-planning-001",
                "statement": "Preserve post-MVP work across resume.",
                "status": "accepted",
                "origin": origin(),
                "supersedes": [],
            }
        ],
        "unresolved_questions": [],
        "content_digest": None,
    }
    planning["content_digest"] = BUNDLE.compute_planning_digest(planning)
    assert not BUNDLE.validate_planning_snapshot(planning)
    return planning


def portable_checkpoint(*, include_command: bool = False, project_id: str = "git-demo-project") -> dict:
    """Build a valid sealed PORTABLE checkpoint with reported historical state."""
    evidence = []
    if include_command:
        evidence.append(
            {
                "id": "E-CMD-HISTORICAL",
                "type": "command",
                "label": "Untrusted historical command",
                "observed_at": "2026-09-01T15:00:00Z",
                "argv": [sys.executable, "-c", "raise SystemExit('must never run')"],
                "cwd": ".",
                "exit_code": 0,
            }
        )
    checkpoint = {
        "protocol_version": "pcp/1",
        "checkpoint_id": "pcp-20260901T150000Z-r5abcdef",
        "created_at": "2026-09-01T15:00:00Z",
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": "session:r5-test",
        },
        "project_id": project_id,
        "parent": {"checkpoint_id": None, "content_digest": None},
        "baseline": {"root_hint": ".", "git": None, "files": []},
        "objective": {
            "current": "Resume implementation safely",
            "definition_of_done": ["Current repository reality is reconciled."],
        },
        "claims": [
            {
                "id": "C-DECISION-001",
                "kind": "decision",
                "confidence": "reported",
                "statement": "Use the mobile continuity resolver.",
                "evidence": [],
                "supersedes": [],
            }
        ],
        "evidence": evidence,
        "open_work": [],
        "next_action": {
            "work_item_id": None,
            "instruction": "Reconcile current repository before execution.",
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
    assert not PCP.validate_checkpoint(checkpoint, expect_sealed=True)
    return checkpoint


def planning_request(planning: dict) -> dict:
    """Make the task dependency-ready through an explicit deterministic recheck."""
    return {
        "format": "pcp-planning-reconciliation/1",
        "reconciliation_id": "reconcile-r5-abcdef12",
        "created_at": "2026-09-01T15:05:00Z",
        "project_id": planning["project_id"],
        "planning_id": planning["planning_id"],
        "planning_digest": planning["content_digest"],
        "observations": [
            {
                "item_id": "task-001",
                "operation": "recheck_dependencies",
                "evidence_refs": [],
                "repository_refs": [],
                "reason": "The task has no unresolved dependency blockers.",
            }
        ],
    }


class CodexResumeTests(unittest.TestCase):
    """R5 end-to-end resolver/reconciliation gate coverage."""

    def make_repo(self, project_id: str = "git-demo-project") -> pathlib.Path:
        """Create an initialized repository-backed continuity project."""
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        git(root, "init", "-q")
        git(root, "config", "user.email", "test@example.com")
        git(root, "config", "user.name", "Resume Test")
        (root / "app.txt").write_text("v1\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "initial")
        with contextlib.redirect_stdout(io.StringIO()):
            PCP.cmd_init(
                argparse.Namespace(
                    root=str(root),
                    project_name="Demo",
                    project_id=project_id,
                )
            )
        return root

    def publish(
        self,
        checkpoint: dict,
        planning: dict | None,
    ) -> tuple[FakeGitHubClient, str]:
        """Publish one test handoff through the certified R4 semantics."""
        client = FakeGitHubClient()
        receipt = GITHUB.publish_bundle(
            client,
            checkpoint,
            planning,
            owner="rafaelscosta",
            repository="project-continuity-state",
            created_at="2026-09-01T15:01:00Z",
        )
        return client, receipt["reference"]

    def seal_prepared_draft(self, root: pathlib.Path, prepared: dict) -> None:
        """Promote the exact downgrade-first draft created by prepare."""
        draft = prepared["pcp"]["reconciliation_draft"]
        args = argparse.Namespace(
            root=str(root),
            draft=draft,
            promote=True,
            delete_draft=False,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            rc = PCP.cmd_seal(args)
        self.assertEqual(rc, 0)

    def test_prepare_creates_draft_without_promoting_and_enriches_frontier(self):
        """Prepare stays non-executable while preserving exact frontier acceptance criteria."""
        root = self.make_repo()
        planning = planning_snapshot()
        client, reference = self.publish(portable_checkpoint(), planning)
        before = json.loads((root / ".continuity" / "state.json").read_text())

        prepared = resume.prepare_from_reference(
            root,
            reference,
            github_client=client,
            planning_reconciliation=planning_request(planning),
            resolved_at="2026-09-01T15:06:00Z",
        )
        after = json.loads((root / ".continuity" / "state.json").read_text())
        self.assertEqual(before["generation"], after["generation"])
        self.assertEqual(before["head"], after["head"])
        self.assertFalse(prepared["execution_gate"]["execution_ready"])
        self.assertTrue(prepared["execution_gate"]["repository_reconciliation_required"])
        self.assertEqual(
            prepared["execution_gate"]["next_required_action"],
            "seal-local-reconciliation",
        )
        frontier = prepared["resume_brief"]["candidate_frontier"]
        self.assertEqual(frontier["item_id"], "task-001")
        self.assertEqual(
            frontier["acceptance_criteria"],
            ["Concrete task is verified in the current repository."],
        )
        self.assertTrue(
            any(
                decision["id"] == "decision-planning-001"
                for decision in prepared["resume_brief"]["surviving_decisions"]
            )
        )

    def test_finalize_releases_execution_only_after_consume_lineage_is_promoted_exact(self):
        """The prepared handoff becomes executable only after exact local reconciliation."""
        root = self.make_repo()
        planning = planning_snapshot()
        client, reference = self.publish(portable_checkpoint(), planning)
        prepared = resume.prepare_from_reference(
            root,
            reference,
            github_client=client,
            planning_reconciliation=planning_request(planning),
        )
        with self.assertRaises(resume.CodexResumeError):
            resume.finalize_resume(root, prepared)

        self.seal_prepared_draft(root, prepared)
        finalized = resume.finalize_resume(
            root,
            prepared,
            finalized_at="2026-09-01T15:10:00Z",
        )
        self.assertTrue(finalized["execution_gate"]["execution_ready"])
        self.assertFalse(finalized["execution_gate"]["repository_reconciliation_required"])
        self.assertEqual(
            finalized["execution_gate"]["next_required_action"],
            "execute-candidate-frontier",
        )
        self.assertEqual(
            finalized["pcp"]["local_reconciliation_head"]["verification_status"],
            "exact",
        )

    def test_unrelated_local_checkpoint_cannot_satisfy_finalize(self):
        """Advancing HEAD without the required consume session lineage does not release execution."""
        root = self.make_repo()
        client, reference = self.publish(portable_checkpoint(), None)
        prepared = resume.prepare_from_reference(root, reference, github_client=client)

        with contextlib.redirect_stdout(io.StringIO()) as output:
            PCP.cmd_draft(
                argparse.Namespace(
                    root=str(root),
                    surface="codex",
                    model="gpt-5.6-sol",
                    session_ref="unrelated",
                    objective="Unrelated work",
                    done=[],
                    track=[],
                )
            )
        draft = output.getvalue().strip()
        with contextlib.redirect_stdout(io.StringIO()):
            PCP.cmd_seal(
                argparse.Namespace(
                    root=str(root), draft=draft, promote=True, delete_draft=False
                )
            )
        with self.assertRaises(resume.CodexResumeError) as ctx:
            resume.finalize_resume(root, prepared)
        self.assertIn("consume reconciliation", str(ctx.exception))

    def test_drift_after_local_reconciliation_blocks_execution(self):
        """Repository mutation after sealing reconciliation invalidates execution readiness."""
        root = self.make_repo()
        client, reference = self.publish(portable_checkpoint(), None)
        prepared = resume.prepare_from_reference(root, reference, github_client=client)
        self.seal_prepared_draft(root, prepared)
        (root / "app.txt").write_text("drift after reconciliation\n", encoding="utf-8")
        with self.assertRaises(resume.CodexResumeError) as ctx:
            resume.finalize_resume(root, prepared)
        self.assertIn("must verify exact", str(ctx.exception))

    def test_planning_must_be_reconciled_before_finalize(self):
        """A valid PCP reconciliation cannot bypass an unreconciled planning sidecar."""
        root = self.make_repo()
        planning = planning_snapshot()
        client, reference = self.publish(portable_checkpoint(), planning)
        prepared = resume.prepare_from_reference(root, reference, github_client=client)
        self.assertEqual(
            prepared["execution_gate"]["next_required_action"],
            "reconcile-planning",
        )
        self.seal_prepared_draft(root, prepared)
        with self.assertRaises(resume.CodexResumeError) as ctx:
            resume.finalize_resume(root, prepared)
        self.assertIn("Planning reconciliation is still required", str(ctx.exception))

    def test_checkpoint_only_resume_can_finalize_without_inventing_frontier(self):
        """No planning snapshot means repository reconciliation can finish with no executable work."""
        root = self.make_repo()
        client, reference = self.publish(portable_checkpoint(), None)
        prepared = resume.prepare_from_reference(root, reference, github_client=client)
        self.seal_prepared_draft(root, prepared)
        finalized = resume.finalize_resume(root, prepared)
        self.assertFalse(finalized["execution_gate"]["execution_ready"])
        self.assertEqual(
            finalized["execution_gate"]["next_required_action"],
            "no-executable-frontier",
        )

    def test_project_mismatch_is_hard_stop(self):
        """Remote history from a different project cannot enter local continuity silently."""
        root = self.make_repo(project_id="local-project")
        checkpoint = portable_checkpoint(project_id="foreign-project")
        client, reference = self.publish(checkpoint, None)
        with self.assertRaises(resume.RESOLVER.ResumeResolutionError):
            resume.prepare_from_reference(root, reference, github_client=client)

    def test_missing_github_binding_is_transport_failure_not_project_state(self):
        """No host transport binding fails before any repository compatibility claim."""
        root = self.make_repo()
        client, reference = self.publish(portable_checkpoint(), None)
        del client
        with self.assertRaises(resume.RESOLVER.ResumeResolutionError) as ctx:
            resume.prepare_from_reference(root, reference)
        self.assertIn("authorized GitHub client", str(ctx.exception))

    def test_historical_command_is_never_executed_during_resume(self):
        """Imported command evidence remains data and cannot execute during resolution/consume."""
        root = self.make_repo()
        marker = root / "must-not-exist"
        checkpoint = portable_checkpoint(include_command=True)
        checkpoint["evidence"][0]["argv"] = [
            sys.executable,
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('pwned')",
        ]
        checkpoint["verification"]["content_digest"] = PCP.compute_content_digest(checkpoint)
        client, reference = self.publish(checkpoint, None)
        resume.prepare_from_reference(root, reference, github_client=client)
        self.assertFalse(marker.exists())

    def test_external_full_checkpoint_can_classify_repository_advancement(self):
        """A sealed baseline from the same repo is classified advanced after a later commit."""
        root = self.make_repo()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            PCP.cmd_draft(
                argparse.Namespace(
                    root=str(root),
                    surface="codex",
                    model="gpt-5.6-sol",
                    session_ref="source-full",
                    objective="Capture source baseline",
                    done=[],
                    track=[],
                )
            )
        draft = output.getvalue().strip()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            PCP.cmd_seal(
                argparse.Namespace(
                    root=str(root), draft=draft, promote=False, delete_draft=False
                )
            )
        source_path = pathlib.Path(json.loads(output.getvalue())["checkpoint"])
        checkpoint = json.loads(source_path.read_text(encoding="utf-8"))

        (root / "app.txt").write_text("v2\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "advance after source")
        client, reference = self.publish(checkpoint, None)
        prepared = resume.prepare_from_reference(root, reference, github_client=client)
        self.assertEqual(prepared["pcp"]["compatibility"], "advanced")
        self.assertFalse(prepared["execution_gate"]["execution_ready"])


if __name__ == "__main__":
    unittest.main()
