"""Pure, testable constraints for an Astra plan over the existing macro actions."""

from .macro_contract import PROTOSS


def plan_progress(plan, catalog, resource):
    remaining = [g for g in plan["goals"]
                 if catalog[str(g["action_id"])]["count_with_pending"] < g["target"]]
    reserve = plan["reserve_for_action"]
    active_reserve = (reserve is not None and resource["worker_supply"] >= plan["reserve_after_workers"]
                      and any(g["action_id"] == reserve for g in remaining)
                      and not catalog[str(reserve)].get("reservation_blocked"))
    cost = catalog[str(reserve)]["cost"] if active_reserve else {"minerals": 0, "gas": 0}
    return {"remaining_goals": remaining, "reserve_for_action": reserve if active_reserve else None,
            "reserved_minerals": cost["minerals"], "reserved_gas": cost["gas"],
            "reservation_suspended_reason": catalog[str(reserve)].get("reservation_blocked") if reserve is not None else None}


def policy_reason(action, plan, catalog, resource, army_intent, last_intent_time, game_time, emergency,
                  contract=PROTOSS):
    """Called only after the action passes actual SC2 legality/affordability checks."""
    progress = plan_progress(plan, catalog, resource)
    worker, base = contract.worker_action, contract.base_action
    if action == worker and catalog[str(worker)]["count_with_pending"] >= plan["worker_target"]:
        return "plan_worker_target_reached"
    if action == base and catalog[str(base)]["count_with_pending"] >= plan["base_target"]:
        return "plan_base_target_reached"
    urgent_supply = action == contract.supply_action and (
        resource.get("needs_power") or resource.get("needs_supply") or
        resource["supply_left"] <= 2 and resource["supply_cap"] < 200)
    urgent_defense = emergency and (action in contract.urgent_defense_actions or
                                    action in plan["allowed_spending_actions"]
                                    and action in contract.army_production_actions)
    override = urgent_supply or urgent_defense
    # Minerals piling up means the plan is too narrow for the income; keep spending on the army.
    banked = action in contract.bank_override_actions and resource["mineral"] >= contract.bank_minerals
    if action in contract.spending_actions and not override:
        if action not in plan["allowed_spending_actions"] and not banked:
            return "plan_spending_not_allowed"
        goal = next((g for g in plan["goals"] if g["action_id"] == action), None)
        if goal and catalog[str(action)]["count_with_pending"] >= goal["target"] and not banked:
            return "plan_goal_target_reached"
        if action != progress["reserve_for_action"]:
            cost = catalog[str(action)]["cost"]
            if ((cost["minerals"] and resource["mineral"] - cost["minerals"] < progress["reserved_minerals"])
                    or (cost["gas"] and resource["gas"] - cost["gas"] < progress["reserved_gas"])):
                return "plan_resource_reservation"
    if action in contract.army_actions:
        ready_army = resource.get("ready_army_supply", resource["army_supply"])
        retreat_needed = emergency or ready_army < plan["retreat_below_army"]
        target = contract.army_actions[action]
        urgent_withdrawal = target == "retreat" and army_intent == "attack" and retreat_needed
        new_defense_order = (target == "defend" and plan["army_posture"] == "defend"
                             and plan.get("accepted_game_seconds", -1) > last_intent_time)
        if (target != army_intent and game_time - last_intent_time < plan["min_posture_seconds"]
                and not urgent_withdrawal and not new_defense_order):
            return "plan_hold_army_intent"
        if target == "attack" and (plan["army_posture"] != "attack" or ready_army < plan["attack_min_army"]):
            return "plan_attack_not_ready"
        if target == "retreat" and plan["army_posture"] == "attack" and not retreat_needed:
            return "plan_continue_attack"
        if target == "defend" and plan["army_posture"] != "defend" and not emergency:
            return "plan_posture_not_defend"
    return None
