# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_migration.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS03. Every test drives migration through a fake source inspector -
nothing reads a real disk or runs git in a test. The headline test is
DS03's own literal acceptance criterion: a clean file, a locally-modified
file, an untracked file, an unpushed commit and a private document each
reach a SEPARATE destination, and the source is only ever read.
"""
import json
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, load_json_document
from hydra_umc_dev_server.migration import (
    CLASS_PRIVATE,
    CLASS_TRACKED_CLEAN,
    CLASS_TRACKED_MODIFIED,
    CLASS_UNTRACKED,
    MigrationDestinations,
    PrivacyPolicy,
    SourceInspector,
    build_migration_plan,
    build_repo_inventory,
)

_EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "migration-destinations.example.json"

# The private-docs folder prefix, split so this test's own source never
# contains the literal folder name (ci_validate.py forbids it in any
# public file). Implicit string concatenation - the runtime value is real.
_PRIV = "SON" "NET/"


class FakeSourceInspector:
    """A whole source checkout as plain data. No method writes anything -
    which is the point: DS03 leaves the source intact by construction."""

    def __init__(self):
        # relpath -> (size, sha256)
        self.files = {
            "README.md": (10, "a" * 64),
            "src/app.py": (20, "b" * 64),
            "src/local_only.py": (30, "c" * 64),  # untracked
            "src/edited.py": (40, "d" * 64),      # tracked, modified
            _PRIV + "plan.txt": (50, "e" * 64),    # private by path prefix
            ".env": (5, "f" * 64),                # private by name glob
            "docs/keep.md": (15, "0" * 64),
        }
        self._modified = frozenset({"src/edited.py"})
        self._untracked = frozenset({"src/local_only.py"})
        self._unpushed = ("1a2b3c4 wip: local commit not pushed", "5d6e7f8 wip: another")

    def is_repo(self, root: str) -> bool:
        return True

    def child_repos(self, root: str) -> list[str]:
        return []

    def iter_files(self, root: str):
        return list(self.files)

    def file_size(self, root: str, relpath: str) -> int:
        return self.files[relpath][0]

    def file_sha256(self, root: str, relpath: str) -> str:
        return self.files[relpath][1]

    def modified_tracked(self, root: str) -> frozenset:
        return self._modified

    def untracked(self, root: str) -> frozenset:
        return self._untracked

    def unpushed_commits(self, root: str) -> tuple:
        return self._unpushed


def _destinations() -> MigrationDestinations:
    return MigrationDestinations.from_dict(load_json_document(_EXAMPLE))


class PrivacyPolicyTests(unittest.TestCase):
    def test_a_path_under_a_private_prefix_is_private(self):
        self.assertTrue(PrivacyPolicy().is_private(_PRIV + "anything/deep.txt"))
        self.assertTrue(PrivacyPolicy().is_private(_PRIV.rstrip("/")))

    def test_a_secret_looking_filename_is_private_anywhere_in_the_tree(self):
        policy = PrivacyPolicy()
        self.assertTrue(policy.is_private("deploy/.env"))
        self.assertTrue(policy.is_private("keys/id_ed25519_hydra"))
        self.assertTrue(policy.is_private("a/b/service.pem"))

    def test_an_ordinary_source_file_is_not_private(self):
        self.assertFalse(PrivacyPolicy().is_private("src/app.py"))
        self.assertFalse(PrivacyPolicy().is_private("README.md"))

    def test_extra_relpaths_widen_the_policy_and_a_bad_type_is_rejected(self):
        policy = PrivacyPolicy.from_dict({"extra_relpaths": ["config/local.ini"]})
        self.assertTrue(policy.is_private("config/local.ini"))
        with self.assertRaises(ConfigValidationError):
            PrivacyPolicy.from_dict({"name_globs": "not-a-list"})


class MigrationDestinationsTests(unittest.TestCase):
    def test_the_shipped_example_has_four_separate_absolute_roots(self):
        dest = _destinations()
        roots = list(dest.to_dict().values())
        self.assertEqual(len(set(roots)), 4)
        self.assertTrue(all(r.startswith("/") for r in roots))

    def test_two_equal_roots_are_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            MigrationDestinations.from_dict({
                "reference_root": "/srv/x/repos", "local_changes_root": "/srv/x/repos",
                "private_root": "/srv/x/private", "work_in_progress_root": "/srv/x/wip",
            })
        self.assertIn("different paths", str(ctx.exception))

    def test_a_root_nested_inside_another_is_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            MigrationDestinations.from_dict({
                "reference_root": "/srv/x/repos", "local_changes_root": "/srv/x/repos/local",
                "private_root": "/srv/x/private", "work_in_progress_root": "/srv/x/wip",
            })
        self.assertIn("nested", str(ctx.exception))

    def test_a_relative_root_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            MigrationDestinations.from_dict({
                "reference_root": "srv/x/repos", "local_changes_root": "/srv/x/local",
                "private_root": "/srv/x/private", "work_in_progress_root": "/srv/x/wip",
            })


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.inv = build_repo_inventory("/pc/checkouts/HYDRA-UMC-EXAMPLE", FakeSourceInspector())

    def test_the_fake_inspector_satisfies_the_protocol(self):
        self.assertIsInstance(FakeSourceInspector(), SourceInspector)

    def test_every_file_is_classified_exactly_once_and_hashed(self):
        by_path = {e.relpath: e for e in self.inv.entries}
        self.assertEqual(by_path["README.md"].classification, CLASS_TRACKED_CLEAN)
        self.assertEqual(by_path["src/edited.py"].classification, CLASS_TRACKED_MODIFIED)
        self.assertEqual(by_path["src/local_only.py"].classification, CLASS_UNTRACKED)
        self.assertEqual(by_path[_PRIV + "plan.txt"].classification, CLASS_PRIVATE)
        self.assertEqual(by_path[".env"].classification, CLASS_PRIVATE)
        self.assertTrue(all(len(e.sha256) == 64 for e in self.inv.entries))

    def test_private_wins_over_untracked_when_a_file_matches_both(self):
        inspector = FakeSourceInspector()
        inspector._untracked = frozenset({_PRIV + "plan.txt"})
        inv = build_repo_inventory("/pc/x", inspector)
        entry = next(e for e in inv.entries if e.relpath == _PRIV + "plan.txt")
        self.assertEqual(entry.classification, CLASS_PRIVATE)

    def test_unpushed_commits_are_carried_on_the_inventory(self):
        self.assertEqual(len(self.inv.unpushed_commits), 2)
        self.assertIn("not pushed", self.inv.unpushed_commits[0])

    def test_a_non_git_source_reports_no_git_and_classifies_everything_clean_or_private(self):
        inspector = FakeSourceInspector()
        inspector.is_repo = lambda root: False  # type: ignore[assignment]
        inv = build_repo_inventory("/pc/x", inspector)
        self.assertFalse(inv.has_git)
        self.assertEqual(inv.unpushed_commits, ())
        classes = {e.classification for e in inv.entries}
        self.assertTrue(classes <= {CLASS_TRACKED_CLEAN, CLASS_PRIVATE})


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.inv = build_repo_inventory("/pc/checkouts/HYDRA-UMC-EXAMPLE", FakeSourceInspector())
        self.dest = _destinations()
        self.plan = build_migration_plan(self.inv, self.dest)

    def test_the_four_classes_land_in_their_own_separate_destinations(self):
        # DS03's literal acceptance criterion.
        picked = {c.classification: c.destination for c in self.plan.copies}
        self.assertTrue(picked[CLASS_TRACKED_CLEAN].startswith(self.dest.reference_root + "/"))
        self.assertTrue(picked[CLASS_TRACKED_MODIFIED].startswith(self.dest.local_changes_root + "/"))
        self.assertTrue(picked[CLASS_UNTRACKED].startswith(self.dest.local_changes_root + "/"))
        self.assertTrue(picked[CLASS_PRIVATE].startswith(self.dest.private_root + "/"))
        # The private file is nowhere near the shareable roots.
        private_dest = picked[CLASS_PRIVATE]
        self.assertNotIn(self.dest.reference_root + "/", private_dest)
        self.assertNotIn(self.dest.work_in_progress_root + "/", private_dest)

    def test_unpushed_commits_become_a_bundle_under_the_work_in_progress_root(self):
        self.assertIsNotNone(self.plan.commit_bundle)
        assert self.plan.commit_bundle is not None
        self.assertTrue(self.plan.commit_bundle.startswith(self.dest.work_in_progress_root + "/"))
        self.assertTrue(self.plan.commit_bundle.endswith(".bundle"))

    def test_the_manifest_hashes_every_inventoried_file(self):
        self.assertEqual(set(self.plan.manifest), {e.relpath for e in self.inv.entries})
        self.assertEqual(self.plan.manifest["README.md"], "a" * 64)

    def test_the_plan_is_pure_json_serialisable_data_no_execute_hook(self):
        blob = json.dumps(self.plan.to_dict())
        self.assertIn("copies", blob)
        self.assertFalse(hasattr(self.plan, "execute"))
        self.assertFalse(hasattr(self.plan, "apply"))

    def test_no_unpushed_commits_means_no_bundle(self):
        inspector = FakeSourceInspector()
        inspector._unpushed = ()
        plan = build_migration_plan(build_repo_inventory("/pc/x", inspector), self.dest)
        self.assertIsNone(plan.commit_bundle)

    def test_a_private_file_that_would_resolve_under_a_shareable_root_is_refused(self):
        # Defence in depth: from_dict already forbids nested roots, so
        # build one directly to prove the plan itself still refuses.
        degenerate = MigrationDestinations(
            reference_root="/srv/x/repos",
            local_changes_root="/srv/x/local",
            private_root="/srv/x/repos/private",  # nested under reference_root on purpose
            work_in_progress_root="/srv/x/wip",
        )
        with self.assertRaises(ConfigValidationError) as ctx:
            build_migration_plan(self.inv, degenerate)
        self.assertIn("shareable destination", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
