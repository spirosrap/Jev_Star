"""Jev macro adapter for the existing LLM Play SC2 Protoss observation/actions."""

import threading

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId

from ...agent.macro_contract import PROTOSS, DEFEND_ACTION, UNIT_LIMITS, BUILDING_LIMITS
from .Protoss_bot import Protoss_Bot
from .jev_macro_bot import JevMacroBot


class JevProtossBot(JevMacroBot, Protoss_Bot):
    contract = PROTOSS
    local_automation = ["worker_distribution", "gateway_morph", "army_intent_execution",
                        "assigned_scout_missions", "one_observer_army_escort"]

    def _initialize_race(self):
        Protoss_Bot.__init__(self, {}, threading.Lock(), threading.Event())
        self.military_unit_types.update({U.SENTRY, U.MOTHERSHIP})

    def _ability_query_units(self):
        return self.units.of_type({U.HIGHTEMPLAR, U.DARKTEMPLAR}).ready

    def _train_reason(self, unit_type, ignore_resources=False):
        if not ignore_resources and not self.can_afford(unit_type):
            return "resources_or_supply"
        limit = UNIT_LIMITS.get(unit_type.name)
        if limit is not None and self._count_with_pending(unit_type) >= limit:
            return "unit_policy_limit"
        for producer in self._producers:
            if producer.type_id not in UNIT_TRAINED_FROM.get(unit_type, set()) or not producer.is_idle:
                continue
            info = TRAIN_INFO[producer.type_id][unit_type]
            if info.get("requires_power") and not producer.is_powered:
                continue
            if self._has_ability(producer, info["ability"], ignore_resources=ignore_resources):
                return None
        return "no_ready_producer_with_available_ability"

    def _build_reason(self, unit_type, worker, ignore_resources=False):
        if not worker:
            return "no_available_builder"
        if not ignore_resources and not self.can_afford(unit_type):
            return "building_resources"
        info = TRAIN_INFO[U.PROBE].get(unit_type)
        if not info or not self._has_ability(worker, info["ability"], ignore_resources=ignore_resources):
            return "missing_build_ability_or_technology"
        if self.already_pending(unit_type) >= (3 if unit_type == U.PYLON else 1):
            return "already_pending"
        limit = BUILDING_LIMITS.get(unit_type.name)
        if limit is not None and self._count_with_pending(unit_type) >= limit:
            return "building_policy_limit"
        if unit_type == U.PYLON:
            forecast = self._supply_forecast()
            if not forecast["needs_supply"] and not forecast["needs_power"]:
                return "supply_and_power_sufficient"
        elif unit_type == U.ASSIMILATOR:
            if not self._assimilator_candidates():
                return "no_free_geyser_at_ready_base"
        elif unit_type != U.NEXUS:
            if not self.structures(U.PYLON).ready:
                return "no_ready_pylon"
        return None

    async def available_actions(self):
        worker = await self._refresh_abilities()
        choices, blocked = {}, {}
        for action, description in self.action_dict.items():
            reason = None
            if self.cooldowns.get(action, 0) > self.time:
                reason = "recent_executor_rejection"
            elif action <= 17:
                reason = self._train_reason(U[description.split()[1]])
            elif action == 18:
                if not self._archon_pair():
                    reason = "need_two_available_templars"
            elif action <= 33:
                reason = self._build_reason(U[description.split()[1]], worker)
            elif action <= 59:
                reason = self._research_reason(UpgradeId[description.split()[1]])
            elif action <= 63:
                if not self._scout_candidates(U[description.split()[1]]):
                    reason = "no_available_scout_keep_army_detector"
                elif self.time - self._last_scout_order < 15:
                    reason = "scout_order_cooldown"
            elif action == 64:
                retarget = self._planned_target() != self._army_target_id
                if not self._combat_units() or self._ready_army_supply() < 10 or (self.army_intent == "attack" and not retarget):
                    reason = "need_army_or_already_attacking"
            elif action == 65:
                if not self._combat_units() or self.army_intent == "retreat":
                    reason = "no_army_or_already_retreating"
            elif action == DEFEND_ACTION:
                if not self._combat_units() or self.army_intent == "defend":
                    reason = "no_army_or_already_defending"
            elif action <= 70:
                target_type = U[description.split()[1]]
                targets = self.structures(target_type).ready.filter(
                    lambda u: not u.is_idle and not u.has_buff(BuffId.CHRONOBOOSTENERGYCOST))
                if not targets or not any(self._has_ability(n, AbilityId.EFFECT_CHRONOBOOSTENERGYCOST)
                                          for n in self.townhalls.ready):
                    reason = "no_chronoboost_target_or_energy"
            if reason:
                blocked[str(action)] = reason
            else:
                choices[action] = description
        return choices, blocked

    def _reservation_reason(self, action):
        """Why a planned purchase cannot happen yet, ignoring banked resources."""
        if action <= 17:
            return self._train_reason(U[self.contract.kind_name(action)], ignore_resources=True)
        if 19 <= action <= 33:
            return self._build_reason(U[self.contract.kind_name(action)], self._build_worker_for_catalog,
                                      ignore_resources=True)
        if 34 <= action <= 59:
            return self._research_reason(UpgradeId[self.contract.kind_name(action)], ignore_resources=True)
        return None

    async def _perform(self, action):
        if action <= 17:
            await self._train_one(action, U[self.action_dict[action].split()[1]])
        elif 19 <= action <= 33:
            await self._build_one(action, U[self.action_dict[action].split()[1]])
        elif 34 <= action <= 59:
            self._research_one(action, UpgradeId[self.action_dict[action].split()[1]])
        elif 60 <= action <= 63:
            await self._start_scout(action, U[self.action_dict[action].split()[1]])
        else:
            await getattr(self, f"handle_action_{action}")()

    def _combat_units(self):
        reserved = self._morph_reserved_tags()
        return self.units.of_type(self.military_unit_types).ready.filter(
            lambda u: (u.can_attack or u.type_id in {U.CARRIER, U.SENTRY})
            and u.type_id not in {U.ORACLE, U.DISRUPTOR, U.WARPPRISM, U.OBSERVER}
            and u.tag not in reserved)

    async def _maintain_local_behaviors(self):
        # Do not replace a fresh construction/scouting order using this frame's old worker state.
        if not any(command.unit.type_id == U.PROBE for command in self.actions):
            workers = self.workers
            self.workers = workers.filter(lambda u: u.tag not in self._scouts)
            try:
                await self.distribute_workers(resource_ratio=4 if self.minerals < 150 and self.vespene > 250 else 2)
            finally:
                self.workers = workers
        if self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1:
            gateways = self.structures(U.GATEWAY).ready.idle.filter(
                lambda u: u.tag not in self.unit_tags_received_action)
            if gateways:
                for gate, abilities in zip(gateways, await self.get_available_abilities(gateways)):
                    if AbilityId.MORPH_WARPGATE in abilities:
                        gate(AbilityId.MORPH_WARPGATE)
        self._issue_army_intent()
        self._maintain_scouts_and_detection()

    async def produce_bg_unit(self, action_id, unit_type, required_buildings=None):
        # Continue using ordinary Gateways while researched gates are morphing.
        gates = self.structures(U.GATEWAY).ready.idle
        ability = TRAIN_INFO[U.GATEWAY][unit_type]["ability"]
        for gate in gates:
            if self._has_ability(gate, ability):
                gate.train(unit_type)
                return
        pylons = self.structures(U.PYLON).ready
        if pylons:
            await self.warp_unit(action_id, unit_type, pylons.closest_to(self.start_location).position)
        else:
            self.record_failure(action_id, "No ready pylon for warp-in")

    async def warp_unit(self, action_id, unit_type, initial_reference_point,
                        required_buildings=None, max_attempts=5):
        ability = TRAIN_INFO[U.WARPGATE][unit_type]["ability"]
        self._warp_reservations = [(p, t) for p, t in self._warp_reservations if self.time - t < 10]
        references = [initial_reference_point]
        references += [p.position for p in sorted(self.structures(U.PYLON).ready,
                       key=lambda p: p.distance_to(initial_reference_point)) if p.distance_to(initial_reference_point) > 4][:3]
        for gate in self.structures(U.WARPGATE).ready.idle:
            if not self._has_ability(gate, ability):
                continue
            for reference in references:
                for distance in range(1, max_attempts + 1):
                    pos = reference.random_on_distance(distance)
                    placement = await self.find_placement(ability, pos, max_distance=6, placement_step=1)
                    if not placement or placement.distance_to(reference) > 6:
                        continue
                    if any(placement.distance_to(p) < 1.5 for p, _ in self._warp_reservations):
                        continue
                    if any(u.distance_to(placement) < getattr(u, "radius", .5) + .7 for u in self.units):
                        continue
                    gate.warp_in(unit_type, placement)
                    self._warp_reservations.append((placement, self.time))
                    return
        self.record_failure(action_id, "No available warpgate or warp-in placement")

    async def apply_chronoboost(self, action_id, target_type, supply_requirement, description):
        targets = self.structures(target_type).ready.filter(
            lambda u: not u.is_idle and not u.has_buff(BuffId.CHRONOBOOSTENERGYCOST))
        for nexus in self.townhalls.ready:
            if targets and self._has_ability(nexus, AbilityId.EFFECT_CHRONOBOOSTENERGYCOST):
                nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, targets.first)
                return
        self.record_failure(action_id, "No eligible chronoboost target or Nexus")

    async def handle_action_18(self):
        pair = self._archon_pair()
        if not pair:
            self.record_failure(18, "need_two_available_templars")
            return
        # SC2 97563 omits this multi-unit ability from single-unit queries.
        # The controlled engine probe verifies the grouped two-tag command.
        for unit in pair:
            unit(AbilityId.MORPH_ARCHON)

    async def handle_action_64(self):
        self._set_army_intent("attack")

    async def handle_action_65(self):
        self._set_army_intent("retreat")

    async def handle_action_72(self):
        self._set_army_intent("defend")
