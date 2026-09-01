from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_module(name: str, filename: str):
    """Load one sibling script under an isolated module name."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


facade = load_module("pcp_test_session_compile_facade", "session_compile.py")


def blocker(blocker_id: str, depends_on: list[str] | None = None) -> dict:
    """Build the minimal blocker shape needed by the facade guard."""
    return {
        "id": blocker_id,
        "title": blocker_id,
        "priority": "high",
        "acceptance_criteria": [f"Resolve {blocker_id}"],
        "depends_on": list(depends_on or []),
    }


class BlockerDependencyGuardTests(unittest.TestCase):
    """Cross-record blocker dependency semantics that JSON Schema cannot express."""

    def test_valid_blocker_chain_is_preserved(self):
        """Known acyclic blocker dependencies pass validation."""
        source = {
            "blockers": [
                blocker("blocker-a"),
                blocker("blocker-b", ["blocker-a"]),
                blocker("blocker-c", ["blocker-b"]),
            ]
        }
        facade.validate_blocker_dependencies(source)

    def test_unknown_blocker_dependency_fails_closed(self):
        """Unknown blocker IDs cannot be silently dropped during PCP mapping."""
        source = {
            "blockers": [
                blocker("blocker-a", ["missing-blocker"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("unknown blocker dependencies", str(ctx.exception))

    def test_direct_blocker_cycle_fails_closed(self):
        """A two-node blocker cycle is rejected before PCP conversion."""
        source = {
            "blockers": [
                blocker("blocker-a", ["blocker-b"]),
                blocker("blocker-b", ["blocker-a"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("Blocker dependency cycle", str(ctx.exception))

    def test_self_dependency_fails_closed(self):
        """A blocker cannot depend on itself."""
        source = {
            "blockers": [
                blocker("blocker-a", ["blocker-a"]),
            ]
        }
        with self.assertRaises(facade.COMPILER.SessionCompilationError) as ctx:
            facade.validate_blocker_dependencies(source)
        self.assertIn("Blocker dependency cycle", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
