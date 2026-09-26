"""Shared, explicit limits and command IDs for planning and execution."""

from dataclasses import dataclass, field

from ..utils.action_info import ActionDescriptions

VERSION = "macro-v2.3.0"

# Action kinds. Spending kinds cost resources and may appear in plan goals.
SPENDING_KINDS = {"train", "merge", "build", "addon", "morph", "research"}


@dataclass(frozen=True)
class RaceContract:
    """Everything the shared planner, policy and executor need to know about a race's actions."""
    race: str
    worker_type: str
    actions: dict
    kinds: dict
    army_actions: dict
    worker_action: int
    base_action: int
    supply_action: int
    empty_action: int
    unit_limits: dict
    building_limits: dict
    max_workers: int
    max_bases: int
    # Emergency production allowed past the spending budget while a base is attacked.
    urgent_defense_actions: frozenset
    army_production_actions: frozenset
    # Goals whose completion should ask Astra for the next phase.
    milestone_actions: frozenset
    limits: dict = field(default_factory=dict)
    # With this many minerals banked, these purchases may exceed the plan's lists and ceilings.
    bank_minerals: int = 800
    bank_override_actions: frozenset = frozenset()
    # Recommended to Jev, in order, while minerals are banked (more production).
    bank_spend_actions: tuple = ()
    # Keep enough for the supply building when supply is about to block production.
    supply_reserve: bool = False
    # Ready army supply below which no attack starts, whatever the plan says.
    min_attack_army: int = 0
    # A lower floor that applies once total supply reaches 190 (a maxed army); 0 keeps min_attack_army.
    maxed_attack_army: int = 0
    # (game seconds, action): buildings and upgrades recommended from that time until started once.
    tech_schedule: tuple = ()
    # Under a defend plan, do not retreat from an attacked base while the army is above the plan's retreat threshold.
    hold_defense: bool = False

    @property
    def spending_actions(self):
        return tuple(a for a in sorted(self.kinds) if self.kinds[a] in SPENDING_KINDS)

    @property
    def single_target_actions(self):
        return frozenset(a for a, k in self.kinds.items() if k == "research")

    @property
    def priority_actions(self):
        return tuple(a for a in sorted(self.actions) if a != self.empty_action)

    def action_for(self, posture):
        return next(a for a, p in self.army_actions.items() if p == posture)

    def kind_name(self, action):
        """Unit, structure or upgrade name of a spending action."""
        return self.actions[action].split()[1]


def _limits(kinds, actions, unit_limits, building_limits):
    limits = {}
    for action, kind in kinds.items():
        if kind == "research":
            limits[action] = 1
        elif kind in SPENDING_KINDS:
            name = actions[action].split()[1]
            limits[action] = (unit_limits if kind in {"train", "merge"} else building_limits).get(name, 200)
    return limits


def _protoss():
    actions = dict(ActionDescriptions("Protoss").flattened_actions)
    actions[72] = "MULTI-DEFEND"
    kinds = {a: "train" for a in range(18)}
    kinds[18] = "merge"
    kinds.update({a: "build" for a in range(19, 34)})
    kinds.update({a: "research" for a in range(34, 60)})
    kinds.update({a: "scout" for a in range(60, 64)})
    kinds.update({64: "army", 65: "army", 72: "army", 71: "empty"})
    kinds.update({a: "chrono" for a in range(66, 71)})
    # These are policy limits, not game technology requirements. Expose them to Astra.
    unit_limits = {"PROBE": 76, "OBSERVER": 4, "WARPPRISM": 2, "MOTHERSHIP": 1}
    building_limits = {
        "NEXUS": 8, "GATEWAY": 16, "FORGE": 3, "ROBOTICSFACILITY": 6,
        "STARGATE": 6, "PHOTONCANNON": 32, "SHIELDBATTERY": 24,
        "CYBERNETICSCORE": 1, "TWILIGHTCOUNCIL": 1, "TEMPLARARCHIVE": 1,
        "DARKSHRINE": 1, "ROBOTICSBAY": 1, "FLEETBEACON": 1,
    }
    return RaceContract(
        race="Protoss", worker_type="PROBE", actions=actions, kinds=kinds,
        army_actions={64: "attack", 65: "retreat", 72: "defend"},
        worker_action=0, base_action=21, supply_action=19, empty_action=71,
        unit_limits=unit_limits, building_limits=building_limits, max_workers=76, max_bases=8,
        urgent_defense_actions=frozenset({1, 3, 14, 32, 33}),
        army_production_actions=frozenset(range(1, 19)) - {13, 15},
        milestone_actions=frozenset(range(21, 32)) | frozenset(range(34, 60)),
        limits=_limits(kinds, actions, unit_limits, building_limits))


def _terran():
    actions = dict(ActionDescriptions("Terran").flattened_actions)
    kinds = {}
    for action, description in actions.items():
        verb = description.split()[0]
        kinds[action] = {"TRAIN": "train", "BUILD": "build", "ADDON": "addon", "MORPH": "morph",
                         "RESEARCH": "research", "SCOUTING": "scout", "MULTI-ATTACK": "army",
                         "MULTI-RETREAT": "army", "MULTI-DEFEND": "army", "EMPTY": "empty"}[verb]
    ids = {v: k for k, v in actions.items()}
    unit_limits = {"SCV": 76, "RAVEN": 3, "MEDIVAC": 8, "BATTLECRUISER": 8}
    building_limits = {
        "COMMANDCENTER": 8, "BARRACKS": 12, "FACTORY": 4, "STARPORT": 4,
        "ENGINEERINGBAY": 2, "ARMORY": 2, "FUSIONCORE": 1, "MISSILETURRET": 16,
        "SUPPLYDEPOT": 30, "REFINERY": 16, "ORBITALCOMMAND": 8, "PLANETARYFORTRESS": 4,
        "BUNKER": 4, "BARRACKSTECHLAB": 12, "BARRACKSREACTOR": 12, "FACTORYTECHLAB": 4,
        "FACTORYREACTOR": 4, "STARPORTTECHLAB": 4, "STARPORTREACTOR": 4,
    }
    trains = {a for a, k in kinds.items() if k == "train"}
    return RaceContract(
        race="Terran", worker_type="SCV", actions=actions, kinds=kinds,
        army_actions={ids["MULTI-ATTACK"]: "attack", ids["MULTI-RETREAT"]: "retreat",
                      ids["MULTI-DEFEND"]: "defend"},
        worker_action=ids["TRAIN SCV"], base_action=ids["BUILD COMMANDCENTER"],
        supply_action=ids["BUILD SUPPLYDEPOT"], empty_action=ids["EMPTY ACTION"],
        unit_limits=unit_limits, building_limits=building_limits, max_workers=76, max_bases=8,
        urgent_defense_actions=frozenset({ids["TRAIN MARINE"], ids["TRAIN SIEGETANK"],
                                          ids["BUILD MISSILETURRET"], ids["BUILD BUNKER"]}),
        army_production_actions=frozenset(trains - {ids["TRAIN SCV"], ids["TRAIN MEDIVAC"], ids["TRAIN RAVEN"]}),
        milestone_actions=frozenset(ids[f"BUILD {n}"] for n in (
            "COMMANDCENTER", "ENGINEERINGBAY", "FACTORY", "STARPORT", "ARMORY", "FUSIONCORE"))
        | frozenset(a for a, k in kinds.items() if k in {"research", "addon", "morph"}),
        limits=_limits(kinds, actions, unit_limits, building_limits),
        bank_override_actions=frozenset(ids[n] for n in (
            "TRAIN MARINE", "TRAIN MARAUDER", "TRAIN SIEGETANK", "TRAIN MEDIVAC", "BUILD BARRACKS")),
        supply_reserve=True, min_attack_army=40, bank_minerals=600, hold_defense=True,
        tech_schedule=tuple((t, ids[n]) for t, n in (
            (390, "BUILD ENGINEERINGBAY"),
            (420, "RESEARCH TERRANINFANTRYWEAPONSLEVEL1"), (420, "RESEARCH TERRANINFANTRYARMORSLEVEL1"),
            (480, "BUILD ARMORY"),
            (480, "RESEARCH TERRANINFANTRYWEAPONSLEVEL2"), (480, "RESEARCH TERRANINFANTRYARMORSLEVEL2"),
            (480, "RESEARCH TERRANINFANTRYWEAPONSLEVEL3"), (480, "RESEARCH TERRANINFANTRYARMORSLEVEL3"))),
        bank_spend_actions=(ids["BUILD BARRACKS"],))


PROTOSS = _protoss()
TERRAN = _terran()
CONTRACTS = {"Protoss": PROTOSS, "Terran": TERRAN}

# Protoss names kept for existing callers.
DEFEND_ACTION = 72
ARMY_ACTIONS = PROTOSS.army_actions
UNIT_LIMITS = PROTOSS.unit_limits
BUILDING_LIMITS = PROTOSS.building_limits
ACTION_LIMITS = PROTOSS.limits


MAXED_SUPPLY = 190


def tech_due(contract, game_time, catalog):
    """Scheduled buildings and upgrades whose time has come and that were never started."""
    return tuple(action for t, action in contract.tech_schedule
                 if game_time >= t and catalog.get(str(action), {}).get("count_with_pending", 0) == 0)


def attack_floor(contract, plan_threshold, supply_used=0):
    """Ready army supply an attack needs: the plan's threshold, raised to the race's floor."""
    floor = contract.min_attack_army
    if contract.maxed_attack_army and supply_used >= MAXED_SUPPLY:
        floor = contract.maxed_attack_army
    return max(plan_threshold, floor)


def primary_action(plan, choices, army_intent, ready_army_supply, target_changed=False, acknowledged_actions=(),
                   contract=PROTOSS, minerals=0, supply_used=0, tech_due=()):
    """Recommend a legal next action; Jev still selects the actual command."""
    desired = contract.action_for(plan["army_posture"])
    ready = (plan["army_posture"] != "attack"
             or ready_army_supply >= attack_floor(contract, plan["attack_min_army"], supply_used))
    if ready and (army_intent != plan["army_posture"] or target_changed) and desired in choices:
        return desired, "apply_army_order_before_optional_production"
    preferred = plan.get("priority_action")
    if preferred in choices and preferred != contract.empty_action and preferred not in acknowledged_actions:
        return preferred, "commander_priority"
    for action in tech_due:
        if action in choices:
            return action, "tech_schedule"
    if minerals >= contract.bank_minerals:
        for action in contract.bank_spend_actions:
            if action in choices:
                return action, "spend_banked_minerals"
    for action in plan.get("production_priority", []):
        if action in choices:
            return action, "first_attainable_production_priority"
    return None, "no_priority_currently_executable"
