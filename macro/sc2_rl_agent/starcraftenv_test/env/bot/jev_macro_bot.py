"""Race-independent Jev macro loop: decision scheduling, execution records and shutdown."""

import statistics
import time
from collections import Counter, deque
from pathlib import Path

from sc2.bot_ai import BotAI
from sc2.protocol import ProtocolError
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM

from ...agent.jev_agent import DecisionScheduler
from ...agent.macro_contract import VERSION
from ...utils.run_logging import RunLog
from .macro_execution import MacroExecution
from .macro_navigation import MacroNavigation


class JevMacroBot(MacroExecution, MacroNavigation, BotAI):
    """Subclasses set `contract` and implement the race's legality checks and actions."""

    contract = None
    local_automation = []

    def __init__(self, jev_client, output_dir: Path, decision_interval=1.0,
                 max_decision_age=4.0, max_requests=2000, run_log=None):
        self._initialize_race()
        self.action_dict = dict(self.contract.actions)
        self.empty_action = self.contract.empty_action
        self.output_dir = output_dir
        self._owns_log = run_log is None
        self.log = run_log if run_log is not None else RunLog(output_dir)
        self.scheduler = DecisionScheduler(jev_client, self.log, decision_interval,
                                           max_decision_age, max_requests)
        self.recent_outcomes = deque(maxlen=8)
        self.cooldowns = {}
        self.army_intent = "defend"
        self._last_maintenance = -100.0
        self._last_heartbeat = -100.0
        self._abilities = {}
        self._abilities_ignoring_cost = {}
        self._producers = []
        self._started_at = time.monotonic()
        self._closed = False
        self._last_game_loop = 0
        self._last_economy = {}
        self._steps = 0
        self._steps_while_inflight = 0
        self._max_step_ms = 0.0
        self._action_stats = Counter()
        self._initialize_execution()
        self._initialize_navigation()
        self._build_worker_for_catalog = None

    def _initialize_race(self):
        self.temp_failure_list = []
        self.military_unit_types = set()

    def record_failure(self, action, reason):
        self.temp_failure_list.append(f'Action failed: {self.action_dict[action]}, Reason: {reason}')

    async def on_start(self):
        self.client.game_step = 4
        self._set_search_sites(self.expansion_locations_list)
        self._install_action_feedback()
        self.log("start", model=self.scheduler.client.model, race=self.contract.race, realtime=True,
                 action_count=len(self.action_dict), empty_action_id=self.empty_action,
                 map=self.game_info.map_name, base_build=self.base_build,
                 decision_interval_s=self.scheduler.interval,
                 max_decision_age_s=self.scheduler.max_age,
                 macro_contract=VERSION,
                 initial_workers=self.supply_workers, initial_supply_cap=self.supply_cap,
                 local_automation=list(self.local_automation))

    def get_enemy_unity(self):
        return dict(Counter(u.type_id.name for u in self.enemy_units if u.is_visible))

    def get_enemy_structure(self):
        return dict(Counter(u.type_id.name for u in self.enemy_structures if u.is_visible))

    def _snapshot(self):
        information = self.get_information()
        information["game_loop"] = self.state.game_loop
        information["enemy_race"] = self.enemy_race.name
        information["visibility"] = "Enemy counts cover currently visible units only; unseen forces are unknown."
        information["army_intent"] = self.army_intent
        information["navigation"] = self._navigation_snapshot()
        information["supply_forecast"] = self._supply_forecast()
        information["base_under_attack"] = self._emergency()
        information["ready_idle_producers"] = dict(Counter(
            u.type_id.name for u in self.structures.ready.idle))
        information["bases"] = [{
            "tag": b.tag, "position": list(b.position),
            "workers": b.assigned_harvesters, "ideal_workers": b.ideal_harvesters,
            "health_fraction": round(b.health_percentage, 2),
            "visible_enemies_within_30": self.enemy_units.filter(
                lambda e: e.is_visible and e.distance_to(b) < 30).amount,
        } for b in self.townhalls.ready]
        information["recent_outcomes"] = list(self.recent_outcomes)
        return information

    def _has_ability(self, unit, ability, ignore_resources=False):
        ability_map = (self._abilities_ignoring_cost or self._abilities) if ignore_resources else self._abilities
        available = ability_map.get(unit.tag, set())
        data = self.game_data.abilities.get(ability.value)
        return ability in available or (data is not None and data.id in available)

    def _ready_base_count(self):
        return self.townhalls.ready.amount

    def _ability_query_units(self):
        """Units other than structures and one builder whose abilities decide legality."""
        return []

    async def _refresh_abilities(self):
        self._producers = list(self.structures.ready)
        workers = self.workers.filter(lambda w: w.is_gathering or w.is_idle)
        units = self._producers + list(self._ability_query_units())
        if workers:
            units.append(workers.first)
        # Ignoring resources also exposes uncharged Warpgate abilities in this SC2
        # build. Only the ordinary query may authorize an actual order.
        abilities = await self.get_available_abilities(units) if units else []
        self._abilities = {u.tag: set(a) for u, a in zip(units, abilities)}
        readiness = await self.get_available_abilities(units, ignore_resource_requirements=True) if units else []
        self._abilities_ignoring_cost = {u.tag: set(a) for u, a in zip(units, readiness)}
        self._build_worker_for_catalog = workers.first if workers else None
        return self._build_worker_for_catalog

    def _research_reason(self, upgrade, ignore_resources=False):
        data = self.game_data.upgrades.get(upgrade.value)
        # SC2 retains obsolete upgrade records with no research ability. The SDK's
        # pending-upgrade query dereferences that ability, so check it first.
        if data is None or data.research_ability is None:
            return "upgrade_not_in_game_version"
        if self.already_pending_upgrade(upgrade) or (not ignore_resources and not self.can_afford(upgrade)):
            return "research_started_or_resources"
        source = UPGRADE_RESEARCHED_FROM.get(upgrade)
        info = RESEARCH_INFO.get(source, {}).get(upgrade)
        if not info:
            return "unknown_research_ability"
        for producer in self._producers:
            if producer.type_id == source and producer.is_idle and self._has_ability(producer, info["ability"], ignore_resources=ignore_resources):
                return None
        return "no_ready_researcher_with_available_ability"

    async def available_actions(self):
        raise NotImplementedError

    async def _perform(self, action):
        """Submit the SC2 commands for one legal action."""
        raise NotImplementedError

    async def _execute_decision(self, decision):
        choices, blocked = await self.available_actions()
        action = decision.action_id
        context_rejection = self._decision_context_rejection(decision)
        if context_rejection or action not in choices:
            self._action_stats["invalidated_before_execution"] += 1
            if context_rejection:
                self._action_stats["plan_changed_discards"] += 1
            self.log("action_discarded", request_id=decision.request_id, action_id=action,
                     plan_id=decision.plan_id, execution_plan_id=self._active_plan_id(),
                     game_loop=self.state.game_loop, reason=context_rejection or blocked.get(str(action), "unavailable"))
            return
        self.temp_failure_list.clear()
        count_before = len(self.actions)
        await self._perform(action)
        submitted = self.actions[count_before:]
        self._track_production_order(decision, submitted)
        army_actions = self.contract.army_actions
        outcome = {
            "game_loop": self.state.game_loop, "action_id": action,
            "description": self.action_dict[action], "orders_submitted": len(submitted),
            "failures": list(self.temp_failure_list),
            "intent_applied": action in army_actions and self.army_intent == army_actions[action],
        }
        self.recent_outcomes.append(outcome)
        self._action_stats["decisions_executed"] += 1
        self._action_stats["orders_submitted"] += len(submitted)
        if action != self.empty_action and not submitted and not outcome["intent_applied"]:
            self.cooldowns[action] = self.time + 5
            self._action_stats["executor_no_order"] += 1
        self.log("action", request_id=decision.request_id, **outcome,
                 plan_id=decision.plan_id, execution_plan_id=self._active_plan_id(),
                 status="wait" if action == self.empty_action else "intent_applied" if outcome["intent_applied"] else "executor_no_order" if not submitted else
                        "orders_submitted_with_failures" if outcome["failures"] else "orders_submitted",
                 orders=[self._order_record(c) for c in submitted])

    def _active_plan_id(self):
        return None

    def _decision_context_rejection(self, decision):
        return None

    @staticmethod
    def _order_record(command):
        target = getattr(command, "target", None)
        if hasattr(target, "x") and hasattr(target, "y"):
            target = {"x": float(target.x), "y": float(target.y)}
        elif target is not None:
            target = int(getattr(target, "tag", target))
        return {"ability": command.ability.name, "unit_tag": command.unit.tag,
                "target": target, "queue": bool(getattr(command, "queue", False))}

    async def _pull_match_result(self):
        """Read Victory or Defeat after StarCraft has already closed the match."""
        client = self.client
        results = getattr(client, "_game_result", None) or {}
        player_id = getattr(client, "_player_id", None)
        if player_id in results:
            return results[player_id]
        try:
            await client.observation()
        except ProtocolError:
            return None
        results = getattr(client, "_game_result", None) or {}
        return results.get(player_id)

    async def on_step(self, iteration):
        try:
            await self._step(iteration)
        except ProtocolError as exc:
            if not exc.is_game_over_error:
                if self.log.failure is None:
                    self.log.fail(exc)
                raise
            result = await self._pull_match_result()
            self.actions.clear()
            if result is None:
                if self.log.failure is None:
                    self.log.fail(exc)
                raise
            return
        except Exception as exc:
            if self.log.failure is None:
                self.log.fail(exc)
            raise

    async def _step(self, iteration):
        started = time.monotonic()
        self.log.set_game_loop(self.state.game_loop)
        self.iteration = iteration
        self._steps += 1
        self._last_game_loop = self.state.game_loop
        self._update_navigation()
        self._consume_engine_feedback()
        if self.scheduler.task is not None and not self.scheduler.task.done():
            self._steps_while_inflight += 1
        # Update the legacy counters used by handlers before dispatch.
        self._last_economy = self.get_information()["resource"]
        decision = self.scheduler.poll(self.state.game_loop)
        # Let the runner mark this as an interrupted/failed trial and close both
        # model clients. A disabled decision service cannot play a valid game.
        self.scheduler.require_service()
        if decision is not None:
            await self._execute_decision(decision)
        # Give production/movement orders a frame to become visible before the next snapshot.
        elif self.scheduler.ready:
            choices, blocked = await self.available_actions()
            if len(choices) > 1:
                self.scheduler.submit(self.state.game_loop, self._snapshot(), choices)
                self.log("action_mask", request_id=self.scheduler.request_id, blocked=blocked)
        if self.time - self._last_maintenance >= 1:
            await self._maintain_local_behaviors()
            self._last_maintenance = self.time
        self._max_step_ms = max(self._max_step_ms, (time.monotonic() - started) * 1000)
        if self.time - self._last_heartbeat >= 5:
            self.log("heartbeat", game_loop=self.state.game_loop, steps=self._steps,
                     steps_while_inflight=self._steps_while_inflight,
                     inflight=self.scheduler.task is not None, economy=self._last_economy,
                     units=dict(Counter(u.type_id.name for u in self.units)),
                     structures=dict(Counter(u.type_id.name for u in self.structures)),
                     stats=dict(self.scheduler.stats), actions=dict(self._action_stats))
            self._last_heartbeat = self.time

    async def _maintain_local_behaviors(self):
        pass

    async def _set_posture(self, action):
        self._set_army_intent(self.contract.army_actions[action])

    async def on_end(self, game_result):
        await self.shutdown(game_result.name)

    def _extra_summary(self):
        return {}

    async def shutdown(self, result="interrupted"):
        if self._closed:
            return
        self._closed = True
        await self.scheduler.close()
        if self._original_client_actions is not None:
            self.client.actions = self._original_client_actions
            self._original_client_actions = None
        latencies = self.scheduler.latencies
        summary = {
            "result": result, "realtime": True, "game_loop": self._last_game_loop,
            "game_seconds": self._last_game_loop / 22.4,
            "wall_seconds": time.monotonic() - self._started_at,
            "steps": self._steps, "steps_while_inflight": self._steps_while_inflight,
            "max_on_step_ms": self._max_step_ms, "economy": self._last_economy,
            "api": dict(self.scheduler.stats), "actions": dict(self._action_stats),
            "macro_contract": VERSION, "race": self.contract.race,
            "production_orders_unresolved": list(self._production_orders.values()),
            "latency_median_ms": statistics.median(latencies) if latencies else None,
            "latency_max_ms": max(latencies) if latencies else None,
            "note": "Submitted commands are not proof of completed production. Check heartbeat observations/replay.",
        }
        summary.update(self._extra_summary())
        self.log("end", **summary)
        self.log.write_summary(summary)
        if self._owns_log:
            self.log.finish("interrupted" if result == "interrupted" else "completed", result)
            self.log.close()
