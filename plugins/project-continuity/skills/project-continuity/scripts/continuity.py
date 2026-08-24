#!/usr/bin/env python3
"""Project Continuity Protocol (PCP/1) reference CLI.

Standard-library-only except for optional Git CLI integration.

The CLI deliberately never executes commands stored inside checkpoint data.
The `run` subcommand executes only argv explicitly supplied by the current
caller after `--` and records the result as evidence.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Iterable
from urllib.parse import urlparse

PROTOCOL = "pcp/1"
POLICY = "evidence-required-v1"
HARD_EVIDENCE_TYPES = {"file_hash", "git_commit", "command", "test", "artifact"}
EVIDENCE_TYPES = HARD_EVIDENCE_TYPES | {"source", "user_confirmation"}
CLAIM_KINDS = {"completed", "decision", "constraint", "finding", "assumption"}
CONFIDENCE = {"verified", "reported", "inferred"}
CHECKPOINT_ID_RE = re.compile(r"^pcp-[A-Za-z0-9._-]{8,}$")
WORK_STATUS = {"todo", "blocked"}
PRIORITY = {"critical", "high", "medium", "low"}
MAX_CAPTURED_LOG_BYTES = 2 * 1024 * 1024
LOCK_STALE_SECONDS = 300
HANDOFF_FILENAME = "pcp-handoff.json"


class ContinuityError(Exception):
    pass


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return "sha256:" + h.hexdigest(), size


def compute_content_digest(checkpoint: dict[str, Any]) -> str:
    clone = copy.deepcopy(checkpoint)
    clone.setdefault("verification", {})["content_digest"] = None
    return sha256_bytes(canonical_bytes(clone))


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as exc:
        raise ContinuityError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContinuityError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ContinuityError(f"Expected a JSON object in {path}")
    return data


def atomic_write_json(path: pathlib.Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def default_handoff_path() -> pathlib.Path:
    return pathlib.Path.home() / "Downloads" / HANDOFF_FILENAME


def resolve_handoff_path(supplied: str | None) -> pathlib.Path:
    path = pathlib.Path(supplied).expanduser() if supplied else default_handoff_path()
    if path.is_symlink():
        raise ContinuityError(f"Handoff path must not be a symlink: {path}")
    return path


def atomic_copy_file(source: pathlib.Path, dest: pathlib.Path) -> None:
    if source.is_symlink():
        raise ContinuityError(f"Source checkpoint must not be a symlink: {source}")
    dest = resolve_handoff_path(str(dest))
    if dest.exists() and dest.is_dir():
        raise ContinuityError(f"Handoff path is a directory: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = pathlib.Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "project"


def run_process(argv: list[str], cwd: pathlib.Path, *, timeout: int | None = 60) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ContinuityError(f"Executable not found: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ContinuityError(f"Command timed out after {timeout}s: {argv!r}") from exc


def git_output(root: pathlib.Path, args: list[str], *, timeout: int = 30, allow_fail: bool = False) -> bytes | None:
    if shutil.which("git") is None:
        return None
    cp = run_process(["git", *args], root, timeout=timeout)
    if cp.returncode != 0:
        if allow_fail:
            return None
        text = cp.stdout.decode("utf-8", errors="replace").strip()
        raise ContinuityError(f"git {' '.join(args)} failed ({cp.returncode}): {text}")
    return cp.stdout


def is_git_repo(root: pathlib.Path) -> bool:
    out = git_output(root, ["rev-parse", "--is-inside-work-tree"], allow_fail=True)
    return bool(out and out.strip() == b"true")


def git_remote_origin(root: pathlib.Path) -> str | None:
    out = git_output(root, ["remote", "get-url", "origin"], allow_fail=True)
    if not out:
        return None
    return out.decode("utf-8", errors="replace").strip() or None


def normalize_git_remote(remote: str) -> str:
    """Normalize common Git transport forms into one repository identity.

    Examples such as `git@github.com:org/repo.git`,
    `ssh://git@github.com/org/repo.git`, and
    `https://github.com/org/repo.git` should identify the same project.
    Credentials and usernames are intentionally excluded from identity.
    """
    value = remote.strip()
    host: str | None = None
    path = ""
    port: int | None = None

    # SCP-like Git syntax: [user@]host:path (but do not misread Windows drive paths).
    scp = re.match(r"^(?:[^/@:]+@)?([^/:]+):(.+)$", value) if "://" not in value else None
    if scp and not re.match(r"^[A-Za-z]:[\/]", value):
        host = scp.group(1).lower()
        path = scp.group(2)
    else:
        parsed = urlparse(value)
        if parsed.hostname:
            host = parsed.hostname.lower()
            port = parsed.port
            path = parsed.path
        elif parsed.scheme == "file":
            path = parsed.path
        else:
            path = value

    path = path.replace("\\", "/").strip().strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if host:
        default_port = (value.startswith("ssh://") and port == 22) or (value.startswith("https://") and port == 443) or (value.startswith("http://") and port == 80)
        port_part = f":{port}" if port and not default_port else ""
        return f"{host}{port_part}/{path}" if path else f"{host}{port_part}"
    return path or value


def ensure_internal_dir(root: pathlib.Path, relative: str, *, create: bool = False) -> pathlib.Path:
    """Return an internal continuity directory without following symlink escapes."""
    root = root.resolve()
    rel = pathlib.Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise ContinuityError(f"Invalid internal continuity path: {relative}")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ContinuityError(f"Symlink not allowed in continuity internal path: {current}")
        if current.exists() and not current.is_dir():
            raise ContinuityError(f"Continuity internal path must be a directory: {current}")
        if create and not current.exists():
            current.mkdir()
    try:
        current.resolve().relative_to(root)
    except ValueError as exc:
        raise ContinuityError(f"Continuity internal path escapes project root: {relative}") from exc
    return current


def safe_internal_file(parent: pathlib.Path, name: str) -> pathlib.Path:
    path = parent / name
    if path.is_symlink():
        raise ContinuityError(f"Symlink not allowed for continuity internal file: {path}")
    return path


def safe_project_path(root: pathlib.Path, supplied: str) -> tuple[pathlib.Path, str]:
    root_resolved = root.resolve()
    candidate = (root / supplied).resolve()
    try:
        rel = candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ContinuityError(f"Tracked path escapes project root: {supplied}") from exc
    if not candidate.exists():
        raise ContinuityError(f"Tracked path does not exist: {supplied}")
    if not candidate.is_file():
        raise ContinuityError(f"Tracked path must be a regular file: {supplied}")
    return candidate, rel.as_posix()


def safe_draft_path(root: pathlib.Path, supplied: str) -> pathlib.Path:
    path = pathlib.Path(supplied)
    if not path.is_absolute():
        path = root / path
    drafts_root = ensure_internal_dir(root, ".continuity/drafts", create=False).resolve()
    if path.is_symlink():
        raise ContinuityError(f"Draft path must not be a symlink: {supplied}")
    resolved = path.resolve()
    try:
        resolved.relative_to(drafts_root)
    except ValueError as exc:
        raise ContinuityError(f"Draft path must stay inside .continuity/drafts: {supplied}") from exc
    return resolved


def safe_output_path(root: pathlib.Path, supplied: str) -> pathlib.Path:
    path = pathlib.Path(supplied)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ContinuityError(f"Output path escapes project root: {supplied}") from exc
    return resolved


CONTINUITY_PATHSPECS = [".", ":(exclude).continuity/**", ":(exclude)CONTINUITY.md"]


def project_git_status(root: pathlib.Path) -> bytes:
    return git_output(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *CONTINUITY_PATHSPECS],
    ) or b""


def worktree_fingerprint(root: pathlib.Path) -> str:
    """Fingerprint project diffs plus untracked contents.

    Continuity's own metadata (`.continuity/` and generated `CONTINUITY.md`) is
    excluded so checkpoint creation cannot create self-induced drift. Ignored
    files are also excluded. This is a drift detector, not a full filesystem
    Merkle tree.
    """
    status = project_git_status(root)
    diff = git_output(root, ["diff", "--binary", "HEAD", "--", *CONTINUITY_PATHSPECS]) or b""
    untracked_raw = git_output(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *CONTINUITY_PATHSPECS],
    ) or b""
    h = hashlib.sha256()
    h.update(b"STATUS\0")
    h.update(status)
    h.update(b"\0DIFF\0")
    h.update(diff)
    h.update(b"\0UNTRACKED\0")
    for raw_name in sorted(p for p in untracked_raw.split(b"\0") if p):
        name = raw_name.decode("utf-8", errors="surrogateescape")
        path = (root / name)
        h.update(raw_name)
        h.update(b"\0")
        try:
            if path.is_symlink():
                h.update(b"SYMLINK\0")
                h.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                digest, size = sha256_file(path)
                h.update(str(size).encode("ascii"))
                h.update(b"\0")
                h.update(digest.encode("ascii"))
            else:
                h.update(b"NONREGULAR")
        except OSError as exc:
            h.update(f"ERROR:{exc.__class__.__name__}".encode("ascii", errors="ignore"))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def project_snapshot_fingerprint(root: pathlib.Path) -> str:
    """Hash effective project content while excluding continuity metadata.

    The committed tree listing is cheap to obtain because it hashes Git object
    identities rather than reading every tracked file. The worktree fingerprint
    is then mixed in so dirty/untracked project changes remain visible.
    """
    raw_tree = git_output(root, ["ls-tree", "-r", "-z", "HEAD"]) or b""
    kept: list[bytes] = []
    for entry in raw_tree.split(b"\0"):
        if not entry:
            continue
        try:
            path = entry.split(b"\t", 1)[1].decode("utf-8", errors="surrogateescape")
        except (IndexError, UnicodeError):
            kept.append(entry)
            continue
        if path == "CONTINUITY.md" or path == ".continuity" or path.startswith(".continuity/"):
            continue
        kept.append(entry)
    tree = b"\0".join(kept)
    worktree = worktree_fingerprint(root).encode("ascii")
    return sha256_bytes(b"TREE\0" + tree + b"\0WORKTREE\0" + worktree)


def capture_git(root: pathlib.Path) -> dict[str, Any] | None:
    if not is_git_repo(root):
        return None
    # An initialized repository may not have its first commit yet. Treat that
    # as a non-Git verification surface rather than crashing or inventing a HEAD.
    commit_b = git_output(root, ["rev-parse", "HEAD"], allow_fail=True)
    if not commit_b:
        return None
    branch_b = git_output(root, ["branch", "--show-current"], allow_fail=True)
    status_b = project_git_status(root)
    assert commit_b is not None
    branch = branch_b.decode("utf-8", errors="replace").strip() if branch_b else None
    return {
        "commit": commit_b.decode("ascii", errors="replace").strip(),
        "branch": branch or None,
        "dirty": bool(status_b),
        "worktree_sha256": worktree_fingerprint(root),
        "project_snapshot_sha256": project_snapshot_fingerprint(root),
    }


def project_id_from(root: pathlib.Path, project_name: str) -> str:
    remote = git_remote_origin(root) if is_git_repo(root) else None
    if remote:
        canonical_remote = normalize_git_remote(remote)
        suffix = hashlib.sha256(canonical_remote.encode("utf-8")).hexdigest()[:16]
        # Display names may differ across surfaces; remote-backed identity must not.
        return f"git-{suffix}"
    return slugify(project_name)


def validate_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("protocol_version") != PROTOCOL:
        errors.append(f"state.protocol_version must be {PROTOCOL}")
    project = state.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("id"), str) or not project.get("id"):
        errors.append("state.project.id must be a non-empty string")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project.get("name"):
        errors.append("state.project.name must be a non-empty string")
    generation = state.get("generation")
    if not isinstance(generation, int) or generation < 0:
        errors.append("state.generation must be a non-negative integer")
    head = state.get("head")
    if not isinstance(head, dict):
        errors.append("state.head must be an object")
    else:
        hid = head.get("checkpoint_id")
        hdig = head.get("content_digest")
        if (hid is None) != (hdig is None):
            errors.append("state.head checkpoint_id and content_digest must both be null or both be set")
        if hid is not None and not CHECKPOINT_ID_RE.fullmatch(str(hid)):
            errors.append("state.head.checkpoint_id has invalid format")
        if hdig is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(hdig)):
            errors.append("state.head.content_digest has invalid format")
    return errors


def validate_checkpoint(checkpoint: dict[str, Any], *, expect_sealed: bool | None = None) -> list[str]:
    errors: list[str] = []
    if checkpoint.get("protocol_version") != PROTOCOL:
        errors.append(f"protocol_version must be {PROTOCOL}")
    cid = checkpoint.get("checkpoint_id")
    if not isinstance(cid, str) or not CHECKPOINT_ID_RE.fullmatch(cid):
        errors.append("checkpoint_id must match ^pcp-[A-Za-z0-9._-]{8,}$")
    if not isinstance(checkpoint.get("created_at"), str):
        errors.append("created_at must be a string")
    if not isinstance(checkpoint.get("project_id"), str) or not checkpoint.get("project_id"):
        errors.append("project_id must be a non-empty string")

    parent = checkpoint.get("parent")
    if not isinstance(parent, dict):
        errors.append("parent must be an object")
    else:
        pid = parent.get("checkpoint_id")
        pdig = parent.get("content_digest")
        if (pid is None) != (pdig is None):
            errors.append("parent checkpoint_id and content_digest must both be null or both be set")
        if pid is not None and not CHECKPOINT_ID_RE.fullmatch(str(pid)):
            errors.append("parent.checkpoint_id has invalid format")
        if pdig is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(pdig)):
            errors.append("parent.content_digest has invalid format")

    baseline = checkpoint.get("baseline")
    if not isinstance(baseline, dict):
        errors.append("baseline must be an object")
    else:
        git = baseline.get("git")
        if git is not None:
            if not isinstance(git, dict):
                errors.append("baseline.git must be an object or null")
            else:
                if not isinstance(git.get("commit"), str) or not git.get("commit"):
                    errors.append("baseline.git.commit must be a non-empty string")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(git.get("worktree_sha256", ""))):
                    errors.append("baseline.git.worktree_sha256 has invalid format")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(git.get("project_snapshot_sha256", ""))):
                    errors.append("baseline.git.project_snapshot_sha256 has invalid format")
        files = baseline.get("files")
        if not isinstance(files, list):
            errors.append("baseline.files must be an array")
        else:
            seen_paths: set[str] = set()
            for i, item in enumerate(files):
                if not isinstance(item, dict):
                    errors.append(f"baseline.files[{i}] must be an object")
                    continue
                path = item.get("path")
                if not isinstance(path, str) or not path:
                    errors.append(f"baseline.files[{i}].path must be non-empty")
                elif path in seen_paths:
                    errors.append(f"duplicate tracked path: {path}")
                else:
                    seen_paths.add(path)
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("sha256", ""))):
                    errors.append(f"baseline.files[{i}].sha256 has invalid format")

    objective = checkpoint.get("objective")
    if not isinstance(objective, dict) or not isinstance(objective.get("current"), str) or not objective.get("current"):
        errors.append("objective.current must be a non-empty string")

    evidence = checkpoint.get("evidence")
    evidence_by_id: dict[str, dict[str, Any]] = {}
    if not isinstance(evidence, list):
        errors.append("evidence must be an array")
    else:
        for i, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errors.append(f"evidence[{i}] must be an object")
                continue
            eid = ev.get("id")
            etype = ev.get("type")
            if not isinstance(eid, str) or not eid:
                errors.append(f"evidence[{i}].id must be non-empty")
            elif eid in evidence_by_id:
                errors.append(f"duplicate evidence id: {eid}")
            else:
                evidence_by_id[eid] = ev
            if etype not in EVIDENCE_TYPES:
                errors.append(f"evidence[{i}].type is invalid: {etype}")

    claims = checkpoint.get("claims")
    claim_ids: set[str] = set()
    if not isinstance(claims, list):
        errors.append("claims must be an array")
    else:
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                errors.append(f"claims[{i}] must be an object")
                continue
            cid2 = claim.get("id")
            kind = claim.get("kind")
            confidence = claim.get("confidence")
            refs = claim.get("evidence")
            if not isinstance(cid2, str) or not cid2:
                errors.append(f"claims[{i}].id must be non-empty")
            elif cid2 in claim_ids:
                errors.append(f"duplicate claim id: {cid2}")
            else:
                claim_ids.add(cid2)
            if kind not in CLAIM_KINDS:
                errors.append(f"claims[{i}].kind is invalid: {kind}")
            if confidence not in CONFIDENCE:
                errors.append(f"claims[{i}].confidence is invalid: {confidence}")
            if not isinstance(claim.get("statement"), str) or not claim.get("statement"):
                errors.append(f"claims[{i}].statement must be non-empty")
            if not isinstance(refs, list):
                errors.append(f"claims[{i}].evidence must be an array")
                refs = []
            unknown = [r for r in refs if r not in evidence_by_id]
            if unknown:
                errors.append(f"claim {cid2 or i} references unknown evidence: {', '.join(map(str, unknown))}")
            if kind == "completed":
                if confidence != "verified":
                    errors.append(f"completed claim {cid2 or i} must have confidence=verified")
                hard = [r for r in refs if r in evidence_by_id and evidence_by_id[r].get("type") in HARD_EVIDENCE_TYPES]
                if not hard:
                    errors.append(f"completed claim {cid2 or i} requires at least one hard evidence reference")

    open_work = checkpoint.get("open_work")
    work_ids: set[str] = set()
    if not isinstance(open_work, list):
        errors.append("open_work must be an array")
    else:
        for i, work in enumerate(open_work):
            if not isinstance(work, dict):
                errors.append(f"open_work[{i}] must be an object")
                continue
            wid = work.get("id")
            if not isinstance(wid, str) or not wid:
                errors.append(f"open_work[{i}].id must be non-empty")
            elif wid in work_ids:
                errors.append(f"duplicate open_work id: {wid}")
            else:
                work_ids.add(wid)
            if work.get("status") not in WORK_STATUS:
                errors.append(f"open_work[{i}].status is invalid")
            if work.get("priority") not in PRIORITY:
                errors.append(f"open_work[{i}].priority is invalid")
            if not isinstance(work.get("acceptance_criteria"), list):
                errors.append(f"open_work[{i}].acceptance_criteria must be an array")

    next_action = checkpoint.get("next_action")
    if not isinstance(next_action, dict):
        errors.append("next_action must be an object")
    else:
        nwid = next_action.get("work_item_id")
        if nwid is not None and nwid not in work_ids:
            errors.append(f"next_action.work_item_id references unknown open_work item: {nwid}")
        if not isinstance(next_action.get("instruction"), str):
            errors.append("next_action.instruction must be a string")

    risks = checkpoint.get("risks")
    if not isinstance(risks, list):
        errors.append("risks must be an array")

    verification = checkpoint.get("verification")
    if not isinstance(verification, dict):
        errors.append("verification must be an object")
    else:
        status = verification.get("status")
        if status not in {"draft", "sealed"}:
            errors.append("verification.status must be draft or sealed")
        if verification.get("policy") != POLICY:
            errors.append(f"verification.policy must be {POLICY}")
        if expect_sealed is True and status != "sealed":
            errors.append("checkpoint must be sealed")
        if expect_sealed is False and status != "draft":
            errors.append("checkpoint must be a draft")
        digest = verification.get("content_digest")
        if status == "sealed":
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest or "")):
                errors.append("sealed checkpoint requires a valid content_digest")
            if not verification.get("sealed_at"):
                errors.append("sealed checkpoint requires sealed_at")
        elif digest is not None:
            errors.append("draft checkpoint content_digest must be null")

    return errors


def next_evidence_id(checkpoint: dict[str, Any], prefix: str) -> str:
    used = {str(ev.get("id")) for ev in checkpoint.get("evidence", []) if isinstance(ev, dict)}
    i = 1
    while True:
        candidate = f"E-{prefix}-{i:03d}"
        if candidate not in used:
            return candidate
        i += 1


def refresh_baseline_and_auto_evidence(root: pathlib.Path, checkpoint: dict[str, Any]) -> None:
    baseline = checkpoint.setdefault("baseline", {"root_hint": ".", "git": None, "files": []})
    current_git = capture_git(root)
    baseline["git"] = current_git

    evidence = checkpoint.setdefault("evidence", [])
    # Replace auto Git evidence in place so claim references stay stable.
    auto_git = next((ev for ev in evidence if isinstance(ev, dict) and ev.get("auto") is True and ev.get("type") == "git_commit"), None)
    if current_git is not None:
        payload = {
            "type": "git_commit",
            "label": "Project Git baseline at checkpoint seal",
            "observed_at": now_utc(),
            "commit": current_git["commit"],
            "branch": current_git["branch"],
            "dirty": current_git["dirty"],
            "worktree_sha256": current_git["worktree_sha256"],
            "project_snapshot_sha256": current_git["project_snapshot_sha256"],
            "auto": True,
        }
        if auto_git is None:
            payload["id"] = next_evidence_id(checkpoint, "GIT")
            evidence.append(payload)
        else:
            eid = auto_git["id"]
            auto_git.clear()
            auto_git.update({"id": eid, **payload})
    elif auto_git is not None:
        evidence.remove(auto_git)

    tracked = baseline.get("files", [])
    new_tracked: list[dict[str, Any]] = []
    for item in tracked:
        rel = item.get("path") if isinstance(item, dict) else None
        if not rel:
            continue
        path, normalized = safe_project_path(root, rel)
        digest, size = sha256_file(path)
        new_tracked.append({"path": normalized, "size": size, "sha256": digest})
        auto_file = next(
            (
                ev
                for ev in evidence
                if isinstance(ev, dict)
                and ev.get("auto") is True
                and ev.get("type") == "file_hash"
                and ev.get("path") == normalized
            ),
            None,
        )
        payload = {
            "type": "file_hash",
            "label": f"Tracked file {normalized}",
            "observed_at": now_utc(),
            "path": normalized,
            "sha256": digest,
            "size": size,
            "auto": True,
        }
        if auto_file is None:
            payload["id"] = next_evidence_id(checkpoint, "FILE")
            evidence.append(payload)
        else:
            eid = auto_file["id"]
            auto_file.clear()
            auto_file.update({"id": eid, **payload})
    baseline["files"] = new_tracked


def current_state_fingerprint(root: pathlib.Path, checkpoint: dict[str, Any] | None = None) -> str | None:
    git = capture_git(root)
    if git is not None:
        return f"git-project:{git['project_snapshot_sha256']}"
    if checkpoint is not None:
        records: list[dict[str, Any]] = []
        for item in checkpoint.get("baseline", {}).get("files", []) or []:
            rel = item.get("path") if isinstance(item, dict) else None
            if not rel:
                continue
            try:
                path, normalized = safe_project_path(root, rel)
                digest, size = sha256_file(path)
                records.append({"path": normalized, "sha256": digest, "size": size})
            except ContinuityError:
                records.append({"path": str(rel), "missing": True})
        if records:
            return "files:" + sha256_bytes(canonical_bytes(sorted(records, key=lambda x: x["path"])))
    return None


def stale_command_evidence(checkpoint: dict[str, Any], current_fingerprint: str | None) -> set[str]:
    stale: set[str] = set()
    if current_fingerprint is None:
        return stale
    for ev in checkpoint.get("evidence", []):
        if not isinstance(ev, dict) or ev.get("type") not in {"command", "test"}:
            continue
        recorded = ev.get("state_fingerprint")
        if recorded and recorded != current_fingerprint:
            stale.add(str(ev.get("id")))
    return stale


def hard_evidence_issues(root: pathlib.Path, checkpoint: dict[str, Any], current_fingerprint: str | None) -> list[str]:
    """Check evidence used by completed claims against current project state.

    This cannot authenticate a malicious producer, but it prevents unsupported
    or stale evidence objects from satisfying PCP/1 completion semantics.
    """
    evidence_by_id = {
        str(ev.get("id")): ev
        for ev in checkpoint.get("evidence", [])
        if isinstance(ev, dict) and ev.get("id")
    }
    refs = {
        str(ref)
        for claim in checkpoint.get("claims", [])
        if isinstance(claim, dict) and claim.get("kind") == "completed"
        for ref in claim.get("evidence", [])
    }
    issues: list[str] = []
    current_git = capture_git(root)
    for ref in sorted(refs):
        ev = evidence_by_id.get(ref)
        if not ev or ev.get("type") not in HARD_EVIDENCE_TYPES:
            continue
        etype = ev.get("type")
        if etype in {"file_hash", "artifact"}:
            rel = ev.get("path")
            expected = ev.get("sha256")
            if not rel or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected or "")):
                issues.append(f"{ref}: {etype} evidence used for completion requires path and sha256")
                continue
            try:
                path, _ = safe_project_path(root, str(rel))
                actual, _ = sha256_file(path)
                if actual != expected:
                    issues.append(f"{ref}: current file hash does not match recorded evidence")
            except ContinuityError as exc:
                issues.append(f"{ref}: cannot verify current file evidence: {exc}")
        elif etype == "git_commit":
            if current_git is None:
                issues.append(f"{ref}: Git evidence cannot be verified in the current project")
                continue
            if ev.get("project_snapshot_sha256") != current_git.get("project_snapshot_sha256"):
                issues.append(f"{ref}: Git evidence does not match the current seal-time project snapshot")
        elif etype in {"command", "test"}:
            if ev.get("exit_code") != 0:
                issues.append(f"{ref}: command/test evidence used for completion must have exit_code=0")
            if ev.get("capture_method") != "pcp-cli/1":
                issues.append(f"{ref}: command/test evidence used for completion must be captured by pcp-cli/1")
            recorded_fp = ev.get("state_fingerprint")
            if current_fingerprint is None:
                issues.append(f"{ref}: current project fingerprint is unavailable; cannot prove test/command freshness")
            elif recorded_fp != current_fingerprint:
                issues.append(f"{ref}: command/test evidence is stale for the current project state")
            log_path = ev.get("log_path")
            log_digest = ev.get("log_sha256")
            if log_path and log_digest:
                try:
                    path, _ = safe_project_path(root, str(log_path))
                    actual, _ = sha256_file(path)
                    if actual != log_digest:
                        issues.append(f"{ref}: captured evidence log hash mismatch")
                except ContinuityError as exc:
                    issues.append(f"{ref}: captured evidence log is unavailable: {exc}")
            else:
                issues.append(f"{ref}: command/test evidence requires a captured log and log_sha256")
    return issues


@contextmanager
def write_lock(root: pathlib.Path):
    cont = ensure_internal_dir(root, ".continuity", create=True)
    lock_path = safe_internal_file(cont, "write.lock")
    payload = {"pid": os.getpid(), "created_at": now_utc()}
    fd = None
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, (json.dumps(payload) + "\n").encode("utf-8"))
        os.close(fd)
        fd = None
    except FileExistsError as exc:
        age = None
        try:
            age = time.time() - lock_path.stat().st_mtime
        except OSError:
            pass
        suffix = f" (age {int(age)}s)" if age is not None else ""
        raise ContinuityError(f"Continuity write lock already exists: {lock_path}{suffix}. Run doctor before removing it.") from exc
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock_path.unlink(missing_ok=True)


def load_state(root: pathlib.Path) -> tuple[pathlib.Path, dict[str, Any]]:
    cont = ensure_internal_dir(root, ".continuity", create=False)
    path = safe_internal_file(cont, "state.json")
    state = read_json(path)
    errors = validate_state(state)
    if errors:
        raise ContinuityError("Invalid state.json:\n- " + "\n- ".join(errors))
    return path, state


def checkpoint_path(root: pathlib.Path, checkpoint_id: str) -> pathlib.Path:
    if not CHECKPOINT_ID_RE.fullmatch(str(checkpoint_id)):
        raise ContinuityError(f"Invalid checkpoint id for path resolution: {checkpoint_id!r}")
    cp_dir = ensure_internal_dir(root, ".continuity/checkpoints", create=False)
    return safe_internal_file(cp_dir, f"{checkpoint_id}.json")


def resolve_checkpoint(root: pathlib.Path, explicit: str | None) -> pathlib.Path:
    if explicit:
        path = pathlib.Path(explicit)
        if not path.is_absolute():
            path = root / path
        return path
    _, state = load_state(root)
    cid = state["head"]["checkpoint_id"]
    if cid is None:
        raise ContinuityError("Continuity state has no canonical head yet")
    return checkpoint_path(root, cid)


def cmd_init(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    cont = ensure_internal_dir(root, ".continuity", create=True)
    state_path = safe_internal_file(cont, "state.json")
    if state_path.exists():
        raise ContinuityError(f"Continuity already initialized: {state_path}")
    for rel in [".continuity/checkpoints", ".continuity/drafts", ".continuity/evidence"]:
        ensure_internal_dir(root, rel, create=True)
    project_id = args.project_id or project_id_from(root, args.project_name)
    state = {
        "protocol_version": PROTOCOL,
        "project": {"id": project_id, "name": args.project_name},
        "generation": 0,
        "head": {"checkpoint_id": None, "content_digest": None},
        "updated_at": now_utc(),
    }
    atomic_write_json(state_path, state)
    print(state_path)
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    _, state = load_state(root)
    cid = f"pcp-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    tracked: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for supplied in args.track or []:
        path, rel = safe_project_path(root, supplied)
        digest, size = sha256_file(path)
        tracked.append({"path": rel, "size": size, "sha256": digest})
        evidence.append(
            {
                "id": f"E-FILE-{len(evidence) + 1:03d}",
                "type": "file_hash",
                "label": f"Tracked file {rel}",
                "observed_at": now_utc(),
                "path": rel,
                "sha256": digest,
                "size": size,
                "auto": True,
            }
        )
    git = capture_git(root)
    if git is not None:
        evidence.insert(
            0,
            {
                "id": "E-GIT-001",
                "type": "git_commit",
                "label": "Project Git baseline at draft creation",
                "observed_at": now_utc(),
                "commit": git["commit"],
                "branch": git["branch"],
                "dirty": git["dirty"],
                "worktree_sha256": git["worktree_sha256"],
                "project_snapshot_sha256": git["project_snapshot_sha256"],
                "auto": True,
            },
        )
    head = state["head"]
    checkpoint = {
        "protocol_version": PROTOCOL,
        "checkpoint_id": cid,
        "created_at": now_utc(),
        "producer": {"surface": args.surface, "model": args.model, "session_ref": args.session_ref},
        "project_id": state["project"]["id"],
        "parent": {"checkpoint_id": head["checkpoint_id"], "content_digest": head["content_digest"]},
        "baseline": {"root_hint": ".", "git": git, "files": tracked},
        "objective": {"current": args.objective, "definition_of_done": args.done or []},
        "claims": [],
        "evidence": evidence,
        "open_work": [],
        "next_action": {"work_item_id": None, "instruction": "", "acceptance_criteria": []},
        "risks": [],
        "verification": {
            "status": "draft",
            "sealed_at": None,
            "content_digest": None,
            "policy": POLICY,
            "surface_status": "unknown",
        },
    }
    draft_dir = ensure_internal_dir(root, ".continuity/drafts", create=True)
    draft_path = safe_internal_file(draft_dir, f"{cid}.json")
    atomic_write_json(draft_path, checkpoint)
    print(draft_path)
    return 0


SECRET_PATTERNS = [
    re.compile(r"(?i)\b(authorization\s*:\s*bearer)\s+[^\s]+"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[^\s]+"),
]


def redact_text(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        if "authorization" in pat.pattern.lower():
            out = pat.sub(r"\1 [REDACTED]", out)
        else:
            out = pat.sub(lambda m: f"{m.group(1)}=[REDACTED]", out)
    return out


def cmd_run(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    draft_path = safe_draft_path(root, args.draft)
    checkpoint = read_json(draft_path)
    errors = validate_checkpoint(checkpoint, expect_sealed=False)
    if errors:
        raise ContinuityError("Cannot record evidence into invalid draft:\n- " + "\n- ".join(errors))
    argv = list(args.command)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        raise ContinuityError("run requires an explicit command after --")
    before = current_state_fingerprint(root, checkpoint)
    started = time.monotonic()
    cp = run_process(argv, root, timeout=args.timeout)
    duration_ms = int((time.monotonic() - started) * 1000)
    raw_text = cp.stdout.decode("utf-8", errors="replace")
    redacted = redact_text(raw_text)
    full_bytes = redacted.encode("utf-8")
    output_digest = sha256_bytes(full_bytes)
    eid = next_evidence_id(checkpoint, "TEST" if args.kind == "test" else "CMD")
    evidence_base = ensure_internal_dir(root, ".continuity/evidence", create=True)
    evidence_dir = evidence_base / checkpoint["checkpoint_id"]
    if evidence_dir.is_symlink():
        raise ContinuityError(f"Symlink not allowed for continuity evidence directory: {evidence_dir}")
    evidence_dir.mkdir(exist_ok=True)
    if not evidence_dir.is_dir():
        raise ContinuityError(f"Continuity evidence path must be a directory: {evidence_dir}")
    log_path = safe_internal_file(evidence_dir, f"{eid}.log")
    truncated = len(full_bytes) > MAX_CAPTURED_LOG_BYTES
    persisted = full_bytes[-MAX_CAPTURED_LOG_BYTES:] if truncated else full_bytes
    atomic_write_text(log_path, persisted.decode("utf-8", errors="replace"))
    log_digest = sha256_bytes(persisted)
    after = current_state_fingerprint(root, checkpoint)
    ev = {
        "id": eid,
        "type": args.kind,
        "label": args.label,
        "observed_at": now_utc(),
        "argv": argv,
        "cwd": ".",
        "exit_code": cp.returncode,
        "duration_ms": duration_ms,
        "output_sha256": output_digest,
        "log_path": log_path.relative_to(root).as_posix(),
        "log_sha256": log_digest,
        "log_truncated": truncated,
        "state_fingerprint": after,
        "state_changed_during_command": before != after,
        "capture_method": "pcp-cli/1",
    }
    checkpoint.setdefault("evidence", []).append(ev)
    atomic_write_json(draft_path, checkpoint)
    print(json.dumps({"evidence_id": eid, "exit_code": cp.returncode, "log_path": ev["log_path"], "truncated": truncated}))
    return cp.returncode


def promote_checkpoint(root: pathlib.Path, checkpoint: dict[str, Any]) -> None:
    state_path, state = load_state(root)
    parent = checkpoint["parent"]
    current = state["head"]
    if current.get("checkpoint_id") != parent.get("checkpoint_id") or current.get("content_digest") != parent.get("content_digest"):
        raise ContinuityError(
            "Parallel-head conflict: checkpoint parent no longer matches canonical HEAD. "
            f"Current HEAD={current.get('checkpoint_id')}, checkpoint parent={parent.get('checkpoint_id')}. "
            "Checkpoint remains sealed but detached; reconcile instead of overwriting."
        )
    state["head"] = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "content_digest": checkpoint["verification"]["content_digest"],
    }
    state["generation"] += 1
    state["updated_at"] = now_utc()
    atomic_write_json(state_path, state)


def cmd_seal(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    draft_path = safe_draft_path(root, args.draft)
    checkpoint = read_json(draft_path)
    initial_errors = validate_checkpoint(checkpoint, expect_sealed=False)
    if initial_errors:
        raise ContinuityError("Invalid draft:\n- " + "\n- ".join(initial_errors))
    _, state = load_state(root)
    if checkpoint["project_id"] != state["project"]["id"]:
        raise ContinuityError("Draft project_id does not match continuity state")

    # Refresh baseline to represent seal-time reality while preserving stable auto evidence IDs.
    refresh_baseline_and_auto_evidence(root, checkpoint)
    current_fp = current_state_fingerprint(root, checkpoint)
    stale = stale_command_evidence(checkpoint, current_fp)
    if stale:
        completed_refs = {
            ref
            for claim in checkpoint.get("claims", [])
            if isinstance(claim, dict) and claim.get("kind") == "completed"
            for ref in claim.get("evidence", [])
        }
        stale_used = sorted(stale & completed_refs)
        if stale_used:
            raise ContinuityError(
                "Completed claims reference command/test evidence captured against an older project state: "
                + ", ".join(stale_used)
                + ". Re-run the relevant validation against the current state before sealing."
            )

    evidence_issues = hard_evidence_issues(root, checkpoint, current_fp)
    if evidence_issues:
        raise ContinuityError("Hard evidence verification failed:\n- " + "\n- ".join(evidence_issues))

    errors = validate_checkpoint(checkpoint, expect_sealed=False)
    if errors:
        raise ContinuityError("Invalid draft after baseline refresh:\n- " + "\n- ".join(errors))

    baseline_has_current_evidence = bool(checkpoint.get("baseline", {}).get("git")) or bool(
        checkpoint.get("baseline", {}).get("files")
    )
    has_verified_completion = any(
        isinstance(claim, dict) and claim.get("kind") == "completed"
        for claim in checkpoint.get("claims", [])
    )
    checkpoint["verification"] = {
        "status": "sealed",
        "sealed_at": now_utc(),
        "content_digest": None,
        "policy": POLICY,
        "surface_status": "historically-verified" if (baseline_has_current_evidence or has_verified_completion) else "unverifiable",
    }
    checkpoint["verification"]["content_digest"] = compute_content_digest(checkpoint)
    sealed_errors = validate_checkpoint(checkpoint, expect_sealed=True)
    if sealed_errors:
        raise ContinuityError("Sealed checkpoint failed validation:\n- " + "\n- ".join(sealed_errors))

    sealed_path = checkpoint_path(root, checkpoint["checkpoint_id"])
    with write_lock(root):
        if sealed_path.exists():
            existing = read_json(sealed_path)
            if canonical_bytes(existing) != canonical_bytes(checkpoint):
                raise ContinuityError(f"Refusing to overwrite immutable sealed checkpoint: {sealed_path}")
        else:
            atomic_write_json(sealed_path, checkpoint)
        promoted = False
        if args.promote:
            promote_checkpoint(root, checkpoint)
            promoted = True
    if args.delete_draft:
        draft_path.unlink(missing_ok=True)
    print(json.dumps({"checkpoint": str(sealed_path), "digest": checkpoint["verification"]["content_digest"], "promoted": promoted}))
    return 0


def compare_baseline(root: pathlib.Path, checkpoint: dict[str, Any]) -> dict[str, Any]:
    baseline = checkpoint.get("baseline", {})
    recorded_git = baseline.get("git")
    current_git = capture_git(root)
    file_results: list[dict[str, Any]] = []
    for item in baseline.get("files", []) or []:
        rel = item.get("path")
        result: dict[str, Any] = {"path": rel, "expected": item.get("sha256")}
        try:
            path, _ = safe_project_path(root, rel)
            digest, size = sha256_file(path)
            result.update({"actual": digest, "size": size, "match": digest == item.get("sha256")})
        except ContinuityError as exc:
            result.update({"actual": None, "match": False, "error": str(exc)})
        file_results.append(result)

    git_class = "unavailable"
    git_detail: dict[str, Any] = {"recorded": recorded_git, "current": current_git}
    if recorded_git is not None and current_git is None:
        git_class = "unverifiable"
    elif recorded_git is None and current_git is not None:
        git_class = "unrecorded-current-git"
    elif recorded_git is not None and current_git is not None:
        if recorded_git.get("project_snapshot_sha256") == current_git.get("project_snapshot_sha256"):
            # Exact effective project state, even if Git HEAD advanced only because
            # continuity metadata itself was committed.
            git_class = "exact"
        elif recorded_git.get("commit") == current_git.get("commit"):
            git_class = "drift"
        else:
            ancestor = run_process(
                ["git", "merge-base", "--is-ancestor", str(recorded_git.get("commit")), str(current_git.get("commit"))],
                root,
                timeout=30,
            )
            git_class = "advanced" if ancestor.returncode == 0 else "diverged"

    file_any = bool(file_results)
    file_all_match = file_any and all(x.get("match") is True for x in file_results)
    file_any_mismatch = any(x.get("match") is False for x in file_results)

    if git_class == "diverged":
        overall = "diverged"
    elif git_class == "advanced":
        overall = "advanced"
    elif git_class == "drift":
        overall = "drift"
    elif git_class == "exact":
        overall = "drift" if file_any_mismatch else "exact"
    elif recorded_git is None:
        if file_any:
            overall = "exact" if file_all_match else "drift"
        else:
            overall = "unverifiable"
    else:
        overall = "unverifiable"

    return {
        "status": overall,
        "git_status": git_class,
        "git": git_detail,
        "files": file_results,
    }


def verify_checkpoint(
    root: pathlib.Path,
    checkpoint: dict[str, Any],
    *,
    expected_project_id: str | None = None,
) -> dict[str, Any]:
    errors = validate_checkpoint(checkpoint, expect_sealed=True)
    digest_expected = checkpoint.get("verification", {}).get("content_digest")
    digest_actual = compute_content_digest(checkpoint) if isinstance(checkpoint.get("verification"), dict) else None
    digest_match = digest_expected == digest_actual
    if not digest_match:
        errors.append(f"content digest mismatch: expected {digest_expected}, computed {digest_actual}")
    if errors:
        return {
            "status": "invalid",
            "integrity": {"valid": False, "errors": errors, "expected_digest": digest_expected, "actual_digest": digest_actual},
            "compatibility": None,
        }
    if expected_project_id is not None and checkpoint.get("project_id") != expected_project_id:
        return {
            "status": "project-mismatch",
            "integrity": {"valid": True, "errors": [], "expected_digest": digest_expected, "actual_digest": digest_actual},
            "compatibility": {
                "status": "project-mismatch",
                "expected_project_id": expected_project_id,
                "checkpoint_project_id": checkpoint.get("project_id"),
            },
        }
    compatibility = compare_baseline(root, checkpoint)
    return {
        "status": compatibility["status"],
        "integrity": {"valid": True, "errors": [], "expected_digest": digest_expected, "actual_digest": digest_actual},
        "compatibility": compatibility,
    }


def cmd_verify(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    _, state = load_state(root)
    path = resolve_checkpoint(root, args.checkpoint)
    checkpoint = read_json(path)
    result = verify_checkpoint(root, checkpoint, expected_project_id=state["project"]["id"])
    result["checkpoint"] = str(path)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"checkpoint: {path}")
        print(f"status: {result['status']}")
        if result["integrity"]["errors"]:
            for err in result["integrity"]["errors"]:
                print(f"- {err}")
    return 0 if result["status"] not in {"invalid", "project-mismatch"} else 2



def cmd_consume(args: argparse.Namespace) -> int:
    """Consume an external checkpoint into a safe local reconciliation draft.

    Imported claims are treated as historical reports. In particular, imported
    `completed` claims are downgraded to reported findings until the current
    project supplies fresh hard evidence. No imported command is executed or
    copied as executable evidence.
    """
    root = pathlib.Path(args.root).resolve()
    _, state = load_state(root)
    source_path = pathlib.Path(args.checkpoint)
    if not source_path.is_absolute():
        source_path = (root / source_path).resolve()
    source = read_json(source_path)

    source_status = source.get("verification", {}).get("status")
    if source_status == "sealed":
        source_verification = verify_checkpoint(root, source, expected_project_id=None)
        if not source_verification["integrity"]["valid"]:
            raise ContinuityError(
                "Cannot consume checkpoint with invalid integrity: "
                + "; ".join(source_verification["integrity"]["errors"])
            )
        source_integrity = "sealed-valid"
    elif source_status == "draft":
        errors = validate_checkpoint(source, expect_sealed=False)
        if errors:
            raise ContinuityError("Cannot consume invalid checkpoint draft:\n- " + "\n- ".join(errors))
        source_verification = {"status": "unsealed", "integrity": {"valid": True}}
        source_integrity = "unsealed-reported"
    else:
        raise ContinuityError("External checkpoint verification.status must be draft or sealed")

    local_project_id = state["project"]["id"]
    source_project_id = source.get("project_id")
    project_match = source_project_id == local_project_id
    if not project_match and not args.confirm_project_mapping:
        raise ContinuityError(
            "External checkpoint project_id does not match local continuity project. "
            f"external={source_project_id!r}, local={local_project_id!r}. "
            "Verify project identity independently, then rerun with --confirm-project-mapping if this is intentionally the same project."
        )

    cid = f"pcp-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    source_evidence_id = "E-SOURCE-001"
    evidence: list[dict[str, Any]] = [
        {
            "id": source_evidence_id,
            "type": "source",
            "label": "Imported continuity checkpoint (historical state only)",
            "observed_at": now_utc(),
            "source_checkpoint_id": source.get("checkpoint_id"),
            "source_project_id": source_project_id,
            "source_content_digest": source.get("verification", {}).get("content_digest"),
            "source_integrity": source_integrity,
            "source_filename": source_path.name,
            "project_mapping_confirmed": bool(args.confirm_project_mapping and not project_match),
        }
    ]

    imported_claims: list[dict[str, Any]] = []
    completion_count = 0
    for i, claim in enumerate(source.get("claims", []) or [], start=1):
        if not isinstance(claim, dict):
            continue
        kind = claim.get("kind") if claim.get("kind") in CLAIM_KINDS else "finding"
        statement = str(claim.get("statement") or "Imported claim")
        source_claim_id = str(claim.get("id") or f"claim-{i}")
        if kind == "completed":
            completion_count += 1
            kind = "finding"
            statement = f"Historical completion claim requiring current re-verification [{source_claim_id}]: {statement}"
        else:
            statement = f"Imported historical claim [{source_claim_id}]: {statement}"
        imported_claims.append(
            {
                "id": f"IMP-C-{i:03d}",
                "kind": kind,
                "confidence": "reported",
                "statement": statement,
                "evidence": [source_evidence_id],
                "supersedes": [],
            }
        )

    imported_work: list[dict[str, Any]] = []
    source_work = [w for w in (source.get("open_work", []) or []) if isinstance(w, dict)]
    id_map = {str(w.get("id")): f"IMP-W-{i:03d}" for i, w in enumerate(source_work, start=1)}
    for i, item in enumerate(source_work, start=1):
        deps = [id_map[d] for d in item.get("depends_on", []) or [] if d in id_map]
        imported_work.append(
            {
                "id": f"IMP-W-{i:03d}",
                "title": f"Imported: {item.get('title') or 'open work'}",
                "status": item.get("status") if item.get("status") in WORK_STATUS else "todo",
                "priority": item.get("priority") if item.get("priority") in PRIORITY else "medium",
                "acceptance_criteria": [str(x) for x in item.get("acceptance_criteria", []) or [] if str(x).strip()],
                "depends_on": deps,
            }
        )

    reconcile_work_id = "W-RECONCILE-001"
    reconcile_criteria = [
        "Current project identity and state are inspected with authoritative tools.",
        "Imported historical claims are reconciled with current repository/files.",
        "Any completion claim retained as completed is backed by fresh hard evidence.",
    ]
    if completion_count:
        reconcile_criteria.append(f"All {completion_count} imported historical completion claim(s) are re-verified or left explicitly unverified.")
    imported_work.insert(
        0,
        {
            "id": reconcile_work_id,
            "title": "Reconcile imported continuity checkpoint with current project state",
            "status": "todo",
            "priority": "critical",
            "acceptance_criteria": reconcile_criteria,
            "depends_on": [],
        },
    )

    risks: list[dict[str, Any]] = []
    if not project_match:
        risks.append(
            {
                "id": "R-MAPPING-001",
                "description": f"External project_id {source_project_id!r} was explicitly mapped to local project_id {local_project_id!r}.",
                "severity": "high",
                "mitigation": "Confirm repository identity and re-verify all imported empirical claims before promoting reconciliation state.",
            }
        )
    if source_integrity != "sealed-valid":
        risks.append(
            {
                "id": "R-UNSEALED-001",
                "description": "Imported checkpoint was not sealed; its content has no PCP/1 tamper-evident digest.",
                "severity": "high",
                "mitigation": "Treat all imported content as reported state and verify it against current authoritative project evidence.",
            }
        )

    head = state["head"]
    checkpoint = {
        "protocol_version": PROTOCOL,
        "checkpoint_id": cid,
        "created_at": now_utc(),
        "producer": {"surface": args.surface, "model": args.model, "session_ref": f"consume:{source.get('checkpoint_id')}"},
        "project_id": local_project_id,
        "parent": {"checkpoint_id": head["checkpoint_id"], "content_digest": head["content_digest"]},
        "baseline": {"root_hint": ".", "git": capture_git(root), "files": []},
        "objective": {
            "current": source.get("objective", {}).get("current") or "Reconcile imported project continuity state",
            "definition_of_done": list(source.get("objective", {}).get("definition_of_done", []) or []),
        },
        "claims": imported_claims,
        "evidence": evidence,
        "open_work": imported_work,
        "next_action": {
            "work_item_id": reconcile_work_id,
            "instruction": "Verify the imported checkpoint against the current authoritative project before resuming implementation.",
            "acceptance_criteria": reconcile_criteria,
        },
        "risks": risks,
        "verification": {
            "status": "draft",
            "sealed_at": None,
            "content_digest": None,
            "policy": POLICY,
            "surface_status": "unknown",
        },
    }
    # Add only locally observed auto evidence. Imported command/test evidence is
    # intentionally not copied because it is historical data, not executable proof.
    refresh_baseline_and_auto_evidence(root, checkpoint)
    errors = validate_checkpoint(checkpoint, expect_sealed=False)
    if errors:
        raise ContinuityError("Generated reconciliation draft is invalid:\n- " + "\n- ".join(errors))
    draft_dir = ensure_internal_dir(root, ".continuity/drafts", create=True)
    draft_path = safe_internal_file(draft_dir, f"{cid}.json")
    atomic_write_json(draft_path, checkpoint)
    print(
        json.dumps(
            {
                "status": "reconciliation-required",
                "draft": str(draft_path),
                "source_checkpoint_id": source.get("checkpoint_id"),
                "source_integrity": source_integrity,
                "project_match": project_match,
                "project_mapping_confirmed": bool(args.confirm_project_mapping and not project_match),
                "imported_claims": len(imported_claims),
                "historical_completion_claims": completion_count,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_handoff_out(args: argparse.Namespace) -> int:
    """Copy the canonical sealed HEAD to the interchange file."""
    root = pathlib.Path(args.root).resolve()
    source = resolve_checkpoint(root, None)
    dest = resolve_handoff_path(args.out)
    checkpoint = read_json(source)
    if checkpoint.get("verification", {}).get("status") != "sealed":
        raise ContinuityError("Canonical head is not a sealed checkpoint; seal before handoff-out")
    atomic_copy_file(source, dest)
    print(
        json.dumps(
            {
                "status": "ready",
                "checkpoint_id": checkpoint.get("checkpoint_id"),
                "content_digest": checkpoint.get("verification", {}).get("content_digest"),
                "path": str(dest),
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_handoff_in(args: argparse.Namespace) -> int:
    """Consume the interchange file into a reconciliation draft."""
    source = resolve_handoff_path(args.checkpoint)
    if not source.is_file():
        raise ContinuityError(
            f"No interchange file at {source}. "
            "Save the ChatGPT portable checkpoint there, or pass --checkpoint."
        )
    args.checkpoint = str(source)
    if not getattr(args, "surface", None):
        args.surface = "codex"
    return cmd_consume(args)


def render_checkpoint(checkpoint: dict[str, Any], verify_result: dict[str, Any] | None = None) -> str:
    lines: list[str] = []
    lines.append("# Project Continuity")
    lines.append("")
    lines.append(f"- Protocol: `{checkpoint.get('protocol_version')}`")
    lines.append(f"- Checkpoint: `{checkpoint.get('checkpoint_id')}`")
    lines.append(f"- Created: `{checkpoint.get('created_at')}`")
    lines.append(f"- Producer: `{checkpoint.get('producer', {}).get('surface')}` / `{checkpoint.get('producer', {}).get('model')}`")
    lines.append(f"- Digest: `{checkpoint.get('verification', {}).get('content_digest')}`")
    if verify_result:
        lines.append(f"- Current compatibility: **{verify_result.get('status')}**")
    lines.append("")
    lines.append("## Objective")
    lines.append("")
    lines.append(checkpoint.get("objective", {}).get("current", ""))
    dod = checkpoint.get("objective", {}).get("definition_of_done", []) or []
    if dod:
        lines.append("")
        lines.append("### Definition of done")
        for item in dod:
            lines.append(f"- {item}")

    claims = checkpoint.get("claims", []) or []
    lines.append("")
    lines.append("## Claims")
    lines.append("")
    if not claims:
        lines.append("_No claims recorded._")
    else:
        for claim in claims:
            refs = ", ".join(claim.get("evidence", [])) or "none"
            lines.append(
                f"- **{claim.get('id')} · {claim.get('kind')} · {claim.get('confidence')}** — "
                f"{claim.get('statement')} _(evidence: {refs})_"
            )

    work = checkpoint.get("open_work", []) or []
    lines.append("")
    lines.append("## Open work")
    lines.append("")
    if not work:
        lines.append("_No open work recorded._")
    else:
        for item in work:
            lines.append(f"- **{item.get('id')} · {item.get('priority')} · {item.get('status')}** — {item.get('title')}")
            for ac in item.get("acceptance_criteria", []) or []:
                lines.append(f"  - Acceptance: {ac}")

    next_action = checkpoint.get("next_action", {}) or {}
    lines.append("")
    lines.append("## Next action")
    lines.append("")
    if next_action.get("work_item_id"):
        lines.append(f"Work item: `{next_action.get('work_item_id')}`")
        lines.append("")
    lines.append(next_action.get("instruction") or "_No next action recorded._")
    for ac in next_action.get("acceptance_criteria", []) or []:
        lines.append(f"- Acceptance: {ac}")

    risks = checkpoint.get("risks", []) or []
    lines.append("")
    lines.append("## Risks")
    lines.append("")
    if not risks:
        lines.append("_No risks recorded._")
    else:
        for risk in risks:
            lines.append(f"- **{risk.get('id')} · {risk.get('severity')}** — {risk.get('description')} Mitigation: {risk.get('mitigation')}")

    evidence = checkpoint.get("evidence", []) or []
    lines.append("")
    lines.append("## Evidence index")
    lines.append("")
    if not evidence:
        lines.append("_No evidence recorded._")
    else:
        for ev in evidence:
            extra = ""
            if ev.get("type") in {"command", "test"}:
                extra = f" exit={ev.get('exit_code')}"
            elif ev.get("type") == "file_hash":
                extra = f" `{ev.get('path')}`"
            elif ev.get("type") == "git_commit":
                extra = f" commit=`{ev.get('commit')}`"
            lines.append(f"- `{ev.get('id')}` · `{ev.get('type')}` — {ev.get('label')}{extra}")

    lines.append("")
    lines.append("> This file is a generated convenience view. `.continuity/state.json` and the sealed checkpoint JSON are canonical.")
    lines.append("")
    return "\n".join(lines)


def cmd_render(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    path = resolve_checkpoint(root, args.checkpoint)
    _, state = load_state(root)
    checkpoint = read_json(path)
    verification = verify_checkpoint(root, checkpoint, expected_project_id=state["project"]["id"])
    out = safe_output_path(root, args.out) if args.out else root / "CONTINUITY.md"
    atomic_write_text(out, render_checkpoint(checkpoint, verification))
    print(out)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    _, state = load_state(root)
    payload: dict[str, Any] = {"state": state}
    if state["head"]["checkpoint_id"]:
        cp = read_json(checkpoint_path(root, state["head"]["checkpoint_id"]))
        payload["verification"] = verify_checkpoint(root, cp, expected_project_id=state["project"]["id"])
    else:
        payload["verification"] = None
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"project: {state['project']['name']} ({state['project']['id']})")
        print(f"generation: {state['generation']}")
        print(f"head: {state['head']['checkpoint_id']}")
        if payload["verification"]:
            print(f"status: {payload['verification']['status']}")
    return 0


def reachable_from_head(root: pathlib.Path, state: dict[str, Any], all_by_id: dict[str, dict[str, Any]]) -> tuple[set[str], list[str]]:
    reachable: set[str] = set()
    errors: list[str] = []
    cid = state["head"]["checkpoint_id"]
    expected_digest = state["head"]["content_digest"]
    while cid is not None:
        if cid in reachable:
            errors.append(f"checkpoint lineage cycle detected at {cid}")
            break
        reachable.add(cid)
        cp = all_by_id.get(cid)
        if cp is None:
            errors.append(f"lineage references missing checkpoint {cid}")
            break
        actual = cp.get("verification", {}).get("content_digest")
        if expected_digest is not None and actual != expected_digest:
            errors.append(f"lineage digest mismatch for {cid}: expected {expected_digest}, found {actual}")
        parent = cp.get("parent", {})
        cid = parent.get("checkpoint_id")
        expected_digest = parent.get("content_digest")
    return reachable, errors


def cmd_doctor(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    findings: list[dict[str, Any]] = []
    try:
        _, state = load_state(root)
    except ContinuityError as exc:
        result = {"healthy": False, "findings": [{"severity": "critical", "code": "invalid-state", "message": str(exc)}]}
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else str(exc))
        return 2

    all_by_id: dict[str, dict[str, Any]] = {}
    cp_dir = ensure_internal_dir(root, ".continuity/checkpoints", create=False)
    for path in sorted(cp_dir.glob("*.json")):
        if path.is_symlink():
            findings.append({"severity": "critical", "code": "symlink-checkpoint", "message": f"Symlink checkpoint is not allowed: {path.name}"})
            continue
        try:
            cp = read_json(path)
            cid = cp.get("checkpoint_id")
            if cid in all_by_id:
                findings.append({"severity": "critical", "code": "duplicate-id", "message": f"Duplicate checkpoint id {cid}"})
                continue
            all_by_id[cid] = cp
            ver = verify_checkpoint(root, cp, expected_project_id=state["project"]["id"])
            if not ver["integrity"]["valid"]:
                findings.append({"severity": "critical", "code": "invalid-checkpoint", "message": f"{path.name}: {'; '.join(ver['integrity']['errors'])}"})
            elif ver["status"] == "project-mismatch":
                findings.append({"severity": "critical", "code": "project-mismatch", "message": f"{path.name}: checkpoint project_id does not match continuity state"})
        except ContinuityError as exc:
            findings.append({"severity": "critical", "code": "unreadable-checkpoint", "message": f"{path.name}: {exc}"})

    head_id = state["head"]["checkpoint_id"]
    if head_id is not None and head_id not in all_by_id:
        findings.append({"severity": "critical", "code": "missing-head", "message": f"Canonical HEAD checkpoint is missing: {head_id}"})

    reachable, lineage_errors = reachable_from_head(root, state, all_by_id)
    for msg in lineage_errors:
        findings.append({"severity": "critical", "code": "lineage-error", "message": msg})
    for cid in sorted(set(all_by_id) - reachable):
        findings.append({"severity": "info", "code": "detached-checkpoint", "message": f"Sealed checkpoint is detached from canonical HEAD: {cid}"})

    cont = ensure_internal_dir(root, ".continuity", create=False)
    lock = safe_internal_file(cont, "write.lock")
    if lock.exists():
        age = time.time() - lock.stat().st_mtime
        severity = "warning" if age > LOCK_STALE_SECONDS else "info"
        findings.append({"severity": severity, "code": "write-lock", "message": f"write.lock exists and is {int(age)}s old"})

    healthy = not any(f["severity"] == "critical" for f in findings)
    result = {"healthy": healthy, "findings": findings, "checkpoint_count": len(all_by_id), "reachable_count": len(reachable)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"healthy: {healthy}")
        for f in findings:
            print(f"- {f['severity']} {f['code']}: {f['message']}")
        if not findings:
            print("- no findings")
    return 0 if healthy else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project Continuity Protocol (PCP/1) reference CLI")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("init", help="Initialize .continuity state")
    p.add_argument("--root", default=".")
    p.add_argument("--project-name", required=True)
    p.add_argument("--project-id")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("draft", help="Create a checkpoint draft from current state")
    p.add_argument("--root", default=".")
    p.add_argument("--surface", required=True)
    p.add_argument("--model")
    p.add_argument("--session-ref")
    p.add_argument("--objective", required=True)
    p.add_argument("--done", action="append", default=[])
    p.add_argument("--track", action="append", default=[])
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("run", help="Run explicitly supplied argv and record evidence in a draft")
    p.add_argument("--root", default=".")
    p.add_argument("--draft", required=True)
    p.add_argument("--kind", choices=["command", "test"], default="command")
    p.add_argument("--label", required=True)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("consume", help="Consume an external checkpoint into a safe reconciliation draft")
    p.add_argument("--root", default=".")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--surface", required=True)
    p.add_argument("--model")
    p.add_argument(
        "--confirm-project-mapping",
        action="store_true",
        help="Explicitly confirm that a mismatched external project_id refers to this local project after independent verification",
    )
    p.set_defaults(func=cmd_consume)

    p = sub.add_parser("handoff-out", help="Copy sealed HEAD to ~/Downloads/pcp-handoff.json")
    p.add_argument("--root", default=".")
    p.add_argument(
        "--out",
        help="Interchange file (default: ~/Downloads/pcp-handoff.json)",
    )
    p.set_defaults(func=cmd_handoff_out)

    p = sub.add_parser("handoff-in", help="Consume ~/Downloads/pcp-handoff.json into a reconciliation draft")
    p.add_argument("--root", default=".")
    p.add_argument(
        "--checkpoint",
        help="Interchange file (default: ~/Downloads/pcp-handoff.json)",
    )
    p.add_argument("--surface", default="codex")
    p.add_argument("--model")
    p.add_argument(
        "--confirm-project-mapping",
        action="store_true",
        help="Explicitly confirm that a mismatched external project_id refers to this local project after independent verification",
    )
    p.set_defaults(func=cmd_handoff_in)

    p = sub.add_parser("seal", help="Validate, seal, and optionally promote a draft")
    p.add_argument("--root", default=".")
    p.add_argument("--draft", required=True)
    p.add_argument("--promote", action="store_true")
    p.add_argument("--delete-draft", action="store_true")
    p.set_defaults(func=cmd_seal)

    p = sub.add_parser("verify", help="Verify checkpoint integrity and compatibility with current state")
    p.add_argument("--root", default=".")
    p.add_argument("--checkpoint")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("render", help="Render canonical checkpoint as human-readable CONTINUITY.md")
    p.add_argument("--root", default=".")
    p.add_argument("--checkpoint")
    p.add_argument("--out")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("status", help="Show current continuity head and verification status")
    p.add_argument("--root", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="Audit continuity structure, lineage, integrity, and detached checkpoints")
    p.add_argument("--root", default=".")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ContinuityError as exc:
        print(f"continuity: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("continuity: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
