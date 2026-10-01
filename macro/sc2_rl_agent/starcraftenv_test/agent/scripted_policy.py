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
BARRACKS_PLAN = ((60, 1), (150, 2), (330, 3), (480, 5), (600, 8), (720, 12))
REACTOR_BARRACKS = 2  # the rest get Tech Labs, for Marauders and Ghosts
# A Bunker at the natural once it is started: T124 (Jev) had one before 3:03 and held the Rush build; batch
# baseline2 had none until 5:30 and lost to it at 10:30.
FIRST_BUNKER = 140
# Gas goes to Tanks first: in the baseline2 Babylon loss the bot trained 67 Marauders and 13 Medivacs after 14:00
# but only 16 Tanks (Jev wins: 22-32), and its Tanks fell from 15 to 1-5.
GAS_SPARE = 200
# Save minerals for a Command Center that is due: in round1 the Rush game lost its natural at 4:00 and never had
# 400 minerals again (every mineral went on Marines), so it played on one base and 21-23 SCVs to the end.
SAVE_FOR_BASE_ALLOWS = ("BUILD SUPPLYDEPOT", "TRAIN SCV")
# Once Ultralisks (or their Cavern) are seen, Marauders before Marines: in round1's Babylon and Neohumanity losses
# Ultralisks killed 138 and 167 army supply of a Marine-and-Tank army with almost no Marauders.
ULTRALISK_SIGNS = {"ULTRALISK", "ULTRALISKBURROWED", "ULTRALISKCAVERN"}
MARINE_CAP_AGAINST_ULTRALISKS = 20
# Round2's Cistern and Rush losses: Marauders at 100 spare gas took the gas Tanks need (Tanks fell to 1-8 while
# Marauders rose to 21-25), and Tanks kill 2.2 Zerg supply per supply lost against 0.9 for Marauders. So against
# Ultralisks Marauders still wait for TANKS_WANTED Tanks or MARAUDER_GAS_AGAINST_ULTRALISKS spare gas.
MARAUDER_GAS_AGAINST_ULTRALISKS = 250
TANKS_WANTED = 12
# Marines are the anti-air: with Zerg air seen they stay at MARINE_CAP even against Ultralisks (round2's Rush loss:
# Mutalisks and Brood Lords killed 274 army supply of an army capped at 20 Marines).
ZERG_AIR = {"MUTALISK", "CORRUPTOR", "BROODLORD", "BROODLORDCOCOON", "SPIRE", "GREATERSPIRE"}
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
        self.memory = {}  # what the rules remember across decisions (e.g. Ultralisks seen)

    def payload(self, state: dict, choices: dict) -> dict:
        return {"model": self.model, "state": state, "choices": {str(k): v for k, v in choices.items()}}

    async def choose(self, payload: dict) -> dict:
        choice = pick(payload["state"], payload["choices"], self.memory)
        probabilities = {key: float(key == choice) for key in payload["choices"]}
        return {"model": self.model, "usage": {},
                "answer": {"type": "choice", "choice": choice, "confidence": 1.0, "probabilities": probabilities}}

    async def close(self):
        pass


def pick(state: dict, choices: dict, memory: dict = None) -> str:
    """The id (as a string) of the first wanted action that is legal now."""
    by_name = {name: key for key, name in choices.items()}
    wanted = wanted_actions(state, {} if memory is None else memory)
    if ("BUILD COMMANDCENTER" in wanted and "BUILD COMMANDCENTER" not in by_name and behind_on_bases(state)
            and not state.get("base_under_attack") and state["resource"].get("mineral", 0) < 400):
        wanted = [name for name in wanted if name in SAVE_FOR_BASE_ALLOWS]
    for name in wanted:
        if name in by_name:
            return by_name[name]
    return by_name.get("EMPTY ACTION", next(iter(choices)))


def behind_on_bases(state: dict) -> bool:
    """Fewer bases than the schedule wants by now (not merely more workers than the bases can use)."""
    building, planning = state.get("building", {}), state.get("planning", {})
    bases = sum(building.get(k, 0) + planning.get(k, 0)
                for k in ("COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS"))
    return bases < _planned(EXPANSIONS, state.get("game_loop", 0) / 22.4)


def wanted_actions(state: dict, memory: dict = None):
    """Action names in priority order; the first legal one is taken."""
    memory = {} if memory is None else memory
    resource, building, unit = state["resource"], state.get("building", {}), state.get("unit", {})
    enemy = state.get("enemy", {})
    seen = set(enemy.get("unit", {})) | set(enemy.get("structure", {}))
    if ULTRALISK_SIGNS & seen:
        memory["ultralisks"] = True
    if ZERG_AIR & seen:
        memory["zerg_air"] = True
    planning = state.get("planning", {})
    seconds = state.get("game_loop", 0) / 22.4
    have = lambda *kinds: sum(building.get(k, 0) + unit.get(k, 0) + planning.get(k, 0) for k in kinds)
    bases = have("COMMANDCENTER", "ORBITALCOMMAND", "PLANETARYFORTRESS")
    workers = resource.get("worker_supply", 0)
    forecast = state.get("supply_forecast", {})
    wanted = []

    if resource.get("supply_cap", 0) < 200 and (forecast.get("needs_supply") or resource.get("needs_supply")):
        wanted.append("BUILD SUPPLYDEPOT")
    if seconds >= FIRST_BUNKER and bases >= 2 and not have("BUNKER"):
        wanted.append("BUILD BUNKER")
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
    gas_to_spare = resource.get("gas", 0) >= GAS_SPARE
    if memory.get("ultralisks"):
        tanks = have("SIEGETANK", "SIEGETANKSIEGED")
        if tanks >= TANKS_WANTED or resource.get("gas", 0) >= MARAUDER_GAS_AGAINST_ULTRALISKS:
            wanted.append("TRAIN MARAUDER")
        marine_cap = MARINE_CAP if memory.get("zerg_air") else MARINE_CAP_AGAINST_ULTRALISKS
    else:
        marine_cap = MARINE_CAP
    if gas_to_spare and have("MARAUDER") * 2 < have("MARINE") + 4:
        wanted.append("TRAIN MARAUDER")
    if have("MARINE") < marine_cap:
        wanted.append("TRAIN MARINE")
    if gas_to_spare and have("MEDIVAC") < MEDIVACS:
        wanted.append("TRAIN MEDIVAC")
    if gas_to_spare:
        wanted.append("TRAIN MARAUDER")
    return [name for name in wanted if not re.match(r"MULTI-|SCOUTING", name)]
