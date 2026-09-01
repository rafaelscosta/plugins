#!/usr/bin/env python3
"""Fixture-driven evaluation harness for Project Continuity Session Compiler.

The evaluator deliberately separates two boundaries:

1. semantic extraction (transcript -> pcp-session-compilation/1 IR), which may be
   scored by supplying model predictions; and
2. deterministic compilation (IR -> PCP/1 + pcp-planning/1), which is certified
   in CI against the canonical gold fixture corpus.

Gold mode does not pretend to evaluate an LLM. It proves that the deterministic
compiler preserves the semantics encoded by the canonical fixture expectations.
Prediction mode accepts externally-produced IR and scores that semantic output
against the same expectations before compiling it through the supported facade.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import pathlib
import re
import sys
from typing import Any

FORMAT = "pcp-session-compiler-evals/1"
REQUIRED_FIXTURES = {
    "simple-handoff",
    "superseded-decisions",
    "long-roadmap",
    "partial-implementation",
    "false-done-claim",
    "multiple-epics",
    "parallel-agent-work",
    "conflicting-decisions",
    "ambiguous-project",
    "sensitive-content",
    "long-session-compaction",
    "multi-session-incremental",
    "mvp-with-post-mvp-work",
    "repository-ahead-of-plan",
    "plan-ahead-of-repository",
    "portable-seal-without-verification",
}
DIMENSIONS = (
    "decision_preservation",
    "supersession_accuracy",
    "plan_recall",
    "open_loop_recall",
    "implementation_state_accuracy",
    "evidence_discipline",
    "dependency_preservation",
    "frontier_accuracy",
    "compression",
    "sensitive_data_leakage",
)
SECRET_PATTERNS = [
    re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\s*[:=]\s*\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]


class SessionEvalError(Exception):
    """Fail-closed eval corpus/scoring error."""


def _load(name: str, filename: str):
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SessionEvalError(f"Unable to load required sibling module: {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


FACADE = _load("pcp_session_eval_facade", "session_compile.py")
CORE = FACADE.COMPILER
MERGE = FACADE.MERGE


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SessionEvalError(f"Input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SessionEvalError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SessionEvalError(f"Expected JSON object in {path}")
    return value


def load_corpus(path: pathlib.Path) -> dict[str, Any]:
    corpus = read_json(path)
    if corpus.get("format") != FORMAT:
        raise SessionEvalError(f"Eval corpus format must be {FORMAT}")
    fixtures = corpus.get("fixtures")
    if not isinstance(fixtures, list):
        raise SessionEvalError("Eval corpus fixtures must be an array")
    ids = [fixture.get("id") for fixture in fixtures if isinstance(fixture, dict)]
    if len(ids) != len(fixtures) or any(not isinstance(value, str) or not value for value in ids):
        raise SessionEvalError("Every eval fixture requires a non-empty id")
    if len(ids) != len(set(ids)):
        raise SessionEvalError("Eval fixture ids must be unique")
    missing = sorted(REQUIRED_FIXTURES - set(ids))
    extra = sorted(set(ids) - REQUIRED_FIXTURES)
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing canonical fixtures: " + ", ".join(missing))
        if extra:
            parts.append("unknown canonical fixtures: " + ", ".join(extra))
        raise SessionEvalError("; ".join(parts))
    return corpus


def transcript_text(fixture: dict[str, Any]) -> str:
    text = fixture.get("transcript")
    if isinstance(text, str):
        return text
    repeat = fixture.get("transcript_repeat")
    if isinstance(repeat, dict):
        part = repeat.get("text")
        count = repeat.get("count")
        if isinstance(part, str) and isinstance(count, int) and count > 0:
            return part * count
    raise SessionEvalError(f"Fixture {fixture.get('id')!r} requires transcript or transcript_repeat")


def _origin(kind: str = "conversation", ref: str = "eval:fixture") -> dict[str, Any]:
    return {"kind": kind, "ref": ref}


def _decision(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "statement": raw.get("statement", raw["id"]),
        "status": raw.get("status", "accepted"),
        "confidence": raw.get("confidence", "reported"),
        "origin": _origin(raw.get("origin_kind", "conversation")),
        "supersedes": list(raw.get("supersedes", [])),
    }


def _finding(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "statement": raw.get("statement", raw["id"]),
        "confidence": raw.get("confidence", "reported"),
        "origin": _origin(raw.get("origin_kind", "conversation")),
    }


def _item(raw: dict[str, Any]) -> dict[str, Any]:
    status = raw.get("status", "accepted")
    evidence = list(raw.get("evidence_refs", []))
    if status == "verified_done" and not evidence:
        evidence = [f"evidence:{raw['id']}"]
    return {
        "id": raw["id"],
        "kind": raw.get("kind", "story"),
        "title": raw.get("title", raw["id"]),
        "status": status,
        "parent_id": raw.get("parent_id"),
        "priority": raw.get("priority", "high"),
        "depends_on": list(raw.get("depends_on", [])),
        "acceptance_criteria": list(
            raw.get("acceptance_criteria", [f"{raw['id']} acceptance is satisfied."])
        ),
        "origin": _origin(raw.get("origin_kind", "conversation")),
        "supersedes": list(raw.get("supersedes", [])),
        "evidence_refs": evidence,
        "repository_refs": list(raw.get("repository_refs", [])),
    }


def _blocker(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "title": raw.get("title", raw["id"]),
        "priority": raw.get("priority", "high"),
        "acceptance_criteria": list(raw.get("acceptance_criteria", [f"Resolve {raw['id']}."])),
        "depends_on": list(raw.get("depends_on", [])),
    }


def _risk(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "description": raw.get("description", raw["id"]),
        "severity": raw.get("severity", "medium"),
        "mitigation": raw.get("mitigation", "Reconcile before execution."),
    }


def build_compilation(
    fixture_id: str,
    raw: dict[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    """Expand compact fixture semantics into full pcp-session-compilation/1 IR."""
    decisions = [_decision(value) for value in raw.get("decisions", [])]
    findings = [_finding(value) for value in raw.get("findings", [])]
    items = [_item(value) for value in raw.get("items", [])]
    frontier_id = raw.get("next_frontier")
    frontier = None
    if frontier_id is not None:
        item = next((value for value in items if value["id"] == frontier_id), None)
        if item is None:
            raise SessionEvalError(
                f"Fixture {fixture_id} {phase} frontier references unknown item {frontier_id!r}"
            )
        frontier = {
            "planning_item_id": frontier_id,
            "instruction": f"Advance {frontier_id} after authoritative reconciliation.",
            "acceptance_criteria": list(item["acceptance_criteria"]),
        }
    safe_id = re.sub(r"[^A-Za-z0-9._-]", "-", fixture_id)
    suffix = "prior" if phase == "prior" else "current"
    return {
        "format": "pcp-session-compilation/1",
        "compilation_id": f"compilation-eval-{safe_id}-{suffix}",
        "created_at": "2026-09-01T16:10:00Z" if phase == "prior" else "2026-09-01T16:20:00Z",
        "project": {
            "id": raw.get("project_id", "git-session-eval-project"),
            "name": raw.get("project_name", "Session Eval Project"),
            "repository": raw.get("repository", "github:rafaelscosta/session-eval-project"),
        },
        "producer": {
            "surface": "chatgpt",
            "model": "gpt-5.6-sol",
            "session_ref": f"eval:{fixture_id}:{suffix}",
        },
        "prior_checkpoint": None,
        "objective": {
            "current": raw.get("objective", f"Evaluate {fixture_id}."),
            "definition_of_done": list(
                raw.get("definition_of_done", ["Canonical semantic expectations are preserved."])
            ),
        },
        "decisions": decisions,
        "findings": findings,
        "planning": {
            "vision": raw.get("vision", "Preserve accepted project state across surfaces."),
            "items": items,
        },
        "blockers": [_blocker(value) for value in raw.get("blockers", [])],
        "risks": [_risk(value) for value in raw.get("risks", [])],
        "uncertainties": list(raw.get("uncertainties", [])),
        "next_frontier": frontier,
    }


def _validate_and_compile(source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    errors = CORE.validate_compilation(source)
    if errors:
        raise SessionEvalError("Invalid compilation IR:\n- " + "\n- ".join(errors))
    FACADE.validate_blocker_dependencies(source)
    FACADE.validate_supersession_references(source)
    checkpoint, planning = CORE.compile_session(
        source,
        seal_portable=True,
        sealed_at="2026-09-01T16:30:00Z",
    )
    FACADE.normalize_pcp_decision_supersedes(checkpoint, source)
    FACADE.refresh_digests_after_normalization(checkpoint, planning)
    return checkpoint, planning


def gold_source(fixture: dict[str, Any]) -> dict[str, Any]:
    current = build_compilation(fixture["id"], fixture.get("current", {}), phase="current")
    mode = fixture.get("mode", "bootstrap")
    if mode == "bootstrap":
        return current
    if mode != "incremental":
        raise SessionEvalError(f"Fixture {fixture['id']} has invalid mode {mode!r}")
    prior_raw = fixture.get("prior")
    if not isinstance(prior_raw, dict):
        raise SessionEvalError(f"Incremental fixture {fixture['id']} requires prior state")
    prior = build_compilation(fixture["id"], prior_raw, phase="prior")
    _, prior_planning = _validate_and_compile(prior)
    FACADE.validate_prior_planning_integrity(prior_planning)
    merged = MERGE.merge_compilation_with_prior(current, prior_planning)
    return merged


def _ratio_score(actual: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return actual / total


def _output_text(checkpoint: dict[str, Any], planning: dict[str, Any]) -> str:
    return json.dumps(
        {"checkpoint": checkpoint, "planning": planning},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def score_outputs(
    fixture: dict[str, Any],
    source: dict[str, Any],
    checkpoint: dict[str, Any],
    planning: dict[str, Any],
) -> dict[str, Any]:
    expected = fixture.get("expected")
    if not isinstance(expected, dict):
        raise SessionEvalError(f"Fixture {fixture['id']} requires expected object")
    decisions = {
        value.get("id"): value
        for value in planning.get("decisions", [])
        if isinstance(value, dict)
    }
    items = {
        value.get("id"): value
        for value in planning.get("items", [])
        if isinstance(value, dict)
    }

    decision_statuses = expected.get("decision_statuses", {})
    accepted_expectations = {
        key: value for key, value in decision_statuses.items() if value == "accepted"
    }
    superseded_expectations = {
        key: value for key, value in decision_statuses.items() if value == "superseded"
    }
    accepted_ok = sum(
        1 for key, status in accepted_expectations.items()
        if key in decisions and decisions[key].get("status") == status
    )
    superseded_ok = sum(
        1 for key, status in superseded_expectations.items()
        if key in decisions and decisions[key].get("status") == status
    )

    preserved = list(expected.get("preserved_item_ids", []))
    preserved_ok = sum(1 for key in preserved if key in items)
    item_statuses = expected.get("item_statuses", {})
    state_ok = sum(
        1 for key, status in item_statuses.items()
        if key in items and items[key].get("status") == status
    )
    dependencies = expected.get("depends_on", {})
    dependency_ok = sum(
        1 for key, deps in dependencies.items()
        if key in items and items[key].get("depends_on") == deps
    )

    frontier_expected = expected.get("frontier")
    frontier_source = source.get("next_frontier")
    frontier_work = next(
        (
            value for value in checkpoint.get("open_work", [])
            if isinstance(value, dict) and value.get("id") == "W-FRONTIER-001"
        ),
        None,
    )
    if frontier_expected is None:
        frontier_ok = frontier_source is None and frontier_work is None
    else:
        frontier_ok = (
            isinstance(frontier_source, dict)
            and frontier_source.get("planning_item_id") == frontier_expected
            and isinstance(frontier_work, dict)
            and frontier_work.get("depends_on") == ["W-RECONCILE-001"]
            and checkpoint.get("next_action", {}).get("work_item_id") == "W-RECONCILE-001"
        )

    completed_claims = [
        claim for claim in checkpoint.get("claims", [])
        if isinstance(claim, dict) and claim.get("kind") == "completed"
    ]
    verified_without_evidence = [
        item for item in items.values()
        if item.get("status") == "verified_done" and not item.get("evidence_refs")
    ]
    evidence_ok = not verified_without_evidence and (
        not expected.get("forbid_completed_claims", False) or not completed_claims
    )

    output = _output_text(checkpoint, planning)
    must_not = list(expected.get("must_not_contain", []))
    explicit_secret_ok = all(marker not in output for marker in must_not)
    generic_secret_ok = not any(pattern.search(output) for pattern in SECRET_PATTERNS)

    max_ratio = expected.get("compression_max_ratio")
    transcript = transcript_text(fixture)
    output_size = len(output.encode("utf-8"))
    transcript_size = len(transcript.encode("utf-8"))
    compression_ratio = output_size / max(transcript_size, 1)
    compression_ok = True if max_ratio is None else compression_ratio <= float(max_ratio)

    scores = {
        "decision_preservation": _ratio_score(accepted_ok, len(accepted_expectations)),
        "supersession_accuracy": _ratio_score(superseded_ok, len(superseded_expectations)),
        "plan_recall": _ratio_score(preserved_ok, len(preserved)),
        "open_loop_recall": _ratio_score(preserved_ok, len(preserved)),
        "implementation_state_accuracy": _ratio_score(state_ok, len(item_statuses)),
        "evidence_discipline": 1.0 if evidence_ok else 0.0,
        "dependency_preservation": _ratio_score(dependency_ok, len(dependencies)),
        "frontier_accuracy": 1.0 if frontier_ok else 0.0,
        "compression": 1.0 if compression_ok else 0.0,
        "sensitive_data_leakage": 1.0 if (explicit_secret_ok and generic_secret_ok) else 0.0,
    }
    return {
        "fixture_id": fixture["id"],
        "pass": all(scores[name] == 1.0 for name in DIMENSIONS),
        "scores": scores,
        "details": {
            "compression_ratio": compression_ratio,
            "transcript_bytes": transcript_size,
            "output_bytes": output_size,
            "frontier_expected": frontier_expected,
            "frontier_actual": (
                frontier_source.get("planning_item_id")
                if isinstance(frontier_source, dict)
                else None
            ),
            "completed_claims": len(completed_claims),
            "surface_status": checkpoint.get("verification", {}).get("surface_status"),
        },
    }


def evaluate_fixture(
    fixture: dict[str, Any],
    *,
    prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = copy.deepcopy(prediction) if prediction is not None else gold_source(fixture)
    checkpoint, planning = _validate_and_compile(source)
    result = score_outputs(fixture, source, checkpoint, planning)
    expected_surface = fixture.get("expected", {}).get("surface_status")
    if expected_surface is not None and result["details"]["surface_status"] != expected_surface:
        result["scores"]["evidence_discipline"] = 0.0
        result["pass"] = False
    result["mode"] = "prediction" if prediction is not None else "gold"
    return result


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        raise SessionEvalError("No eval results")
    metrics = {
        name: sum(float(result["scores"][name]) for result in results) / len(results)
        for name in DIMENSIONS
    }
    return {
        "fixtures": len(results),
        "passed": sum(1 for result in results if result["pass"]),
        "failed": sum(1 for result in results if not result["pass"]),
        "metrics": metrics,
        "pass": all(result["pass"] for result in results),
    }


def evaluate_corpus(
    corpus: dict[str, Any],
    *,
    prediction_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for fixture in corpus["fixtures"]:
        prediction = None
        if prediction_dir is not None:
            prediction = read_json(prediction_dir / f"{fixture['id']}.json")
        results.append(evaluate_fixture(fixture, prediction=prediction))
    return {
        "format": "pcp-session-compiler-eval-report/1",
        "mode": "prediction" if prediction_dir is not None else "gold",
        "aggregate": aggregate(results),
        "results": results,
    }


def default_corpus_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "assets" / "evals" / "session-compiler-fixtures.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate Session Compiler semantic preservation")
    parser.add_argument("--corpus", default=str(default_corpus_path()))
    parser.add_argument(
        "--predictions",
        help="Optional directory containing <fixture-id>.json model-produced compilation IR files",
    )
    parser.add_argument("--out")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        corpus = load_corpus(pathlib.Path(args.corpus))
        report = evaluate_corpus(
            corpus,
            prediction_dir=pathlib.Path(args.predictions) if args.predictions else None,
        )
        text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
        if args.out:
            out = pathlib.Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report["aggregate"]["pass"] else 1
    except (SessionEvalError, CORE.SessionCompilationError, MERGE.PlanningMergeError) as exc:
        print(f"session-eval: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
