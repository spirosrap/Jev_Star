"""Pure, testable constraints for an Astra plan over the existing macro actions."""

from .macro_contract import PROTOSS, attack_floor, tech_due


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


def scheduled_reserve(contract, game_time, catalog):
    """Scheduled or recommended purchases, and the first of them that only lacks resources."""
    due = [int(a) for a, entry in catalog.items() if entry.get("recommended")]
    due += [a for a in tech_due(contract, game_time, catalog) if a not in due]
    held = next((a for a in due if not catalog[str(a)].get("reservation_blocked")), None)
    return due, held


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
    banked = ((action in contract.bank_override_actions and resource["mineral"] >= contract.bank_minerals)
              or action in tech_due(contract, game_time, catalog)
              or catalog.get(str(action), {}).get("recommended", False))
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
        # Keep the money for due tech (e.g. Tanks, Vikings) instead of spending it on something else first.
        due, held = scheduled_reserve(contract, game_time, catalog)
        if held is not None and action not in due and action not in (worker, contract.supply_action):
            cost, reserved = catalog[str(action)]["cost"], catalog[str(held)]["cost"]
            if ((cost["minerals"] and resource["mineral"] - cost["minerals"] < reserved["minerals"])
                    or (cost["gas"] and resource["gas"] - cost["gas"] < reserved["gas"])):
                return "scheduled_tech_reservation"
            # A due counter unit also keeps supply free, so a maxed army refills with it first.
            supply, needed = catalog[str(action)].get("supply", 0), catalog[str(held)].get("supply", 0)
            if supply and needed and resource["supply_left"] - supply < needed:
                return "scheduled_supply_reservation"
    if (contract.supply_reserve and action in contract.spending_actions and action != contract.supply_action
            and resource.get("needs_supply") and resource["supply_left"] <= 4 and resource["supply_cap"] < 200
            and not catalog[str(contract.supply_action)].get("pending")):
        cost = catalog[str(action)]["cost"]["minerals"]
        depot = catalog[str(contract.supply_action)]["cost"]["minerals"]
        if cost and resource["mineral"] - cost < depot:
            return "plan_supply_reserve"
    if action in contract.army_actions:
        ready_army = resource.get("ready_army_supply", resource["army_supply"])
        retreat_needed = emergency or ready_army < plan["retreat_below_army"]
        target = contract.army_actions[action]
        urgent_withdrawal = target == "retreat" and army_intent == "attack" and retreat_needed
        new_defense_order = (target == "defend" and plan["army_posture"] == "defend"
                             and plan.get("accepted_game_seconds", -1) > last_intent_time)
        if (contract.hold_defense and target == "retreat" and plan["army_posture"] == "defend" and emergency
                and ready_army >= plan["retreat_below_army"]):
            return "plan_hold_defense"
        if (target != army_intent and game_time - last_intent_time < plan["min_posture_seconds"]
                and not urgent_withdrawal and not new_defense_order):
            return "plan_hold_army_intent"
        floor = attack_floor(contract, plan["attack_min_army"], resource.get("supply_used", 0))
        if target == "attack" and (plan["army_posture"] != "attack" or ready_army < floor):
            return "plan_attack_not_ready"
        if target == "retreat" and plan["army_posture"] == "attack" and not retreat_needed:
            return "plan_continue_attack"
        if target == "defend" and plan["army_posture"] != "defend" and not emergency:
            return "plan_posture_not_defend"
    return None
