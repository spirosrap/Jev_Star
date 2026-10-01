"""Jev macro executor for Terran: SC2-checked legality, placement and local unit upkeep."""

import math
from collections import Counter, deque

from sc2.bot_ai import BotAI
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from ...agent.macro_contract import TERRAN, SPENDING_KINDS, attack_floor
from .jev_macro_bot import JevMacroBot
from .macro_navigation import WORKERS

PRODUCTION = {U.BARRACKS, U.FACTORY, U.STARPORT}
ADDONS = {
    U.BARRACKSTECHLAB: (U.BARRACKS, A.BUILD_TECHLAB_BARRACKS),
    U.BARRACKSREACTOR: (U.BARRACKS, A.BUILD_REACTOR_BARRACKS),
    U.FACTORYTECHLAB: (U.FACTORY, A.BUILD_TECHLAB_FACTORY),
    U.FACTORYREACTOR: (U.FACTORY, A.BUILD_REACTOR_FACTORY),
    U.STARPORTTECHLAB: (U.STARPORT, A.BUILD_TECHLAB_STARPORT),
    U.STARPORTREACTOR: (U.STARPORT, A.BUILD_REACTOR_STARPORT),
}
MORPHS = {
    U.ORBITALCOMMAND: A.UPGRADETOORBITAL_ORBITALCOMMAND,
    U.PLANETARYFORTRESS: A.UPGRADETOPLANETARYFORTRESS_PLANETARYFORTRESS,
}
COMBAT = {
    U.MARINE, U.MARAUDER, U.REAPER, U.GHOST, U.HELLION, U.HELLIONTANK, U.WIDOWMINE,
    U.WIDOWMINEBURROWED, U.SIEGETANK, U.SIEGETANKSIEGED, U.CYCLONE, U.THOR, U.THORAP,
    U.VIKINGFIGHTER, U.VIKINGASSAULT, U.LIBERATOR, U.LIBERATORAG, U.BANSHEE, U.BATTLECRUISER,
}
SUPPORT = {U.MEDIVAC, U.RAVEN}
DEPOTS = {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED}
# Seconds a tank or mine keeps its mode before local code may switch it back.
MODE_HOLD = 3
# Seconds a build spot the engine rejected stays excluded from placement.
REJECTED_SPOT_SECONDS = 120
# Placeable spots checked for a walking path from the builder, in one batched query.
PATH_CHECKS = 16
# Distances from each base, (other buildings, production), and turns away from the mineral line searched for spots.
PLACEMENT_RINGS = {False: (8, 11, 14, 17, 20, 23), True: (10, 13, 16, 19, 22, 25)}
PLACEMENT_TURNS = tuple(sorted({sign * k * math.pi / 8 for k in range(9) for sign in (1, -1)}, key=abs))
# Filtered spots sent to the engine's placement query, nearest base first.
PLACEMENT_QUERY = 800
# Grid steps around each anchor, nearest first.
ANCHOR_OFFSETS = sorted(((x, y) for x in range(-4, 5, 2) for y in range(-4, 5, 2)), key=lambda d: abs(d[0]) + abs(d[1]))
# Buildings other than Supply Depots, Missile Turrets and Bunkers keep this many cells of walkable
# terrain (no cliff, map edge or rocks) around their footprint and add-on slot, so units they make
# are never trapped in a pocket between a building and the edge of the base.
EDGE_CLEARANCE = 2
EDGE_EXEMPT = {U.SUPPLYDEPOT, U.MISSILETURRET, U.BUNKER}
# Marines and SCVs this close to a Baneling step away from it.
BANELING_DODGE_RANGE = 5
BANELING_DODGE_STEP = 3
# SCVs near Banelings leave the mineral line for the far side of their Command Center and stay off the minerals until
# the Banelings are gone: stepping 3 away was not enough, and worker distribution sent them straight back. In T126
# Banelings killed 17 SCVs before 15:00 (15 in one run-by at 11:00) and in T119 12; the economy never recovered.
WORKER_FLEE_RANGE = 8
WORKER_FLEE_DISTANCE = 6  # beyond the Command Center, on the side away from the Banelings
WORKER_FLEE_CLEAR = 10  # SCVs go back to work once no Baneling is this close
# Pull SCVs off gas while this much gas is banked and it is more than twice the minerals;
# send them back once gas falls below the lower mark.
# Unspent minerals above the contract's bank threshold go into army from idle production, down to this floor,
# once a second: Jev gives about one order a second and spent a 1,500-mineral bank on buildings before T58's fight.
BANK_SPEND_FLOOR = 200
BANK_ARMY = (U.SIEGETANK, U.MARAUDER, U.MARINE)  # Tech Lab units first, Marines from what is left
# Once Brood Lord tech is seen, keep Vikings coming (T62 met Brood Lords with a single Viking): 2 per Brood Lord seen,
# at least 6 and at most 16, from at least two Starports with Reactors. Brood Lords morph from Corruptors, which T63
# saw two minutes before the first Brood Lord, so Corruptors start it too.
AIR_TECH = {U.CORRUPTOR, U.GREATERSPIRE, U.BROODLORDCOCOON, U.BROODLORD}
VIKINGS_MIN, VIKINGS_PER_BROODLORD, VIKINGS_MAX = 6, 2, 16
AIR_STARPORTS = 2
# Against CheatMoney and stronger, once Infestors or Vipers are seen, a Ghost Academy and up to GHOST_CAP Ghosts from
# Tech Lab Barracks, and each Ghost with the energy EMPs the nearest group of them: EMP drains all their energy, so no
# Fungal Growth, Neural Parasite, Abduct or Blinding Cloud. T109 and T110 were broken after 20:00 by armies with 6-9
# Infestors and 2 Vipers (Infestors took our Tanks with Neural Parasite in T110).
CASTERS = {U.INFESTOR, U.VIPER}
GHOST_CAP = 6
EMP_ENERGY = 75
EMP_REACH = 13  # EMP range is 10; a Ghost walks the last cells itself
EMP_RADIUS = 1.5
EMP_REPEAT = 10  # seconds before a drained caster is worth another EMP
# Ghosts with Snipe energy and no caster to EMP snipe Ultralisks (170 damage to biological units, range 10): in
# round1's Babylon and Neohumanity losses Ultralisks were the top killer of our army after 20:00.
SNIPE_ENERGY = 50
SNIPE_REACH = 11
SNIPES_PER_ULTRALISK = 3  # 500 hit points
SNIPE_TARGETS = {U.ULTRALISK}
MEDIVAC_FRONT = 8  # the bio units nearest the army's heading that Medivacs stay over
MEDIVAC_SLACK = 6
# Against CheatMoney and stronger, surplus minerals grow the bot into the map (T70-T73 sat on 3,000-17,000 unused
# minerals while Zerg held the map): new bases as Planetary Fortresses, a Missile Turret per base, their Refineries,
# and Scans of expansion sites nobody has looked at, so exposed Zerg bases are found.
GROW_BANK = 1500
GROW_INTERVAL = 5
GROW_ORBITALS = 3  # Command Centers beyond this many Orbitals become Planetary Fortresses
SCOUT_SCAN_INTERVAL = 45
# Against CheatMoney and stronger, until 9:30 get ready for the Zerg attack that comes at about 8:45: Siege Tanks
# (up to 4) and Marauders (up to 6) from idle Tech Lab producers, a second Bunker at the front from 5:00, and Tanks
# sieged at the front position. The games that went long held that attack; the ones lost met it with 33-47 Marines
# and one to three unsieged Tanks (T74-T78).
EARLY_DEFENSE_UNTIL = 570
EARLY_TANKS = 4
EARLY_MARAUDERS = 6
EARLY_BUNKERS = 2
EARLY_BUNKER_FROM = 300
EARLY_SIEGE_RADIUS = 6
# After 9:30, against CheatMoney and stronger, a defending army's Tanks near the rally base stay sieged there too, so
# each Zerg wave meets them set up. In T95 the first wave, with five of six Tanks sieged by the rule above, was won
# 27 to 17; every later wave began with no Tank sieged and ended close to even (1.04-1.10 in the big ones).
HOLD_SIEGE_RADIUS = 10
# Against CheatMoney and stronger, a defending army's Tanks siege when Zerg army units come within 20, not only once
# they are inside the Tanks' own range (13): sieging takes about 3 s, in which Banelings cover that distance. In 7 of
# the 9 biggest fights in the T67-T83 replays no Tank was sieged when the fight began; in the one where most were
# sieged within 10 s, the Zerg lost more than we did.
DEFENSE_SIEGE_RANGE = 20
DEFENSE_UNSIEGE_RANGE = 22
# Against CheatMoney and stronger, a Marine-heavy army lost to Banelings and to +3/+3 Zerg: Banelings were the top
# killer in 7 of the 9 biggest replay fights (T67-T83), our army was 50-87 Marines, and the Zerg had +3/+3 by about
# 15:00 while we mostly had +1/+1. So Marines stop at a cap and the bank goes to Tanks, Marauders and Hellbats, and
# two Engineering Bays and an Armory keep infantry and vehicle upgrades going.
MARINE_CAP = 40
# No Hellbats against CheatMoney: they come from the Factories that make Tanks, and in the replays of T114-T127 they
# killed 62 Zerg army supply for 450 of their own in the seven losses and 98 for 344 in the six wins, while Siege
# Tanks killed 1,491 for 657 and 1,700 for 318 (52-65% of all Zerg army supply killed).
CAUTIOUS_BANK_ARMY = (U.SIEGETANK, U.MARAUDER, U.MARINE)
HELLBAT_CAP = 0
UPGRADE_INTERVAL = 2
UPGRADE_BUILDINGS = ((U.ENGINEERINGBAY, 1, 300), (U.ENGINEERINGBAY, 2, 420), (U.ARMORY, 1, 480))  # kind, count, from
UPGRADES = tuple(UpgradeId[n] for n in (
    "STIMPACK", "SHIELDWALL",
    "TERRANINFANTRYWEAPONSLEVEL1", "TERRANINFANTRYARMORSLEVEL1",
    "TERRANINFANTRYWEAPONSLEVEL2", "TERRANINFANTRYARMORSLEVEL2", "TERRANVEHICLEWEAPONSLEVEL1",
    "TERRANINFANTRYWEAPONSLEVEL3", "TERRANINFANTRYARMORSLEVEL3", "TERRANVEHICLEWEAPONSLEVEL2",
    "TERRANVEHICLEWEAPONSLEVEL3", "PUNISHERGRENADES"))
# Against CheatMoney and stronger, holding alone only delays the loss: the Zerg out-produce us, and the best result
# so far is a stalemate tie. The Zerg army is weakest right after one of its waves dies against our defense, so then
# the army counter-attacks the nearest known Zerg base for a short window and comes home. When we are maxed with
# +2 weapons, that attack may also go into the Zerg main and crawler cover (a push to win).
COUNTER_ENEMY_LOSS = 30  # enemy army supply killed within COUNTER_LOOKBACK seconds that counts as a beaten wave
COUNTER_LOOKBACK = 45
COUNTER_MIN_ARMY = 100
COUNTER_WINDOW = 45
COUNTER_COOLDOWN = 120
COUNTER_RECALL_THREAT = 8  # enemy army supply near a base that ends the window early
COUNTER_RECALL_DISTANCE = 30
PUSH_MIN_SUPPLY = 185
PUSH_WINDOW = 90
# The push also goes when the Zerg have not attacked for this long: in T102 the army sat maxed at home with 4,800
# minerals from 36:14 on, because the push waited for a wave that did not come.
PUSH_IDLE = 60
ZERG_BASES = {U.HATCHERY, U.LAIR, U.HIVE}
# Against CheatMoney and stronger, the bot keeps Siege Tanks coming itself instead of leaving it to Jev's and the
# planner's orders: four Factories with Tech Labs from 6:00, and every free Tech Lab Factory trains a Tank whenever it
# can. With the same code and two Factories, T102 had 11 Tanks at 11:00 and held to a 43-minute stalemate; T103 had
# five and lost every wave by 18:31.
TANK_FACTORIES = 4
TANK_FACTORIES_FROM = 360
TANK_CAP = 20
TANK_INTERVAL = 1
GAS_THROTTLE_ON = 300
GAS_THROTTLE_OFF = 150
# Against CheatMoney and stronger the minerals are nearly always spent down to 100-200, so "gas over 300 and twice the
# minerals" was true most of the game: in T100 the throttle switched on eleven times and each time emptied every
# Refinery until gas fell to 25-135, and by 19:00 the army had five Tanks and was rebuilt from Marines. Tanks and
# upgrades need that gas, so here only a real surplus moves SCVs off gas.
CAUTIOUS_GAS_THROTTLE_ON = 500
CAUTIOUS_GAS_THROTTLE_OFF = 250
# At 1,000 (T101) gas piled up unused (700-1,100) while minerals stayed at 25-120, so the third base came late and the
# army lagged; 500/250, without the ratio to minerals, keeps a modest gas bank for Tanks and upgrades.
# With a mineral bank, the gas is the limit: in scripted batch round2's Ancient Cistern loss the bot sat on 10,000-
# 20,000 minerals while the throttle emptied its Refineries (12 of 42 minutes), and after each lost fight it had
# 35-60 gas and 4-8 Tanks (the wins kept 15-24); Tanks waited for gas in half of the decisions from 20:00 to 28:00.
# From this bank on, SCVs stay on gas and the surplus gas is kept for rebuilding Tanks.
CAUTIOUS_GAS_KEEP_MINERALS = 1000
# Burrowed Lurkers need detection: seen this recently, an Orbital keeps energy for a scan.
LURKERS = {U.LURKERMP, U.LURKERMPBURROWED, U.LURKERMPEGG, U.LURKERDENMP}
LURKER_MEMORY = 90
SCAN_INTERVAL = 12


class TerranObservation(BotAI):
    """The state Jev and Astra read; keys mirror the Protoss observation where they overlap."""

    def get_information(self):
        research = {}
        for action, kind in self.contract.kinds.items():
            if kind != "research":
                continue
            upgrade = UpgradeId[self.contract.kind_name(action)]
            data = self.game_data.upgrades.get(upgrade.value)
            # The SDK's pending query dereferences the research ability; obsolete records have none.
            if data is not None and data.research_ability is not None:
                research[upgrade.name] = self.already_pending_upgrade(upgrade)
        pending = {}
        for action, kind in self.contract.kinds.items():
            if kind in {"train", "build", "addon", "morph"}:
                unit_type = U[self.contract.kind_name(action)]
                amount = self.already_pending(unit_type)
                if amount:
                    pending[unit_type.name] = amount
        return {
            "resource": {
                "game_time": self.time_formatted, "worker_supply": self.workers.amount,
                "mineral": self.minerals, "gas": self.vespene, "supply_left": self.supply_left,
                "supply_cap": self.supply_cap, "supply_used": self.supply_used, "army_supply": self.supply_army,
            },
            "building": dict(Counter(s.type_id.name for s in self.structures)),
            "unit": dict(Counter(u.type_id.name for u in self.units)),
            "planning": pending,
            "research": research,
            "enemy": {"unit": self.get_enemy_unity(), "structure": self.get_enemy_structure()},
        }


class JevTerranBot(JevMacroBot, TerranObservation):
    contract = TERRAN
    stationary_army_types = frozenset({U.SIEGETANKSIEGED, U.WIDOWMINEBURROWED})
    local_automation = ["worker_distribution", "mule_calldown", "supply_depot_lowering",
                        "resume_unfinished_construction", "bunker_load_unload", "scv_repair_under_fire",
                        "baneling_dodge", "gas_balance", "changeling_targeting", "lurker_scans",
                        "army_intent_execution", "tank_siege", "building_edge_clearance",
                        "widow_mine_burrow", "combat_stimpack", "assigned_scout_missions",
                        "medivac_front_healing", "raven_escort", "anti_air_response", "grow_into_map", "early_defense",
                        "bank_army_spend"]

    def _initialize_race(self):
        super()._initialize_race()
        self.military_unit_types = set(COMBAT | SUPPORT)
        self._mode_changed = {}
        self._resume_orders = {}
        self._rejected_spots = {}
        self._addon_blocked = {}
        self._gas_throttled = False
        self._terrain = None
        self._lurker_seen = -1000
        self._last_scan = -1000
        self._last_bank_spend = -1000
        self._action_ids = {name: action for action, name in self.contract.actions.items()}
        self._air_threat_since = None
        self._casters_since = None
        self._last_caster_response = -1000
        self._emp_until = {}  # enemy caster tag -> game time its energy is drained until
        self._fleeing = set()  # SCVs kept off the minerals while Banelings are near
        self.gas_reserve = 0  # scripted play sets this: bank spending leaves this much gas for Tanks
        self._broodlords_seen = 0
        self._last_air_response = -1000
        self._last_grow = -1000
        self._last_early_defense = -1000
        self._last_scout_scan = -1000
        self._last_upgrade_check = -1000
        self._last_tank_check = -1000
        self._enemy_army_supply = {}  # tag -> supply of enemy army units seen, to count what dies
        self._enemy_losses = deque()  # (game seconds, supply)
        self._counter_until = None
        self._last_counter = -1000
        self._push_active = False
        self._last_threat_seen = 0.0
        self._own_army_supply = {}  # tag -> supply of our combat units, to count what each wave costs us
        self._wave = None  # the Zerg attack now under way: when it began and what each side has lost

    # ---- counts and forecasts -------------------------------------------------

    async def on_start(self):
        self._repair_creation_abilities()
        await super().on_start()

    def _repair_creation_abilities(self):
        """Campaign data leaves out the build/train ability of some units (Command Center, SCV) although the
        ability itself exists with its multiplayer id. Fill it in so the SDK can train, build and count them.
        Melee data is complete, so nothing changes there."""
        repaired = []
        for producer, kinds in TRAIN_INFO.items():
            # Only our own race's units; melee data lacks the Changeling's ability and must stay as it is.
            producer_data = self.game_data.units.get(producer.value)
            if producer_data is None or producer_data.race != self.race:
                continue
            for kind, info in kinds.items():
                data = self.game_data.units.get(kind.value)
                if (data is not None and data.creation_ability is None
                        and info["ability"].value in self.game_data.abilities):
                    data._proto.ability_id = info["ability"].value
                    repaired.append(kind.name)
        if repaired:
            self.log("game_data_repaired", units=sorted(set(repaired)))

    def calculate_cost(self, item_id):
        # Campaign data lacks some multiplayer units entirely (e.g. the Hellbat in Wings of Liberty).
        try:
            return super().calculate_cost(item_id)
        except (AttributeError, KeyError):
            return Cost(0, 0)

    def calculate_supply_cost(self, unit_type):
        try:
            return super().calculate_supply_cost(unit_type)
        except (AttributeError, KeyError):
            return 0

    def already_pending(self, unit_type):
        if isinstance(unit_type, U) and unit_type.value not in self.game_data.units:
            return 0
        return super().already_pending(unit_type)

    def _count_with_pending(self, kind):
        if kind == U.SCV:
            return self.supply_workers + self.already_pending(kind)
        if kind == U.COMMANDCENTER:
            return self.townhalls.amount + self.worker_en_route_to_build(kind)
        if kind in ADDONS or kind in MORPHS:
            # The host keeps the add-on/morph order until it finishes.
            return self.structures(kind).ready.amount + self.already_pending(kind)
        if kind in TRAIN_INFO[U.SCV]:
            kinds = DEPOTS if kind == U.SUPPLYDEPOT else {kind}
            # Unfinished structures count even after losing their SCV.
            return self.structures.of_type(kinds).amount + self.worker_en_route_to_build(kind)
        return self.units(kind).ready.amount + self.already_pending(kind)

    def _ready_base_count(self):
        # A finished Orbital/Planetary morph reports build progress below 1 for a frame.
        return self.townhalls.filter(lambda t: t.is_ready or t.type_id in MORPHS).amount

    def _supply_forecast(self):
        production = self.structures.of_type(PRODUCTION).ready
        slots = production.amount + production.filter(lambda b: b.has_reactor).amount
        desired_headroom = min(28, max(4, self.townhalls.ready.amount * 2 + slots * 3))
        pending_depots = self.already_pending(U.SUPPLYDEPOT)
        return {"headroom_target": desired_headroom, "pending_supply_depots": pending_depots,
                "needs_supply": self.supply_cap < 200 and self.supply_left + 8 * pending_depots <= desired_headroom,
                "needs_power": False}

    def _combat_units(self):
        return self.units.of_type(COMBAT).ready

    # ---- legality -------------------------------------------------------------

    def _producer_free(self, producer):
        return len(producer.orders) < (2 if producer.has_reactor else 1)

    def _train_reason(self, unit_type, ignore_resources=False):
        if not ignore_resources and not self.can_afford(unit_type):
            return "resources_or_supply"
        limit = self.contract.unit_limits.get(unit_type.name)
        if limit is not None and self._count_with_pending(unit_type) >= limit:
            return "unit_policy_limit"
        if self._over_cautious_cap(unit_type):
            return "cap_against_banelings"
        if self._train_producer(unit_type, ignore_resources) is not None:
            return None
        return "no_ready_producer_with_available_ability"

    def _over_cautious_cap(self, unit_type, extra=0):
        cap = {U.MARINE: MARINE_CAP, U.HELLIONTANK: HELLBAT_CAP}.get(unit_type)
        return self.cautious_attacks and cap is not None and self._count_with_pending(unit_type) + extra >= cap

    def _train_producer(self, unit_type, ignore_resources=False):
        sources = UNIT_TRAINED_FROM.get(unit_type, set())
        candidates = [p for p in self._producers if p.type_id in sources and self._producer_free(p)]
        # Fill an empty producer before the second slot of a Reactor.
        for producer in sorted(candidates, key=lambda p: len(p.orders)):
            info = TRAIN_INFO[producer.type_id][unit_type]
            if info.get("requires_techlab") and not producer.has_techlab:
                continue
            if self._has_ability(producer, info["ability"], ignore_resources=ignore_resources):
                return producer
        return None

    def _train_slots(self, unit_type):
        """Every free production slot for this unit, a Reactor counting twice."""
        sources = UNIT_TRAINED_FROM.get(unit_type, set())
        slots = []
        for producer in sorted((p for p in self._producers if p.type_id in sources and self._producer_free(p)),
                               key=lambda p: len(p.orders)):
            info = TRAIN_INFO[producer.type_id][unit_type]
            if info.get("requires_techlab") and not producer.has_techlab:
                continue
            if self._has_ability(producer, info["ability"]):
                slots += [producer] * ((2 if producer.has_reactor else 1) - len(producer.orders))
        return slots

    def _banked(self):
        return self.minerals >= self.contract.bank_minerals

    def _build_reason(self, unit_type, worker, ignore_resources=False):
        if not worker:
            return "no_available_builder"
        if not ignore_resources and not self.can_afford(unit_type):
            return "building_resources"
        info = TRAIN_INFO[U.SCV].get(unit_type)
        if not info or not self._has_ability(worker, info["ability"], ignore_resources=ignore_resources):
            return "missing_build_ability_or_technology"
        # Production buildings take 46-60 seconds; with a large bank allow more of them at once.
        pending_limit = (4 if unit_type in PRODUCTION and self._banked()
                         else 2 if unit_type == U.SUPPLYDEPOT or unit_type in PRODUCTION else 1)
        if self.already_pending(unit_type) >= pending_limit:
            return "already_pending"
        limit = self.contract.building_limits.get(unit_type.name)
        if limit is not None and self._count_with_pending(unit_type) >= limit:
            return "building_policy_limit"
        if unit_type == U.SUPPLYDEPOT and not self._supply_forecast()["needs_supply"]:
            return "supply_sufficient"
        if unit_type == U.REFINERY and not self._assimilator_candidates():
            return "no_free_geyser_at_ready_base"
        return None

    def _addon_hosts(self, addon, ignore_resources=False):
        host_type, ability = ADDONS[addon]
        return [h for h in self.structures(host_type).ready
                if h.is_idle and not h.has_add_on and h.tag not in self.unit_tags_received_action
                and self._has_ability(h, ability, ignore_resources=ignore_resources)]

    def _addon_reason(self, addon, ignore_resources=False):
        if not ignore_resources and not self.can_afford(addon):
            return "resources"
        limit = self.contract.building_limits.get(addon.name)
        if limit is not None and self._count_with_pending(addon) >= limit:
            return "building_policy_limit"
        hosts = self._addon_hosts(addon, ignore_resources)
        if not hosts:
            return "no_idle_producer_without_addon"
        self._addon_blocked = {t: until for t, until in self._addon_blocked.items() if until > self.time}
        if all(h.tag in self._addon_blocked for h in hosts):
            return "addon_space_blocked"
        return None

    def _morph_hosts(self, target, ignore_resources=False):
        return [c for c in self.structures(U.COMMANDCENTER).ready
                if c.is_idle and c.tag not in self.unit_tags_received_action
                and self._has_ability(c, MORPHS[target], ignore_resources=ignore_resources)]

    def _morph_reason(self, target, ignore_resources=False):
        if not ignore_resources and not self.can_afford(target):
            return "resources"
        limit = self.contract.building_limits.get(target.name)
        if limit is not None and self._count_with_pending(target) >= limit:
            return "building_policy_limit"
        if not self._morph_hosts(target, ignore_resources):
            return "no_idle_command_center_with_technology"
        return None

    def _reason(self, action, worker, ignore_resources=False):
        kind = self.contract.kinds[action]
        if kind not in SPENDING_KINDS:
            return None
        name = self.contract.kind_name(action)
        if kind == "train":
            return self._train_reason(U[name], ignore_resources)
        if kind == "build":
            return self._build_reason(U[name], worker, ignore_resources)
        if kind == "addon":
            return self._addon_reason(U[name], ignore_resources)
        if kind == "morph":
            return self._morph_reason(U[name], ignore_resources)
        return self._research_reason(UpgradeId[name], ignore_resources)

    def _reservation_reason(self, action):
        return self._reason(action, self._build_worker_for_catalog, ignore_resources=True)

    def _scout_candidates(self, kind):
        if kind == U.SCV:
            return self.workers.filter(lambda w: (w.is_gathering or w.is_idle) and not w.is_carrying_resource)
        return super()._scout_candidates(kind)

    async def available_actions(self):
        worker = await self._refresh_abilities()
        choices, blocked = {}, {}
        for action, description in self.action_dict.items():
            kind = self.contract.kinds[action]
            if self.cooldowns.get(action, 0) > self.time:
                reason = "recent_executor_rejection"
            elif kind in SPENDING_KINDS:
                reason = self._reason(action, worker)
            elif kind == "scout":
                reason = None
                if not self._scout_candidates(U[self.contract.kind_name(action)]):
                    reason = "no_available_scout"
                elif self.time - self._last_scout_order < 15:
                    reason = "scout_order_cooldown"
            elif kind == "army":
                reason = self._posture_reason(self.contract.army_actions[action])
            else:
                reason = None
            if reason:
                blocked[str(action)] = reason
            else:
                choices[action] = description
        return choices, blocked

    def _posture_reason(self, posture):
        if self._counter_until is not None:
            return "counter_attack_under_way"
        if posture == "attack" and self.cautious_attacks:
            # Against CheatMoney and stronger the army goes out only in the bot's own push, so the Tanks stay sieged
            # at home between pushes: the planner's attack orders broke the defence at bad moments (T91 at 23:07,
            # T98 at 13:25).
            return "attacks_only_as_pushes"
        army = self._combat_units()
        if posture == "attack":
            retarget = self._planned_target() != self._army_target_id
            floor = max(10, attack_floor(self.contract, 0, self.supply_used))
            if not army or self._ready_army_supply() < floor or (self.army_intent == "attack" and not retarget):
                return "need_army_or_already_attacking"
        elif not army or self.army_intent == posture:
            return f"no_army_or_already_{'retreating' if posture == 'retreat' else 'defending'}"
        return None

    # ---- execution ------------------------------------------------------------

    async def _perform(self, action):
        kind = self.contract.kinds[action]
        if kind in {"army", "empty"}:
            if kind == "army":
                await self._set_posture(action)
            return
        name = self.contract.kind_name(action)
        if kind == "train":
            unit_type = U[name]
            producer = self._train_producer(unit_type)
            if producer is None:
                self.record_failure(action, "no_ready_producer_with_available_ability")
            elif self._banked() and action in self.contract.bank_override_actions:
                # One decision per second cannot keep a dozen producers busy; fill every free slot.
                limit = self.contract.unit_limits.get(name)
                count = self._count_with_pending(unit_type)
                trained = 0
                for slot in self._train_slots(unit_type):
                    if (not self.can_afford(unit_type) or (limit is not None and count + trained >= limit)
                            or self._over_cautious_cap(unit_type, trained)):
                        break
                    slot.train(unit_type)
                    trained += 1
                self._action_stats["batch_trained_units"] += trained
            else:
                producer.train(unit_type)
        elif kind == "build":
            await self._build_one(action, U[name])
        elif kind == "addon":
            await self._build_addon(action, U[name])
        elif kind == "morph":
            hosts = self._morph_hosts(U[name])
            if hosts:
                hosts[0](MORPHS[U[name]])
            else:
                self.record_failure(action, "no_idle_command_center_with_technology")
        elif kind == "research":
            self._research_one(action, UpgradeId[name])
        elif kind == "scout":
            await self._start_scout(action, U[name])

    async def _build_addon(self, action, addon):
        for host in self._addon_hosts(addon):
            if host.tag in self._addon_blocked:
                continue
            # The add-on occupies the 2x2 footprint to the host's lower right.
            if await self.can_place_single(U.SUPPLYDEPOT, host.position.offset((2.5, -0.5))):
                host(ADDONS[addon][1])
                return
            # Keep offering the add-on only while some producer has room for it.
            self._addon_blocked[host.tag] = self.time + REJECTED_SPOT_SECONDS
        self.record_failure(action, "no_space_for_addon")

    def _free_workers(self):
        """SCVs that can take an order now: not scouting, and not on the gas run.

        A worker inside a Refinery rejects orders (NotSupported), so gas workers are left alone.
        """
        gas = {g.tag for g in self.gas_buildings}
        return self.workers.filter(lambda w: (w.is_gathering or w.is_idle) and w.tag not in self._scouts
                                   and w.tag not in self.unit_tags_received_action
                                   and not w.is_carrying_vespene and w.order_target not in gas)

    def _expansion_builder(self, position):
        return self._builder(position)

    def _builder(self, position):
        workers = self._free_workers()
        if not workers:
            return None
        return workers.closest_to(position)

    def _production_event(self, order, phase, **details):
        position = order.get("position")
        if (phase == "failed" and position and order.get("order_type", "production") == "production"
                and order["kind"] in {k.name for k in TRAIN_INFO[U.SCV]}):
            self._rejected_spots[tuple(position)] = self.time + REJECTED_SPOT_SECONDS
        super()._production_event(order, phase, **details)

    def _reserved_areas(self):
        """(centre, half-size) of add-on slots and sites that builders are still walking to."""
        areas = [(b.position.offset((2.5, -0.5)), 1) for b in self.structures.of_type(PRODUCTION)
                 if not b.has_add_on]
        areas += [(Point2(o["position"]), 1.5) for o in self._production_orders.values()
                  if o["position"] and o["phase"] in {"submitted", "accepted"}
                  and o["kind"] in {k.name for k in TRAIN_INFO[U.SCV]}]
        self._rejected_spots = {p: t for p, t in self._rejected_spots.items() if t > self.time}
        areas += [(Point2(p), 1.5) for p in self._rejected_spots]
        return areas

    @staticmethod
    def _overlaps(point, half, areas):
        return any(abs(point.x - c.x) < half + h and abs(point.y - c.y) < half + h for c, h in areas)

    def _blocks_resources(self, position, kind, obstacles):
        """obstacles: (resource points, townhall points) as (x, y) tuples, from _resource_obstacles."""
        resources, halls = obstacles
        clearance = 3 if kind == U.MISSILETURRET else 4 if kind == U.BUNKER else 6
        x, y = position
        if any(math.hypot(x - rx, y - ry) < clearance for rx, ry in resources):
            return True
        return (kind not in {U.MISSILETURRET, U.BUNKER}
                and any(math.hypot(x - hx, y - hy) < 7 for hx, hy in halls))

    def _resource_obstacles(self):
        # Plain tuples, built once per search: the search tests thousands of spots.
        return ([tuple(r.position) for r in self.mineral_field | self.vespene_geyser],
                [tuple(t.position) for t in self.townhalls])

    def _anchors(self, kind):
        bases = list(self.townhalls.ready) or list(self.townhalls)
        if not bases:
            return [self.start_location]
        anchors = []
        center = self.game_info.map_center
        if kind == U.BUNKER:
            # In front of the base closest to the enemy, on the side they arrive from.
            enemy = self.enemy_start_locations[0]
            return [b.position.towards(enemy, d) for b in sorted(bases, key=lambda b: b.distance_to(enemy))
                    for d in (6, 8)]
        for base in sorted(bases, key=lambda b: b.distance_to(self.start_location)):
            minerals = self.mineral_field.closer_than(12, base)
            mineral_center = minerals.center if minerals else base.position.towards(center, -5)
            if kind == U.MISSILETURRET:
                anchors.append(base.position.towards(mineral_center, 3))
                continue
            away = base.position.towards(mineral_center, -1)
            direction = math.atan2(away.y - base.position.y, away.x - base.position.x)
            # Rings of points, nearest first, starting on the side away from the mineral line and going all
            # the way round. Babylon's corner main fills by 6:00 and the three rings to 18 found 2 spots at its
            # natural in T108's layout (54 Factory orders, 1 Factory); out to 25 in 16 directions they find 32.
            for distance in PLACEMENT_RINGS[kind in PRODUCTION]:
                for turn in PLACEMENT_TURNS:
                    angle = direction + turn
                    anchors.append(base.position + Point2((math.cos(angle), math.sin(angle))) * distance)
        return anchors

    async def _build_one(self, action, kind):
        if kind == U.COMMANDCENTER:
            await self._build_expansion(action, kind)
            return
        if kind == U.REFINERY:
            for geyser in sorted(self._assimilator_candidates(), key=lambda g: g.distance_to(self.start_location)):
                worker = self._builder(geyser.position)
                if worker is not None:
                    worker.build_gas(geyser)
                    return
            self.record_failure(action, "no_free_geyser_or_available_builder")
            return
        position = await self._placement(kind)
        if position is None:
            self.record_failure(action, "no_valid_placement")
            return
        worker = self._builder(position)
        if worker is None:
            self.record_failure(action, "no_available_builder")
            return
        worker.build(kind, position)

    def _clear_of_edges(self, point, kind):
        """True when the footprint (and add-on slot) has EDGE_CLEARANCE walkable terrain cells around it."""
        rects = [(point, 1.5)]
        if kind in PRODUCTION:
            rects.append((point.offset((2.5, -0.5)), 1))
        terrain = self._terrain.data_numpy  # Indexed [y, x].
        height, width = terrain.shape
        for centre, half in rects:
            x0, x1 = int(centre.x - half) - EDGE_CLEARANCE, int(centre.x + half) + EDGE_CLEARANCE
            y0, y1 = int(centre.y - half) - EDGE_CLEARANCE, int(centre.y + half) + EDGE_CLEARANCE
            if x0 < 0 or y0 < 0 or x1 > width or y1 > height:  # Too close to the map edge.
                return False
            if not terrain[y0:y1, x0:x1].all():
                return False
        return True

    def _placement_candidates(self, kind):
        """Grid-aligned spots near the anchors, nearest anchor first, after local filtering."""
        grid = self.game_info.placement_grid
        if self._terrain is None:
            # SDK refreshes pathing every step, marking our own buildings; keep the first one as terrain.
            self._terrain = self.game_info.pathing_grid
        odd = kind not in {U.SUPPLYDEPOT, U.MISSILETURRET}  # 3x3 footprints centre on half cells.
        half = 1.5 if odd else 1
        reserved = self._reserved_areas()
        obstacles = self._resource_obstacles()
        production, edges = kind in PRODUCTION, kind not in EDGE_EXEMPT
        candidates, seen = [], set()
        for anchor in self._anchors(kind):
            if len(candidates) >= PLACEMENT_QUERY:
                break
            for dx, dy in ANCHOR_OFFSETS:
                x, y = round(anchor.x) + dx, round(anchor.y) + dy
                point = Point2((x + .5, y + .5)) if odd else Point2((x, y))
                if point in seen:
                    continue
                seen.add(point)
                try:
                    if not grid[(int(point.x), int(point.y))]:
                        continue
                except (AssertionError, IndexError):  # Outside the map.
                    continue
                if self._blocks_resources(point, kind, obstacles) or self._overlaps(point, half, reserved):
                    continue
                if production and self._overlaps(point.offset((2.5, -0.5)), 1, reserved):
                    continue
                if production and self._blocks_resources(point.offset((2.5, -0.5)), kind, obstacles):
                    continue
                if edges and not self._clear_of_edges(point, kind):
                    continue
                candidates.append(point)
        return candidates

    async def _placement(self, kind):
        # Two batched engine queries; per-spot queries stall the realtime game.
        candidates = self._placement_candidates(kind)[:PLACEMENT_QUERY]
        if not candidates:
            return None
        valid = [p for p, ok in zip(candidates, await self.can_place(kind, candidates)) if ok]
        if valid and kind in PRODUCTION:
            addons = await self.can_place(U.SUPPLYDEPOT, [p.offset((2.5, -0.5)) for p in valid])
            valid = [p for p, ok in zip(valid, addons) if ok]
        if not valid:
            return None
        # A free spot can still be walled in by our own buildings or terrain; the SCV would walk
        # for ~40 s before the engine answers "couldn't reach target". Check paths in one batch.
        builder = self._builder(valid[0])
        if builder is None:
            return valid[0]
        checked = valid[:PATH_CHECKS]
        distances = await self.client.query_pathings([[builder, p] for p in checked])
        for position, distance in zip(checked, distances):
            if distance > 0:
                return position
            self._action_stats["unreachable_spots_skipped"] += 1
        return None

    # ---- local upkeep ---------------------------------------------------------

    async def _maintain_local_behaviors(self):
        if not any(command.unit.type_id == U.SCV for command in self.actions):
            self._balance_gas()
            workers, gas_buildings = self.workers, self.gas_buildings
            self.workers = workers.filter(lambda u: u.tag not in self._scouts and u.tag not in self._fleeing)
            if self._gas_throttled:
                # Otherwise worker distribution refills the Refineries every second.
                self.gas_buildings = gas_buildings.filter(lambda g: False)
            try:
                await self.distribute_workers(resource_ratio=4 if self.minerals < 150 and self.vespene > 250 else 2)
            finally:
                self.workers, self.gas_buildings = workers, gas_buildings
        for depot in self.structures(U.SUPPLYDEPOT).ready:
            depot(A.MORPH_SUPPLYDEPOT_LOWER)
        await self._early_defense()
        if not self._early_defense_window():
            self._siege_at_front()
        await self._keep_upgrading()
        await self._keep_tanks_coming()
        await self._grow_into_map()
        self._call_down_mules()
        await self._answer_air_threat()
        await self._answer_casters()
        self._spend_bank()
        self._resume_construction()
        self._deploy_units()
        self._stim()
        # Before army orders, so units sent into a Bunker are not ordered elsewhere this frame.
        self._man_bunkers()
        self._repair()
        self._clear_changelings()
        self._counter_attack()
        self._issue_army_intent()
        self._maintain_scouts_and_detection()

    async def on_unit_destroyed(self, unit_tag):
        await super().on_unit_destroyed(unit_tag)
        supply = self._enemy_army_supply.pop(unit_tag, None)
        if supply:
            self._enemy_losses.append((self.time, supply))
            if self._wave is not None:
                self._wave["enemy_lost"] += supply
        own = self._own_army_supply.pop(unit_tag, None)
        if own and self._wave is not None:
            self._wave["own_lost"] += own

    def _counter_attack(self):
        """Against CheatMoney and stronger: attack right after beating a Zerg wave, for a fixed window."""
        if not self.cautious_attacks:
            return
        for enemy in self.enemy_units:
            if enemy.is_visible and enemy.can_attack and enemy.type_id not in WORKERS:
                self._enemy_army_supply[enemy.tag] = self.calculate_supply_cost(enemy.type_id)
        while self._enemy_losses and self._enemy_losses[0][0] < self.time - COUNTER_LOOKBACK:
            self._enemy_losses.popleft()
        army = self._combat_units()
        self._record_waves(army)
        if self._counter_until is not None:
            threats = self._threat_units()
            threat = sum(self.calculate_supply_cost(e.type_id) for e in threats)
            far = (army and self.townhalls and threat >= COUNTER_RECALL_THREAT and army.center.distance_to(
                min(self.townhalls, key=lambda b: threats.closest_distance_to(b))) >= COUNTER_RECALL_DISTANCE)
            if self.time >= self._counter_until or not army or far:
                self._end_counter("base_attacked" if far else "window_over" if army else "army_gone")
            return
        killed = sum(supply for _, supply in self._enemy_losses)
        # A few Zerg units at a base are not a wave: in T113, maxed with 7-8 bases after 21:00, pokes of one to a few
        # units every 10-15 s kept resetting the quiet clock and the army stood at home while the Zerg wished to
        # surrender. Only an attack of COUNTER_RECALL_THREAT supply or more holds the push back.
        attack = sum(self.calculate_supply_cost(e.type_id) for e in self._threat_units()) >= COUNTER_RECALL_THREAT
        if attack:
            self._last_threat_seen = self.time
        quiet = self.time - self._last_threat_seen >= PUSH_IDLE
        if ((killed < COUNTER_ENEMY_LOSS and not quiet) or attack or not army or not self.townhalls
                or self._ready_army_supply() < COUNTER_MIN_ARMY or self.time - self._last_counter < COUNTER_COOLDOWN):
            return
        # No bank needed: a bot that spends as it goes never has one. In T112 it was maxed with 127 army at 15:15 and
        # beat a wave 90 to 55 at 16:40 with 51 minerals banked, so the push waited until 24:27 and met 7 Ultralisks;
        # the Cistern wins pushed at 12:29 (T104) and 14:07 (T111), before that army existed.
        if not (self.supply_used >= PUSH_MIN_SUPPLY and UpgradeId.TERRANINFANTRYWEAPONSLEVEL2 in self.state.upgrades):
            # The army leaves home only for the push: smaller counter-attacks cost far more than they gained
            # (T93: 33 army supply for no kill; T98: 23 and six Tanks, then a wave caught the army on its way home).
            return
        self._push_active = True
        bases = [m for m in self._known_enemy_buildings.values()
                 if m["type"] in {b.name for b in ZERG_BASES} and self._attack_allowed(m["position"])]
        target = min(bases, key=lambda m: army.center.distance_to(Point2(m["position"])))["id"] if bases else None
        self._counter_until = self.time + (PUSH_WINDOW if self._push_active else COUNTER_WINDOW)
        self._last_counter = self.time
        self._enemy_losses.clear()
        self.army_intent = "attack"
        self._army_target_id = target
        self._issue_army_intent(include_busy=True)
        self._action_stats["siege_pushes" if self._push_active else "counter_attacks"] += 1
        self.log("counter_attack", game_loop=self.state.game_loop, push=self._push_active, enemy_supply_killed=killed,
                 army_supply=self._ready_army_supply(), target_id=target)

    def _record_waves(self, army):
        """Log each Zerg attack on our bases with what it cost both sides; measurement only."""
        self._own_army_supply = {u.tag: self.calculate_supply_cost(u.type_id) for u in army}
        emergency = self._emergency()
        if emergency and self._wave is None:
            self._wave = {"start": self.time, "enemy_lost": 0, "own_lost": 0,
                          "army_at_start": self._ready_army_supply(),
                          "tanks_sieged_at_start": self.units(U.SIEGETANKSIEGED).amount,
                          "tanks_at_start": self.units.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}).amount}
            self.log("wave_start", game_loop=self.state.game_loop, **self._wave)
        elif not emergency and self._wave is not None:
            wave, self._wave = self._wave, None
            self.log("wave_over", game_loop=self.state.game_loop, seconds=round(self.time - wave["start"]),
                     enemy_supply_killed=wave["enemy_lost"], own_supply_lost=wave["own_lost"],
                     army_at_start=wave["army_at_start"], army_at_end=self._ready_army_supply(),
                     tanks_sieged_at_start=wave["tanks_sieged_at_start"], tanks_at_start=wave["tanks_at_start"])

    def _end_counter(self, why):
        self._counter_until = None
        self._push_active = False
        self._set_army_intent("defend")
        self.log("counter_attack_end", game_loop=self.state.game_loop, reason=why)

    async def _keep_upgrading(self):
        """Against CheatMoney and stronger: two Engineering Bays and an Armory, and the upgrades in order."""
        if not self.cautious_attacks or self.time - self._last_upgrade_check < UPGRADE_INTERVAL:
            return
        self._last_upgrade_check = self.time
        # These are not Jev's orders: keep their failures out of the feedback Jev reads.
        failures = list(self.temp_failure_list)
        try:
            for kind, count, start in UPGRADE_BUILDINGS:
                if (self.time >= start and self._count_with_pending(kind) < count and not self.already_pending(kind)
                        and self.tech_requirement_progress(kind) == 1 and self.can_afford(kind)):
                    await self._build_one(self._action_ids[f"BUILD {kind.name}"], kind)
                    self._upgraded("build_" + kind.name.lower())
                    break
            for upgrade in UPGRADES:
                if self._research_reason(upgrade) is None:
                    self._research_one(self._action_ids[f"RESEARCH {upgrade.name}"], upgrade)
                    self._upgraded(upgrade.name.lower())
                    break  # One per check: the researcher stays "idle" until the next step.
        finally:
            self.temp_failure_list = failures

    async def _keep_tanks_coming(self):
        """Against CheatMoney and stronger: four Factories with Tech Labs, and a Tank from every free one."""
        if not self.cautious_attacks or self.time - self._last_tank_check < TANK_INTERVAL:
            return
        self._last_tank_check = self.time
        # These are not Jev's orders: keep their failures out of the feedback Jev reads.
        failures = list(self.temp_failure_list)
        try:
            if (self.time >= TANK_FACTORIES_FROM and self._count_with_pending(U.FACTORY) < TANK_FACTORIES
                    and not self.already_pending(U.FACTORY) and self.tech_requirement_progress(U.FACTORY) == 1
                    and self.can_afford(U.FACTORY)):
                await self._build_one(self._action_ids["BUILD FACTORY"], U.FACTORY)
                self._tanks("build_factory")
            if self._addon_hosts(U.FACTORYTECHLAB) and self.can_afford(U.FACTORYTECHLAB):
                await self._build_addon(self._action_ids["ADDON FACTORYTECHLAB"], U.FACTORYTECHLAB)
                self._tanks("factory_techlab")
            tanks = self._count_with_pending(U.SIEGETANK) + self.units(U.SIEGETANKSIEGED).amount
            for factory in self._train_slots(U.SIEGETANK):
                if (tanks >= TANK_CAP or factory.tag in self.unit_tags_received_action
                        or not self.can_afford(U.SIEGETANK)):
                    break
                factory.train(U.SIEGETANK)
                tanks += 1
                self._tanks("train_siegetank")
        finally:
            self.temp_failure_list = failures

    def _tanks(self, what):
        self._action_stats[f"tanks_{what}"] += 1
        self.log("keep_tanks_coming", game_loop=self.state.game_loop, what=what)

    def _upgraded(self, what):
        self._action_stats[f"upgrade_{what}"] += 1
        self.log("keep_upgrading", game_loop=self.state.game_loop, what=what)

    def _early_defense_window(self):
        return self.cautious_attacks and self.time <= EARLY_DEFENSE_UNTIL

    async def _early_defense(self):
        """Against CheatMoney, until 9:30: Tanks, Marauders, a second Bunker and Tanks sieged at the front."""
        if not self._early_defense_window() or self.time - self._last_early_defense < 1:
            return
        self._last_early_defense = self.time
        for kind, limit in ((U.SIEGETANK, EARLY_TANKS), (U.MARAUDER, EARLY_MARAUDERS)):
            if self._count_with_pending(kind) >= limit:
                continue
            for producer in self._train_slots(kind):
                if producer.tag in self.unit_tags_received_action or not self.can_afford(kind):
                    break
                producer.train(kind)
                self._early("train_" + kind.name.lower())
                break
        if (self.time >= EARLY_BUNKER_FROM and self.structures(U.BARRACKS).ready
                and not self.already_pending(U.BUNKER) and self._count_with_pending(U.BUNKER) < EARLY_BUNKERS
                and self.can_afford(U.BUNKER)):
            failures = list(self.temp_failure_list)  # Not Jev's order: keep its failures out of Jev's feedback.
            try:
                await self._build_one(self._action_ids["BUILD BUNKER"], U.BUNKER)
            finally:
                self.temp_failure_list = failures
            self._early("bunker")
        self._siege_at_front()

    def _hold_window(self):
        """Tanks hold the front sieged: before 9:30, and afterwards while the army defends."""
        return self._early_defense_window() or (
            self.cautious_attacks and self.army_intent == "defend" and self._counter_until is None)

    def _hold_radius(self):
        return EARLY_SIEGE_RADIUS if self._early_defense_window() else HOLD_SIEGE_RADIUS

    def _defense_anchor(self, position):
        """Against CheatMoney and stronger, a defending army stays with the Tanks sieged at the front: in T97 the Tanks
        were sieged for nearly every wave, but the Marines and Marauders chased Zerg units 10-16 away, outside their
        cover, and the 13:11 and 15:18 waves were lost that way (124 -> 63 in five seconds, one or two Tanks lost)."""
        if not self._hold_window() or self._early_defense_window():
            return None
        sieged = self.units(U.SIEGETANKSIEGED).closer_than(HOLD_SIEGE_RADIUS + 4, position)
        if sieged:
            return sieged.center
        # Defending a base away from the Tanks: they go there, and the rest of the army moves with them rather
        # than ahead of them. In T99 and T100 the waves that hit a base away from the rally were lost (130 -> 14;
        # 124 -> 63) because the bio arrived first and fought before the Tanks were set up.
        tanks = self.units.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}).ready
        return tanks.center if tanks and tanks.center.distance_to(position) > HOLD_SIEGE_RADIUS else None

    defense_lead_types = frozenset({U.SIEGETANK})

    def _siege_at_front(self):
        if not self._hold_window():
            return
        front = self._defense_position()
        for tank in self.units(U.SIEGETANK).ready:
            if tank.distance_to(front) < self._hold_radius() and self._may_switch(tank):
                self._switch(tank, A.SIEGEMODE_SIEGEMODE)

    def _early(self, what):
        self._action_stats[f"early_{what}"] += 1
        self.log("early_defense", game_loop=self.state.game_loop, what=what)

    def _holding_front(self, tank):
        """A Tank sieged at the front stays sieged while no enemy is near (before 9:30, or while defending)."""
        return self._hold_window() and tank.distance_to(self._defense_position()) < self._hold_radius() + 2

    async def _grow_into_map(self):
        """Against CheatMoney and stronger: spend a mineral surplus on bases, Planetary Fortresses, turrets and gas,
        and Scan unexplored expansion sites."""
        if not self.cautious_attacks or self.time - self._last_grow < GROW_INTERVAL:
            return
        self._last_grow = self.time
        self._scout_by_scan()
        if self.structures(U.ORBITALCOMMAND).amount >= GROW_ORBITALS:
            hosts = self._morph_hosts(U.PLANETARYFORTRESS)
            if hosts and self.can_afford(U.PLANETARYFORTRESS):
                hosts[0](MORPHS[U.PLANETARYFORTRESS])
                self._grown("planetary_fortress")
        if self.minerals < GROW_BANK:
            return
        # These are not Jev's orders: keep their placement failures out of the feedback Jev reads.
        failures = list(self.temp_failure_list)
        try:
            await self._grow_structures()
        finally:
            self.temp_failure_list = failures

    async def _grow_structures(self):
        bases = self.townhalls.amount
        if (not self.already_pending(U.COMMANDCENTER) and bases < self.contract.building_limits["COMMANDCENTER"]
                and self.can_afford(U.COMMANDCENTER)):
            await self._build_expansion(self._action_ids["BUILD COMMANDCENTER"], U.COMMANDCENTER)
            self._grown("base")
        if (self.structures(U.ENGINEERINGBAY).ready and not self.already_pending(U.MISSILETURRET)
                and self._count_with_pending(U.MISSILETURRET) < min(bases, self.contract.building_limits["MISSILETURRET"])
                and self.can_afford(U.MISSILETURRET)):
            await self._build_one(self._action_ids["BUILD MISSILETURRET"], U.MISSILETURRET)
            self._grown("missile_turret")
        if (not self.already_pending(U.REFINERY) and self._assimilator_candidates()
                and self.gas_buildings.amount < min(2 * self.townhalls.ready.amount, self.contract.building_limits["REFINERY"])
                and self.can_afford(U.REFINERY)):
            await self._build_one(self._action_ids["BUILD REFINERY"], U.REFINERY)
            self._grown("refinery")

    def _grown(self, what):
        self._action_stats[f"grow_{what}"] += 1
        self.log("grow_into_map", game_loop=self.state.game_loop, what=what, minerals=self.minerals)

    def _scout_by_scan(self):
        """Scan the expansion site checked longest ago (never first) that is away from our bases."""
        if self.time - self._last_scout_scan < SCOUT_SCAN_INTERVAL:
            return
        orbitals = self.structures(U.ORBITALCOMMAND).ready.filter(
            lambda o: o.energy >= 50 and o.tag not in self.unit_tags_received_action)
        sites = [s for s in self._search_sites
                 if not any(b.distance_to(Point2(s["position"])) < 15 for b in self.townhalls)]
        if not orbitals or not sites:
            return
        site = min(sites, key=lambda s: (s["last_checked"] is not None, s["last_checked"] or 0))
        orbitals.first(A.SCANNERSWEEP_SCAN, Point2(site["position"]))
        self._last_scout_scan = self.time
        self._action_stats["scout_scans"] += 1
        self.log("scout_scan", game_loop=self.state.game_loop, site=site["id"], position=site["position"])

    async def _answer_air_threat(self):
        """Once Brood Lord tech is seen, add a second Starport and Reactors first, then keep Vikings coming."""
        seen = [e for e in list(self.enemy_units) + list(self.enemy_structures) if e.type_id in AIR_TECH]
        if seen and self._air_threat_since is None:
            self._air_threat_since = self.time
            self.log("air_threat", game_loop=self.state.game_loop, types=sorted({e.type_id.name for e in seen}))
        self._broodlords_seen = max(self._broodlords_seen, sum(
            1 for e in self.enemy_units if e.type_id in {U.BROODLORD, U.BROODLORDCOCOON}))
        if self._air_threat_since is None or self.time - self._last_air_response < 1:
            return
        self._last_air_response = self.time
        starports = self.structures(U.STARPORT).amount + self.already_pending(U.STARPORT)
        if (starports < AIR_STARPORTS and self.tech_requirement_progress(U.STARPORT) == 1
                and self.can_afford(U.STARPORT)):
            await self._build_one(self._action_ids["BUILD STARPORT"], U.STARPORT)
        elif self.can_afford(U.STARPORTREACTOR) and self._addon_hosts(U.STARPORTREACTOR):
            await self._build_addon(self._action_ids["ADDON STARPORTREACTOR"], U.STARPORTREACTOR)
        target = min(VIKINGS_MAX, max(VIKINGS_MIN, VIKINGS_PER_BROODLORD * self._broodlords_seen))
        vikings = self._count_with_pending(U.VIKINGFIGHTER) + self.units(U.VIKINGASSAULT).amount
        used = Counter()
        trained = 0
        for starport in self._train_slots(U.VIKINGFIGHTER):
            free = (2 if starport.has_reactor else 1) - len(starport.orders)
            if starport.tag in self.unit_tags_received_action or used[starport.tag] >= free:
                continue
            if vikings + trained >= target or not self.can_afford(U.VIKINGFIGHTER):
                break
            starport.train(U.VIKINGFIGHTER)
            used[starport.tag] += 1
            trained += 1
        if trained:
            self._action_stats["anti_air_vikings"] += trained
            self.log("anti_air_vikings", game_loop=self.state.game_loop, trained=trained,
                     vikings=vikings + trained, target=target)

    async def _answer_casters(self):
        """Against CheatMoney and stronger: once Infestors or Vipers are seen, a Ghost Academy and Ghosts."""
        if not self.cautious_attacks or self.time - self._last_caster_response < 1:
            return
        self._last_caster_response = self.time
        seen = [e for e in self.enemy_units if e.type_id in CASTERS]
        if seen and self._casters_since is None:
            self._casters_since = self.time
            self.log("caster_threat", game_loop=self.state.game_loop, types=sorted({e.type_id.name for e in seen}))
        if self._casters_since is None:
            return
        # Not Jev's orders (Ghosts are not in its action list): keep their failures out of the feedback Jev reads.
        failures = list(self.temp_failure_list)
        try:
            if (not self._count_with_pending(U.GHOSTACADEMY) and not self.already_pending(U.GHOSTACADEMY)
                    and self.tech_requirement_progress(U.GHOSTACADEMY) == 1 and self.can_afford(U.GHOSTACADEMY)):
                await self._build_one(self.empty_action, U.GHOSTACADEMY)
                self._ghosts("build_ghostacademy")
            ghosts = self._count_with_pending(U.GHOST)
            for barracks in self._train_slots(U.GHOST):
                if (ghosts >= GHOST_CAP or barracks.tag in self.unit_tags_received_action
                        or not self.can_afford(U.GHOST)):
                    break
                barracks.train(U.GHOST)
                ghosts += 1
                self._ghosts("train_ghost")
        finally:
            self.temp_failure_list = failures

    def _ghosts(self, what):
        self._action_stats[f"ghosts_{what}"] += 1
        self.log("answer_casters", game_loop=self.state.game_loop, what=what)

    def _emp_casters(self):
        """Each Ghost with the energy EMPs the visible Infestor or Viper with most undrained casters around it."""
        casters = [e for e in self.enemy_units if e.type_id in CASTERS and e.is_visible
                   and self._emp_until.get(e.tag, 0) <= self.time]
        if not casters:
            return
        for ghost in self.units(U.GHOST).ready:
            if ghost.energy < EMP_ENERGY or ghost.tag in self.unit_tags_received_action:
                continue
            near = [c for c in casters if ghost.distance_to(c) <= EMP_REACH]
            if not near:
                continue
            target = max(near, key=lambda c: (sum(1 for o in casters if o.distance_to(c) <= EMP_RADIUS),
                                              -ghost.distance_to(c)))
            hit = [c for c in casters if c.distance_to(target) <= EMP_RADIUS]
            ghost(A.EMP_EMP, target.position)
            for caster in hit:
                self._emp_until[caster.tag] = self.time + EMP_REPEAT
            casters = [c for c in casters if c not in hit]
            self._action_stats["ghost_emps"] += 1
            self.log("ghost_emp", game_loop=self.state.game_loop, ghost_tag=ghost.tag,
                     targets=[c.type_id.name for c in hit])
            if not casters:
                return

    def _spend_bank(self):
        """Queue army in every idle production slot while unspent minerals pile up."""
        if self.minerals < self.contract.bank_minerals or self.time - self._last_bank_spend < 1:
            return
        self._last_bank_spend = self.time
        used = Counter()
        trained = Counter()
        for unit_type in CAUTIOUS_BANK_ARMY if self.cautious_attacks else BANK_ARMY:
            limit = self.contract.unit_limits.get(unit_type.name)
            count = self._count_with_pending(unit_type)
            cost = self.calculate_cost(unit_type)
            for producer in self._train_slots(unit_type):
                free = (2 if producer.has_reactor else 1) - len(producer.orders)
                if (producer.tag in self.unit_tags_received_action or used[producer.tag] >= free
                        or limit is not None and count + trained[unit_type] >= limit
                        or self._over_cautious_cap(unit_type, trained[unit_type])):
                    continue
                if not self.can_afford(unit_type) or self.minerals - cost.minerals < BANK_SPEND_FLOOR:
                    break
                if self.gas_reserve and cost.vespene and unit_type != U.SIEGETANK \
                        and self.vespene - cost.vespene < self.gas_reserve:
                    break  # Scripted play keeps gas for Tanks.
                producer.train(unit_type)
                used[producer.tag] += 1
                trained[unit_type] += 1
        if trained:
            self._action_stats["bank_army_units"] += sum(trained.values())
            self.log("bank_army_spend", game_loop=self.state.game_loop, minerals=self.minerals,
                     units={k.name: v for k, v in trained.items()})

    def _balance_gas(self):
        """Move SCVs from gas to minerals while unspent gas piles up far beyond minerals."""
        on, off = (CAUTIOUS_GAS_THROTTLE_ON, CAUTIOUS_GAS_THROTTLE_OFF) if self.cautious_attacks else (
            GAS_THROTTLE_ON, GAS_THROTTLE_OFF)
        if self.cautious_attacks and self.minerals >= CAUTIOUS_GAS_KEEP_MINERALS:
            if self._gas_throttled:
                self._gas_throttled = False
                self.log("gas_throttle", game_loop=self.state.game_loop, active=False,
                         gas=self.vespene, minerals=self.minerals)
            return
        if self._gas_throttled and self.vespene < off:
            self._gas_throttled = False
            self.log("gas_throttle", game_loop=self.state.game_loop, active=False,
                     gas=self.vespene, minerals=self.minerals)
        elif not self._gas_throttled and self.vespene >= on and (
                self.cautious_attacks or self.vespene > 2 * self.minerals):
            self._gas_throttled = True
            self.log("gas_throttle", game_loop=self.state.game_loop, active=True,
                     gas=self.vespene, minerals=self.minerals)
        if not self._gas_throttled:
            return
        bases = self.townhalls.ready
        fields = self.mineral_field.filter(lambda m: any(m.distance_to(b) < 10 for b in bases))
        if not fields:
            return
        gas = {g.tag for g in self.gas_buildings}
        for worker in self.workers:
            # A worker carrying gas returns it first; it is moved on the next pass.
            if (worker.order_target in gas and not worker.is_carrying_vespene
                    and worker.tag not in self.unit_tags_received_action):
                worker.gather(fields.closest_to(worker))
                self._action_stats["gas_to_minerals"] += 1

    def _clear_changelings(self):
        """Changelings are not attacked automatically; the nearest soldiers shoot visible ones."""
        army = self._combat_units().filter(lambda u: u.can_attack and u.type_id not in self.stationary_army_types)
        for changeling in (e for e in self.enemy_units if e.is_visible and e.type_id.name.startswith("CHANGELING")):
            shooters = sorted((u for u in army if u.distance_to(changeling) < 12
                               and u.tag not in self.unit_tags_received_action),
                              key=lambda u: u.distance_to(changeling))
            for unit in shooters[:3]:
                unit.attack(changeling)

    def _lurker_threat(self):
        if any(e.type_id in LURKERS for e in list(self.enemy_units) + list(self.enemy_structures)):
            self._lurker_seen = self.time
        return self.time - self._lurker_seen < LURKER_MEMORY

    def _scan_for_burrowed(self):
        """Scan ahead of a fighting army when Lurkers are about and no Raven is with it."""
        if not self._lurker_threat() or self.time - self._last_scan < SCAN_INTERVAL:
            return
        army = self._combat_units()
        if not army or not any(u.weapon_cooldown > 0 for u in army):
            return
        centre = army.center
        if any(r.distance_to(centre) < 10 for r in self.units(U.RAVEN).ready):
            return
        orbitals = self.structures(U.ORBITALCOMMAND).ready.filter(
            lambda o: o.energy >= 50 and o.tag not in self.unit_tags_received_action)
        if not orbitals:
            return
        target = centre.towards(self._army_destination, 6) if self._army_destination else centre
        orbitals.first(A.SCANNERSWEEP_SCAN, target)
        self._last_scan = self.time
        self._action_stats["scans"] += 1
        self.log("scanner_sweep", game_loop=self.state.game_loop, position=list(target))

    def _call_down_mules(self):
        # Keep 50 energy for a scan while Lurkers may be burrowed nearby.
        keep = 50 if self._lurker_threat() else 0
        bases = self.townhalls.ready
        fields = self.mineral_field.filter(lambda m: any(m.distance_to(b) < 10 for b in bases))
        if not fields:
            return
        for orbital in self.structures(U.ORBITALCOMMAND).ready:
            if orbital.energy >= 50 + keep and orbital.tag not in self.unit_tags_received_action:
                orbital(A.CALLDOWNMULE_CALLDOWNMULE, max(fields, key=lambda m: m.mineral_contents))

    def _resume_construction(self):
        self._resume_orders = {t: s for t, s in self._resume_orders.items() if self.time - s < 10}
        for structure in self.structures_without_construction_SCVs:
            if structure.tag in self._resume_orders:
                continue
            if any(e.can_attack and e.distance_to(structure) < 10 for e in self.enemy_units if e.is_visible):
                continue
            worker = self._builder(structure.position)
            if worker is not None:
                worker(A.SMART, structure)
                self._resume_orders[structure.tag] = self.time
                self.log("construction_resumed", game_loop=self.state.game_loop, structure=structure.type_id.name,
                         structure_tag=structure.tag, worker_tag=worker.tag)

    def _fast_micro(self):
        self._emp_casters()
        self._snipe_ultralisks()
        self._workers_flee_banelings()
        self._dodge_banelings()
        self._scan_for_burrowed()

    def _snipe_ultralisks(self):
        """Ghosts with the energy, and no Infestor or Viper in EMP reach, snipe the nearest Ultralisk."""
        if not self.cautious_attacks:
            return
        targets = [e for e in self.enemy_units if e.type_id in SNIPE_TARGETS and e.is_visible]
        if not targets:
            return
        casters = [e for e in self.enemy_units if e.type_id in CASTERS and e.is_visible]
        now = self.time
        self._snipes = {tag: [t for t in times if t > now] for tag, times in getattr(self, "_snipes", {}).items()}
        for ghost in self.units(U.GHOST).ready:
            if ghost.energy < SNIPE_ENERGY or ghost.tag in self.unit_tags_received_action:
                continue
            if any(ghost.distance_to(c) <= EMP_REACH for c in casters) or ghost.is_using_ability(A.EFFECT_GHOSTSNIPE):
                continue
            near = [t for t in targets if ghost.distance_to(t) <= SNIPE_REACH
                    and len(self._snipes.get(t.tag, [])) < SNIPES_PER_ULTRALISK]
            if not near:
                continue
            target = min(near, key=lambda t: ghost.distance_to(t))
            ghost(A.EFFECT_GHOSTSNIPE, target)
            self._snipes.setdefault(target.tag, []).append(now + 2)
            self._action_stats["ghost_snipes"] += 1

    def _workers_flee_banelings(self):
        """SCVs near Banelings run behind their Command Center and stay off the minerals until the Banelings are gone."""
        banelings = [e for e in self.enemy_units if e.type_id == U.BANELING and e.is_visible]
        workers = {w.tag: w for w in self.workers}
        self._fleeing = {tag for tag in self._fleeing if tag in workers and any(
            workers[tag].distance_to(b) < WORKER_FLEE_CLEAR for b in banelings)}
        if not banelings or not self.townhalls:
            return
        for worker in workers.values():
            if (worker.tag in self._scouts or worker.is_constructing_scv or worker.is_repairing
                    or worker.tag in self.unit_tags_received_action):
                continue
            near = [b for b in banelings if worker.distance_to(b) < WORKER_FLEE_RANGE]
            if not near:
                continue
            hall = self.townhalls.closest_to(worker)
            danger = Point2((sum(b.position.x for b in near) / len(near), sum(b.position.y for b in near) / len(near)))
            if hall.distance_to(danger) < 1:
                refuge = worker.position.towards(danger, -WORKER_FLEE_DISTANCE)
            else:
                refuge = hall.position.towards(danger, -WORKER_FLEE_DISTANCE)
            worker.move(refuge)
            if worker.tag not in self._fleeing:
                self._fleeing.add(worker.tag)
                self._action_stats["workers_fled_banelings"] += 1

    def _dodge_banelings(self):
        banelings = [e for e in self.enemy_units if e.type_id == U.BANELING and e.is_visible]
        if not banelings:
            return
        builders = {w.tag for w in self.workers if w.is_constructing_scv or w.is_repairing}
        dodgers = list(self.units(U.MARINE).ready) + [w for w in self.workers
                                                        if w.tag not in builders and w.tag not in self._scouts]
        for unit in dodgers:
            if unit.tag in self.unit_tags_received_action:
                continue
            baneling = min(banelings, key=lambda b: unit.distance_to(b))
            if unit.distance_to(baneling) >= BANELING_DODGE_RANGE:
                continue
            away = unit.position.towards(baneling.position, -BANELING_DODGE_STEP)
            # Alternate sides so neighbours spread out instead of running in a clump.
            dx, dy = away.x - unit.position.x, away.y - unit.position.y
            side = 1 if unit.tag % 2 else -1
            unit.move(Point2((away.x - dy * side * .5, away.y + dx * side * .5)))
            self._action_stats["baneling_dodges"] += 1

    def _ground_threats(self):
        return [e for e in self.enemy_units if e.is_visible and e.can_attack and not e.is_flying
                and not e.type_id.name.startswith("CHANGELING")]

    def _man_bunkers(self):
        threats = self._ground_threats()
        for bunker in self.structures(U.BUNKER).ready:
            near = any(e.distance_to(bunker) < 12 for e in threats)
            if not near:
                if self.army_intent == "attack" and bunker.cargo_used:
                    bunker(A.UNLOADALL_BUNKER)
                continue
            room = bunker.cargo_max - bunker.cargo_used
            marines = sorted((m for m in self.units(U.MARINE).ready
                              if m.distance_to(bunker) < 15 and m.tag not in self._scouts
                              and m.tag not in self.unit_tags_received_action),
                             key=lambda m: m.distance_to(bunker))
            for marine in marines[:max(0, room)]:
                marine(A.SMART, bunker)

    def _repair(self):
        """Up to two SCVs repair a damaged Bunker or Planetary Fortress while it is under fire."""
        if self.minerals < 25:
            return
        threats = self._ground_threats()
        for target in self.structures.of_type({U.BUNKER, U.PLANETARYFORTRESS}).ready:
            if target.health_percentage >= 1 or not any(e.distance_to(target) < 12 for e in threats):
                continue
            busy = sum(1 for w in self.workers if w.is_repairing and w.distance_to(target) < 4)
            helpers = sorted((w for w in self._free_workers() if w.distance_to(target) < 25),
                             key=lambda w: w.distance_to(target))
            for worker in helpers[:max(0, 2 - busy)]:
                worker(A.EFFECT_REPAIR_SCV, target)

    def _may_switch(self, unit):
        return (self.time - self._mode_changed.get(unit.tag, -100) >= MODE_HOLD
                and unit.tag not in self.unit_tags_received_action)

    def _switch(self, unit, ability):
        unit(ability)
        self._mode_changed[unit.tag] = self.time

    def _deploy_units(self):
        enemies = [e for e in list(self.enemy_units) + list(self.enemy_structures)
                   if e.is_visible and not e.type_id.name.startswith("CHANGELING")]
        ground = [e for e in enemies if not e.is_flying]
        retreating = self.army_intent == "retreat"
        # Zerg army units, not buildings or workers, trigger the longer defensive siege range.
        early = self.cautious_attacks and self.army_intent == "defend"
        army_ground = [e for e in ground if e.can_attack and e.type_id not in WORKERS
                       and not getattr(e, "is_structure", False)] if early else []

        def nearest(unit, targets):
            return min((unit.distance_to(e) for e in targets), default=math.inf)

        for tank in self.units(U.SIEGETANK).ready:
            if (not retreating and (nearest(tank, ground) < 13 or nearest(tank, army_ground) < DEFENSE_SIEGE_RANGE)
                    and self._may_switch(tank)):
                self._switch(tank, A.SIEGEMODE_SIEGEMODE)
        for tank in self.units(U.SIEGETANKSIEGED):
            far = nearest(tank, ground) > 15 and nearest(tank, army_ground) > DEFENSE_UNSIEGE_RANGE
            if (retreating or far) and not self._holding_front(tank) and self._may_switch(tank):
                self._switch(tank, A.UNSIEGE_UNSIEGE)
        for mine in self.units(U.WIDOWMINE).ready:
            if not retreating and nearest(mine, enemies) < 8 and self._may_switch(mine):
                self._switch(mine, A.BURROWDOWN_WIDOWMINE)
        for mine in self.units(U.WIDOWMINEBURROWED):
            if (retreating or nearest(mine, enemies) > 12) and self._may_switch(mine):
                self._switch(mine, A.BURROWUP_WIDOWMINE)
        alive = {u.tag for u in self.units}
        self._mode_changed = {t: s for t, s in self._mode_changed.items() if t in alive}

    def _stim(self):
        if UpgradeId.STIMPACK not in self.state.upgrades:
            return
        threats = [e for e in self.enemy_units if e.is_visible and e.can_attack]
        if not threats:
            return
        for kind, ability, buff in ((U.MARINE, A.EFFECT_STIM_MARINE, BuffId.STIMPACK),
                                    (U.MARAUDER, A.EFFECT_STIM_MARAUDER, BuffId.STIMPACKMARAUDER)):
            for unit in self.units(kind).ready:
                if (unit.health_percentage >= .7 and not unit.has_buff(buff)
                        and unit.tag not in self.unit_tags_received_action
                        and any(unit.distance_to(e) < 7 for e in threats)):
                    unit(ability)

    def _maintain_escorts(self):
        army = self._combat_units()
        destination = army.center.towards(self._defense_position(), 3) if army else self._defense_position()
        free = lambda u: u.tag not in self._scouts and u.tag not in self.unit_tags_received_action
        ravens = self.units(U.RAVEN).ready.filter(free)
        detector = ravens.sorted(lambda u: u.tag).first if ravens and army else None
        if detector is not None and detector.distance_to(destination) > 4:
            detector.move(destination)
        # Medivacs heal only when idle or attack-moving, so attack-move them over the front of the bio (the Marines
        # and Marauders nearest where the army is going), never interrupting a heal. Sending them to the centre of
        # all combat units with move orders kept them away from the fights (they outlived the army in T59-T65).
        bio = army.of_type({U.MARINE, U.MARAUDER})
        if bio:
            heading = self._army_destination or self._defense_position()
            front = bio.closest_n_units(heading, MEDIVAC_FRONT).center
        else:
            front = destination
        for unit in self.units(U.MEDIVAC).ready.filter(free):
            if unit.distance_to(front) > MEDIVAC_SLACK and not unit.is_using_ability(A.MEDIVACHEAL_HEAL):
                unit.attack(front)
        for unit in ravens:
            if unit is not detector and unit.distance_to(destination) > 5:
                unit.move(destination)
