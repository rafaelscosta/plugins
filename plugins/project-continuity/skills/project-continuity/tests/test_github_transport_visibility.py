from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "github_transport.py"
spec = importlib.util.spec_from_file_location("pcp_github_visibility_test", MODULE_PATH)
github = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["pcp_github_visibility_test"] = github
spec.loader.exec_module(github)


class RepositoryVisibilityTests(unittest.TestCase):
    """Publication safety must fail closed when repository visibility is ambiguous."""

    def test_unknown_visibility_is_transport_unavailable(self):
        """Missing visibility/private metadata cannot be interpreted as safe."""
        with self.assertRaises(github.TransportError) as ctx:
            github._repo_is_public({})
        self.assertEqual(ctx.exception.code, "transport-unavailable")

    def test_explicit_private_boolean_is_safe_fallback(self):
        """Hosts that expose only GitHub's private boolean still classify safely."""
        self.assertFalse(github._repo_is_public({"private": True}))
        self.assertTrue(github._repo_is_public({"private": False}))

    def test_internal_visibility_is_not_public(self):
        """Enterprise internal repositories are not treated as public targets."""
        self.assertFalse(github._repo_is_public({"visibility": "internal"}))


if __name__ == "__main__":
    unittest.main()
