"""Campaign mission objectives: their text from the map, and their live state from the JevObjectives bank.

scripts/campaign/campaign.py prepares a mission map with a small reporter trigger that saves every objective's
state to the JevObjectives bank once per game second; this module reads that bank. A mission counts as complete
only when every objective, primary and secondary, has been completed.
"""

import json
import xml.etree.ElementTree as ElementTree
from pathlib import Path

# ObjectiveGetState values (natives.galaxy).
STATES = {-1: "unknown", 0: "hidden", 1: "active", 2: "completed", 3: "failed"}
BANK_NAME = "JevObjectives.SC2Bank"
DIFFICULTIES = {"Casual": 1, "Normal": 2, "Hard": 3, "Brutal": 4}  # PlayerDifficulty values the missions read
REFRESH_SECONDS = 2


def read_bank(path):
    """{objective id: {"key": str, "state": int, "primary": bool}} from a JevObjectives bank file."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return {}
    return _objectives(root)


def read_applied_difficulty(path):
    """The difficulty the mission itself reports (PlayerDifficulty), or None before its first report."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    for section in root.findall("Section"):
        for key in section.findall("Key"):
            if section.get("name") == "clock" and key.get("name") == "difficulty" and key.find("Value") is not None:
                value = int(key.find("Value").get("int"))
                return next((name for name, number in DIFFICULTIES.items() if number == value), str(value))
    return None


def read_markers(path):
    """[{"id", "position", "kind"}] for the lasting pings the mission shows (e.g. a rescue site), from the bank."""
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return []
    markers = []
    for section in root.findall("Section"):
        if section.get("name") != "ping":
            continue
        for key in section.findall("Key"):
            value = key.find("Value")
            parts = (value.get("string") if value is not None else "").split()
            try:
                x, y = float(parts[0]), float(parts[1])
            except (IndexError, ValueError):
                continue
            markers.append({"id": f"mission_marker_{key.get('name')}", "position": [x, y],
                            "kind": parts[2] if len(parts) > 2 else "ping"})
    return markers


def _objectives(root):
    sections = {section.get("name"): {key.get("name"): key.find("Value") for key in section.findall("Key")}
                for section in root.findall("Section")}
    objectives = {}
    for objective_id, value in sections.get("key", {}).items():
        state = sections.get("state", {}).get(objective_id)
        primary = sections.get("primary", {}).get(objective_id)
        objectives[objective_id] = {
            "key": value.get("string") if value is not None else "",
            "state": int(state.get("int")) if state is not None else -1,
            "primary": primary is not None and primary.get("int") == "1",
        }
    return objectives


class MissionObjectives:
    def __init__(self, mission_path, bank_directory, difficulty=None):
        self.mission = json.loads(Path(mission_path).read_text(encoding="utf-8"))
        self.bank_path = Path(bank_directory) / BANK_NAME
        self.by_key = {o["key"]: o for o in self.mission.get("objectives", [])}
        self.states = {}  # key -> state name
        self.difficulty = difficulty  # chosen; each difficulty is its own prepared map
        self.applied_difficulty = None  # what the mission reports it is running on
        self.markers = []  # lasting minimap pings of the mission, as navigation targets
        self._last_refresh = -REFRESH_SECONDS

    def clear_bank(self):
        """A bank left by an earlier game must not look like this game's progress."""
        try:
            self.bank_path.unlink()
        except FileNotFoundError:
            pass

    def refresh(self, game_time, force=False):
        """Read the bank at most every REFRESH_SECONDS; returns {key: (old, new)} for objectives that changed."""
        if not force and game_time - self._last_refresh < REFRESH_SECONDS:
            return {}
        self._last_refresh = game_time
        changes = {}
        self.applied_difficulty = read_applied_difficulty(self.bank_path) or self.applied_difficulty
        self.markers = read_markers(self.bank_path)
        for entry in read_bank(self.bank_path).values():
            new = STATES.get(entry["state"], "unknown")
            old = self.states.get(entry["key"])
            if new != old:
                changes[entry["key"]] = (old, new)
                self.states[entry["key"]] = new
        return changes

    def snapshot(self):
        """What the models read: every known objective with its state (not yet shown ones are 'not shown yet')."""
        return [{"name": o["name"], "description": o["description"],
                 "type": "primary" if o["primary"] else "secondary",
                 "state": self.states.get(o["key"], "not shown yet")}
                for o in self.mission.get("objectives", [])]

    def outcome(self):
        objectives = self.snapshot()
        return {
            "mission": self.mission.get("title"), "map": self.mission.get("map"),
            "difficulty": self.difficulty, "applied_difficulty": self.applied_difficulty,
            "objectives": objectives,
            "all_objectives_completed": bool(objectives) and all(o["state"] == "completed" for o in objectives),
            "primary_objectives_completed": all(o["state"] == "completed" for o in objectives if o["type"] == "primary"),
        }

    def planner_text(self):
        lines = [f"This game is the campaign mission \"{self.mission.get('title')}\" on "
                 f"{self.difficulty or 'Normal'} difficulty. It is won only when every "
                 "mission objective below is completed, primary and secondary; destroying the enemy alone is not "
                 "enough. The mission's own script decides victory and may end the game when the primary "
                 "objectives are done, so complete the secondary objectives before or alongside them. Current "
                 "objective states are in state.mission_objectives. The pings the mission puts on the minimap "
                 "(where to rescue units, reach or destroy something) are navigation.targets with ids "
                 "mission_marker_N; to get there, choose army_posture attack with that army_target_id, and "
                 "return home when the base needs defending. Objectives:"]
        for o in self.mission.get("objectives", []):
            lines.append(f"- {'Primary' if o['primary'] else 'Secondary'}: {o['name']} — {o['description']}")
        return "\n".join(lines)
