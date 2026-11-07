# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_migration_real_git.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The real source inspector, driven with a real `git` against a bare repository on the same machine acting as the remote.

The other migration tests use a fake inspector. These start `git` itself: a bare repository stands in for the private remote, a clone of it is the source,
and the inspector must tell what is clean, modified, untracked, ignored and not yet pushed. Nothing is written to the source by the inspector. The tests
are skipped when `git` is not installed.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_dev_server.migration import SystemSourceInspector

GIT = shutil.which("git")
_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=_ENV, check=True)
    return done.stdout


@unittest.skipIf(GIT is None, "git is not installed")
class RealGitInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.remote = self.base / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remote)], check=True, capture_output=True, env=_ENV)
        self.source = self.base / "source"
        subprocess.run(["git", "clone", str(self.remote), str(self.source)], check=True, capture_output=True, env=_ENV)
        git(self.source, "checkout", "-b", "main")
        (self.source / "kept.txt").write_text("one\n", encoding="utf-8")
        (self.source / "also.txt").write_text("two\n", encoding="utf-8")
        (self.source / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-m", "first")
        git(self.source, "push", "-u", "origin", "main")
        self.inspector = SystemSourceInspector()

    def test_a_clone_with_everything_pushed_has_nothing_unpushed_modified_or_untracked(self) -> None:
        root = str(self.source)
        self.assertTrue(self.inspector.is_repo(root))
        self.assertEqual(self.inspector.unpushed_commits(root), ())
        self.assertEqual(self.inspector.unpushed_files(root), ())
        self.assertEqual(self.inspector.modified_tracked(root), frozenset())
        self.assertEqual(self.inspector.untracked(root), frozenset())

    def test_a_commit_that_was_never_pushed_is_listed_with_its_files(self) -> None:
        (self.source / "kept.txt").write_text("changed\n", encoding="utf-8")
        (self.source / "new.txt").write_text("new\n", encoding="utf-8")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-m", "local only")
        root = str(self.source)
        commits = self.inspector.unpushed_commits(root)
        self.assertEqual(len(commits), 1)
        self.assertTrue(commits[0].endswith("local only"))
        self.assertEqual(set(self.inspector.unpushed_files(root)), {"kept.txt", "new.txt"})
        git(self.source, "push")
        self.assertEqual(self.inspector.unpushed_commits(root), ())
        self.assertEqual(self.inspector.unpushed_files(root), ())

    def test_modified_and_untracked_files_are_told_apart_and_ignored_ones_are_not_listed(self) -> None:
        (self.source / "kept.txt").write_text("edited\n", encoding="utf-8")
        (self.source / "loose.txt").write_text("loose\n", encoding="utf-8")
        (self.source / "sub").mkdir()
        (self.source / "sub" / "deep.txt").write_text("deep\n", encoding="utf-8")
        (self.source / "build").mkdir()
        (self.source / "build" / "out.bin").write_bytes(b"\x00\x01")
        (self.source / "run.log").write_text("log\n", encoding="utf-8")
        root = str(self.source)
        self.assertEqual(self.inspector.modified_tracked(root), frozenset({"kept.txt"}))
        self.assertEqual(self.inspector.untracked(root), frozenset({"loose.txt", "sub/deep.txt"}))
        files = set(self.inspector.iter_files(root))
        self.assertIn("kept.txt", files)
        self.assertIn("sub/deep.txt", files)
        self.assertNotIn("build/out.bin", files)
        self.assertNotIn("run.log", files)
        self.assertFalse([name for name in files if name.startswith(".git/")])

    def test_a_renamed_file_is_one_row_and_its_old_name_is_not_taken_for_a_file(self) -> None:
        git(self.source, "mv", "also.txt", "renamed.txt")
        root = str(self.source)
        modified = self.inspector.modified_tracked(root)
        self.assertIn("renamed.txt", modified)
        self.assertNotIn("also.txt", self.inspector.untracked(root))

    def test_a_branch_without_an_upstream_has_no_unpushed_commits_to_report(self) -> None:
        git(self.source, "checkout", "-b", "lonely")
        (self.source / "lonely.txt").write_text("x\n", encoding="utf-8")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-m", "on a branch nobody tracks")
        root = str(self.source)
        self.assertEqual(self.inspector.unpushed_commits(root), ())
        self.assertEqual(self.inspector.unpushed_files(root), ())

    def test_a_folder_that_is_not_a_repository_is_walked_and_the_inspector_writes_nothing(self) -> None:
        plain = self.base / "plain"
        (plain / "node_modules").mkdir(parents=True)
        (plain / "node_modules" / "x.js").write_text("x", encoding="utf-8")
        (plain / "a.txt").write_text("a", encoding="utf-8")
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.base)}):  # git does not look for a repository above the throw-away folder
            self.assertFalse(self.inspector.is_repo(str(plain)))
            self.assertEqual(set(self.inspector.iter_files(str(plain))), {"a.txt"})
        self.assertEqual(self.inspector.file_size(str(plain), "a.txt"), 1)
        self.assertEqual(self.inspector.file_sha256(str(plain), "a.txt"), "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb")
        before = git(self.source, "status", "--porcelain=v1", "-uall")
        self.inspector.iter_files(str(self.source))
        list(self.inspector.iter_files(str(self.source)))
        self.assertEqual(git(self.source, "status", "--porcelain=v1", "-uall"), before)

    def test_child_repos_lists_only_the_folders_that_are_repositories(self) -> None:
        workspace = self.base / "workspace"
        (workspace / "one").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(workspace / "one")], check=True, env=_ENV)
        (workspace / "two").mkdir()
        (workspace / "file.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.inspector.child_repos(str(workspace)), [str(workspace / "one")])


if __name__ == "__main__":
    unittest.main()
