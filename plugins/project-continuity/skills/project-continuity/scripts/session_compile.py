#!/usr/bin/env python3
"""CLI facade for bootstrap and incremental Session Compiler workflows."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys


def _load(name: str, filename: str):
    path = pathlib.Path(__file__).resolve().with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


COMPILER = _load("pcp_session_compile_core", "session_compiler.py")
MERGE = _load("pcp_session_compile_merge", "planning_merge.py")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile bootstrap or incremental Session Compilation IR into PCP portable state"
    )
    parser.add_argument("--input", required=True, help="Current pcp-session-compilation/1 JSON")
    parser.add_argument(
        "--prior-planning",
        help="Optional prior pcp-planning/1 snapshot. When supplied, omitted prior work is preserved.",
    )
    parser.add_argument("--checkpoint-out", required=True)
    parser.add_argument("--planning-out", required=True)
    parser.add_argument("--seal-portable", action="store_true")
    parser.add_argument("--sealed-at", help="Optional RFC3339 seal time for deterministic tests")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = COMPILER.read_json(pathlib.Path(args.input))
        mode = "bootstrap"
        if args.prior_planning:
            prior = COMPILER.read_json(pathlib.Path(args.prior_planning))
            source = MERGE.merge_compilation_with_prior(source, prior)
            mode = "incremental"
        checkpoint, planning = COMPILER.compile_session(
            source,
            seal_portable=bool(args.seal_portable),
            sealed_at=args.sealed_at,
        )
        COMPILER.atomic_write_json(pathlib.Path(args.checkpoint_out), checkpoint)
        COMPILER.atomic_write_json(pathlib.Path(args.planning_out), planning)
        print(
            json.dumps(
                {
                    "status": "compiled",
                    "mode": mode,
                    "checkpoint_id": checkpoint["checkpoint_id"],
                    "checkpoint_status": checkpoint["verification"]["status"],
                    "checkpoint_digest": checkpoint["verification"]["content_digest"],
                    "planning_id": planning["planning_id"],
                    "planning_digest": planning["content_digest"],
                    "planning_items": len(planning["items"]),
                    "decisions": len(planning["decisions"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (COMPILER.SessionCompilationError, MERGE.PlanningMergeError, RuntimeError) as exc:
        print(f"session-compile: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
