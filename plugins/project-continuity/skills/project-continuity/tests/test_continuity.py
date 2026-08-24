from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "continuity.py"
spec = importlib.util.spec_from_file_location("continuity", MODULE_PATH)
continuity = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(continuity)


def git(root: pathlib.Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
    if cp.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {cp.stdout}")
    return cp.stdout.strip()


def run_cli(*args: str) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = continuity.main(list(args))
    return rc, out.getvalue(), err.getvalue()


class ContinuityTests(unittest.TestCase):
    def make_repo(self) -> pathlib.Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        git(root, "init", "-q")
        git(root, "config", "user.email", "test@example.com")
        git(root, "config", "user.name", "Continuity Test")
        (root / "app.txt").write_text("v1\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "initial")
        rc, _, err = run_cli("init", "--root", str(root), "--project-name", "Demo")
        self.assertEqual(rc, 0, err)
        return root

    def make_draft(self, root: pathlib.Path, *, track: bool = True) -> pathlib.Path:
        args = [
            "draft",
            "--root", str(root),
            "--surface", "codex",
            "--model", "gpt-5.6-sol",
            "--objective", "Validate continuity",
        ]
        if track:
            args += ["--track", "app.txt"]
        rc, out, err = run_cli(*args)
        self.assertEqual(rc, 0, err)
        return pathlib.Path(out.strip())

    def seal(self, root: pathlib.Path, draft: pathlib.Path, *, promote: bool = True) -> dict:
        args = ["seal", "--root", str(root), "--draft", str(draft)]
        if promote:
            args.append("--promote")
        rc, out, err = run_cli(*args)
        self.assertEqual(rc, 0, err)
        return json.loads(out)

    def test_completed_claim_requires_hard_evidence(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["claims"].append({
            "id": "C-001",
            "kind": "completed",
            "confidence": "verified",
            "statement": "Something is complete.",
            "evidence": [],
            "supersedes": [],
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("requires at least one hard evidence", err)

    def test_exact_seal_and_verify(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["claims"].append({
            "id": "C-001",
            "kind": "completed",
            "confidence": "verified",
            "statement": "The tracked baseline file is captured.",
            "evidence": ["E-FILE-002"],
            "supersedes": [],
        })
        # draft inserts Git evidence first, then tracked file evidence keeps its generated id E-FILE-001
        cp["claims"][0]["evidence"] = [next(ev["id"] for ev in cp["evidence"] if ev["type"] == "file_hash")]
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        self.seal(root, draft)
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "exact")
        self.assertTrue(result["integrity"]["valid"])

    def test_tamper_detection(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        sealed = self.seal(root, draft)
        path = pathlib.Path(sealed["checkpoint"])
        cp = json.loads(path.read_text(encoding="utf-8"))
        cp["objective"]["current"] = "Tampered objective"
        path.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        rc, out, _ = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 2)
        result = json.loads(out)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("content digest mismatch", " ".join(result["integrity"]["errors"]))

    def test_dirty_drift_detection(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft)
        (root / "app.txt").write_text("changed without commit\n", encoding="utf-8")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "drift")

    def test_forward_progress_is_advanced(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft)
        (root / "app.txt").write_text("v2\n", encoding="utf-8")
        git(root, "add", "app.txt")
        git(root, "commit", "-qm", "advance")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "advanced")

    def test_diverged_history_detection(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft)
        git(root, "checkout", "--orphan", "other")
        # remove tracked files from orphan index/worktree and create unrelated history
        git(root, "rm", "-rf", ".")
        (root / "other.txt").write_text("unrelated\n", encoding="utf-8")
        git(root, "add", "other.txt")
        git(root, "commit", "-qm", "unrelated")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "diverged")

    def test_parallel_writer_promotion_is_rejected(self):
        root = self.make_repo()
        a = self.make_draft(root)
        b = self.make_draft(root)
        self.seal(root, a, promote=True)
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(b), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("Parallel-head conflict", err)
        # Detached B was still sealed.
        b_id = json.loads(b.read_text(encoding="utf-8"))["checkpoint_id"]
        self.assertTrue((root / ".continuity" / "checkpoints" / f"{b_id}.json").exists())
        state = json.loads((root / ".continuity" / "state.json").read_text(encoding="utf-8"))
        self.assertNotEqual(state["head"]["checkpoint_id"], b_id)

    def test_stale_test_evidence_cannot_support_completion(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        rc, out, err = run_cli(
            "run", "--root", str(root), "--draft", str(draft),
            "--kind", "test", "--label", "sample test", "--",
            sys.executable, "-c", "print('ok')"
        )
        self.assertEqual(rc, 0, err)
        eid = json.loads(out)["evidence_id"]
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["claims"].append({
            "id": "C-001",
            "kind": "completed",
            "confidence": "verified",
            "statement": "Behavior is validated by the recorded test.",
            "evidence": [eid],
            "supersedes": [],
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        (root / "app.txt").write_text("changed after test\n", encoding="utf-8")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("older project state", err)

    def test_doctor_reports_detached_checkpoint_without_corrupting_head(self):
        root = self.make_repo()
        a = self.make_draft(root)
        b = self.make_draft(root)
        self.seal(root, a, promote=True)
        rc, _, _ = run_cli("seal", "--root", str(root), "--draft", str(b))
        self.assertEqual(rc, 0)
        rc, out, err = run_cli("doctor", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertTrue(result["healthy"])
        self.assertTrue(any(f["code"] == "detached-checkpoint" for f in result["findings"]))

    def test_continuity_only_commit_does_not_create_false_advancement(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft)
        git(root, "add", ".continuity")
        git(root, "commit", "-qm", "record continuity metadata")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "exact")

    def test_failing_test_evidence_cannot_support_completion(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        rc, out, _ = run_cli(
            "run", "--root", str(root), "--draft", str(draft),
            "--kind", "test", "--label", "failing test", "--",
            sys.executable, "-c", "import sys; print('fail'); sys.exit(1)"
        )
        self.assertEqual(rc, 1)
        eid = json.loads(out)["evidence_id"]
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["claims"].append({
            "id": "C-FAIL-001",
            "kind": "completed",
            "confidence": "verified",
            "statement": "A failing test proves completion.",
            "evidence": [eid],
            "supersedes": [],
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("exit_code=0", err)

    def test_verify_never_executes_command_stored_in_checkpoint(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        marker = root / "should-not-exist"
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["evidence"].append({
            "id": "E-CMD-MAL",
            "type": "command",
            "label": "untrusted stored command",
            "observed_at": "2026-08-21T00:00:00Z",
            "argv": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('pwned')"],
            "cwd": ".",
            "exit_code": 0,
            "capture_method": "untrusted-import"
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        self.seal(root, draft)
        rc, _, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertFalse(marker.exists())

    def test_unborn_git_repository_degrades_without_crashing(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        git(root, "init", "-q")
        (root / "app.txt").write_text("unborn\n", encoding="utf-8")
        rc, _, err = run_cli("init", "--root", str(root), "--project-name", "Unborn")
        self.assertEqual(rc, 0, err)
        rc, out, err = run_cli(
            "draft", "--root", str(root), "--surface", "codex",
            "--objective", "Handle an unborn repository", "--track", "app.txt"
        )
        self.assertEqual(rc, 0, err)
        draft = pathlib.Path(out.strip())
        cp = json.loads(draft.read_text(encoding="utf-8"))
        self.assertIsNone(cp["baseline"]["git"])
        sealed = self.seal(root, draft)
        sealed_cp = json.loads(pathlib.Path(sealed["checkpoint"]).read_text(encoding="utf-8"))
        self.assertEqual(sealed_cp["verification"]["surface_status"], "historically-verified")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "exact")

    def test_portable_checkpoint_without_project_evidence_is_unverifiable(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        rc, _, err = run_cli("init", "--root", str(root), "--project-name", "Portable")
        self.assertEqual(rc, 0, err)
        rc, out, err = run_cli(
            "draft", "--root", str(root), "--surface", "chatgpt",
            "--objective", "Carry reported state"
        )
        self.assertEqual(rc, 0, err)
        draft = pathlib.Path(out.strip())
        sealed = self.seal(root, draft)
        cp = json.loads(pathlib.Path(sealed["checkpoint"]).read_text(encoding="utf-8"))
        self.assertEqual(cp["verification"]["surface_status"], "unverifiable")
        rc, out, err = run_cli("verify", "--root", str(root), "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["status"], "unverifiable")

    def test_tracking_symlink_outside_root_is_rejected(self):
        root = self.make_repo()
        outside = root.parent / "outside-target.txt"
        outside.write_text("secret outside\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        link = root / "escape-link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        rc, _, err = run_cli(
            "draft", "--root", str(root), "--surface", "codex",
            "--objective", "Reject symlink escape", "--track", "escape-link.txt"
        )
        self.assertEqual(rc, 2)
        self.assertIn("escapes project root", err)

    def test_recorded_command_output_redacts_common_secrets(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        secret_a = "pcp-super-secret-token"
        secret_b = "pcp-password-value"
        rc, out, err = run_cli(
            "run", "--root", str(root), "--draft", str(draft),
            "--kind", "command", "--label", "redaction check", "--",
            sys.executable, "-c",
            f"print('Authorization: Bearer {secret_a}'); print('password={secret_b}')"
        )
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        log = (root / payload["log_path"]).read_text(encoding="utf-8")
        self.assertNotIn(secret_a, log)
        self.assertNotIn(secret_b, log)
        self.assertIn("[REDACTED]", log)

    def test_tampered_evidence_log_cannot_support_completion(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        rc, out, err = run_cli(
            "run", "--root", str(root), "--draft", str(draft),
            "--kind", "test", "--label", "passing test", "--",
            sys.executable, "-c", "print('pass')"
        )
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        eid = payload["evidence_id"]
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["claims"].append({
            "id": "C-LOG-001", "kind": "completed", "confidence": "verified",
            "statement": "Validation passed.", "evidence": [eid], "supersedes": []
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        (root / payload["log_path"]).write_text("tampered\n", encoding="utf-8")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("log hash mismatch", err)

    def test_git_remote_identity_is_transport_and_display_name_independent(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name)
        git(root, "init", "-q")
        git(root, "remote", "add", "origin", "git@github.com:ExampleOrg/Continuity-Demo.git")
        first = continuity.project_id_from(root, "Display Name A")
        git(root, "remote", "set-url", "origin", "https://github.com/ExampleOrg/Continuity-Demo.git")
        second = continuity.project_id_from(root, "Completely Different Display Name")
        git(root, "remote", "set-url", "origin", "ssh://git@github.com/ExampleOrg/Continuity-Demo.git")
        third = continuity.project_id_from(root, "Third Name")
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertTrue(first.startswith("git-"))

    def test_verify_rejects_valid_checkpoint_from_other_project(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        sealed = self.seal(root, draft)
        source = pathlib.Path(sealed["checkpoint"])
        cp = json.loads(source.read_text(encoding="utf-8"))
        cp["project_id"] = "different-project"
        cp["verification"]["content_digest"] = None
        cp["verification"]["content_digest"] = continuity.compute_content_digest(cp)
        foreign = root / "foreign-checkpoint.json"
        foreign.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        rc, out, err = run_cli("verify", "--root", str(root), "--checkpoint", str(foreign), "--json")
        self.assertEqual(rc, 2, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "project-mismatch")
        self.assertTrue(result["integrity"]["valid"])

    def test_consume_requires_explicit_mapping_for_project_mismatch(self):
        root = self.make_repo()
        portable = json.loads((MODULE_PATH.parents[1] / "assets" / "templates" / "portable-checkpoint.json").read_text(encoding="utf-8"))
        portable["project_id"] = "foreign-project"
        source = root / "portable-foreign.json"
        source.write_text(json.dumps(portable, indent=2), encoding="utf-8")
        rc, _, err = run_cli(
            "consume", "--root", str(root), "--checkpoint", str(source),
            "--surface", "codex", "--model", "gpt-5.6-sol"
        )
        self.assertEqual(rc, 2)
        self.assertIn("--confirm-project-mapping", err)
        rc, out, err = run_cli(
            "consume", "--root", str(root), "--checkpoint", str(source),
            "--surface", "codex", "--model", "gpt-5.6-sol", "--confirm-project-mapping"
        )
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertTrue(result["project_mapping_confirmed"])
        draft = json.loads(pathlib.Path(result["draft"]).read_text(encoding="utf-8"))
        self.assertTrue(any(r["id"] == "R-MAPPING-001" for r in draft["risks"]))
        self.assertTrue(any(r["id"] == "R-UNSEALED-001" for r in draft["risks"]))

    def test_consume_downgrades_historical_completion_and_drops_imported_commands(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        cp = json.loads(draft.read_text(encoding="utf-8"))
        file_eid = next(ev["id"] for ev in cp["evidence"] if ev["type"] == "file_hash")
        cp["claims"].append({
            "id": "C-OLD-001", "kind": "completed", "confidence": "verified",
            "statement": "Old implementation was complete.", "evidence": [file_eid], "supersedes": []
        })
        cp["evidence"].append({
            "id": "E-MAL-001", "type": "command", "label": "historical command",
            "observed_at": "2026-08-21T00:00:00Z",
            "argv": [sys.executable, "-c", "raise SystemExit('must never import as executable proof')"],
            "cwd": ".", "exit_code": 0, "capture_method": "untrusted-import"
        })
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        sealed = self.seal(root, draft, promote=True)
        rc, out, err = run_cli(
            "consume", "--root", str(root), "--checkpoint", sealed["checkpoint"],
            "--surface", "codex", "--model", "gpt-5.6-sol"
        )
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["historical_completion_claims"], 1)
        reconciled = json.loads(pathlib.Path(result["draft"]).read_text(encoding="utf-8"))
        self.assertTrue(any(c["kind"] == "finding" and c["confidence"] == "reported" for c in reconciled["claims"]))
        self.assertFalse(any(ev["type"] in {"command", "test"} for ev in reconciled["evidence"]))
        self.assertTrue(any(w["id"] == "W-RECONCILE-001" for w in reconciled["open_work"]))

    def test_wrong_project_draft_is_rejected(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["project_id"] = "another-project"
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("project_id does not match", err)

    def test_doctor_detects_missing_parent_in_lineage(self):
        root = self.make_repo()
        first = self.make_draft(root)
        first_sealed = self.seal(root, first, promote=True)
        second = self.make_draft(root)
        self.seal(root, second, promote=True)
        pathlib.Path(first_sealed["checkpoint"]).unlink()
        rc, out, err = run_cli("doctor", "--root", str(root), "--json")
        self.assertEqual(rc, 2, err)
        result = json.loads(out)
        self.assertFalse(result["healthy"])
        self.assertTrue(any(f["code"] == "lineage-error" for f in result["findings"]))

    def test_malicious_checkpoint_id_cannot_escape_internal_paths(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        cp = json.loads(draft.read_text(encoding="utf-8"))
        cp["checkpoint_id"] = "pcp-/../../../../outside-checkpoint"
        draft.write_text(json.dumps(cp, indent=2), encoding="utf-8")
        outside = root.parent / "outside-checkpoint.json"
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("checkpoint_id must match", err)
        self.assertFalse(outside.exists())

    def test_symlinked_checkpoints_directory_is_rejected(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        checkpoints = root / ".continuity" / "checkpoints"
        checkpoints.rmdir()
        outside_dir = root.parent / "outside-checkpoints"
        outside_dir.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside_dir.rmdir() if outside_dir.exists() and not any(outside_dir.iterdir()) else None)
        try:
            checkpoints.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        rc, _, err = run_cli("seal", "--root", str(root), "--draft", str(draft), "--promote")
        self.assertEqual(rc, 2)
        self.assertIn("Symlink not allowed", err)
        self.assertEqual(list(outside_dir.iterdir()), [])

    def test_symlinked_evidence_directory_is_rejected(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        evidence = root / ".continuity" / "evidence"
        evidence.rmdir()
        outside_dir = root.parent / "outside-evidence"
        outside_dir.mkdir(exist_ok=True)
        self.addCleanup(lambda: outside_dir.rmdir() if outside_dir.exists() and not any(outside_dir.iterdir()) else None)
        try:
            evidence.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        rc, _, err = run_cli(
            "run", "--root", str(root), "--draft", str(draft),
            "--kind", "test", "--label", "must not escape", "--",
            sys.executable, "-c", "print('ok')"
        )
        self.assertEqual(rc, 2)
        self.assertIn("Symlink not allowed", err)
        self.assertEqual(list(outside_dir.iterdir()), [])

    def test_init_rejects_symlinked_continuity_directory(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = pathlib.Path(td.name) / "project"
        outside = pathlib.Path(td.name) / "outside"
        root.mkdir(); outside.mkdir()
        try:
            (root / ".continuity").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        rc, _, err = run_cli("init", "--root", str(root), "--project-name", "Symlink Attack")
        self.assertEqual(rc, 2)
        self.assertIn("Symlink not allowed", err)
        self.assertEqual(list(outside.iterdir()), [])

    def test_seal_cannot_delete_draft_outside_project(self):
        root = self.make_repo()
        outside = root.parent / "outside-draft.json"
        outside.write_text("{}\n", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        rc, _, err = run_cli(
            "seal", "--root", str(root), "--draft", str(outside),
            "--delete-draft", "--promote"
        )
        self.assertEqual(rc, 2)
        self.assertIn("inside .continuity/drafts", err)
        self.assertTrue(outside.exists())

    def test_render_output_cannot_escape_project_root(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft)
        outside = root.parent / "outside-render.md"
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        rc, _, err = run_cli("render", "--root", str(root), "--out", str(outside))
        self.assertEqual(rc, 2)
        self.assertIn("escapes project root", err)
        self.assertFalse(outside.exists())

    def test_tracking_path_outside_root_is_rejected(self):
        root = self.make_repo()
        outside = root.parent / "outside.txt"
        outside.write_text("nope", encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        rc, _, err = run_cli(
            "draft", "--root", str(root), "--surface", "codex",
            "--objective", "Reject traversal", "--track", "../outside.txt"
        )
        self.assertEqual(rc, 2)
        self.assertIn("escapes project root", err)

    def test_handoff_out_copies_sealed_head_bytes(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        sealed = self.seal(root, draft, promote=True)
        dest = root.parent / "pcp-handoff.json"
        self.addCleanup(lambda: dest.unlink(missing_ok=True))
        rc, out, err = run_cli("handoff-out", "--root", str(root), "--out", str(dest))
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        source = pathlib.Path(sealed["checkpoint"])
        source_cp = json.loads(source.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["checkpoint_id"], source_cp["checkpoint_id"])
        self.assertEqual(dest.read_bytes(), source.read_bytes())

    def test_handoff_out_requires_canonical_head(self):
        root = self.make_repo()
        dest = root.parent / "pcp-handoff-empty.json"
        self.addCleanup(lambda: dest.unlink(missing_ok=True))
        rc, _, err = run_cli("handoff-out", "--root", str(root), "--out", str(dest))
        self.assertEqual(rc, 2)
        self.assertIn("no canonical head", err)
        self.assertFalse(dest.exists())

    def test_handoff_in_consumes_interchange_file(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft, promote=True)
        interchange = root.parent / "pcp-handoff.json"
        self.addCleanup(lambda: interchange.unlink(missing_ok=True))
        rc, _, err = run_cli("handoff-out", "--root", str(root), "--out", str(interchange))
        self.assertEqual(rc, 0, err)
        rc, out, err = run_cli("handoff-in", "--root", str(root), "--checkpoint", str(interchange))
        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["status"], "reconciliation-required")
        self.assertTrue(result["project_match"])
        self.assertEqual(result["source_integrity"], "sealed-valid")

    def test_handoff_in_missing_file_is_rejected(self):
        root = self.make_repo()
        missing = root.parent / "missing-pcp-handoff.json"
        rc, _, err = run_cli("handoff-in", "--root", str(root), "--checkpoint", str(missing))
        self.assertEqual(rc, 2)
        self.assertIn("No interchange file", err)

    def test_handoff_out_rejects_symlink_dest(self):
        root = self.make_repo()
        draft = self.make_draft(root)
        self.seal(root, draft, promote=True)
        target = root.parent / "handoff-target.json"
        dest = root.parent / "handoff-link.json"
        target.write_text("{}\n", encoding="utf-8")
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        self.addCleanup(lambda: dest.unlink(missing_ok=True))
        try:
            dest.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        rc, _, err = run_cli("handoff-out", "--root", str(root), "--out", str(dest))
        self.assertEqual(rc, 2)
        self.assertIn("must not be a symlink", err)
        self.assertEqual(target.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
