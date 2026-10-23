# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_version_rule.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The bump of this repository and the shared utility apply one rule."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location("_t_" + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OneRuleTests(unittest.TestCase):
    def test_the_local_bump_gives_what_the_shared_utility_gives_below_the_extra_component(self):
        local, shared = _load("bump_version"), _load("bump_manifest_version")
        for major in range(0, 2):
            for minor in range(0, 10):
                for patch in range(0, 10):
                    if (major, minor, patch) >= shared.FOUR_PART_FROM and (major, minor, patch) != (0, 7, 9):
                        continue
                    expected = shared.next_version(f"{major}.{minor}.{patch}")
                    if expected.count(".") == 3:
                        continue  # from there on the shared utility does the bump itself
                    with self.subTest(version=f"{major}.{minor}.{patch}"):
                        self.assertEqual(".".join(map(str, local.bump(major, minor, patch))), expected)


if __name__ == "__main__":
    unittest.main()
