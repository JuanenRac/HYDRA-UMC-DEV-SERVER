# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_bridge_bench_scenarios.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The CNC scenarios of the bridge bench that only run inside the container bench, run here against a stand-in rig and a stand-in operator: what each
scenario asks of the bridge, what it checks in the answer and in the bytes the emulator received, and that it fails with a clear message when the
bridge misbehaves. The coverage job lists these scenarios as not run (evidence: simulator; no broker, no container, no device)."""
import json
import unittest
from unittest import mock

from hydra_umc_dev_server import bridge_bench

PREFIX = "hydra-umc/cnc/"


class FakeOperator:
    def __init__(self, messages):
        self.messages = list(messages)
        self.published = []
        self.closed = False

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    def next_message(self, wait):
        return self.messages.pop(0) if self.messages else None

    def close(self):
        self.closed = True


class FakeRig:
    """What the scenarios use of the rig: the topic prefix, the reset, the control calls and the bytes the emulator received."""

    def __init__(self, written=(), operator=None):
        self.prefix = PREFIX
        self.written = list(written)
        self.resets = 0
        self.controls = []
        self.operator = operator or FakeOperator([])

    def reset(self):
        self.resets += 1

    def control(self, method, path):
        self.controls.append((method, path))

    def log(self):
        return list(self.written)


class AskScript:
    """Replaces `_ask`: answers the verbs in order and records what was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, rig, run_id, verb, payload, answer=None):
        self.asked.append((verb, payload, answer))
        return self.answers.pop(0)


class UnknownVerbTests(unittest.TestCase):
    def run_scenario(self, messages):
        operator = FakeOperator(messages)
        rig = FakeRig(operator=operator)
        with mock.patch.object(bridge_bench, "_listen", return_value=operator):
            text = bridge_bench.scenario_unknown_verb(rig, "run-1")
        return text, operator

    def test_silence_is_the_pass_and_the_operator_is_closed(self):
        text, operator = self.run_scenario([])
        self.assertIn("ignored", text)
        self.assertEqual(operator.published, [(PREFIX + "cmd/not_a_verb", b"{}")])
        self.assertTrue(operator.closed)

    def test_the_echo_of_the_same_topic_is_not_an_answer(self):
        text, _ = self.run_scenario([(PREFIX + "cmd/not_a_verb", b"{}")])
        self.assertIn("ignored", text)

    def test_any_other_topic_is_an_answer_and_fails_the_scenario(self):
        with self.assertRaises(AssertionError) as caught:
            self.run_scenario([(PREFIX + "cmd/not_a_verb/result", b"{}")])
        self.assertIn("was answered", str(caught.exception))


class FeedHoldTests(unittest.TestCase):
    def test_the_real_time_byte_must_reach_the_controller(self):
        ask = AskScript({"executed": True})
        rig = FakeRig(written=["G0 X1\n", "!"])
        with mock.patch.object(bridge_bench, "_ask", ask):
            text = bridge_bench.scenario_cnc_feed_hold_reaches_the_controller(rig, "run-1")
        self.assertIn("feed hold", text)
        self.assertEqual(ask.asked, [("feed_hold", b"", None)])
        self.assertEqual(rig.resets, 1)

    def test_a_feed_hold_that_was_not_executed_fails_first(self):
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": False})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_feed_hold_reaches_the_controller(FakeRig(written=["!"]), "run-1")
        self.assertIn("not executed", str(caught.exception))

    def test_a_missing_byte_fails_with_what_the_emulator_got(self):
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": True})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_feed_hold_reaches_the_controller(FakeRig(written=["?"]), "run-1")
        self.assertIn("did not receive the feed hold byte", str(caught.exception))
        self.assertIn("'?'", str(caught.exception))


class ResumeTests(unittest.TestCase):
    def test_refused_when_idle_and_sent_only_from_a_hold(self):
        ask = AskScript({"executed": False}, {"executed": True})
        rig = FakeRig()

        def log():
            # the cycle start byte appears only after the hold was put on the emulator
            return ["~"] if ("POST", "/_bench/hold") in rig.controls else []

        rig.log = log
        with mock.patch.object(bridge_bench, "_ask", ask):
            text = bridge_bench.scenario_cnc_resume_needs_a_hold(rig, "run-1")
        self.assertIn("refused while the machine is idle", text)
        self.assertEqual([a[0] for a in ask.asked], ["cycle_start_resume", "cycle_start_resume"])
        self.assertEqual(rig.controls, [("POST", "/_bench/hold")])
        self.assertEqual(rig.resets, 2)

    def test_a_resume_that_runs_on_an_idle_machine_fails(self):
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": True})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_resume_needs_a_hold(FakeRig(), "run-1")
        self.assertIn("idle machine was executed", str(caught.exception))

    def test_the_byte_on_an_idle_machine_fails(self):
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": False})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_resume_needs_a_hold(FakeRig(written=["~"]), "run-1")
        self.assertIn("reached the controller of an idle machine", str(caught.exception))

    def test_a_resume_refused_in_a_hold_fails(self):
        rig = FakeRig()
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": False}, {"executed": False})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_resume_needs_a_hold(rig, "run-1")
        self.assertIn("in hold was refused", str(caught.exception))

    def test_no_byte_after_the_hold_fails(self):
        with mock.patch.object(bridge_bench, "_ask", AskScript({"executed": False}, {"executed": True})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_resume_needs_a_hold(FakeRig(), "run-1")
        self.assertIn("cycle start byte did not reach", str(caught.exception))


class AlarmTests(unittest.TestCase):
    def test_an_alarm_is_published_as_anything_but_idle_and_the_rig_is_reset(self):
        ask = AskScript({"machine_state": "ALARM"})
        rig = FakeRig()
        with mock.patch.object(bridge_bench, "_ask", ask):
            text = bridge_bench.scenario_cnc_alarm_is_not_idle(rig, "run-1")
        self.assertIn("ALARM", text)
        self.assertEqual(ask.asked, [("status", b"", "state")])
        self.assertEqual(rig.controls, [("POST", "/_bench/alarm")])
        self.assertEqual(rig.resets, 2)

    def test_idle_in_alarm_fails_and_the_rig_is_still_reset(self):
        rig = FakeRig()
        with mock.patch.object(bridge_bench, "_ask", AskScript({"machine_state": "IDLE"})):
            with self.assertRaises(AssertionError) as caught:
                bridge_bench.scenario_cnc_alarm_is_not_idle(rig, "run-1")
        self.assertIn("published as 'IDLE'", str(caught.exception))
        self.assertEqual(rig.resets, 2)

    def test_the_state_json_of_the_answer_is_what_is_read(self):
        # the real `_ask` decodes the JSON of the answer; the scenario reads `machine_state` from it
        operator = FakeOperator([(PREFIX + "state", json.dumps({"machine_state": "HOLD"}).encode())])
        rig = FakeRig(operator=operator)
        rig.ops = lambda run_id: operator
        with mock.patch.object(bridge_bench, "_listen", return_value=operator):
            text = bridge_bench.scenario_cnc_alarm_is_not_idle(rig, "run-1")
        self.assertIn("HOLD", text)


if __name__ == "__main__":
    unittest.main()
