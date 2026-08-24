#!/usr/bin/env python3
"""Lightweight local validator for the Agent Skills structure used by this package.

This is not the official skills-ref validator. It mirrors the constraints used
by this package so validation can run without network access or third-party
packages.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ALLOWED_TOP_LEVEL = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REF_RE = re.compile(r"(?<![A-Za-z0-9_./-])((?:scripts|references|assets)/[A-Za-z0-9_./-]+)")


def parse_frontmatter(text: str) -> tuple[dict[str, object], list[str]]:
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["SKILL.md must begin with YAML frontmatter delimiter ---"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, ["SKILL.md frontmatter is not closed with ---"]
    fm_lines = lines[1:end]
    data: dict[str, object] = {}
    current_map: str | None = None
    for raw in fm_lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  "):
            if current_map != "metadata":
                errors.append(f"Unsupported nested frontmatter line: {raw.strip()}")
                continue
            m = re.match(r"\s{2}([A-Za-z0-9_.-]+):\s*(.*)$", raw)
            if not m:
                errors.append(f"Malformed metadata line: {raw.strip()}")
                continue
            meta = data.setdefault("metadata", {})
            assert isinstance(meta, dict)
            val = m.group(2).strip().strip('"').strip("'")
            meta[m.group(1)] = val
            continue
        m = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", raw)
        if not m:
            errors.append(f"Malformed frontmatter line: {raw}")
            continue
        key, value = m.group(1), m.group(2).strip()
        current_map = key if value == "" else None
        if key == "metadata" and value == "":
            data[key] = {}
        else:
            data[key] = value.strip('"').strip("'")
    return data, errors


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    skill = root / "SKILL.md"
    errors: list[str] = []
    if not skill.exists():
        errors.append("SKILL.md is missing")
    else:
        text = skill.read_text(encoding="utf-8")
        fm, fm_errors = parse_frontmatter(text)
        errors.extend(fm_errors)
        name = fm.get("name")
        description = fm.get("description")
        compatibility = fm.get("compatibility")
        if not isinstance(name, str) or not name:
            errors.append("frontmatter.name is required")
        else:
            if len(name) > 64:
                errors.append("frontmatter.name exceeds 64 characters")
            if not NAME_RE.fullmatch(name):
                errors.append("frontmatter.name must use lowercase letters, numbers, and single hyphens only")
            if name != root.name:
                errors.append(f"frontmatter.name '{name}' must match parent directory '{root.name}'")
        if not isinstance(description, str) or not description:
            errors.append("frontmatter.description is required")
        elif len(description) > 1024:
            errors.append("frontmatter.description exceeds 1024 characters")
        if isinstance(compatibility, str) and len(compatibility) > 500:
            errors.append("frontmatter.compatibility exceeds 500 characters")
        unknown = set(fm) - ALLOWED_TOP_LEVEL
        if unknown:
            errors.append(f"unsupported frontmatter fields: {sorted(unknown)}")
        metadata = fm.get("metadata")
        if metadata is not None:
            if not isinstance(metadata, dict):
                errors.append("frontmatter.metadata must be a mapping")
            elif any(not isinstance(v, str) for v in metadata.values()):
                errors.append("frontmatter.metadata values must be strings")
        line_count = len(text.splitlines())
        if line_count > 500:
            errors.append(f"SKILL.md has {line_count} lines; recommended maximum is 500")
        for ref in sorted(set(REF_RE.findall(text))):
            clean = ref.rstrip("`.,);:")
            if not (root / clean).exists():
                errors.append(f"referenced file does not exist: {clean}")

    for schema in (root / "assets" / "schemas").glob("*.json"):
        try:
            json.loads(schema.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON schema {schema.name}: {exc}")

    required = [
        root / "scripts" / "continuity.py",
        root / "references" / "PROTOCOL.md",
        root / "references" / "SECURITY.md",
        root / "assets" / "schemas" / "checkpoint.schema.json",
        root / "assets" / "schemas" / "state.schema.json",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"required package file is missing: {path.relative_to(root)}")

    if errors:
        print("FAIL")
        for err in errors:
            print(f"- {err}")
        return 1
    print("PASS")
    print(f"- skill: {root.name}")
    print(f"- SKILL.md lines: {len(skill.read_text(encoding='utf-8').splitlines())}")
    print("- frontmatter constraints: pass")
    print("- local references: pass")
    print("- JSON schemas parse: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
