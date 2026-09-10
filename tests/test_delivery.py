# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_delivery.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS10 - the delivery package and an honest maturity evaluation, run
against this repository itself."""
import unittest
from pathlib import Path

from hydra_umc_dev_server import __version__
from hydra_umc_dev_server.delivery import build_delivery_manifest, evaluate_maturity

_REPO = Path(__file__).resolve().parent.parent


class DeliveryManifestTests(unittest.TestCase):
    def setUp(self):
        self.manifest = build_delivery_manifest(_REPO)

    def test_it_hashes_every_shipped_module_and_doc(self):
        rels = set(self.manifest.files)
        for expected in (
            "src/hydra_umc_dev_server/config.py",
            "src/hydra_umc_dev_server/runner.py",
            "src/hydra_umc_dev_server/delivery.py",
            "docs/CLI_REFERENCE.md",
            "hydra-umc.project.json",
            "README.md",
        ):
            self.assertIn(expected, rels)
        self.assertTrue(all(len(h) == 64 for h in self.manifest.files.values()))

    def test_it_reports_the_real_version_and_the_cli_surface(self):
        self.assertEqual(self.manifest.version, __version__)
        for sub in ("config", "station", "migrate", "task", "queue", "provider", "incident", "repair", "ops", "deliver"):
            self.assertIn(sub, self.manifest.cli_subcommands)
        self.assertGreaterEqual(self.manifest.test_files, 10)


class MaturityEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.evaluation = evaluate_maturity(_REPO)

    def test_it_lists_all_ten_deliveries_with_a_present_module(self):
        self.assertEqual(len(self.evaluation.deliveries), 10)
        for d in self.evaluation.deliveries:
            self.assertTrue(d.module_present, f"{d.delivery_id}: {d.module} missing")
            self.assertIn(d.status, ("shipped", "partial"))

    def test_ds06_is_reported_partial_because_only_the_fake_ships(self):
        ds06 = next(d for d in self.evaluation.deliveries if d.delivery_id == "DS06")
        self.assertEqual(ds06.status, "partial")

    def test_the_evaluation_never_claims_more_than_scaffolding(self):
        self.assertEqual(self.evaluation.overall_maturity, "scaffolding")
        self.assertNotIn("established", self.evaluation.honest_summary.lower())

    def test_it_states_the_known_limitations_plainly(self):
        blob = " ".join(self.evaluation.known_limitations).lower()
        for phrase in ("no real ai provider", "no real network transport", "no target hardware", "deploys anything"):
            self.assertIn(phrase, blob)


if __name__ == "__main__":
    unittest.main()
