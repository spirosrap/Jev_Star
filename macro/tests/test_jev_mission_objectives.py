import json
import tempfile
import unittest
from pathlib import Path

from sc2_rl_agent.starcraftenv_test.env.bot.mission_objectives import MissionObjectives

BANK = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
    <Section name="key">
        <Key name="1"><Value string="AAA"/></Key>
        <Key name="2"><Value string="BBB"/></Key>
    </Section>
    <Section name="state">
        <Key name="1"><Value int="2"/></Key>
        <Key name="2"><Value int="{secondary}"/></Key>
    </Section>
    <Section name="primary">
        <Key name="1"><Value int="1"/></Key>
        <Key name="2"><Value int="0"/></Key>
    </Section>
</Bank>
"""


class MissionObjectivesTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        mission = {"title": "The Outlaws", "map": "TRaynor02", "objectives": [
            {"key": "AAA", "name": "Destroy the Dominion Base", "description": "", "primary": True},
            {"key": "BBB", "name": "Rescue the Rebels", "description": "", "primary": False}]}
        (self.folder / "mission.json").write_text(json.dumps(mission))
        self.mission = MissionObjectives(self.folder / "mission.json", self.folder)

    def write_bank(self, secondary):
        (self.folder / "JevObjectives.SC2Bank").write_text(BANK.format(secondary=secondary))

    def test_primary_alone_is_not_a_complete_mission(self):
        self.write_bank(secondary=1)
        changes = self.mission.refresh(10)
        self.assertEqual(changes["AAA"], (None, "completed"))
        outcome = self.mission.outcome()
        self.assertTrue(outcome["primary_objectives_completed"])
        self.assertFalse(outcome["all_objectives_completed"])

    def test_every_objective_completed_is_a_complete_mission(self):
        self.write_bank(secondary=2)
        self.mission.refresh(10)
        self.assertTrue(self.mission.outcome()["all_objectives_completed"])

    def test_objectives_not_yet_reported_are_not_shown_yet(self):
        self.mission.clear_bank()
        self.mission.refresh(10)
        self.assertEqual({o["state"] for o in self.mission.snapshot()}, {"not shown yet"})
        self.assertFalse(self.mission.outcome()["all_objectives_completed"])


    def test_difficulty_chosen_and_applied_are_reported(self):
        mission = MissionObjectives(self.folder / "mission.json", self.folder, "Hard")
        (self.folder / "JevObjectives.SC2Bank").write_text(BANK.format(secondary=1).replace(
            '</Bank>', '<Section name="clock"><Key name="difficulty"><Value int="3"/></Key></Section></Bank>'))
        mission.refresh(10)
        outcome = mission.outcome()
        self.assertEqual((outcome["difficulty"], outcome["applied_difficulty"]), ("Hard", "Hard"))
        self.assertIn("Hard difficulty", mission.planner_text())


if __name__ == "__main__":
    unittest.main()
