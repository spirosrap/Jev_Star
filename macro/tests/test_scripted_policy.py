import asyncio
import unittest

from sc2_rl_agent.starcraftenv_test.agent.scripted_policy import ScriptedClient, pick


def state(seconds=0, workers=12, supply_used=12, supply_cap=15, needs_supply=False, building=None, unit=None,
          planning=None, research=None):
    return {"game_loop": int(seconds * 22.4),
            "resource": {"worker_supply": workers, "supply_used": supply_used, "supply_cap": supply_cap,
                         "needs_supply": needs_supply, "mineral": 100},
            "building": {"COMMANDCENTER": 1, **(building or {})}, "unit": unit or {}, "planning": planning or {},
            "research": research or {}, "supply_forecast": {"needs_supply": needs_supply}}


CHOICES = {"0": "TRAIN SCV", "1": "TRAIN MARINE", "5": "TRAIN HELLIONTANK", "7": "TRAIN SIEGETANK",
           "16": "BUILD SUPPLYDEPOT", "18": "BUILD COMMANDCENTER", "19": "BUILD BARRACKS", "66": "MULTI-ATTACK",
           "69": "EMPTY ACTION"}


class ScriptedPolicyTests(unittest.TestCase):
    def test_supply_first_then_workers(self):
        self.assertEqual(pick(state(needs_supply=True), CHOICES), "16")
        self.assertEqual(pick(state(), CHOICES), "0")

    def test_expands_on_schedule_and_builds_barracks(self):
        self.assertEqual(pick(state(seconds=80, workers=20), CHOICES), "18")  # Second base due at 75 s.
        full = state(seconds=80, workers=40, building={"COMMANDCENTER": 2})
        self.assertEqual(pick(full, CHOICES), "18")  # Workers for two bases already: a third.
        rax_due = state(seconds=70, workers=20, planning={"COMMANDCENTER": 1})
        self.assertEqual(pick(rax_due, {k: v for k, v in CHOICES.items() if k != "0"}), "19")

    def test_tanks_before_infantry_and_never_hellbats_or_attack_orders(self):
        army = {"5": "TRAIN HELLIONTANK", "7": "TRAIN SIEGETANK", "1": "TRAIN MARINE", "66": "MULTI-ATTACK",
                "69": "EMPTY ACTION"}
        self.assertEqual(pick(state(seconds=600, workers=76, building={"COMMANDCENTER": 4}), army), "7")
        no_tank = {k: v for k, v in army.items() if k != "7"}
        self.assertEqual(pick(state(seconds=600, workers=76, building={"COMMANDCENTER": 4}), no_tank), "1")
        idle = {"5": "TRAIN HELLIONTANK", "66": "MULTI-ATTACK", "69": "EMPTY ACTION"}
        self.assertEqual(pick(state(seconds=600, workers=76, building={"COMMANDCENTER": 4}), idle), "69")

    def test_marines_stop_at_forty(self):
        army = {"1": "TRAIN MARINE", "69": "EMPTY ACTION"}
        self.assertEqual(pick(state(seconds=600, workers=76, building={"COMMANDCENTER": 4},
                                    unit={"MARINE": 40}), army), "69")

    def test_client_answers_in_the_jev_shape(self):
        client = ScriptedClient()
        response = asyncio.run(client.choose(client.payload(state(needs_supply=True), CHOICES)))
        self.assertEqual(response["answer"]["choice"], "16")
        self.assertEqual(sum(response["answer"]["probabilities"].values()), 1)
        self.assertEqual(response["usage"], {})


if __name__ == "__main__":
    unittest.main()
