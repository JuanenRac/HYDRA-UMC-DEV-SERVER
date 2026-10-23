# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_identifiers.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The one allow-list of names, and the three places that use it."""
import unittest

from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.identifiers import is_account_name, is_identifier, path_text_problem
from hydra_umc_dev_server.remote_station import RemoteIdentity
from hydra_umc_dev_server.workspace import WorkspaceError, _require_safe_id


class AccountNameTests(unittest.TestCase):
    def test_a_plain_lowercase_account_is_valid(self):
        for name in ("hydra-dev-station", "_svc", "a", "svc_01", "x" * 32):
            with self.subTest(name=name):
                self.assertTrue(is_account_name(name))

    def test_everything_else_is_refused(self):
        for name in ("", "Root", "1abc", "-abc", "a b", "a;b", "a$(id)", "x" * 33, "ünï", "a\n", "a/b", None, 5):
            with self.subTest(name=name):
                self.assertFalse(is_account_name(name))


class PathTextTests(unittest.TestCase):
    def test_a_plain_path_is_valid(self):
        for text in ("/srv/hydra-umc-dev/station", "workspace", "a/b.c/d_e-f"):
            with self.subTest(text=text):
                self.assertIsNone(path_text_problem(text))

    def test_characters_that_break_a_unit_or_an_argv_are_refused(self):
        for text in ("a b", "a'b", 'a"b', "a$HOME", "a;b", "a\nb", "a\b", "a\tb", "ａ", "a%h"):
            with self.subTest(text=text):
                self.assertIn("may only contain", path_text_problem(text))

    def test_a_dot_dot_segment_is_refused_wherever_it_stands(self):
        for text in ("..", "../x", "a/../b", "/srv/..", "/srv/a/.."):
            with self.subTest(text=text):
                self.assertEqual(path_text_problem(text), "it has a '..' segment")
        self.assertIsNone(path_text_problem("a..b/c"), "'..' inside a name is not a segment")

    def test_empty_or_not_text_is_refused(self):
        for text in ("", None, 3):
            self.assertEqual(path_text_problem(text), "it is empty")


class IdentifierTests(unittest.TestCase):
    def test_one_safe_segment_is_valid(self):
        for text in ("run-0001", "A1", "a.b_c-d", "x" * 128):
            with self.subTest(text=text):
                self.assertTrue(is_identifier(text))

    def test_a_trailing_newline_and_other_tricks_are_refused(self):
        # `$` in the old pattern accepted a trailing newline
        for text in ("run-1\n", "", "-x", ".x", "a/b", "a..b", "a b", "x" * 129, None):
            with self.subTest(text=text):
                self.assertFalse(is_identifier(text))


class UsersOfTheRulesTests(unittest.TestCase):
    """The workspace and the remote-station profile refuse what the shared rules refuse."""

    def identity(self, **extra):
        data = {"user": "hydra-dev-station", "home": "/srv/hydra-umc-dev/station", "workspace_subdir": "workspace"}
        data.update(extra)
        return RemoteIdentity.from_dict(data)

    def test_the_profile_uses_the_account_and_path_rules(self):
        self.identity()
        for bad in ({"user": "Root"}, {"user": "a b"}, {"home": "/srv/a b"}, {"home": "/srv/../etc"}, {"workspace_subdir": "a$b"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ConfigValidationError):
                    self.identity(**bad)

    def test_the_workspace_uses_the_identifier_rule(self):
        self.assertEqual(_require_safe_id("run-1"), "run-1")
        with self.assertRaises(WorkspaceError):
            _require_safe_id("run-1\n")


if __name__ == "__main__":
    unittest.main()
