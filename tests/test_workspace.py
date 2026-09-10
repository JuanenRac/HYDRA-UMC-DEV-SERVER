# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_workspace.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS04 workspace boundary - driven through a fake filesystem, never a
real private tree (the plan's "los controles se prueban con fixtures")."""
import unittest

from hydra_umc_dev_server.workspace import (
    Workspace,
    WorkspaceCollisionError,
    WorkspaceEscapeError,
    WorkspaceFs,
    allocate_workspace,
)


class FakeFs:
    """A filesystem as two dicts: which paths exist, and where a symlink
    really points. `make_dir` records the creation."""

    def __init__(self, existing=(), links=None):
        self.existing = set(existing)
        self.links = dict(links or {})
        self.made: list[str] = []

    def exists(self, path: str) -> bool:
        return path in self.existing

    def make_dir(self, path: str) -> None:
        if path in self.existing:
            raise FileExistsError(path)
        self.existing.add(path)
        self.made.append(path)

    def realpath(self, path: str) -> str:
        # Resolve the longest known symlink prefix.
        for link, target in self.links.items():
            if path == link or path.startswith(link + "/"):
                return target + path[len(link):]
        return path


class WorkspaceResolveTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(task_id="t1", root="/srv/dev/workspaces/t1")

    def test_a_plain_relative_path_resolves_inside_the_workspace(self):
        self.assertEqual(self.ws.resolve("src/app.py"), "/srv/dev/workspaces/t1/src/app.py")

    def test_a_dotdot_that_climbs_out_is_refused(self):
        with self.assertRaises(WorkspaceEscapeError):
            self.ws.resolve("../t2/secret")
        with self.assertRaises(WorkspaceEscapeError):
            self.ws.resolve("a/b/../../../etc/passwd")

    def test_a_dotdot_that_stays_inside_is_fine(self):
        self.assertEqual(self.ws.resolve("a/b/../c"), "/srv/dev/workspaces/t1/a/c")

    def test_an_absolute_path_is_refused(self):
        with self.assertRaises(WorkspaceEscapeError):
            self.ws.resolve("/etc/passwd")

    def test_a_symlink_pointing_outside_the_workspace_is_refused(self):
        fs = FakeFs(
            existing=["/srv/dev/workspaces/t1"],
            links={"/srv/dev/workspaces/t1/evil": "/home/pi/.ssh"},
        )
        with self.assertRaises(WorkspaceEscapeError):
            self.ws.resolve_with("evil/id_ed25519", fs)

    def test_a_symlink_pointing_back_inside_the_workspace_is_allowed(self):
        fs = FakeFs(
            existing=["/srv/dev/workspaces/t1"],
            links={"/srv/dev/workspaces/t1/link": "/srv/dev/workspaces/t1/real"},
        )
        self.assertEqual(
            self.ws.resolve_with("link/file.txt", fs),
            "/srv/dev/workspaces/t1/real/file.txt",
        )


class AllocateWorkspaceTests(unittest.TestCase):
    def test_the_fake_fs_satisfies_the_protocol(self):
        self.assertIsInstance(FakeFs(), WorkspaceFs)

    def test_a_fresh_task_id_gets_its_own_directory(self):
        fs = FakeFs(existing=["/srv/dev/workspaces"])
        ws = allocate_workspace("/srv/dev/workspaces", "build-42", fs)
        self.assertEqual(ws.root, "/srv/dev/workspaces/build-42")
        self.assertIn("/srv/dev/workspaces/build-42", fs.made)

    def test_two_tasks_never_collide_an_existing_workspace_is_refused(self):
        fs = FakeFs(existing=["/srv/dev/workspaces", "/srv/dev/workspaces/build-42"])
        with self.assertRaises(WorkspaceCollisionError):
            allocate_workspace("/srv/dev/workspaces", "build-42", fs)

    def test_an_unsafe_task_id_is_refused(self):
        fs = FakeFs(existing=["/srv/dev/workspaces"])
        for bad in ("../escape", "a/b", "", ".hidden", "x" * 200):
            with self.assertRaises(Exception):
                allocate_workspace("/srv/dev/workspaces", bad, fs)

    def test_a_non_absolute_base_is_refused(self):
        with self.assertRaises(Exception):
            allocate_workspace("relative/workspaces", "t1", FakeFs())


if __name__ == "__main__":
    unittest.main()
