from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys
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


evalmod = load_module("pcp_test_session_eval", "session_eval.py")


class SessionCompilerEvalTests(unittest.TestCase):
    """R6 fixture-driven semantic-preservation eval contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = evalmod.load_corpus(evalmod.default_corpus_path())
        cls.by_id = {fixture["id"]: fixture for fixture in cls.corpus["fixtures"]}

    def test_corpus_contains_exact_canonical_fixture_set(self):
        """R0's 16 canonical compiler scenarios are all present and uniquely named."""
        self.assertEqual(set(self.by_id), evalmod.REQUIRED_FIXTURES)
        self.assertEqual(len(self.by_id), 16)
        for fixture in self.by_id.values():
            self.assertTrue(evalmod.transcript_text(fixture).strip())
            self.assertIsInstance(fixture.get("expected"), dict)

    def test_gold_corpus_passes_every_dimension(self):
        """Deterministic compilation of the gold semantic state must score 16/16 with no partial metric."""
        report = evalmod.evaluate_corpus(self.corpus)
        aggregate = report["aggregate"]
        self.assertTrue(aggregate["pass"], report)
        self.assertEqual(aggregate["fixtures"], 16)
        self.assertEqual(aggregate["passed"], 16)
        self.assertEqual(aggregate["failed"], 0)
        self.assertEqual(set(aggregate["metrics"]), set(evalmod.DIMENSIONS))
        self.assertTrue(
            all(score == 1.0 for score in aggregate["metrics"].values()),
            aggregate,
        )

    def test_incremental_prediction_that_drops_post_mvp_fails_plan_recall(self):
        """The scorer catches the exact failure mode that motivated mobile continuity."""
        fixture = self.by_id["multi-session-incremental"]
        gold = evalmod.gold_source(fixture)
        bad = copy.deepcopy(gold)
        bad["planning"]["items"] = [
            item for item in bad["planning"]["items"]
            if item["id"] != "story-inc-post"
        ]
        result = evalmod.evaluate_fixture(fixture, prediction=bad)
        self.assertFalse(result["pass"])
        self.assertLess(result["scores"]["plan_recall"], 1.0)
        self.assertLess(result["scores"]["open_loop_recall"], 1.0)

    def test_prediction_with_secret_material_fails_sensitive_data_gate(self):
        """A model prediction that persists credential material cannot pass the eval."""
        fixture = self.by_id["sensitive-content"]
        bad = evalmod.gold_source(fixture)
        bad["findings"].append(
            {
                "id": "finding-secret-leak",
                "statement": "access_token=ghp_123456789012345678901234567890",
                "confidence": "reported",
                "origin": {"kind": "conversation", "ref": "eval:leak"},
            }
        )
        with self.assertRaises(evalmod.SessionEvalError):
            # Compiler validation is intentionally stricter than scoring: secret-like
            # durable IR should fail before it can become a checkpoint.
            evalmod.evaluate_fixture(fixture, prediction=bad)

    def test_long_session_fixture_enforces_real_compression_gate(self):
        """The compression dimension is measured against expanded transcript bytes, not fixture metadata size."""
        fixture = self.by_id["long-session-compaction"]
        result = evalmod.evaluate_fixture(fixture)
        self.assertTrue(result["pass"], result)
        self.assertLessEqual(
            result["details"]["compression_ratio"],
            fixture["expected"]["compression_max_ratio"],
        )
        self.assertGreater(result["details"]["transcript_bytes"], 50000)

    def test_portable_seal_dimension_never_confuses_integrity_with_verification(self):
        """Gold eval explicitly protects the sealed + unverifiable trust boundary."""
        fixture = self.by_id["portable-seal-without-verification"]
        result = evalmod.evaluate_fixture(fixture)
        self.assertTrue(result["pass"], result)
        self.assertEqual(result["details"]["surface_status"], "unverifiable")
        self.assertEqual(result["details"]["completed_claims"], 0)


if __name__ == "__main__":
    unittest.main()
