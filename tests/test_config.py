# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_config.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import (
    ConfigValidationError,
    HostProfile,
    TaskPolicy,
    ToolchainPolicy,
    load_json_document,
)


class HostProfileTests(unittest.TestCase):
    def test_a_real_valid_profile_round_trips(self):
        data = {"hostname": "hydra-umc-dev", "arch": "aarch64", "storage_root": "/srv/hydra-umc-dev", "created_from": "fresh-image"}
        profile = HostProfile.from_dict(data)
        self.assertEqual(profile.to_dict(), data)

    def test_a_relative_storage_root_is_rejected(self):
        data = {"hostname": "h", "arch": "aarch64", "storage_root": "srv/hydra-umc-dev", "created_from": "fresh-image"}
        with self.assertRaises(ConfigValidationError) as ctx:
            HostProfile.from_dict(data)
        self.assertIn("absolute path", str(ctx.exception))

    def test_an_unknown_created_from_value_is_rejected(self):
        data = {"hostname": "h", "arch": "aarch64", "storage_root": "/srv/x", "created_from": "invented-by-hand"}
        with self.assertRaises(ConfigValidationError) as ctx:
            HostProfile.from_dict(data)
        self.assertIn("created_from", str(ctx.exception))

    def test_a_missing_field_is_reported_by_name(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            HostProfile.from_dict({"hostname": "h"})
        message = str(ctx.exception)
        self.assertIn("arch", message)
        self.assertIn("storage_root", message)

    def test_a_non_object_document_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            HostProfile.from_dict([1, 2, 3])  # type: ignore[arg-type]


class ToolchainPolicyTests(unittest.TestCase):
    def test_a_real_valid_toolchain_round_trips(self):
        data = {"name": "python", "min_version": "3.11", "required": True}
        policy = ToolchainPolicy.from_dict(data)
        self.assertEqual(policy.to_dict(), data)

    def test_required_defaults_to_true_when_absent(self):
        policy = ToolchainPolicy.from_dict({"name": "node", "min_version": "20"})
        self.assertTrue(policy.required)

    def test_a_non_boolean_required_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            ToolchainPolicy.from_dict({"name": "python", "min_version": "3.11", "required": "yes"})


class TaskPolicyTests(unittest.TestCase):
    def test_allow_deploy_defaults_to_false_when_absent(self):
        # DS01's own literal acceptance criterion: "ninguna tarea tiene
        # permiso de despliegue por defecto" - a document that never
        # mentions allow_deploy at all must never grant it.
        policy = TaskPolicy.from_dict({"max_concurrent_tasks": 1})
        self.assertFalse(policy.allow_deploy)

    def test_a_non_boolean_allow_deploy_never_grants_it(self):
        # The same invariant, defended against a malformed document too -
        # a string "true" must not be treated as a real True.
        with self.assertRaises(ConfigValidationError):
            TaskPolicy.from_dict({"allow_deploy": "true", "max_concurrent_tasks": 1})

    def test_allow_deploy_true_is_only_honored_from_a_real_boolean(self):
        policy = TaskPolicy.from_dict({"allow_deploy": True, "max_concurrent_tasks": 1})
        self.assertTrue(policy.allow_deploy)

    def test_a_zero_or_negative_max_concurrent_tasks_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": 0})

    def test_a_boolean_is_not_accepted_as_max_concurrent_tasks(self):
        # bool is a subclass of int in Python - True/False must not slip
        # through an isinstance(value, int) check meant for real counts.
        with self.assertRaises(ConfigValidationError):
            TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": True})

    def test_allowed_commands_must_be_a_list_of_non_empty_strings(self):
        with self.assertRaises(ConfigValidationError):
            TaskPolicy.from_dict({"allow_deploy": False, "max_concurrent_tasks": 1, "allowed_commands": ["pytest", ""]})

    def test_the_real_example_config_file_is_valid_and_denies_deploy(self):
        # The concrete, shipped configs/task-policy.example.json - the
        # actual file a real operator would copy from, not a synthetic
        # dict standing in for it.
        example_path = Path(__file__).resolve().parent.parent / "configs" / "task-policy.example.json"
        data = load_json_document(example_path)
        policy = TaskPolicy.from_dict(data)
        self.assertFalse(policy.allow_deploy, "the shipped example must itself deny deploy by default")


class LoadJsonDocumentTests(unittest.TestCase):
    def test_a_missing_file_is_a_real_reported_reason(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            load_json_document(Path("does-not-exist.json"))
        self.assertIn("could not read", str(ctx.exception))

    def test_malformed_json_is_a_real_reported_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigValidationError) as ctx:
                load_json_document(path)
            self.assertIn("not valid JSON", str(ctx.exception))

    def test_a_json_array_is_rejected_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "array.json"
            path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
            with self.assertRaises(ConfigValidationError):
                load_json_document(path)


if __name__ == "__main__":
    unittest.main()
