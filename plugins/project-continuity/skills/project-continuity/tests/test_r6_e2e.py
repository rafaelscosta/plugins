from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import io
import pathlib
import subprocess
import sys
import tempfile
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


SESSION = load_module("pcp_r6_session_compile", "session_compile.py")
CODEX = load_module("pcp_r6_codex_resume", "codex_resume.py")
PCP = CODEX.PCP
GITHUB = CODEX.RESOLVER.GITHUB
PLANNING = CODEX.PLANNING
BUNDLE = CODEX.RESOLVER.BUNDLE


class FakeGitHubClient:
    """Private in-memory store implementing the R4 host-binding contract."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], str] = {}
        self.create_calls: list[tuple[str, str, str]] = []

    def get_repository(self, owner: str, repository: str) -> dict:
        return {"visibility": "private", "private": True}

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
            raise AssertionError(f"unexpected overwrite: {path}")
        self.files[key] = content
        self.create_calls.append(key)


def git(root: pathlib.Path, *args: str) -> str:
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


def ir_origin(kind: str = "conversation", ref: str = "chat:r6-mobile") -> dict:
    return {"kind": kind, "ref": ref}


def ir_item(
    item_id: str,
    kind: str,
    title: str,
    parent_id: str | None,
    *,
    status: str = "accepted",
    priority: str = "high",
) -> dict:
    return {
        "id": item_id,
        "kind": kind,
        "title": title,
        "status": status,
        "parent_id": parent_id,
        "priority": priority,
        "depends_on": [],
        "acceptance_criteria": [f"{title} is verified in the current repository."],
        "origin": ir_origin(),
        "supersedes": [],
        "evidence_refs": [],
        "repository_refs": [],
    }


def mobile_compilation() -> dict:
    """Session IR with an explicit current task plus accepted post-MVP work."""
    return {
        "format": "pcp-session-compilation/1",
        "compilation_id": "compilation-r6-mobile-0001",
        "created_at": "2026-09-01T15:50:00Z",
        "project": {
            "id": "git-r6-mobile-project",
            "name": "R6 Mobile Project",
            "repository": "github:rafaelscosta/r6-mobile-project",
        },
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": "chat:r6-mobile",
        },
        "prior_checkpoint": None,
        "objective": {
            "current": "Continue the accepted mobile continuity implementation.",
            "definition_of_done": [
                "Codex resumes safely and fresh ChatGPT preserves accepted future work."
            ],
        },
        "decisions": [
            {
                "id": "decision-r6-mobile",
                "statement": "Use the content-addressed GitHub handoff path for mobile continuity.",
                "status": "accepted",
                "confidence": "reported",
                "origin": ir_origin("current_user"),
                "supersedes": [],
            }
        ],
        "findings": [],
        "planning": {
            "vision": "Phone-only ChatGPT to Codex continuity without transcript replay.",
            "items": [
                ir_item("rel-r6", "release", "R6 certification", None),
                ir_item("epic-r6", "epic", "Mobile E2E", "rel-r6"),
                ir_item("story-r6", "story", "Codex resume path", "epic-r6"),
                ir_item(
                    "task-r6-current",
                    "task",
                    "Implement the current frontier",
                    "story-r6",
                    priority="critical",
                ),
                ir_item(
                    "story-r6-post-mvp",
                    "story",
                    "Post-MVP continuity hardening",
                    "epic-r6",
                    priority="medium",
                ),
            ],
        },
        "blockers": [],
        "risks": [],
        "uncertainties": ["Current repository reality must be established by Codex."],
        "next_frontier": {
            "planning_item_id": "task-r6-current",
            "instruction": "Implement the current frontier after repository reconciliation.",
            "acceptance_criteria": ["Current frontier is reconciled against repository reality."],
        },
    }


def compile_mobile_in_memory(source: dict) -> tuple[dict, dict]:
    """Exercise the supported Session Compiler semantics without producer filesystem handoff."""
    errors = SESSION.COMPILER.validate_compilation(source)
    if errors:
        raise AssertionError(errors)
    SESSION.validate_blocker_dependencies(source)
    SESSION.validate_supersession_references(source)
    checkpoint, planning = SESSION.COMPILER.compile_session(
        source,
        seal_portable=True,
        sealed_at="2026-09-01T15:51:00Z",
    )
    SESSION.normalize_pcp_decision_supersedes(checkpoint, source)
    SESSION.refresh_digests_after_normalization(checkpoint, planning)
    return checkpoint, planning


def reconciliation_request(
    planning: dict,
    *,
    operation: str,
    item_id: str = "task-r6-current",
    reconciliation_id: str = "reconcile-r6-mobile-0001",
    evidence_refs: list[str] | None = None,
) -> dict:
    return {
        "format": "pcp-planning-reconciliation/1",
        "reconciliation_id": reconciliation_id,
        "created_at": "2026-09-01T15:55:00Z",
        "project_id": planning["project_id"],
        "planning_id": planning["planning_id"],
        "planning_digest": planning["content_digest"],
        "observations": [
            {
                "item_id": item_id,
                "operation": operation,
                "evidence_refs": list(evidence_refs or []),
                "repository_refs": ["git:HEAD"],
                "reason": "Observed current repository state during R6 certification.",
            }
        ],
    }


class R6DeterministicE2ETests(unittest.TestCase):
    """Normative deterministic approximation of ChatGPT-mobile -> Codex -> ChatGPT."""

    def make_repo(self) -> pathlib.Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        git(root, "init", "-q")
        git(root, "config", "user.email", "r6@example.com")
        git(root, "config", "user.name", "R6 Test")
        (root / "app.txt").write_text("before-r6\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "initial")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = PCP.cmd_init(
                argparse.Namespace(
                    root=str(root),
                    project_name="R6 Mobile Project",
                    project_id="git-r6-mobile-project",
                )
            )
        self.assertEqual(rc, 0)
        return root

    def publish(
        self,
        client: FakeGitHubClient,
        checkpoint: dict,
        planning: dict | None,
        *,
        created_at: str,
    ) -> dict:
        return GITHUB.publish_bundle(
            client,
            checkpoint,
            planning,
            owner="rafaelscosta",
            repository="project-continuity-state",
            created_at=created_at,
            project_repository="github:rafaelscosta/r6-mobile-project",
        )

    def promote_prepared_draft(self, root: pathlib.Path, prepared: dict) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = PCP.cmd_seal(
                argparse.Namespace(
                    root=str(root),
                    draft=prepared["pcp"]["reconciliation_draft"],
                    promote=True,
                    delete_draft=False,
                )
            )
        self.assertEqual(rc, 0)

    def create_progress_checkpoint(self, root: pathlib.Path) -> dict:
        """Record actual repository progress and seal a new local Codex checkpoint."""
        (root / "app.txt").write_text("after-r6-material-progress\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "implement R6 frontier")

        with contextlib.redirect_stdout(io.StringIO()) as output:
            rc = PCP.cmd_draft(
                argparse.Namespace(
                    root=str(root),
                    surface="codex",
                    model="gpt-5.6-sol",
                    session_ref="codex:r6-progress",
                    objective="Continue after material R6 progress.",
                    done=["Material repository progress is represented by the current Git baseline."],
                    track=["app.txt"],
                )
            )
        self.assertEqual(rc, 0)
        draft = output.getvalue().strip()
        with contextlib.redirect_stdout(io.StringIO()):
            rc = PCP.cmd_seal(
                argparse.Namespace(
                    root=str(root),
                    draft=draft,
                    promote=True,
                    delete_draft=False,
                )
            )
        self.assertEqual(rc, 0)
        _, state = PCP.load_state(root)
        return PCP.read_json(PCP.checkpoint_path(root, state["head"]["checkpoint_id"]))

    def test_full_mobile_round_trip_preserves_post_mvp_without_transcript_replay(self):
        """A fresh ChatGPT delta inherits accepted future work solely from the returned reference."""
        client = FakeGitHubClient()
        source = mobile_compilation()
        portable, planning = compile_mobile_in_memory(source)

        self.assertEqual(portable["producer"]["surface"], "chatgpt")
        self.assertEqual(portable["verification"]["status"], "sealed")
        self.assertEqual(portable["verification"]["surface_status"], "unverifiable")
        self.assertFalse(any(claim["kind"] == "completed" for claim in portable["claims"]))

        first = self.publish(
            client,
            portable,
            planning,
            created_at="2026-09-01T15:52:00Z",
        )
        self.assertTrue(first["reference"].startswith("pcp+github://"))
        self.assertNotIn("token", first["reference"].lower())

        root = self.make_repo()
        ready_request = reconciliation_request(planning, operation="recheck_dependencies")
        reconciled_planning, _ = PLANNING.reconcile(planning, ready_request)
        prepared = CODEX.prepare_from_reference(
            root,
            first["reference"],
            github_client=client,
            planning_reconciliation=ready_request,
            resolved_at="2026-09-01T15:56:00Z",
        )
        self.assertFalse(prepared["execution_gate"]["execution_ready"])
        self.assertEqual(
            prepared["resume_brief"]["candidate_frontier"]["item_id"],
            "task-r6-current",
        )

        self.promote_prepared_draft(root, prepared)
        finalized = CODEX.finalize_resume(
            root,
            prepared,
            finalized_at="2026-09-01T15:57:00Z",
        )
        self.assertTrue(finalized["execution_gate"]["execution_ready"])

        progress_checkpoint = self.create_progress_checkpoint(root)
        done_request = reconciliation_request(
            reconciled_planning,
            operation="verify_complete",
            reconciliation_id="reconcile-r6-mobile-0002",
            evidence_refs=["E-R6-CURRENT-001"],
        )
        updated_planning, done_report = PLANNING.reconcile(
            reconciled_planning,
            done_request,
        )
        task_transition = next(
            transition
            for transition in done_report["transitions"]
            if transition["item_id"] == "task-r6-current"
        )
        self.assertEqual(task_transition["to_status"], "verified_done")
        updated_planning["source_checkpoint"] = {
            "id": progress_checkpoint["checkpoint_id"],
            "digest": progress_checkpoint["verification"]["content_digest"],
        }
        updated_planning["content_digest"] = None
        updated_planning["content_digest"] = BUNDLE.compute_planning_digest(updated_planning)
        self.assertFalse(BUNDLE.validate_planning_snapshot(updated_planning))

        second = self.publish(
            client,
            progress_checkpoint,
            updated_planning,
            created_at="2026-09-01T16:00:00Z",
        )
        self.assertNotEqual(first["reference"], second["reference"])

        fresh = GITHUB.resolve_bundle(client, second["reference"])
        self.assertEqual(fresh["checkpoint"]["producer"]["surface"], "codex")
        self.assertEqual(
            fresh["planning_snapshot"]["content_digest"],
            updated_planning["content_digest"],
        )

        # New ChatGPT session sees only the new reference plus a tiny current delta.
        delta = mobile_compilation()
        delta["created_at"] = "2026-09-01T16:05:00Z"
        delta["compilation_id"] = "compilation-r6-fresh-chat-0002"
        delta["producer"]["session_ref"] = "chat:r6-fresh"
        delta["decisions"] = []
        delta["findings"] = []
        delta["planning"]["items"] = []
        delta["next_frontier"] = None
        delta["uncertainties"] = []

        SESSION.validate_prior_planning_integrity(fresh["planning_snapshot"])
        merged = SESSION.MERGE.merge_compilation_with_prior(
            delta,
            fresh["planning_snapshot"],
        )
        ids = {item["id"] for item in merged["planning"]["items"]}
        self.assertIn("story-r6-post-mvp", ids)
        current = next(
            item for item in merged["planning"]["items"]
            if item["id"] == "task-r6-current"
        )
        self.assertEqual(current["status"], "verified_done")
        post_mvp = next(
            item for item in merged["planning"]["items"]
            if item["id"] == "story-r6-post-mvp"
        )
        self.assertEqual(post_mvp["status"], "accepted")

        fresh_portable, fresh_planning = compile_mobile_in_memory(merged)
        self.assertEqual(fresh_portable["verification"]["status"], "sealed")
        self.assertEqual(fresh_portable["verification"]["surface_status"], "unverifiable")
        self.assertIn(
            "story-r6-post-mvp",
            {item["id"] for item in fresh_planning["items"]},
        )

    def test_tamper_after_round_trip_still_fails_before_project_authority(self):
        """A remote planning mutation remains integrity failure even after a valid first publish."""
        client = FakeGitHubClient()
        checkpoint, planning = compile_mobile_in_memory(mobile_compilation())
        receipt = self.publish(
            client,
            checkpoint,
            planning,
            created_at="2026-09-01T15:52:00Z",
        )
        planning_path = receipt["paths"]["planning"]
        key = ("rafaelscosta", "project-continuity-state", planning_path)
        original = client.files[key]
        client.files[key] = original.replace("Post-MVP continuity hardening", "tampered planning")
        with self.assertRaises(GITHUB.TransportError) as ctx:
            GITHUB.resolve_bundle(client, receipt["reference"])
        self.assertEqual(ctx.exception.code, "integrity-failed")

    def test_mobile_reference_never_contains_credentials(self):
        """The complete producer path returns a compact locator with no auth material."""
        client = FakeGitHubClient()
        checkpoint, planning = compile_mobile_in_memory(mobile_compilation())
        receipt = self.publish(
            client,
            checkpoint,
            planning,
            created_at="2026-09-01T15:52:00Z",
        )
        reference = receipt["reference"]
        lowered = reference.lower()
        self.assertNotIn("authorization", lowered)
        self.assertNotIn("bearer", lowered)
        self.assertNotIn("access_token", lowered)
        self.assertNotIn("?", reference)
        self.assertNotIn("#", reference)


if __name__ == "__main__":
    unittest.main()
