# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_ai_provider.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS06 - the safety contract around a deterministic fake AI provider.
Nothing here reaches a real provider or acts on a suggestion."""
import json
import unittest
from pathlib import Path

from hydra_umc_dev_server.ai_provider import (
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_REJECTED,
    OUTCOME_SUGGESTED,
    OUTCOME_TIMED_OUT,
    AIProvider,
    FakeProvider,
    ProviderBudget,
    ProviderConfig,
    ProviderUsage,
    RawCompletion,
    run_provider_step,
)
from hydra_umc_dev_server.config import ConfigValidationError, load_json_document

_EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "ai-provider.example.json"


def _config(**overrides) -> ProviderConfig:
    data = {"kind": "fake", "timeout_seconds": 30, "budget": {"max_calls": 4, "max_tokens": 20000, "max_cost_usd": 1.0}}
    data.update(overrides)
    return ProviderConfig.from_dict(data)


class SpyProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, prompt: str, *, timeout_seconds: int) -> RawCompletion:
        self.calls += 1
        return RawCompletion(text="ok", tokens=10, cost_usd=0.001)


class OkPathTests(unittest.TestCase):
    def test_the_ok_scenario_is_deterministic_and_inert(self):
        cfg = _config()
        a = run_provider_step(cfg, FakeProvider("ok"), "why did the unit fail?")
        b = run_provider_step(cfg, FakeProvider("ok"), "why did the unit fail?")
        c = run_provider_step(cfg, FakeProvider("ok"), "a different prompt")
        self.assertEqual(a.outcome, OUTCOME_SUGGESTED)
        self.assertEqual(a.suggested_text, b.suggested_text)
        self.assertNotEqual(a.suggested_text, c.suggested_text)
        self.assertFalse(a.injection_flagged)
        self.assertTrue(a.grants_no_permissions)
        self.assertTrue(a.triggers_no_deploy)


class AdverseOutcomeTests(unittest.TestCase):
    def test_a_provider_timeout_is_a_bounded_outcome(self):
        r = run_provider_step(_config(), FakeProvider("timeout"), "p")
        self.assertEqual(r.outcome, OUTCOME_TIMED_OUT)
        self.assertIn("30s", r.reason or "")
        self.assertEqual(r.suggested_text, "")

    def test_malformed_output_is_rejected(self):
        r = run_provider_step(_config(), FakeProvider("malformed"), "p")
        self.assertEqual(r.outcome, OUTCOME_REJECTED)

    def test_quota_exhaustion_is_budget_exhausted(self):
        r = run_provider_step(_config(), FakeProvider("quota"), "p")
        self.assertEqual(r.outcome, OUTCOME_BUDGET_EXHAUSTED)

    def test_an_unusable_empty_completion_is_rejected(self):
        class Blank:
            def complete(self, prompt, *, timeout_seconds):
                return RawCompletion(text="   ", tokens=1, cost_usd=0.0)

        self.assertEqual(run_provider_step(_config(), Blank(), "p").outcome, OUTCOME_REJECTED)


class InjectionTests(unittest.TestCase):
    def test_an_instruction_like_suggestion_is_flagged_but_never_acted_on(self):
        r = run_provider_step(_config(), FakeProvider("injection"), "p")
        self.assertEqual(r.outcome, OUTCOME_SUGGESTED)  # still just a suggestion
        self.assertTrue(r.injection_flagged)
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", r.suggested_text)  # copied verbatim, as data
        self.assertTrue(r.grants_no_permissions)
        self.assertTrue(r.triggers_no_deploy)

    def test_every_outcome_still_grants_nothing_and_deploys_nothing(self):
        for scenario in ("ok", "timeout", "malformed", "quota", "injection"):
            r = run_provider_step(_config(), FakeProvider(scenario), "p")
            self.assertTrue(r.grants_no_permissions, scenario)
            self.assertTrue(r.triggers_no_deploy, scenario)
        self.assertFalse(hasattr(run_provider_step(_config(), FakeProvider("ok"), "p"), "execute"))


class BudgetTests(unittest.TestCase):
    def test_a_budget_already_reached_stops_before_calling_the_provider(self):
        spy = SpyProvider()
        used_up = ProviderUsage(calls=4, tokens=100, cost_usd=0.01)
        r = run_provider_step(_config(), spy, "p", usage_so_far=used_up)
        self.assertEqual(r.outcome, OUTCOME_BUDGET_EXHAUSTED)
        self.assertIn("call budget", r.reason or "")
        self.assertEqual(spy.calls, 0)

    def test_the_token_budget_also_stops_the_step(self):
        r = run_provider_step(_config(budget={"max_calls": 99, "max_tokens": 50, "max_cost_usd": 9.0}),
                              SpyProvider(), "p", usage_so_far=ProviderUsage(tokens=50))
        self.assertEqual(r.outcome, OUTCOME_BUDGET_EXHAUSTED)

    def test_usage_accumulates_across_steps(self):
        cfg = _config()
        first = run_provider_step(cfg, FakeProvider("ok"), "p")
        second = run_provider_step(cfg, FakeProvider("ok"), "p2", usage_so_far=first.usage)
        self.assertEqual(second.usage.calls, 2)
        self.assertGreater(second.usage.tokens, first.usage.tokens)


class ConfigTests(unittest.TestCase):
    def test_the_shipped_example_is_valid_fake_only(self):
        cfg = ProviderConfig.from_dict(load_json_document(_EXAMPLE))
        self.assertEqual(cfg.kind, "fake")
        self.assertEqual(cfg.to_dict(), load_json_document(_EXAMPLE))

    def test_a_non_fake_kind_is_refused_as_a_user_decision(self):
        with self.assertRaises(ConfigValidationError) as ctx:
            ProviderConfig.from_dict({"kind": "anthropic", "timeout_seconds": 30})
        self.assertIn("user decision", str(ctx.exception))

    def test_a_bad_budget_is_rejected(self):
        with self.assertRaises(ConfigValidationError):
            ProviderConfig.from_dict({"kind": "fake", "timeout_seconds": 30, "budget": {"max_tokens": -1}})

    def test_the_fake_provider_and_spy_satisfy_the_protocol(self):
        self.assertIsInstance(FakeProvider(), AIProvider)
        self.assertIsInstance(SpyProvider(), AIProvider)

    def test_result_to_dict_is_json_shaped(self):
        payload = run_provider_step(_config(), FakeProvider("ok"), "p").to_dict()
        json.dumps(payload)
        self.assertEqual(set(payload) >= {"outcome", "usage", "grants_no_permissions", "triggers_no_deploy"}, True)


if __name__ == "__main__":
    unittest.main()
