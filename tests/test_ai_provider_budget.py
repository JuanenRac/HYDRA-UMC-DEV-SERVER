# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_ai_provider_budget.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The budget holds for one call too, whatever a provider reports or raises."""
import threading
import unittest

from hydra_umc_dev_server.ai_provider import (
    OUTCOME_BUDGET_EXHAUSTED,
    OUTCOME_REJECTED,
    OUTCOME_SUGGESTED,
    OUTCOME_TIMED_OUT,
    ProviderConfig,
    ProviderUsage,
    RawCompletion,
    run_provider_step,
)


def config(**budget):
    return ProviderConfig.from_dict({"kind": "fake", "timeout_seconds": 1, "budget": {"max_calls": 4, "max_tokens": 1000, "max_cost_usd": 1.0, **budget}})


class Fixed:
    def __init__(self, tokens, cost, text="a diagnosis"):
        self.completion = RawCompletion(text=text, tokens=tokens, cost_usd=cost)

    def complete(self, prompt, *, timeout_seconds):
        return self.completion


class AwareProvider:
    """Asks to be told what is left."""

    def __init__(self):
        self.seen = None

    def complete(self, prompt, *, timeout_seconds, max_tokens, max_cost_usd):
        self.seen = (max_tokens, max_cost_usd)
        return RawCompletion(text="fine", tokens=10, cost_usd=0.001)


class BudgetPerCallTests(unittest.TestCase):
    def test_a_provider_that_takes_limits_is_told_what_is_left(self):
        provider = AwareProvider()
        result = run_provider_step(config(), provider, "p", usage_so_far=ProviderUsage(calls=1, tokens=400, cost_usd=0.25))
        self.assertEqual(provider.seen, (600, 0.75))
        self.assertEqual(result.outcome, OUTCOME_SUGGESTED)

    def test_a_provider_that_does_not_take_limits_is_still_called(self):
        self.assertEqual(run_provider_step(config(), Fixed(10, 0.001), "p").outcome, OUTCOME_SUGGESTED)

    def test_one_call_that_goes_past_the_tokens_left_is_not_a_suggestion(self):
        result = run_provider_step(config(), Fixed(5000, 0.01), "p", usage_so_far=ProviderUsage(calls=1, tokens=900))
        self.assertEqual(result.outcome, OUTCOME_BUDGET_EXHAUSTED)
        self.assertEqual(result.suggested_text, "")
        self.assertEqual(result.usage.tokens, 5900)  # what it burned is counted
        self.assertIn("more than", result.reason or "")

    def test_one_call_that_goes_past_the_cost_left_is_not_a_suggestion(self):
        result = run_provider_step(config(), Fixed(10, 3.0), "p")
        self.assertEqual(result.outcome, OUTCOME_BUDGET_EXHAUSTED)
        self.assertEqual(result.suggested_text, "")

    def test_exactly_what_is_left_is_allowed(self):
        self.assertEqual(run_provider_step(config(), Fixed(1000, 1.0), "p").outcome, OUTCOME_SUGGESTED)

    def test_negative_or_odd_usage_is_rejected_not_a_refund(self):
        for tokens, cost in ((-5, 0.0), (10, -0.1), (float("nan"), 0.0), (10, float("inf")), (True, 0.0), ("10", 0.0)):
            with self.subTest(tokens=tokens, cost=cost):
                result = run_provider_step(config(), Fixed(tokens, cost), "p")
                self.assertEqual(result.outcome, OUTCOME_REJECTED)
                self.assertEqual(result.usage, ProviderUsage())


class ProviderFailureTests(unittest.TestCase):
    def test_any_exception_of_a_real_sdk_is_a_rejected_outcome(self):
        for error in (OSError("network down"), ValueError("bad request"), RuntimeError("boom"), KeyError("k")):
            class Failing:
                def complete(self, prompt, *, timeout_seconds, failure=error):
                    raise failure

            with self.subTest(error=type(error).__name__):
                result = run_provider_step(config(), Failing(), "p")
                self.assertEqual(result.outcome, OUTCOME_REJECTED)
                self.assertIn(type(error).__name__, result.reason or "")
                self.assertTrue(result.grants_no_permissions and result.triggers_no_deploy)

    def test_a_provider_that_never_comes_back_is_timed_out_by_the_step_itself(self):
        release = threading.Event()

        class Hanging:
            def complete(self, prompt, *, timeout_seconds):
                release.wait(10)
                return RawCompletion(text="late", tokens=1, cost_usd=0.0)

        try:
            result = run_provider_step(config(), Hanging(), "p")
        finally:
            release.set()
        self.assertEqual(result.outcome, OUTCOME_TIMED_OUT)
        self.assertEqual(result.suggested_text, "")


if __name__ == "__main__":
    unittest.main()
