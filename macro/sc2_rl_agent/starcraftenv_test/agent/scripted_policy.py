"""A scripted stand-in for Jev: the same interface as JevClient, choosing each action by fixed rules.

Everything the bot already does by itself (Tanks, upgrades, pushes, Ghosts, the air response, SCVs fleeing
Banelings, building placement) is unchanged; this only replaces the choices Jev made, from the lessons of the
CheatMoney games: SCVs to the cap without pause, supply before it blocks, expansions on a schedule, Barracks up to
12 (the wins had 11-12 by 15:00, T126 lost with 5), Tanks before infantry, no Hellbats, and no attack orders of its
own (the bot's pushes attack). It needs no API key and answers at once, so games can run faster than real time.
"""
import re

# Game seconds by which the bot wants this many bases (then more whenever it has the workers for them).
EXPANSIONS = ((0, 1), (75, 2), (390, 3), (570, 4), (720, 5))
WORKERS_PER_BASE = 20
MAX_WORKERS = 76
# Barracks wanted by game time; production beyond this comes from the bank routine.
BARRACKS_PLAN = ((60, 1), (240, 2), (330, 3), (480, 5), (600, 8), (720, 12))
REACTOR_BARRACKS = 2  # the rest get Tech Labs, for Marauders and Ghosts
FIRST_FACTORY = 150
FIRST_STARPORT = 480
MEDIVACS = 6
MARINE_CAP = 40
REFINERIES_PER_BASE = 2
FIRST_REFINERY = 45
ORBITALS = 3
RESEARCH = ("STIMPACK", "SHIELDWALL", "PUNISHERGRENADES")


def _planned(plan, seconds):
    wanted = 0
    for at, count in plan:
        if seconds >= at:
            wanted = count
    return wanted


class ScriptedClient:
    """Stands in for JevClient: payload() packs state and choices, choose() answers by rule."""

    model = "scripted"

    def __init__(self, *args, **kwargs):
        self.instructions = self.plan_instructions = ""

    def payload(self, state: dict, choices: dict) -> dict:
        return {"model": self.model, "state": state, "choices": {str(k): v for k, v in choices.items()}}

    async def choose(self, payload: dict) -> dict:
        choice = pick(payload["state"], payload["choices"])
        probabilities = {key: float(key == choice) for key in payload["choices"]}
        return {"model": self.model, "usage": {},
                "answer": {"type": "choice", "choice": choice, "confidence": 1.0, "probabilities": probabilities}}

    async def close(self):
        pass


def pick(state: dict, choices: dict) -> str:
    """The id (as a string) of the first wanted action that is legal now."""
    by_name = {name: key for key, name in choices.items()}
    for name in wanted_actions(state):
        if name in by_name:
            return by_name[name]
    return by_name.get("EMPTY ACTION", next(iter(choices)))


def wanted_actions(state: dict):
    """Action names in priority order; the first legal one is taken."""
    resource, building, unit = state["resource"], state.get("building", {}), state.get("unit", {})
    planning = state.get("planning", {})
    seconds = state.get("game_loop", 0) / 22.4
    have = lambda *kinds: sum(building.get(k, 0) + unit.get(k, 0) + planning.get(k, 0) for k in kinds)
    bases = have("COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS")
    workers = resource.get("worker_supply", 0)
    forecast = state.get("supply_forecast", {})
    wanted = []

    if resource.get("supply_cap", 0) < 200 and (forecast.get("needs_supply") or resource.get("needs_supply")):
        wanted.append("BUILD SUPPLYDEPOT")
    if workers < min(MAX_WORKERS, WORKERS_PER_BASE * max(bases, 1)):
        wanted.append("TRAIN SCV")
    if (bases < _planned(EXPANSIONS, seconds) or workers >= WORKERS_PER_BASE * bases - 4) and bases < 8 \
            and not planning.get("COMMANDCENTER"):
        wanted.append("BUILD COMMANDCENTER")
    if have("ORBITALCOMMAND") < ORBITALS:
        wanted.append("MORPH ORBITALCOMMAND")
    if seconds >= FIRST_REFINERY and have("REFINERY", "REFINERYRICH") < REFINERIES_PER_BASE * bases \
            and workers >= 14 + 6 * have("REFINERY", "REFINERYRICH"):
        wanted.append("BUILD REFINERY")
    if have("BARRACKS") < _planned(BARRACKS_PLAN, seconds):
        wanted.append("BUILD BARRACKS")
    if seconds >= FIRST_FACTORY and not have("FACTORY"):
        wanted.append("BUILD FACTORY")
    if seconds >= FIRST_STARPORT and not have("STARPORT"):
        wanted.append("BUILD STARPORT")
    wanted.append("ADDON FACTORYTECHLAB")
    wanted.append("ADDON BARRACKSREACTOR" if have("BARRACKSREACTOR") < REACTOR_BARRACKS else "ADDON BARRACKSTECHLAB")
    wanted.append("ADDON STARPORTREACTOR")
    research = state.get("research", {})
    wanted += [f"RESEARCH {r}" for r in RESEARCH if not research.get(r)]
    wanted.append("TRAIN SIEGETANK")
    if have("MARAUDER") * 2 < have("MARINE") + 4:
        wanted.append("TRAIN MARAUDER")
    if have("MARINE") < MARINE_CAP:
        wanted.append("TRAIN MARINE")
    if have("MEDIVAC") < MEDIVACS:
        wanted.append("TRAIN MEDIVAC")
    wanted.append("TRAIN MARAUDER")
    return [name for name in wanted if not re.match(r"MULTI-|SCOUTING", name)]
