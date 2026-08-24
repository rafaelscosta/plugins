from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / 'scripts' / 'validate_plugin.py'
spec = importlib.util.spec_from_file_location('validate_plugin', VALIDATOR_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

class PluginPackageTests(unittest.TestCase):
    def test_package_validates(self) -> None:
        checks = module.validate(ROOT)
        self.assertIn('plugin manifest valid', checks)

    def test_manifest_is_skills_only(self) -> None:
        manifest = json.loads((ROOT / '.codex-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        self.assertNotIn('apps', manifest)
        self.assertNotIn('mcpServers', manifest)
        self.assertNotIn('screenshots', manifest['interface'])
        self.assertEqual(manifest['skills'], './skills/')

    def test_skill_is_immediate_child(self) -> None:
        self.assertTrue((ROOT / 'skills' / 'project-continuity' / 'SKILL.md').is_file())

    def test_submission_cases_count(self) -> None:
        cases = json.loads((ROOT / 'submission' / 'test-cases.json').read_text(encoding='utf-8'))
        self.assertEqual(len(cases['positive']), 5)
        self.assertEqual(len(cases['negative']), 3)

    def test_no_symlinks(self) -> None:
        self.assertFalse(any(p.is_symlink() for p in ROOT.rglob('*')))

if __name__ == '__main__':
    unittest.main()
