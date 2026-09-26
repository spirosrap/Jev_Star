"""Terran contract, plan validation and executor regressions with a fake SC2 world."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
from sc2.data import Race
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.units import Units

import test_jev_protoss as support
from sc2_rl_agent.starcraftenv_test.agent.astra_planner import PlannerError, plan_schema, validate_plan
from sc2_rl_agent.starcraftenv_test.agent.jev_agent import Decision, JevClient, TERRAN_INSTRUCTIONS
from sc2_rl_agent.starcraftenv_test.agent.macro_contract import PROTOSS, TERRAN, primary_action, tech_due
from sc2_rl_agent.starcraftenv_test.agent.strategic_policy import policy_reason
from sc2_rl_agent.starcraftenv_test.env.bot.hierarchical_terran_bot import HierarchicalTerranBot
from sc2_rl_agent.starcraftenv_test.env.bot.jev_terran_bot import JevTerranBot


def terran_plan(**changes):
    plan = {"objective": "Reaper expand into bio", "goals": [{"action_id": 18, "target": 2},
                                                              {"action_id": 34, "target": 1}],
            "worker_target": 30, "base_target": 2, "allowed_spending_actions": [0, 1, 16, 18, 19, 26, 34],
            "reserve_for_action": 18, "reserve_after_workers": 16, "army_posture": "defend",
            "attack_min_army": 30, "retreat_below_army": 10, "min_posture_seconds": 20,
            "guidance": "Expand, then Stimpack.", "priority_action": None, "production_priority": [18, 34],
            "army_target_id": None}
    plan.update(changes)
    return plan


def terran_catalog():
    c = {str(a): {"cost": {"minerals": 0, "gas": 0}, "count_with_pending": 0} for a in TERRAN.actions}
    for action, cost in [(0, 50), (1, 50), (16, 100), (18, 400)]:
        c[str(action)]["cost"]["minerals"] = cost
    c["0"]["count_with_pending"] = 30
    c["18"]["count_with_pending"] = 1
    return c


def resource(**changes):
    value = {"worker_supply": 20, "mineral": 350, "gas": 0, "supply_left": 1,
             "supply_cap": 31, "army_supply": 4, "ready_army_supply": 4, "needs_supply": True}
    value.update(changes)
    return value


class TerranContractTests(unittest.TestCase):
    def test_catalog_kinds_and_limits(self):
        self.assertEqual(len(TERRAN.actions), 71)
        self.assertEqual(TERRAN.spending_actions, (*range(63), 70))
        self.assertEqual(TERRAN.kinds[70], "build")
        self.assertIn(70, TERRAN.urgent_defense_actions)
        self.assertEqual(TERRAN.army_actions, {66: "attack", 67: "retreat", 68: "defend"})
        self.assertEqual((TERRAN.worker_action, TERRAN.base_action, TERRAN.supply_action, TERRAN.empty_action),
                         (0, 18, 16, 69))
        self.assertEqual(TERRAN.kinds[26], "addon")
        self.assertEqual(TERRAN.kinds[32], "morph")
        self.assertEqual(TERRAN.limits[34], 1)
        self.assertEqual(TERRAN.limits[19], 12)
        for action, kind in TERRAN.kinds.items():
            if kind in {"train", "build", "addon", "morph"}:
                U[TERRAN.kind_name(action)]
            elif kind == "research":
                UpgradeId[TERRAN.kind_name(action)]

    def test_protoss_contract_matches_previous_constants(self):
        self.assertEqual(PROTOSS.spending_actions, tuple(range(60)))
        self.assertEqual(PROTOSS.priority_actions, (*range(71), 72))
        self.assertEqual(PROTOSS.single_target_actions, frozenset(range(34, 60)))

    def test_schema_uses_terran_ids(self):
        schema = plan_schema(TERRAN)
        self.assertEqual(schema["properties"]["goals"]["items"]["properties"]["action_id"]["enum"], [*range(63), 70])
        self.assertIn(68, schema["properties"]["priority_action"]["enum"])
        self.assertNotIn(69, schema["properties"]["priority_action"]["enum"])

    def test_terran_plan_validation(self):
        self.assertEqual(validate_plan(terran_plan(), contract=TERRAN)["goals"][0]["action_id"], 18)
        with self.assertRaisesRegex(PlannerError, "invalid_spending_action_id"):
            validate_plan(terran_plan(allowed_spending_actions=[0, 18, 34, 66]), contract=TERRAN)
        with self.assertRaisesRegex(PlannerError, "invalid_goal_target"):
            validate_plan(terran_plan(goals=[{"action_id": 34, "target": 2}], reserve_for_action=None,
                                      production_priority=[]), contract=TERRAN)
        with self.assertRaisesRegex(PlannerError, "base_goal_exceeds_cap"):
            validate_plan(terran_plan(base_target=1), contract=TERRAN)
        with self.assertRaisesRegex(PlannerError, "priority_action_conflicts_with_posture"):
            validate_plan(terran_plan(priority_action=66), contract=TERRAN)
        self.assertEqual(validate_plan(terran_plan(priority_action=68), contract=TERRAN)["priority_action"], 68)

    def test_terran_policy(self):
        args = (terran_plan(), terran_catalog(), resource(), "defend", 0, 100, False)
        self.assertEqual(policy_reason(0, *args, contract=TERRAN), "plan_worker_target_reached")
        # A needed Supply Depot overrides the reserve for the second Command Center.
        self.assertIsNone(policy_reason(16, *args, contract=TERRAN))
        self.assertEqual(policy_reason(1, *args, contract=TERRAN), "plan_resource_reservation")
        self.assertEqual(policy_reason(66, *args, contract=TERRAN), "plan_attack_not_ready")
        self.assertIsNone(policy_reason(69, *args, contract=TERRAN))
        emergency = (terran_plan(), terran_catalog(), resource(), "defend", 0, 100, True)
        self.assertIsNone(policy_reason(1, *emergency, contract=TERRAN))

    def test_banked_minerals_allow_army_beyond_the_plan(self):
        plan = terran_plan(reserve_for_action=None)
        catalog = terran_catalog()
        rich = (plan, catalog, resource(mineral=650), "defend", 0, 100, False)
        poor = (plan, catalog, resource(mineral=550), "defend", 0, 100, False)
        self.assertEqual(policy_reason(7, *poor, contract=TERRAN), "plan_spending_not_allowed")
        self.assertIsNone(policy_reason(7, *rich, contract=TERRAN))
        self.assertIsNone(policy_reason(19, *rich, contract=TERRAN))
        plan["goals"].append({"action_id": 1, "target": 5})
        catalog["1"]["count_with_pending"] = 5
        self.assertIsNone(policy_reason(1, *rich, contract=TERRAN))
        self.assertEqual(policy_reason(1, *poor, contract=TERRAN), "plan_goal_target_reached")
        # Research is not part of the override.
        self.assertEqual(policy_reason(37, *rich, contract=TERRAN), "plan_spending_not_allowed")
        # Protoss keeps following the plan strictly.
        self.assertEqual(PROTOSS.bank_override_actions, frozenset())

    def test_due_tech_keeps_its_money(self):
        plan = terran_plan(reserve_for_action=None, allowed_spending_actions=[0, 1, 16, 18, 19, 26, 34])
        catalog = terran_catalog()
        catalog["0"]["count_with_pending"] = 10
        catalog["10"].update(cost={"minerals": 150, "gas": 75}, recommended=True)  # Vikings.
        catalog["1"]["cost"] = {"minerals": 50, "gas": 0}
        catalog["26"]["cost"] = {"minerals": 50, "gas": 50}
        args = lambda m, g: (plan, catalog, resource(mineral=m, gas=g, supply_left=20, needs_supply=False),
                             "defend", 0, 100, False)
        self.assertEqual(policy_reason(1, *args(180, 100), contract=TERRAN), "scheduled_tech_reservation")
        self.assertEqual(policy_reason(26, *args(400, 100), contract=TERRAN), "scheduled_tech_reservation")
        self.assertIsNone(policy_reason(1, *args(250, 100), contract=TERRAN))
        self.assertIsNone(policy_reason(10, *args(180, 100), contract=TERRAN))
        self.assertIsNone(policy_reason(0, *args(100, 0), contract=TERRAN))  # Workers and depots go on.
        catalog["10"]["reservation_blocked"] = "no_ready_producer_with_available_ability"
        self.assertIsNone(policy_reason(1, *args(180, 100), contract=TERRAN))

    def test_supply_reserve_keeps_money_for_a_needed_depot(self):
        plan = terran_plan(reserve_for_action=None, allowed_spending_actions=[0, 1, 16, 18, 19, 26, 34])
        catalog = terran_catalog()
        catalog["0"]["count_with_pending"] = 10
        low = (plan, catalog, resource(mineral=120, supply_left=2, needs_supply=True), "defend", 0, 100, False)
        self.assertEqual(policy_reason(1, *low, contract=TERRAN), "plan_supply_reserve")
        self.assertIsNone(policy_reason(16, *low, contract=TERRAN))
        enough = (plan, catalog, resource(mineral=160, supply_left=2, needs_supply=True), "defend", 0, 100, False)
        self.assertIsNone(policy_reason(1, *enough, contract=TERRAN))
        catalog["16"]["pending"] = 1  # A depot is already on its way.
        self.assertIsNone(policy_reason(1, *low, contract=TERRAN))
        catalog["16"]["pending"] = 0
        roomy = (plan, catalog, resource(mineral=120, supply_left=8, needs_supply=True), "defend", 0, 100, False)
        self.assertIsNone(policy_reason(1, *roomy, contract=TERRAN))
        self.assertFalse(PROTOSS.supply_reserve)

    def test_primary_action_applies_terran_posture(self):
        plan = terran_plan(army_posture="attack", attack_min_army=10)
        self.assertEqual(primary_action(plan, {66: "MULTI-ATTACK"}, "defend", 45, contract=TERRAN),
                         (66, "apply_army_order_before_optional_production"))
        # Below the Terran attack floor the plan's lower threshold does not start an attack.
        self.assertEqual(primary_action(plan, {66: "MULTI-ATTACK"}, "defend", 30, contract=TERRAN)[0], None)

    def test_banked_minerals_recommend_another_barracks(self):
        plan = terran_plan(reserve_for_action=None)
        choices = {1: "TRAIN MARINE", 19: "BUILD BARRACKS", 69: "EMPTY ACTION"}
        self.assertEqual(primary_action(plan, choices, "defend", 5, contract=TERRAN, minerals=650),
                         (19, "spend_banked_minerals"))
        self.assertEqual(primary_action(plan, choices, "defend", 5, contract=TERRAN, minerals=500)[0], None)
        # An army order and the commander's own priority come first.
        attack = terran_plan(army_posture="attack", attack_min_army=40, reserve_for_action=None)
        self.assertEqual(primary_action(attack, {**choices, 66: "MULTI-ATTACK"}, "defend", 50,
                                        contract=TERRAN, minerals=650)[0], 66)
        priority = terran_plan(priority_action=1, reserve_for_action=None)
        self.assertEqual(primary_action(priority, choices, "defend", 5, contract=TERRAN, minerals=650)[0], 1)
        # Protoss has no bank recommendation.
        self.assertEqual(PROTOSS.bank_spend_actions, ())

    def test_no_retreat_from_an_attacked_base_while_the_army_is_healthy(self):
        plan = terran_plan(army_posture="defend", retreat_below_army=40, reserve_for_action=None)
        healthy = (plan, terran_catalog(), resource(ready_army_supply=110), "defend", 0, 100, True)
        weak = (plan, terran_catalog(), resource(ready_army_supply=30), "defend", 0, 100, True)
        calm = (plan, terran_catalog(), resource(ready_army_supply=110), "defend", 0, 100, False)
        self.assertEqual(policy_reason(67, *healthy, contract=TERRAN), "plan_hold_defense")
        self.assertIsNone(policy_reason(67, *weak, contract=TERRAN))
        self.assertIsNone(policy_reason(67, *calm, contract=TERRAN))
        self.assertFalse(PROTOSS.hold_defense)

    def test_cheating_ai_attack_floor_waits_for_a_big_army(self):
        import dataclasses
        cheat = dataclasses.replace(TERRAN, min_attack_army=90, maxed_attack_army=60)
        plan = terran_plan(army_posture="attack", attack_min_army=45, reserve_for_action=None)
        def reason(ready, supply):
            return policy_reason(66, plan, terran_catalog(), resource(ready_army_supply=ready, supply_used=supply),
                                 "defend", 0, 100, False, contract=cheat)
        self.assertEqual(reason(60, 150), "plan_attack_not_ready")
        self.assertIsNone(reason(95, 150))
        self.assertIsNone(reason(65, 192))  # A maxed army may attack with less ready supply.
        self.assertEqual(reason(55, 192), "plan_attack_not_ready")
        self.assertEqual(primary_action(plan, {66: "MULTI-ATTACK"}, "defend", 60, contract=cheat, supply_used=150)[0], None)
        self.assertEqual(primary_action(plan, {66: "MULTI-ATTACK"}, "defend", 95, contract=cheat, supply_used=150)[0], 66)
        # The normal floor is unchanged.
        self.assertIsNone(policy_reason(66, plan, terran_catalog(), resource(ready_army_supply=60, supply_used=150),
                                        "defend", 0, 100, False, contract=TERRAN))

    def test_planner_uses_terran_prompt_for_a_modified_terran_contract(self):
        import dataclasses, tempfile
        from unittest.mock import patch
        from sc2_rl_agent.starcraftenv_test.agent.astra_planner import CodexPlannerClient, TERRAN_PLANNER_INSTRUCTIONS
        cheat = dataclasses.replace(TERRAN, min_attack_army=90)
        with tempfile.TemporaryDirectory() as tmp, patch(
                "sc2_rl_agent.starcraftenv_test.agent.astra_planner.find_codex", return_value=Path("codex")):
            client = CodexPlannerClient(tmp, contract=cheat)
        self.assertIs(client.instructions, TERRAN_PLANNER_INSTRUCTIONS)

    def test_tech_schedule_recommends_upgrades_on_time(self):
        catalog = terran_catalog()
        self.assertEqual(tech_due(TERRAN, 250, catalog), ())
        self.assertEqual(tech_due(TERRAN, 300, catalog), (21,))  # Factory first.
        due = tech_due(TERRAN, 500, catalog)
        # Factory, Factory Tech Lab, Siege Tanks, Widow Mines, then Engineering Bay, upgrades, Armory.
        self.assertEqual(due[:8], (21, 28, 7, 6, 20, 37, 40, 23))
        catalog["20"]["count_with_pending"] = 1  # Engineering Bay started: no longer due.
        self.assertNotIn(20, tech_due(TERRAN, 500, catalog))
        catalog["7"]["count_with_pending"] = 1  # One Siege Tank of the two: still due.
        self.assertIn(7, tech_due(TERRAN, 500, catalog))
        catalog["7"]["count_with_pending"] = 2
        self.assertNotIn(7, tech_due(TERRAN, 500, catalog))
        plan = terran_plan(reserve_for_action=None)
        choices = {1: "TRAIN MARINE", 20: "BUILD ENGINEERINGBAY", 23: "BUILD ARMORY"}
        self.assertEqual(primary_action(plan, choices, "defend", 5, contract=TERRAN, tech_due=(20, 23)),
                         (20, "tech_schedule"))
        # The commander's own priority still comes first.
        self.assertEqual(primary_action(terran_plan(priority_action=1, reserve_for_action=None), choices,
                                        "defend", 5, contract=TERRAN, tech_due=(20,))[0], 1)
        self.assertEqual(PROTOSS.tech_schedule, ())

    def test_scheduled_tech_is_allowed_beyond_the_plan(self):
        plan = terran_plan(reserve_for_action=None)  # Engineering Bay (20) is not in the plan.
        catalog = terran_catalog()
        early = (plan, catalog, resource(mineral=200), "defend", 0, 300, False)
        late = (plan, catalog, resource(mineral=200), "defend", 0, 400, False)
        self.assertEqual(policy_reason(20, *early, contract=TERRAN), "plan_spending_not_allowed")
        self.assertIsNone(policy_reason(20, *late, contract=TERRAN))
        catalog["20"]["count_with_pending"] = 1
        self.assertEqual(policy_reason(20, *late, contract=TERRAN), "plan_spending_not_allowed")

    def test_attack_needs_forty_ready_army_supply(self):
        plan = terran_plan(army_posture="attack", attack_min_army=28, reserve_for_action=None)
        weak = (plan, terran_catalog(), resource(ready_army_supply=30), "defend", 0, 100, False)
        strong = (plan, terran_catalog(), resource(ready_army_supply=42), "defend", 0, 100, False)
        self.assertEqual(policy_reason(66, *weak, contract=TERRAN), "plan_attack_not_ready")
        self.assertIsNone(policy_reason(66, *strong, contract=TERRAN))
        self.assertEqual(PROTOSS.min_attack_army, 0)

    def test_terran_jev_prompt(self):
        client = JevClient("test-only", instructions=TERRAN_INSTRUCTIONS)
        payload = client.payload({}, {0: "TRAIN SCV", 69: "EMPTY ACTION"})
        instructions = payload["questions"]["next_macro_action"]["instructions"]
        self.assertIn("Terran", instructions)
        self.assertNotIn("Protoss", instructions)


class FakeTerranUnit(support.FakeUnit):
    def __init__(self, tag, kind, position=(10, 10)):
        super().__init__(tag, kind, position)
        self.orders = []
        self.has_add_on = self.has_techlab = self.has_reactor = False
        self.is_carrying_resource = self.is_flying = self.is_carrying_vespene = False
        self.is_constructing_scv = self.is_repairing = False
        self.weapon_cooldown = 0
        self.order_target = None
        self.is_gathering = kind == U.SCV
        self.can_attack = kind in {U.MARINE, U.SIEGETANK, U.SIEGETANKSIEGED}
        self.build = Mock()
        self.build_gas = Mock()
        self.gather = Mock()
        self.mineral_contents = 1800

    def __call__(self, ability, target=None, queue=False, **_):
        self.commands.append((ability, target))


class TerranAdapterTests(unittest.IsolatedAsyncioTestCase):
    bot_class = JevTerranBot

    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        client = JevClient("test-only", transport=httpx.MockTransport(lambda _: httpx.Response(500)))
        self.bot = self.make_bot(client)
        self.bot._initialize_variables()
        self.bot.state = SimpleNamespace(game_loop=0, upgrades=set())
        self.bot.enemy_race = Race.Zerg
        self.bot.game_info = SimpleNamespace(player_start_location=Point2((10, 10)),
                                             start_locations=[Point2((100, 100))], map_center=Point2((55, 55)))
        self.bot.game_data = SimpleNamespace(abilities={}, upgrades={})
        self.scv, self.cc = FakeTerranUnit(1, U.SCV), FakeTerranUnit(2, U.COMMANDCENTER)
        self.set_world([self.scv], [self.cc])
        self.bot.already_pending = Mock(return_value=0)
        self.bot.already_pending_upgrade = Mock(return_value=0)
        self.bot.worker_en_route_to_build = Mock(return_value=0)
        self.bot.supply_workers = 1
        self.bot.calculate_supply_cost = Mock(return_value=1)
        self.bot.is_visible = Mock(return_value=False)
        self.bot.can_afford = Mock(return_value=True)
        self.abilities = {self.cc.tag: {TRAIN_INFO[U.COMMANDCENTER][U.SCV]["ability"]}}
        self.bot.get_available_abilities = AsyncMock(side_effect=lambda units, **kwargs: [
            list(self.abilities.get(u.tag, ())) for u in units])
        # Every spot is reachable unless a test says otherwise.
        self.bot.client = SimpleNamespace(query_pathings=AsyncMock(side_effect=lambda pairs: [10.0] * len(pairs)))

    def make_bot(self, client):
        return JevTerranBot(client, Path(self.directory.name))

    def set_world(self, units, structures, enemies=()):
        self.bot.units = Units(units, self.bot)
        self.bot.workers = Units([u for u in units if u.type_id == U.SCV], self.bot)
        self.bot.structures = Units(structures, self.bot)
        self.bot.townhalls = support.FakeBases([s for s in structures if s.type_id in {
            U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS}], self.bot)
        self.bot.enemy_units = Units(list(enemies), self.bot)
        self.bot.enemy_structures = Units([], self.bot)
        self.bot.gas_buildings = Units([s for s in structures if s.type_id == U.REFINERY], self.bot)

    async def asyncTearDown(self):
        await self.bot.shutdown("test")
        self.directory.cleanup()

    async def test_opening_mask(self):
        choices, blocked = await self.bot.available_actions()
        self.assertEqual(choices, {0: "TRAIN SCV", 69: "EMPTY ACTION"})
        self.assertEqual(blocked["16"], "missing_build_ability_or_technology")
        self.assertEqual(blocked["66"], "need_army_or_already_attacking")

    async def test_reactor_barracks_trains_two_and_marauder_needs_techlab(self):
        rax = FakeTerranUnit(3, U.BARRACKS)
        rax.has_add_on = rax.has_reactor = True
        rax.is_idle = False
        rax.orders = [SimpleNamespace(ability=SimpleNamespace(id=A.BARRACKSTRAIN_MARINE))]
        self.set_world([self.scv], [self.cc, rax])
        self.abilities[rax.tag] = {TRAIN_INFO[U.BARRACKS][U.MARINE]["ability"],
                                   TRAIN_INFO[U.BARRACKS][U.MARAUDER]["ability"]}
        choices, blocked = await self.bot.available_actions()
        self.assertIn(1, choices)
        self.assertEqual(blocked["2"], "no_ready_producer_with_available_ability")
        await self.bot._perform(1)
        rax.train.assert_called_once_with(U.MARINE)
        rax.orders.append(rax.orders[0])
        choices, _ = await self.bot.available_actions()
        self.assertNotIn(1, choices)

    async def test_addon_needs_idle_host_and_space(self):
        rax = FakeTerranUnit(3, U.BARRACKS)
        self.set_world([self.scv], [self.cc, rax])
        self.abilities[rax.tag] = {A.BUILD_TECHLAB_BARRACKS, A.BUILD_REACTOR_BARRACKS}
        choices, _ = await self.bot.available_actions()
        self.assertIn(26, choices)
        self.assertIn(27, choices)
        self.bot.can_place_single = AsyncMock(return_value=False)
        await self.bot._perform(26)
        self.assertEqual(rax.commands, [])
        self.assertIn("no_space_for_addon", self.bot.temp_failure_list[-1])
        choices, blocked = await self.bot.available_actions()
        self.assertEqual(blocked["26"], "addon_space_blocked")
        self.bot._addon_blocked.clear()
        self.bot.can_place_single = AsyncMock(return_value=True)
        await self.bot._perform(26)
        self.assertEqual(rax.commands, [(A.BUILD_TECHLAB_BARRACKS, None)])
        rax.has_add_on = True
        choices, blocked = await self.bot.available_actions()
        self.assertEqual(blocked["26"], "no_idle_producer_without_addon")

    async def test_production_placement_uses_two_batched_queries(self):
        self.bot.mineral_field = Units([FakeTerranUnit(10, U.MINERALFIELD, (3, 10))], self.bot)
        self.bot.vespene_geyser = Units([], self.bot)
        grid = Mock()
        grid.__getitem__ = Mock(side_effect=lambda pos: 1 if 0 <= pos[0] < 60 and 0 <= pos[1] < 60 else 0)
        self.bot.game_info.placement_grid = grid
        queries = []

        async def can_place(kind, positions):
            queries.append((kind, positions))
            # The inner ring is occupied; only spots at least 13 away are free, and add-ons fit anywhere.
            return [kind == U.SUPPLYDEPOT or self.cc.distance_to(p) >= 13 for p in positions]

        self.bot.can_place = can_place
        await self.bot._build_one(19, U.BARRACKS)
        self.assertEqual([q[0] for q in queries], [U.BARRACKS, U.SUPPLYDEPOT])
        position = self.scv.build.call_args.args[1]
        self.assertGreaterEqual(self.cc.distance_to(position), 13)
        self.assertEqual((position.x % 1, position.y % 1), (.5, .5))

    def use_open_grid(self):
        self.bot.mineral_field = Units([FakeTerranUnit(10, U.MINERALFIELD, (3, 10))], self.bot)
        self.bot.vespene_geyser = Units([], self.bot)
        grid = Mock()
        grid.__getitem__ = Mock(return_value=1)
        self.bot.game_info.placement_grid = grid

    async def test_walled_in_spot_is_skipped_for_a_reachable_one(self):
        self.use_open_grid()
        self.bot.can_place = AsyncMock(side_effect=lambda kind, positions: [True] * len(positions))
        candidates = self.bot._placement_candidates(U.ARMORY)
        # The first two spots are closed off; the path query returns 0 for them.
        self.bot.client.query_pathings = AsyncMock(
            side_effect=lambda pairs: [0.0, 0.0] + [12.0] * (len(pairs) - 2))
        chosen = await self.bot._placement(U.ARMORY)
        self.assertEqual(chosen, candidates[2])
        pairs = self.bot.client.query_pathings.await_args.args[0]
        self.assertIs(pairs[0][0], self.scv)  # Paths are measured from the SCV that would build.
        self.assertEqual(self.bot._action_stats["unreachable_spots_skipped"], 2)

    async def test_no_placement_when_every_checked_spot_is_unreachable(self):
        self.use_open_grid()
        self.bot.can_place = AsyncMock(side_effect=lambda kind, positions: [True] * len(positions))
        self.bot.client.query_pathings = AsyncMock(side_effect=lambda pairs: [0.0] * len(pairs))
        self.assertIsNone(await self.bot._placement(U.ARMORY))

    async def test_rejected_spot_is_not_chosen_again(self):
        self.use_open_grid()
        self.bot.can_place = AsyncMock(side_effect=lambda kind, positions: [True] * len(positions))
        first = await self.bot._placement(U.ENGINEERINGBAY)
        order = {"request_id": 1, "action_id": 20, "kind": "ENGINEERINGBAY", "order_type": "production",
                 "producer_tag": self.scv.tag, "position": list(first), "submitted_at": 0,
                 "phase": "submitted", "unit_tag": None}
        self.bot._production_orders[1] = order
        self.bot._production_event(order, "failed", reason="engine_action_error", engine_result=44)
        second = await self.bot._placement(U.ENGINEERINGBAY)
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(max(abs(first.x - second.x), abs(first.y - second.y)), 3)

    async def test_placement_keeps_addon_slot_free(self):
        self.use_open_grid()
        rax = FakeTerranUnit(3, U.BARRACKS, (20.5, 20.5))
        self.set_world([self.scv], [self.cc, rax])
        slot = rax.position.offset((2.5, -0.5))
        for point in self.bot._placement_candidates(U.SUPPLYDEPOT):
            self.assertFalse(abs(point.x - slot.x) < 2 and abs(point.y - slot.y) < 2, point)

    async def test_new_buildings_leave_a_lane_for_tanks(self):
        self.use_open_grid()
        rax = FakeTerranUnit(3, U.BARRACKS, (20.5, 20.5))
        rax.has_add_on = True
        lab = FakeTerranUnit(4, U.BARRACKSTECHLAB, (23, 20))
        depot = FakeTerranUnit(5, U.SUPPLYDEPOTLOWERED, (16, 26))
        self.set_world([self.scv], [self.cc, rax, lab, depot])
        for kind in (U.FACTORY, U.ENGINEERINGBAY):
            for point in self.bot._placement_candidates(kind):
                for building, half in ((rax, 1.5), (lab, 1)):
                    gap = max(abs(point.x - building.position.x), abs(point.y - building.position.y)) - 1.5 - half
                    self.assertGreaterEqual(gap, 2, (kind, point, building.type_id))
                if kind == U.FACTORY:  # Its add-on keeps the lane too.
                    slot = point.offset((2.5, -0.5))
                    gap = max(abs(slot.x - rax.position.x), abs(slot.y - rax.position.y)) - 1 - 1.5
                    self.assertGreaterEqual(gap, 2, point)
        # Depots are lowered and walkable, so they may sit next to anything.
        depots = self.bot._placement_candidates(U.SUPPLYDEPOT)
        self.assertTrue(any(max(abs(p.x - rax.position.x), abs(p.y - rax.position.y)) < 4 for p in depots))

    async def test_two_barracks_may_be_under_construction(self):
        self.abilities[self.scv.tag] = {TRAIN_INFO[U.SCV][U.BARRACKS]["ability"]}
        self.bot.already_pending = Mock(side_effect=lambda kind: 1 if kind == U.BARRACKS else 0)
        await self.bot._refresh_abilities()
        self.assertIsNone(self.bot._build_reason(U.BARRACKS, self.scv))
        self.bot.already_pending = Mock(side_effect=lambda kind: 2 if kind == U.BARRACKS else 0)
        self.assertEqual(self.bot._build_reason(U.BARRACKS, self.scv), "already_pending")
        self.bot.already_pending = Mock(side_effect=lambda kind: 1 if kind == U.ENGINEERINGBAY else 0)
        self.abilities[self.scv.tag] = {TRAIN_INFO[U.SCV][U.ENGINEERINGBAY]["ability"]}
        await self.bot._refresh_abilities()
        self.assertEqual(self.bot._build_reason(U.ENGINEERINGBAY, self.scv), "already_pending")

    async def test_bunker_is_placed_in_front_of_the_base_nearest_the_enemy(self):
        natural = FakeTerranUnit(3, U.COMMANDCENTER, (40, 40))
        self.set_world([self.scv], [self.cc, natural])
        self.bot.game_info.start_locations = [Point2((100, 100))]
        anchors = self.bot._anchors(U.BUNKER)
        self.assertLess(natural.distance_to(anchors[0]), 7)
        self.assertLess(anchors[0].distance_to(Point2((100, 100))), natural.distance_to(Point2((100, 100))))

    def bunker_world(self, enemy_at, cargo_used=0):
        bunker = FakeTerranUnit(3, U.BUNKER, (20, 20))
        bunker.cargo_used, bunker.cargo_max = cargo_used, 4
        marines = [FakeTerranUnit(10 + i, U.MARINE, (22 + i, 20)) for i in range(6)]
        far = FakeTerranUnit(30, U.MARINE, (60, 60))
        enemy = FakeTerranUnit(90, U.ZERGLING, enemy_at)
        enemy.can_attack = True
        self.set_world([self.scv, *marines, far], [self.cc, bunker], [enemy])
        return bunker, marines, far

    async def test_marines_enter_bunker_when_enemies_approach(self):
        bunker, marines, far = self.bunker_world((28, 20), cargo_used=1)
        self.bot._man_bunkers()
        loaded = [m for m in marines if m.commands == [(A.SMART, bunker)]]
        self.assertEqual(len(loaded), 3)  # One slot is already taken.
        self.assertEqual(far.commands, [])

    async def test_bunker_unloads_to_attack_only_when_quiet(self):
        bunker, _, _ = self.bunker_world((80, 80), cargo_used=4)
        self.bot.army_intent = "defend"
        self.bot._man_bunkers()
        self.assertEqual(bunker.commands, [])
        self.bot.army_intent = "attack"
        self.bot._man_bunkers()
        self.assertEqual(bunker.commands, [(A.UNLOADALL_BUNKER, None)])

    async def test_scvs_repair_a_bunker_under_fire(self):
        bunker, _, _ = self.bunker_world((25, 20))
        bunker.health_percentage = .6
        self.scv.is_repairing = False
        helpers = [FakeTerranUnit(40 + i, U.SCV, (18, 18 + i)) for i in range(3)]
        for w in helpers:
            w.is_repairing = False
        self.bot.workers = Units([self.scv, *helpers], self.bot)
        self.bot.minerals = 100
        self.bot._repair()
        self.assertEqual(sum(1 for w in [self.scv, *helpers] if w.commands == [(A.EFFECT_REPAIR_SCV, bunker)]), 2)

    async def test_builder_is_never_a_gas_worker(self):
        refinery = FakeTerranUnit(3, U.REFINERY, (40, 40))
        to_gas = FakeTerranUnit(4, U.SCV, (39, 39))
        to_gas.order_target = refinery.tag
        carrying = FakeTerranUnit(5, U.SCV, (41, 41))
        carrying.is_carrying_vespene = True
        self.set_world([self.scv, to_gas, carrying], [self.cc, refinery])
        self.assertIs(self.bot._builder(Point2((40, 38))), self.scv)

    async def test_marines_shoot_banelings_and_step_away_while_reloading(self):
        baneling = FakeTerranUnit(90, U.BANELING, (20, 20))
        ready, reloading = FakeTerranUnit(3, U.MARINE, (24, 20)), FakeTerranUnit(7, U.MARINE, (22, 20))
        on_top, far = FakeTerranUnit(8, U.MARINE, (21, 20)), FakeTerranUnit(4, U.MARINE, (40, 20))
        reloading.weapon_cooldown = 5
        self.set_world([ready, reloading, on_top, far], [self.cc], [baneling])
        self.bot._fast_micro()
        self.assertEqual(ready.commands, [("attack", baneling)])
        for unit in (reloading, on_top):
            (kind, target), = unit.commands
            self.assertEqual(kind, "move")
            self.assertGreater(target.distance_to(baneling.position), unit.distance_to(baneling))
        self.assertEqual(far.commands, [])
        # No repeated order while already shooting at that Baneling.
        ready.order_target = baneling.tag
        ready.commands.clear()
        self.bot.unit_tags_received_action = set()
        self.bot._dodge_banelings()
        self.assertEqual(ready.commands, [])

    async def test_miners_step_away_from_banelings(self):
        baneling = FakeTerranUnit(90, U.BANELING, (20, 20))
        miner = FakeTerranUnit(5, U.SCV, (20, 23))
        builder = FakeTerranUnit(6, U.SCV, (19, 20))
        builder.is_constructing_scv = True
        self.set_world([miner, builder], [self.cc], [baneling])
        self.bot._fast_micro()
        self.assertEqual(miner.commands[0][0], "move")
        self.assertGreater(miner.commands[0][1].distance_to(baneling.position), miner.distance_to(baneling))
        self.assertEqual(builder.commands, [])

    async def test_neighbouring_marines_spread_to_different_sides(self):
        baneling = FakeTerranUnit(90, U.BANELING, (20, 20))
        a, b = FakeTerranUnit(3, U.MARINE, (23, 20)), FakeTerranUnit(4, U.MARINE, (23, 20))
        a.weapon_cooldown = b.weapon_cooldown = 5
        self.set_world([a, b], [self.cc], [baneling])
        self.bot._fast_micro()
        self.assertNotEqual(a.commands[0][1].y, b.commands[0][1].y)

    def gas_world(self, gas, minerals):
        refinery = FakeTerranUnit(3, U.REFINERY, (14, 10))
        field = FakeTerranUnit(9, U.MINERALFIELD, (5, 10))
        going = FakeTerranUnit(4, U.SCV, (13, 10))
        going.order_target = refinery.tag
        carrying = FakeTerranUnit(5, U.SCV, (13, 11))
        carrying.order_target, carrying.is_carrying_vespene = refinery.tag, True
        self.bot.mineral_field = Units([field], self.bot)
        self.set_world([self.scv, going, carrying], [self.cc, refinery])
        self.bot.vespene, self.bot.minerals = gas, minerals
        return field, going, carrying

    async def test_gas_workers_move_to_minerals_while_gas_piles_up(self):
        field, going, carrying = self.gas_world(gas=400, minerals=100)
        self.bot._balance_gas()
        self.assertTrue(self.bot._gas_throttled)
        going.gather.assert_called_once_with(field)
        carrying.gather.assert_not_called()  # It returns its gas first.
        self.bot.vespene = 200
        going.gather.reset_mock()
        self.bot._balance_gas()
        self.assertTrue(self.bot._gas_throttled)  # Still above the lower mark.
        self.bot.vespene = 100
        self.bot._balance_gas()
        self.assertFalse(self.bot._gas_throttled)
        going.gather.assert_called_once()  # Only while throttled.

    async def test_gas_is_not_throttled_when_minerals_keep_up(self):
        _, going, _ = self.gas_world(gas=400, minerals=300)
        self.bot._balance_gas()
        self.assertFalse(self.bot._gas_throttled)
        going.gather.assert_not_called()

    async def test_attack_not_offered_below_the_floor(self):
        marines = [FakeTerranUnit(10 + i, U.MARINE, (30, 30)) for i in range(35)]
        self.set_world([self.scv, *marines], [self.cc])
        self.bot.calculate_supply_cost = Mock(return_value=1)
        self.assertEqual(self.bot._posture_reason("attack"), "need_army_or_already_attacking")
        more = marines + [FakeTerranUnit(60 + i, U.MARINE, (30, 30)) for i in range(6)]
        self.set_world([self.scv, *more], [self.cc])
        self.assertIsNone(self.bot._posture_reason("attack"))

    async def test_soldiers_shoot_a_visible_changeling(self):
        changeling = FakeTerranUnit(90, U.CHANGELINGMARINESHIELD, (30, 30))
        marines = [FakeTerranUnit(10 + i, U.MARINE, (32 + i, 30)) for i in range(5)]
        self.set_world([self.scv, *marines], [self.cc], [changeling])
        self.bot._clear_changelings()
        shooters = [m for m in marines if m.commands == [("attack", changeling)]]
        self.assertEqual(len(shooters), 3)
        self.assertEqual(shooters, marines[:3])

    def barracks_world(self):
        plain, reactor = FakeTerranUnit(3, U.BARRACKS), FakeTerranUnit(4, U.BARRACKS)
        reactor.has_add_on = reactor.has_reactor = True
        busy = FakeTerranUnit(5, U.BARRACKS)
        busy.is_idle, busy.orders = False, [SimpleNamespace()]
        self.set_world([self.scv], [self.cc, plain, reactor, busy])
        marine = TRAIN_INFO[U.BARRACKS][U.MARINE]["ability"]
        for rax in (plain, reactor, busy):
            self.abilities[rax.tag] = {marine}
        return plain, reactor, busy

    async def test_banked_marine_choice_fills_every_free_slot(self):
        plain, reactor, busy = self.barracks_world()
        await self.bot._refresh_abilities()
        self.bot.minerals = 700
        await self.bot._perform(1)
        self.assertEqual(plain.train.call_count + reactor.train.call_count, 3)  # Reactor trains two.
        self.assertEqual(reactor.train.call_count, 2)
        busy.train.assert_not_called()
        self.assertEqual(self.bot._action_stats["batch_trained_units"], 3)

    async def test_marine_choice_trains_one_without_a_bank(self):
        plain, reactor, _ = self.barracks_world()
        await self.bot._refresh_abilities()
        self.bot.minerals = 300
        await self.bot._perform(1)
        self.assertEqual(plain.train.call_count + reactor.train.call_count, 1)

    async def test_batch_stops_when_money_runs_out(self):
        plain, reactor, _ = self.barracks_world()
        await self.bot._refresh_abilities()
        self.bot.minerals = 700
        budget = iter([True, False])
        self.bot.can_afford = Mock(side_effect=lambda kind: next(budget, False))
        await self.bot._perform(1)
        self.assertEqual(plain.train.call_count + reactor.train.call_count, 1)

    async def test_more_barracks_may_be_built_at_once_with_a_bank(self):
        self.abilities[self.scv.tag] = {TRAIN_INFO[U.SCV][U.BARRACKS]["ability"]}
        await self.bot._refresh_abilities()
        self.bot.already_pending = Mock(side_effect=lambda kind: 3 if kind == U.BARRACKS else 0)
        self.bot.minerals = 300
        self.assertEqual(self.bot._build_reason(U.BARRACKS, self.scv), "already_pending")
        self.bot.minerals = 700
        self.assertIsNone(self.bot._build_reason(U.BARRACKS, self.scv))
        self.bot.already_pending = Mock(side_effect=lambda kind: 4 if kind == U.BARRACKS else 0)
        self.assertEqual(self.bot._build_reason(U.BARRACKS, self.scv), "already_pending")

    async def test_expansion_skips_a_rejected_site_and_gas_workers(self):
        near, far = Point2((30, 30)), Point2((60, 60))
        self.bot._initialize_navigation()
        self.bot.expansion_locations_list = [near, far]
        self.bot.client = SimpleNamespace(query_pathing=AsyncMock(return_value=10))
        self.bot.build = AsyncMock(return_value=True)
        self.bot._rejected_spots[(near.x, near.y)] = self.bot.time + 60
        refinery = FakeTerranUnit(3, U.REFINERY, (58, 58))
        gas_worker = FakeTerranUnit(4, U.SCV, (59, 59))
        gas_worker.order_target = refinery.tag
        self.set_world([self.scv, gas_worker], [self.cc, refinery])
        await self.bot._build_expansion(18, U.COMMANDCENTER)
        args, kwargs = self.bot.build.await_args
        self.assertEqual(args[1], far)
        self.assertIs(kwargs["build_worker"], self.scv)

    def lurker_world(self, energy=60, raven=False):
        orbital = FakeTerranUnit(3, U.ORBITALCOMMAND)
        orbital.energy = energy
        marines = [FakeTerranUnit(10 + i, U.MARINE, (40, 40)) for i in range(3)]
        marines[0].weapon_cooldown = 5
        units = [self.scv, *marines] + ([FakeTerranUnit(20, U.RAVEN, (41, 41))] if raven else [])
        lurker = FakeTerranUnit(90, U.LURKERMP, (60, 60))
        self.set_world(units, [orbital], [lurker])
        self.bot._army_destination = Point2((70, 40))
        return orbital

    async def test_scan_ahead_of_a_fighting_army_when_lurkers_are_about(self):
        orbital = self.lurker_world()
        self.bot._fast_micro()
        (ability, target), = orbital.commands
        self.assertEqual(ability, A.SCANNERSWEEP_SCAN)
        self.assertAlmostEqual(target.distance_to(Point2((40, 40))), 6)
        orbital.commands.clear()
        self.bot._fast_micro()
        self.assertEqual(orbital.commands, [])  # At most one scan every few seconds.

    async def test_no_scan_with_a_raven_or_without_lurkers(self):
        orbital = self.lurker_world(raven=True)
        self.bot._fast_micro()
        self.assertEqual(orbital.commands, [])
        orbital = self.lurker_world()
        self.bot.enemy_units = Units([], self.bot)
        self.bot._lurker_seen = -1000
        self.bot._fast_micro()
        self.assertEqual(orbital.commands, [])

    async def test_mules_leave_scan_energy_while_lurkers_are_about(self):
        orbital = self.lurker_world(energy=60)
        self.bot.mineral_field = Units([FakeTerranUnit(9, U.MINERALFIELD, (15, 10))], self.bot)
        self.bot._call_down_mules()
        self.assertEqual(orbital.commands, [])
        orbital.energy = 110
        self.bot._call_down_mules()
        self.assertEqual(orbital.commands[0][0], A.CALLDOWNMULE_CALLDOWNMULE)

    async def test_cheating_ai_floor_hides_attack_from_jev(self):
        import dataclasses
        self.bot.contract = dataclasses.replace(TERRAN, min_attack_army=90, maxed_attack_army=60)
        marines = [FakeTerranUnit(10 + i, U.MARINE, (30, 30)) for i in range(70)]
        self.set_world([self.scv, *marines], [self.cc])
        self.bot.supply_used = 150
        self.assertEqual(self.bot._posture_reason("attack"), "need_army_or_already_attacking")
        self.bot.supply_used = 195
        self.assertIsNone(self.bot._posture_reason("attack"))

    def raid_world(self, raiders, army_at=(80, 80)):
        self.bot._initialize_navigation()
        army = [FakeTerranUnit(100 + i, U.MARINE, army_at) for i in range(20)]
        zerg = [FakeTerranUnit(300 + i, U.ZERGLING, (14, 12)) for i in range(raiders)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *army], [self.cc], zerg)
        self.bot.army_intent = "attack"
        return army

    async def test_raid_behind_a_far_army_recalls_it(self):
        army = self.raid_world(raiders=10)
        self.bot._recall_to_defend()
        self.assertEqual(self.bot.army_intent, "defend")
        self.assertGreater(self.bot.cooldowns[66], self.bot.time)  # No immediate re-attack.
        self.assertEqual(self.bot._action_stats["army_recalls"], 1)

    async def test_small_raid_or_nearby_army_does_not_recall(self):
        self.raid_world(raiders=3)
        self.bot._recall_to_defend()
        self.assertEqual(self.bot.army_intent, "attack")
        self.raid_world(raiders=10, army_at=(20, 20))
        self.bot._recall_to_defend()
        self.assertEqual(self.bot.army_intent, "attack")

    def battle_world(self, ours, theirs, lost_from=None):
        self.bot._initialize_navigation()
        army = [FakeTerranUnit(100 + i, U.MARINE, (60, 60)) for i in range(ours)]
        zerg = [FakeTerranUnit(300 + i, U.ROACH, (66, 60)) for i in range(theirs)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *army], [self.cc], zerg)
        self.bot.army_intent = "attack"
        if lost_from is not None:
            self.bot._attack_peak = lost_from
        return army

    async def test_attack_into_a_much_bigger_army_pulls_back_then_defends(self):
        army = self.battle_world(ours=20, theirs=30)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "retreat")
        self.assertEqual(army[0].commands[-1][0], "move")
        self.assertGreater(self.bot.cooldowns[66], self.bot.time + 30)
        self.assertEqual(self.bot._action_stats["army_disengages"], 1)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "retreat")  # Still moving away.
        self.bot.state.game_loop += 9 * 22.4
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "defend")

    async def test_even_fight_continues_unless_it_already_cost_much_of_the_army(self):
        self.battle_world(ours=20, theirs=22)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")
        self.battle_world(ours=20, theirs=22, lost_from=40)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "retreat")
        # A small enemy group never triggers it, and a winning fight goes on.
        self.battle_world(ours=5, theirs=8, lost_from=40)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")
        self.battle_world(ours=30, theirs=15, lost_from=40)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")

    async def test_fight_is_measured_where_the_army_meets_the_enemy(self):
        # Half the army fights evenly far from the other half: the army's center is empty ground.
        self.bot._initialize_navigation()
        front = [FakeTerranUnit(100 + i, U.MARINE, (80, 60)) for i in range(20)]
        rear = [FakeTerranUnit(200 + i, U.MARINE, (40, 60)) for i in range(20)]
        zerg = [FakeTerranUnit(300 + i, U.ROACH, (86, 60)) for i in range(22)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *front, *rear], [self.cc], zerg)
        self.bot.army_intent = "attack"
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")
        # Only the front half meets 35 Roaches: pull back.
        zerg += [FakeTerranUnit(400 + i, U.ROACH, (86, 62)) for i in range(13)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *front, *rear], [self.cc], zerg)
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "retreat")

    async def test_a_skirmish_at_the_front_does_not_pull_back_the_army(self):
        self.bot._initialize_navigation()
        scouts = [FakeTerranUnit(100 + i, U.MARINE, (80, 60)) for i in range(3)]
        main = [FakeTerranUnit(200 + i, U.MARINE, (40, 60)) for i in range(40)]
        zerg = [FakeTerranUnit(300 + i, U.ROACH, (86, 60)) for i in range(15)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *scouts, *main], [self.cc], zerg)
        self.bot.army_intent = "attack"
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")
        # After heavy losses in the attack the same picture does pull back.
        self.bot._attack_peak = 80
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "retreat")

    async def test_enemies_at_our_bases_are_left_to_the_recall(self):
        self.bot._initialize_navigation()
        army = [FakeTerranUnit(100 + i, U.MARINE, (16, 10)) for i in range(5)]
        zerg = [FakeTerranUnit(300 + i, U.ROACH, (12, 12)) for i in range(20)]
        for z in zerg:
            z.can_attack = True
        self.set_world([self.scv, *army], [self.cc], zerg)
        self.bot.army_intent = "attack"
        self.bot._disengage()
        self.assertEqual(self.bot.army_intent, "attack")

    async def test_bio_waits_for_the_tanks_unless_fighting(self):
        self.bot._initialize_navigation()
        guard = [FakeTerranUnit(400 + i, U.SIEGETANK, (12 + i, 12)) for i in range(2)]
        tank = FakeTerranUnit(410, U.SIEGETANK, (50, 50))
        ahead, beside = FakeTerranUnit(420, U.MARINE, (68, 68)), FakeTerranUnit(421, U.MARINE, (52, 52))
        fighting = FakeTerranUnit(422, U.MARINE, (78, 78))
        ling = FakeTerranUnit(300, U.ZERGLING, (82, 80))
        ling.can_attack = True
        self.set_world([self.scv, *guard, tank, ahead, beside, fighting], [self.cc], [ling])
        self.bot.army_intent = "attack"
        self.bot._army_destination = Point2((90, 90))
        self.bot._wait_for_tanks()
        (kind, target), = ahead.commands
        self.assertEqual(kind, "move")
        self.assertLess(target.distance_to(tank.position), 3)
        self.assertEqual(beside.commands, [])
        self.assertEqual(fighting.commands, [])
        self.bot.army_intent = "defend"
        ahead.commands.clear()
        self.bot._wait_for_tanks()
        self.assertEqual(ahead.commands, [])

    async def test_brood_lords_call_for_vikings_and_a_starport(self):
        catalog = {str(a): {"count_with_pending": 0} for a in TERRAN.actions}
        self.assertEqual(self.bot._conditional_tech(catalog), ())
        lords = [FakeTerranUnit(300 + i, U.BROODLORD, (60, 60)) for i in range(3)]
        self.set_world([self.scv], [self.cc], lords)
        self.bot._track_air_threat()
        self.assertEqual(self.bot._air_threat, 6)
        self.assertEqual(set(self.bot._conditional_tech(catalog)), {10, 22})  # Vikings, Starport.
        catalog["22"]["count_with_pending"] = 1
        self.assertEqual(self.bot._conditional_tech(catalog), (10, 22))  # Six Vikings want a second Starport.
        catalog["22"]["count_with_pending"] = 2
        self.assertEqual(self.bot._conditional_tech(catalog), (10,))
        catalog["10"]["count_with_pending"] = 6
        self.assertEqual(self.bot._conditional_tech(catalog), ())
        catalog["10"]["count_with_pending"] = 2
        self.bot.state.game_loop += 200 * 22.4  # Not seen for a long time.
        self.assertEqual(self.bot._conditional_tech(catalog), ())

    async def test_two_tanks_stay_home_during_an_attack(self):
        self.bot._initialize_navigation()
        near = [FakeTerranUnit(400 + i, U.SIEGETANK, (30 + i, 30)) for i in range(2)]
        far = FakeTerranUnit(410, U.SIEGETANK, (60, 60))
        marine = FakeTerranUnit(420, U.MARINE, (30, 30))
        self.set_world([self.scv, *near, far, marine], [self.cc])
        self.bot._known_enemy_buildings = {1: {"id": "enemy_1", "type": "HATCHERY", "position": [90, 90], "last_seen": 0}}
        self.bot.army_intent = "attack"
        self.bot._issue_army_intent()
        for tank in near:
            self.assertEqual(tank.commands[-1][0], "move")  # Back to the base, not to the enemy.
        self.assertEqual(far.commands[-1][0], "attack")
        self.assertEqual(marine.commands[-1][0], "attack")
        self.bot.army_intent = "defend"
        self.assertEqual(self.bot._held_army_tags(), set())

    async def test_deployed_tanks_and_mines_still_count(self):
        units = [FakeTerranUnit(3, U.SIEGETANKSIEGED), FakeTerranUnit(4, U.SIEGETANK),
                 FakeTerranUnit(5, U.WIDOWMINEBURROWED)]
        self.set_world([self.scv, *units], [self.cc])
        self.assertEqual(self.bot._count_with_pending(U.SIEGETANK), 2)
        self.assertEqual(self.bot._count_with_pending(U.WIDOWMINE), 1)

    async def test_planetary_fortress_goes_to_the_exposed_base_after_banelings(self):
        main = self.cc
        natural, third = FakeTerranUnit(3, U.COMMANDCENTER, (40, 40)), FakeTerranUnit(4, U.COMMANDCENTER, (70, 70))
        self.set_world([self.scv], [main, natural, third])
        catalog = {str(a): {"count_with_pending": 0} for a in TERRAN.actions}
        self.assertEqual(self.bot._conditional_tech(catalog), ())
        self.bot._banelings_seen = True
        self.assertEqual(self.bot._conditional_tech(catalog), (33,))
        for cc in (main, natural, third):
            self.abilities[cc.tag] = {A.UPGRADETOPLANETARYFORTRESS_PLANETARYFORTRESS, A.UPGRADETOORBITAL_ORBITALCOMMAND}
        await self.bot._refresh_abilities()
        self.assertIs(self.bot._morph_hosts(U.PLANETARYFORTRESS)[0], third)
        self.assertIs(self.bot._morph_hosts(U.ORBITALCOMMAND)[0], main)
        catalog["33"]["count_with_pending"] = 1
        self.assertEqual(self.bot._conditional_tech(catalog), ())

    async def test_orbital_morph(self):
        self.abilities[self.cc.tag].add(A.UPGRADETOORBITAL_ORBITALCOMMAND)
        choices, _ = await self.bot.available_actions()
        self.assertIn(32, choices)
        await self.bot._perform(32)
        self.assertEqual(self.cc.commands, [(A.UPGRADETOORBITAL_ORBITALCOMMAND, None)])

    async def test_counts_include_lowered_depots_and_abandoned_structures(self):
        depot = FakeTerranUnit(3, U.SUPPLYDEPOTLOWERED)
        rax = FakeTerranUnit(4, U.BARRACKS)
        rax.is_ready = False
        self.set_world([self.scv], [self.cc, depot, rax])
        self.bot.worker_en_route_to_build = Mock(side_effect=lambda kind: 1 if kind == U.SUPPLYDEPOT else 0)
        self.assertEqual(self.bot._count_with_pending(U.SUPPLYDEPOT), 2)
        self.assertEqual(self.bot._count_with_pending(U.BARRACKS), 1)
        self.assertEqual(self.bot._count_with_pending(U.COMMANDCENTER), 1)

    async def test_finished_orbital_morph_is_not_a_lost_base(self):
        orbital = FakeTerranUnit(3, U.ORBITALCOMMAND)
        orbital.is_ready = False
        building = FakeTerranUnit(4, U.COMMANDCENTER)
        building.is_ready = False
        self.set_world([self.scv], [self.cc, orbital, building])
        self.assertEqual(self.bot._ready_base_count(), 2)

    async def test_tanks_siege_near_ground_enemies_and_unsiege_to_retreat(self):
        tank = FakeTerranUnit(3, U.SIEGETANK, (20, 20))
        ling = FakeTerranUnit(9, U.ZERGLING, (28, 20))
        self.set_world([self.scv, tank], [self.cc], [ling])
        self.bot._deploy_units()
        self.assertEqual(tank.commands, [(A.SIEGEMODE_SIEGEMODE, None)])
        sieged = FakeTerranUnit(3, U.SIEGETANKSIEGED, (20, 20))
        self.set_world([self.scv, sieged], [self.cc], [ling])
        self.bot._deploy_units()
        self.assertEqual(sieged.commands, [])  # Mode is held briefly after switching.
        self.bot._mode_changed[sieged.tag] = -100
        self.bot.army_intent = "retreat"
        self.bot._deploy_units()
        self.assertEqual(sieged.commands, [(A.UNSIEGE_UNSIEGE, None)])

    async def test_army_orders_skip_sieged_tanks(self):
        marine = FakeTerranUnit(3, U.MARINE, (30, 30))
        sieged = FakeTerranUnit(4, U.SIEGETANKSIEGED, (30, 31))
        self.set_world([self.scv, marine, sieged], [self.cc])
        self.bot.army_intent = "retreat"
        self.bot._issue_army_intent()
        self.assertEqual(marine.commands, [("move", self.cc.position)])
        self.assertEqual(sieged.commands, [])

    async def test_mule_goes_to_richest_nearby_patch(self):
        orbital = FakeTerranUnit(3, U.ORBITALCOMMAND)
        orbital.energy = 60
        poor, rich = FakeTerranUnit(10, U.MINERALFIELD, (15, 10)), FakeTerranUnit(11, U.MINERALFIELD, (16, 11))
        poor.mineral_contents = 300
        self.bot.mineral_field = Units([poor, rich], self.bot)
        self.set_world([self.scv], [orbital])
        self.bot._call_down_mules()
        self.assertEqual(orbital.commands, [(A.CALLDOWNMULE_CALLDOWNMULE, rich)])

    async def test_research_offered_only_under_its_generic_id_uses_that_id(self):
        armory = FakeTerranUnit(5, U.ARMORY)
        armory.is_idle = True
        self.set_world([self.scv], [self.cc, armory])
        self.bot._producers = [armory]
        upgrade = UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1
        specific = RESEARCH_INFO[U.ARMORY][upgrade]["ability"]
        self.bot.game_data = SimpleNamespace(abilities={specific.value: SimpleNamespace(id=A.RESEARCH_TERRANVEHICLEANDSHIPPLATING)},
                                             upgrades={})
        self.bot._abilities = {armory.tag: {A.RESEARCH_TERRANVEHICLEANDSHIPPLATING}}
        self.bot._research_one(40, upgrade)
        self.assertEqual(armory.commands, [(A.RESEARCH_TERRANVEHICLEANDSHIPPLATING, None)])
        # The running game's own research ability comes first when the unit offers it.
        armory.commands.clear()
        own = SimpleNamespace(exact_id=A.ARMORYRESEARCHSWARM_TERRANVEHICLEANDSHIPPLATINGLEVEL1,
                              id=A.RESEARCH_TERRANVEHICLEANDSHIPPLATING)
        self.bot.game_data.upgrades = {upgrade.value: SimpleNamespace(research_ability=own)}
        self.bot._abilities = {armory.tag: {A.ARMORYRESEARCHSWARM_TERRANVEHICLEANDSHIPPLATINGLEVEL1,
                                            A.RESEARCH_TERRANVEHICLEANDSHIPPLATING}}
        self.bot._research_one(40, upgrade)
        self.assertEqual(armory.commands, [(A.ARMORYRESEARCHSWARM_TERRANVEHICLEANDSHIPPLATINGLEVEL1, None)])

    async def test_stim_only_when_researched_and_in_combat(self):
        marine = FakeTerranUnit(3, U.MARINE, (20, 20))
        ling = FakeTerranUnit(9, U.ZERGLING, (24, 20))
        ling.can_attack = True
        self.set_world([self.scv, marine], [self.cc], [ling])
        self.bot._stim()
        self.assertEqual(marine.commands, [])
        self.bot.state.upgrades = {UpgradeId.STIMPACK}
        self.bot._stim()
        self.assertEqual(marine.commands, [(A.EFFECT_STIM_MARINE, None)])

    async def test_decision_dispatch_records_production_order(self):
        ability = TRAIN_INFO[U.COMMANDCENTER][U.SCV]["ability"]
        self.cc.train.side_effect = lambda _: self.bot.actions.append(SimpleNamespace(ability=ability, unit=self.cc))
        await self.bot._execute_decision(Decision(1, 0, 0, 0, {}, 100))
        self.cc.train.assert_called_once_with(U.SCV)
        self.assertEqual(self.bot.recent_outcomes[-1]["orders_submitted"], 1)
        self.assertEqual(self.bot._production_orders[1]["kind"], "SCV")

    async def test_order_fails_when_its_producer_dies_before_creating_anything(self):
        order = {"request_id": 5, "action_id": 32, "kind": "ORBITALCOMMAND", "order_type": "production",
                 "producer_tag": self.cc.tag, "position": None, "submitted_at": 0,
                 "phase": "accepted", "unit_tag": None}
        self.bot._production_orders[5] = order
        await self.bot.on_unit_destroyed(self.cc.tag)
        self.assertNotIn(5, self.bot._production_orders)
        self.assertEqual(self.bot.recent_outcomes[-1]["phase"], "failed")
        self.assertIn("producer_destroyed", self.bot.recent_outcomes[-1]["failures"][0])

    async def test_observation_is_json_ready(self):
        import json
        snapshot = self.bot._snapshot()
        json.dumps(snapshot, allow_nan=False)
        self.assertEqual(snapshot["unit"]["scv_count"], 1)
        self.assertFalse(snapshot["supply_forecast"]["needs_power"])


class HierarchicalTerranTests(TerranAdapterTests):
    def make_bot(self, client):
        planner = SimpleNamespace(model="test", timeout=1, effort="low", close=AsyncMock())
        return HierarchicalTerranBot(client, Path(self.directory.name), planner_client=planner)

    async def test_catalog_describes_terran_actions(self):
        self.bot.calculate_cost = Mock(return_value=SimpleNamespace(minerals=50, vespene=25))
        await self.bot._refresh_abilities()
        catalog = self.bot._catalog()
        self.assertEqual(len(catalog), 71)
        self.assertEqual(catalog["26"]["cost"], {"minerals": 50, "gas": 25})
        self.assertEqual(catalog["26"]["reservation_blocked"], "no_idle_producer_without_addon")
        self.assertIsNone(catalog["0"]["reservation_blocked"])
        self.assertFalse(catalog["34"]["exists_in_game_version"])
        self.assertIsNone(catalog["66"]["reservation_blocked"])


if __name__ == "__main__":
    unittest.main()
