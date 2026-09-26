"""Jev macro executor for Terran: SC2-checked legality, placement and local unit upkeep."""

import math
from collections import Counter

from sc2.bot_ai import BotAI
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Units

from ...agent.macro_contract import TERRAN, SPENDING_KINDS, attack_floor
from .jev_macro_bot import JevMacroBot

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
# During an attack: enemy supply at a base that recalls a far-away army, how far "far" is,
# how long attacking stays blocked afterwards, and how many Siege Tanks stay home.
RECALL_THREAT_SUPPLY = 8
RECALL_DISTANCE = 35
RECALL_ATTACK_BLOCK = 30
HOME_GUARD_TANKS = 2
# During an attack, compare the enemy units within FIGHT_RANGE of our army (away from our bases, where
# the recall handles raids) with our units near them. Pull back when that enemy is this many times
# stronger, or when the attack has cost this share of the army and that enemy is at least as strong.
# The army moves away for a few seconds, then defends, and attacking stays blocked for a while.
FIGHT_RANGE = 12
FIGHT_ARRIVING = 5
BASE_AREA = 15
DISENGAGE_RATIO = 1.4
DISENGAGE_LOSS = 0.35
DISENGAGE_MIN_ENEMY = 10
DISENGAGE_MOVE_SECONDS = 8
DISENGAGE_ATTACK_BLOCK = 45
# Units that fight without a weapon of their own.
ENEMY_CASTERS = {U.INFESTOR, U.INFESTORBURROWED, U.VIPER, U.SWARMHOSTMP}
# Tanks siege when ground enemies come this close (siege range is 13) and unsiege past the second distance.
SIEGE_DISTANCE = 15
UNSIEGE_DISTANCE = 17
# Brood Lords and Corruptors call for Vikings: two per Brood Lord (or cocoon), one per Corruptor,
# up to the cap, while one was seen in the last AIR_MEMORY seconds.
VIKINGS_PER_BROODLORD = 2
VIKING_CAP = 12
AIR_MEMORY = 180
# Mining SCVs this close to a Baneling step away from it. Marines and Marauders this close shoot the
# nearest Baneling when their weapon is ready and step away while it reloads (or when one is on top of them).
BANELING_DODGE_RANGE = 5
BANELING_DODGE_STEP = 3
BANELING_FIRE_RANGE = 7
BANELING_TOO_CLOSE = 1.5
# During an attack, Marines and Marauders not in a fight wait for the Siege Tanks: those more than this
# much closer to the target than the leading tank walk back to it.
TANK_LEASH = 6
BIO = {U.MARINE, U.MARAUDER}
# Pull SCVs off gas while this much gas is banked and it is more than twice the minerals;
# send them back once gas falls below the lower mark.
GAS_THROTTLE_ON = 300
GAS_THROTTLE_OFF = 150
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
                        "recall_on_raid", "disengage_losing_fights", "bio_waits_for_tanks", "baneling_target_fire", "home_guard_tanks", "anti_air_response",
                        "army_intent_execution", "tank_siege",
                        "widow_mine_burrow", "combat_stimpack", "assigned_scout_missions",
                        "medivac_and_raven_escort"]

    def _initialize_race(self):
        super()._initialize_race()
        self.military_unit_types = set(COMBAT | SUPPORT)
        self._mode_changed = {}
        self._resume_orders = {}
        self._rejected_spots = {}
        self._addon_blocked = {}
        self._gas_throttled = False
        self._lurker_seen = -1000
        self._banelings_seen = False
        self._air_threat = 0
        self._air_seen = -1000
        self._attack_peak = 0
        self._disengage_until = -1000
        self._disengaging = False
        self._last_scan = -1000

    # ---- counts and forecasts -------------------------------------------------

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
        # Deployed forms are the same unit for counting purposes.
        forms = {U.SIEGETANK: {U.SIEGETANK, U.SIEGETANKSIEGED},
                 U.WIDOWMINE: {U.WIDOWMINE, U.WIDOWMINEBURROWED},
                 U.VIKINGFIGHTER: {U.VIKINGFIGHTER, U.VIKINGASSAULT},
                 U.LIBERATOR: {U.LIBERATOR, U.LIBERATORAG}}.get(kind, {kind})
        return self.units.of_type(forms).ready.amount + self.already_pending(kind)

    def _conditional_tech(self, catalog):
        """A Planetary Fortress at the third base once Banelings have been seen; Vikings against Brood Lords."""
        ids = {d: a for a, d in self.contract.actions.items()}
        count = lambda name: catalog.get(str(ids[name]), {}).get("count_with_pending", 0)
        due = []
        if self._banelings_seen and self.townhalls.amount >= 3 and count("MORPH PLANETARYFORTRESS") == 0:
            due.append(ids["MORPH PLANETARYFORTRESS"])
        if self._air_threat and self.time - self._air_seen <= AIR_MEMORY:
            vikings = min(VIKING_CAP, self._air_threat)
            if count("TRAIN VIKINGFIGHTER") < vikings:
                due.append(ids["TRAIN VIKINGFIGHTER"])
            if count("BUILD STARPORT") < (2 if vikings >= 6 else 1):
                due.append(ids["BUILD STARPORT"])
        return tuple(due)

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
        if self._train_producer(unit_type, ignore_resources) is not None:
            return None
        return "no_ready_producer_with_available_ability"

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
        hosts = [c for c in self.structures(U.COMMANDCENTER).ready
                 if c.is_idle and c.tag not in self.unit_tags_received_action
                 and self._has_ability(c, MORPHS[target], ignore_resources=ignore_resources)]
        # Orbitals at the safe main first; a Planetary Fortress on the most exposed base.
        return sorted(hosts, key=lambda c: c.distance_to(self.start_location),
                      reverse=target == U.PLANETARYFORTRESS)

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
                    if not self.can_afford(unit_type) or (limit is not None and count + trained >= limit):
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

    def _blocks_resources(self, position, kind):
        resources = self.mineral_field | self.vespene_geyser
        clearance = 3 if kind == U.MISSILETURRET else 4 if kind == U.BUNKER else 6
        if any(r.distance_to(position) < clearance for r in resources.closer_than(12, position)):
            return True
        return (kind not in {U.MISSILETURRET, U.BUNKER}
                and any(t.distance_to(position) < 7 for t in self.townhalls))

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
            # Rings of points, nearest first, starting on the side away from the mineral line.
            for distance in ((10, 14, 18) if kind in PRODUCTION else (8, 12, 16)):
                for turn in (0, 0.5, -0.5, 1.0, -1.0, 1.5, -1.5, 2.0, -2.0, 2.6, -2.6):
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

    def _placement_candidates(self, kind):
        """Grid-aligned spots near the anchors, nearest anchor first, after local filtering."""
        grid = self.game_info.placement_grid
        odd = kind not in {U.SUPPLYDEPOT, U.MISSILETURRET}  # 3x3 footprints centre on half cells.
        half = 1.5 if odd else 1
        reserved = self._reserved_areas()
        candidates, seen = [], set()
        for anchor in self._anchors(kind):
            for dx, dy in sorted(((x, y) for x in range(-4, 5, 2) for y in range(-4, 5, 2)),
                                 key=lambda d: abs(d[0]) + abs(d[1])):
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
                if self._blocks_resources(point, kind) or self._overlaps(point, half, reserved):
                    continue
                if kind in PRODUCTION and self._overlaps(point.offset((2.5, -0.5)), 1, reserved):
                    continue
                if kind in PRODUCTION and self._blocks_resources(point.offset((2.5, -0.5)), kind):
                    continue
                candidates.append(point)
        return candidates

    async def _placement(self, kind):
        # Two batched engine queries; per-spot queries stall the realtime game.
        candidates = self._placement_candidates(kind)[:400]
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
            self.workers = workers.filter(lambda u: u.tag not in self._scouts)
            if self._gas_throttled:
                # Otherwise worker distribution refills the Refineries every second.
                self.gas_buildings = gas_buildings.filter(lambda g: False)
            try:
                await self.distribute_workers(resource_ratio=4 if self.minerals < 150 and self.vespene > 250 else 2)
            finally:
                self.workers, self.gas_buildings = workers, gas_buildings
        for depot in self.structures(U.SUPPLYDEPOT).ready:
            depot(A.MORPH_SUPPLYDEPOT_LOWER)
        self._call_down_mules()
        self._resume_construction()
        self._recall_to_defend()
        self._disengage()
        self._deploy_units()
        self._stim()
        # Before army orders, so units sent into a Bunker are not ordered elsewhere this frame.
        self._man_bunkers()
        self._repair()
        self._clear_changelings()
        self._wait_for_tanks()
        self._issue_army_intent()
        self._maintain_scouts_and_detection()

    def _balance_gas(self):
        """Move SCVs from gas to minerals while unspent gas piles up far beyond minerals."""
        if self._gas_throttled and self.vespene < GAS_THROTTLE_OFF:
            self._gas_throttled = False
            self.log("gas_throttle", game_loop=self.state.game_loop, active=False,
                     gas=self.vespene, minerals=self.minerals)
        elif not self._gas_throttled and self.vespene >= GAS_THROTTLE_ON and self.vespene > 2 * self.minerals:
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
        self._dodge_banelings()
        self._scan_for_burrowed()
        self._track_air_threat()

    def _track_air_threat(self):
        visible = [e for e in self.enemy_units if e.is_visible]
        threat = sum(VIKINGS_PER_BROODLORD for e in visible if e.type_id in {U.BROODLORD, U.BROODLORDCOCOON})
        threat += sum(1 for e in visible if e.type_id == U.CORRUPTOR)
        if threat:
            if self.time - self._air_seen > AIR_MEMORY:
                self._air_threat = 0
            self._air_threat = max(self._air_threat, threat)
            self._air_seen = self.time

    def _dodge_banelings(self):
        banelings = [e for e in self.enemy_units if e.type_id == U.BANELING and e.is_visible]
        if not banelings:
            return
        self._banelings_seen = True
        builders = {w.tag for w in self.workers if w.is_constructing_scv or w.is_repairing}
        for unit in self.units.of_type(BIO).ready:
            if unit.tag in self.unit_tags_received_action or unit.tag in self._scouts:
                continue
            baneling = min(banelings, key=lambda b: unit.distance_to(b))
            distance = unit.distance_to(baneling)
            if distance >= BANELING_FIRE_RANGE:
                continue
            if unit.weapon_cooldown == 0 and distance >= BANELING_TOO_CLOSE:
                if unit.order_target != baneling.tag:
                    unit.attack(baneling)
                    self._action_stats["baneling_shots"] += 1
                continue
            self._step_away(unit, baneling)
        miners = [w for w in self.workers if w.tag not in builders and w.tag not in self._scouts]
        for unit in miners:
            if unit.tag in self.unit_tags_received_action:
                continue
            baneling = min(banelings, key=lambda b: unit.distance_to(b))
            if unit.distance_to(baneling) >= BANELING_DODGE_RANGE:
                continue
            self._step_away(unit, baneling)

    def _step_away(self, unit, baneling):
        away = unit.position.towards(baneling.position, -BANELING_DODGE_STEP)
        # Alternate sides so neighbours spread out instead of running in a clump.
        dx, dy = away.x - unit.position.x, away.y - unit.position.y
        side = 1 if unit.tag % 2 else -1
        unit.move(Point2((away.x - dy * side * .5, away.y + dx * side * .5)))
        self._action_stats["baneling_dodges"] += 1

    def _recall_to_defend(self):
        """Bring an attacking army home when a base is raided behind it."""
        if self.army_intent != "attack":
            return
        army = self._combat_units()
        threats = self._threat_units()
        if not army or not threats or not self.townhalls:
            return
        base = min(self.townhalls, key=lambda b: threats.closest_distance_to(b))
        raid = threats.closer_than(20, base)
        supply = sum(self.calculate_supply_cost(e.type_id) for e in raid)
        if supply < RECALL_THREAT_SUPPLY or army.center.distance_to(base) < RECALL_DISTANCE:
            return
        self._set_army_intent("defend")
        attack = self.contract.action_for("attack")
        self.cooldowns[attack] = self.time + RECALL_ATTACK_BLOCK
        self._action_stats["army_recalls"] += 1
        self.log("army_recalled", game_loop=self.state.game_loop, base_tag=base.tag,
                 enemy_supply=supply, army_distance=round(army.center.distance_to(base), 1))

    def _disengage(self):
        """Pull an attacking army out of a fight it is losing, before it is gone."""
        if self._disengaging and self.time >= self._disengage_until:
            self._disengaging = False
            if self.army_intent == "retreat":
                # Far enough; fight again, near the bases.
                self._set_army_intent("defend")
                return
        if self.army_intent != "attack":
            self._attack_peak = 0
            return
        guard = self._home_guard()
        army = self._combat_units().filter(lambda u: u.tag not in guard)
        ready = self._ready_army_supply()
        self._attack_peak = max(self._attack_peak, ready)
        if not army:
            return
        # The fight is where our army meets the enemy, not the army's center: a marching or split
        # army has few units there. Raids on our bases are left to the recall.
        enemies = [e for e in self.enemy_units
                   if e.is_visible and (e.can_attack or e.type_id in ENEMY_CASTERS)
                   and e.type_id.name not in ("DRONE", "SCV", "PROBE")
                   and not e.type_id.name.startswith("CHANGELING")
                   and not any(e.distance_to(b) < BASE_AREA for b in self.townhalls)
                   and army.closest_distance_to(e) < FIGHT_RANGE]
        enemy = sum(self.calculate_supply_cost(e.type_id) for e in enemies)
        if enemy < DISENGAGE_MIN_ENEMY:
            return
        # Units a little farther away are still arriving at the fight.
        fighting = Units(enemies, self)
        ours = sum(self.calculate_supply_cost(u.type_id) for u in army
                   if fighting.closest_distance_to(u) < FIGHT_RANGE + FIGHT_ARRIVING)
        lost = 1 - ready / self._attack_peak if self._attack_peak else 0
        if enemy < DISENGAGE_RATIO * ours and not (lost >= DISENGAGE_LOSS and enemy >= ours):
            return
        self._set_army_intent("retreat")
        self._disengage_until = self.time + DISENGAGE_MOVE_SECONDS
        self._disengaging = True
        self.cooldowns[self.contract.action_for("attack")] = self.time + DISENGAGE_ATTACK_BLOCK
        self._action_stats["army_disengages"] += 1
        self.log("army_disengaged", game_loop=self.state.game_loop, enemy_supply=enemy, army_supply=ours,
                 lost_share=round(lost, 2))
        self._attack_peak = 0

    def _wait_for_tanks(self):
        """Keep Marines and Marauders with the Siege Tanks on the way to a fight, so the tanks are there when it starts."""
        if self.army_intent != "attack" or self._army_destination is None:
            return
        guard = self._home_guard()
        tanks = self.units.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}).ready.filter(lambda t: t.tag not in guard)
        if not tanks:
            return
        target = self._army_destination
        lead = min(tanks, key=lambda t: t.distance_to(target))
        front = lead.distance_to(target)
        enemies = self._ground_threats()
        for unit in self.units.of_type(BIO).ready:
            if (unit.tag in self.unit_tags_received_action or unit.tag in self._scouts
                    or unit.distance_to(target) >= front - TANK_LEASH
                    or any(unit.distance_to(e) < 10 for e in enemies)):
                continue
            unit.move(lead.position.towards(target, 2))
            self._action_stats["waits_for_tanks"] += 1

    def _home_guard(self):
        if self.army_intent != "attack" or not self.townhalls:
            return set()
        home = self._defense_position()
        tanks = sorted(self.units.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}).ready, key=lambda t: t.distance_to(home))
        return {t.tag for t in tanks[:HOME_GUARD_TANKS]}

    def _held_army_tags(self):
        guard = self._home_guard()
        home = self._defense_position()
        for tank in self.units.of_type({U.SIEGETANK}).ready:
            if (tank.tag in guard and tank.distance_to(home) > 6
                    and tank.tag not in self.unit_tags_received_action):
                tank.move(home)
        return guard

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

        def nearest(unit, targets):
            return min((unit.distance_to(e) for e in targets), default=math.inf)

        for tank in self.units(U.SIEGETANK).ready:
            if not retreating and nearest(tank, ground) < SIEGE_DISTANCE and self._may_switch(tank):
                self._switch(tank, A.SIEGEMODE_SIEGEMODE)
        for tank in self.units(U.SIEGETANKSIEGED):
            if (retreating or nearest(tank, ground) > UNSIEGE_DISTANCE) and self._may_switch(tank):
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
        # Idle Medivacs heal nearby units on their own; keep them with the army.
        for unit in self.units(U.MEDIVAC).ready.filter(free):
            if unit.distance_to(destination) > 5:
                unit.move(destination)
        for unit in ravens:
            if unit is not detector and unit.distance_to(destination) > 5:
                unit.move(destination)
