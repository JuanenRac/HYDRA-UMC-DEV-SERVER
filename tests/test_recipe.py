# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_recipe.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, TaskPolicy, load_json_document
from hydra_umc_dev_server.recipe import TaskRecipe
from hydra_umc_dev_server.workspace import Workspace, WorkspaceEscapeError

_EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "task-recipe.example.json"


def _recipe(**overrides) -> dict:
    base = {
        "task_id": "example-lint-0001",
        "repo": "HYDRA-UMC-DEV-SERVER",
        "revision": "0.0.4",
        "command": ["pytest", "-q"],
        "timeout_seconds": 300,
        "input_paths": ["tests", "pyproject.toml"],
    }
    base.update(overrides)
    return base


class TaskRecipeFromDictTests(unittest.TestCase):
    def test_the_real_shipped_example_round_trips(self):
        data = load_json_document(_EXAMPLE)
        self.assertEqual(TaskRecipe.from_dict(data).to_dict(), data)

    def test_a_bare_branch_name_is_not_a_pinned_revision(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            TaskRecipe.from_dict(_recipe(revision="main"))
        self.assertIn("pinned revision", str(ctx.exception))

    def test_a_commit_hash_and_a_tag_are_both_accepted_revisions(self):
        self.assertEqual(TaskRecipe.from_dict(_recipe(revision="a1b2c3d")).revision, "a1b2c3d")
        self.assertEqual(TaskRecipe.from_dict(_recipe(revision="v1.2.3")).revision, "v1.2.3")

    def test_an_empty_command_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            TaskRecipe.from_dict(_recipe(command=[]))

    def test_a_timeout_over_the_maximum_is_rejected(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            TaskRecipe.from_dict(_recipe(timeout_seconds=99999))
        self.assertIn("maximum", str(ctx.exception))

    def test_a_zero_timeout_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            TaskRecipe.from_dict(_recipe(timeout_seconds=0))

    def test_an_unsafe_task_id_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            TaskRecipe.from_dict(_recipe(task_id="../evil"))

    def test_errors_accumulate_into_one_message(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            TaskRecipe.from_dict({"task_id": "ok", "command": [], "revision": "main"})
        message = str(ctx.exception)
        self.assertIn("command", message)
        self.assertIn("revision", message)
        self.assertIn("repo", message)


class ValidateAgainstPolicyTests(unittest.TestCase):
    def _policy(self, allowed):
        return TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": list(allowed)})

    def test_an_allowed_command_passes(self):
        recipe = TaskRecipe.from_dict(_recipe(command=["pytest", "-q"]))
        recipe.validate_against(self._policy(["pytest", "build.sh"]))  # no raise

    def test_a_command_not_in_the_allowlist_is_refused(self):
        recipe = TaskRecipe.from_dict(_recipe(command=["rm", "-rf", "/"]))
        with self.assertRaises(ConfigValidationError) as ctx:
            recipe.validate_against(self._policy(["pytest"]))
        self.assertIn("allowed_commands", str(ctx.exception))

    def test_a_policy_that_allows_no_command_refuses_every_recipe(self):
        recipe = TaskRecipe.from_dict(_recipe())
        with self.assertRaises(ConfigValidationError):
            recipe.validate_against(self._policy([]))


class ResolvedInputPathsTests(unittest.TestCase):
    def test_declared_paths_that_stay_inside_the_workspace_resolve(self):
        recipe = TaskRecipe.from_dict(_recipe(input_paths=["tests", "src/pkg"]))
        ws = Workspace(task_id="t1", root="/srv/dev/workspaces/t1")
        self.assertEqual(
            recipe.resolved_input_paths(ws),
            ("/srv/dev/workspaces/t1/tests", "/srv/dev/workspaces/t1/src/pkg"),
        )

    def test_a_declared_path_that_escapes_the_workspace_is_refused(self):
        recipe = TaskRecipe.from_dict(_recipe(input_paths=["../../.ssh/id_ed25519"]))
        ws = Workspace(task_id="t1", root="/srv/dev/workspaces/t1")
        with self.assertRaises(WorkspaceEscapeError):
            recipe.resolved_input_paths(ws)


if __name__ == "__main__":
    unittest.main()
