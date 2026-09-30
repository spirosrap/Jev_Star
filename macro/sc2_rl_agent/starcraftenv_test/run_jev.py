"""Run the Jev macro agent (Protoss or Terran) against the built-in SC2 AI in realtime."""

import argparse
import asyncio
import dataclasses
import hashlib
import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

from .agent.jev_agent import (INSTRUCTIONS, PLAN_INSTRUCTIONS, TERRAN_INSTRUCTIONS, TERRAN_PLAN_INSTRUCTIONS,
                              JevClient, load_api_key)
from .agent.macro_contract import CONTRACTS, VERSION
from .utils.run_logging import RunLog, atomic_json


def positive_float(value):
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return number


# Against these opponents the army does not attack into the enemy main or bases covered by static defence.
AI_BUILDS = ["RandomBuild", "Rush", "Timing", "Power", "Macro", "Air"]  # sc2.data.AIBuild names
CAUTIOUS_DIFFICULTIES = {"CheatMoney", "CheatInsane"}
STOP_GRACE = 20  # seconds the bot has to save the replay after a stop request
CAUTIOUS_PLANNER_TEXT = (
    "This opponent gathers extra resources and out-produces us, so we win by trading, not by attacking into it. "
    "The army will not attack the enemy main (near enemy_start) or bases covered by Spine or Spore Crawlers; such "
    "navigation targets are marked attack_blocked and an attack order toward them holds the army at home instead. "
    "Attack only exposed expansions and enemy forces near our bases, and defend with sieged Tanks. Surplus minerals "
    "are spent automatically on new bases (as Planetary Fortresses), Missile Turrets and Refineries, and Orbital "
    "Commands Scan expansion sites nobody has seen, so exposed enemy bases appear as navigation targets. "
    "The army attacks only in the bot's own push, when we are maxed with a mineral bank and +2 weapons right after "
    "the Zerg lose a wave; an attack posture order is refused, so keep army_posture defend and plan the economy, "
    "production and upgrades toward that push. Marines stop at 40; the bank "
    "goes to Siege Tanks, Marauders and Hellbats, and two Engineering Bays and an Armory research upgrades "
    "automatically.")


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--race", choices=sorted(CONTRACTS), default="Protoss", help="Race the agent plays")
    parser.add_argument("--map", default="Altitude LE")
    parser.add_argument("--opponent-race", choices=["Zerg", "Terran", "Protoss", "Random"], default="Zerg")
    parser.add_argument("--difficulty", choices=["VeryEasy", "Easy", "Medium", "MediumHard", "Hard", "Harder", "VeryHard", "CheatVision", "CheatMoney", "CheatInsane"], default="Easy")
    parser.add_argument("--model", default="typesafe/jev-1.13")
    parser.add_argument("--decision-interval", type=positive_float, default=1.0, help="Minimum wall seconds between request starts")
    parser.add_argument("--request-timeout", type=positive_float, default=2.5)
    parser.add_argument("--max-decision-age", type=positive_float, default=4.0, help="Maximum age in both wall and game seconds")
    parser.add_argument("--max-requests", type=int, default=2000)
    parser.add_argument("--game-time-limit", type=positive_float, default=1200, help="Stop after this many game seconds; a time limit is a Tie")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ai-build", choices=AI_BUILDS, default="RandomBuild",
                        help="The built-in computer's build; a fixed build makes games comparable")
    parser.add_argument("--sc2-path", type=Path)
    parser.add_argument("--config-file", type=Path, default=repo.parent / "config.md", help="Fallback for api: entry; TYPESAFE_API_KEY takes precedence")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--planner", choices=["none", "codex", "claude"], default="none",
                        help="Strategic planner: the Codex CLI (OpenAI models) or the Claude Code CLI, each with its saved login")
    parser.add_argument("--planner-model", default=None,
                        help="Planner model; defaults to gpt-6-astra for codex and claude-opus-5-5 for claude")
    parser.add_argument("--codex-path", type=Path, help="Optional native Codex executable; uses saved Codex login")
    parser.add_argument("--claude-path", type=Path, help="Optional claude executable; uses saved Claude Code login")
    parser.add_argument("--planner-effort", choices=["low", "medium", "high", "xhigh", "max"], default="low")
    parser.add_argument("--planner-interval", type=positive_float, default=60, help="Game seconds between periodic strategic requests")
    parser.add_argument("--planner-execution-window", type=positive_float, default=30, help="Game seconds to execute an accepted plan before ordinary events refresh it")
    parser.add_argument("--planner-min-interval", type=positive_float, default=10, help="Minimum wall seconds between planner requests, including events")
    parser.add_argument("--planner-event-cooldown", type=positive_float, default=30, help="Wall seconds before the same event type can request another update")
    parser.add_argument("--planner-timeout", type=positive_float, default=60, help="Wall seconds before killing a stalled Codex request")
    parser.add_argument("--plan-ttl", type=positive_float, default=180, help="Game seconds a received plan stays valid")
    parser.add_argument("--max-plan-age", type=positive_float, default=60)
    parser.add_argument("--max-planner-requests", type=int, default=80)
    parser.add_argument("--mission-objectives", type=Path,
                        help="Objectives JSON of a campaign mission prepared by scripts/campaign/campaign.py")
    parser.add_argument("--bank-directory", type=Path,
                        help="Where SC2 writes banks (Documents/StarCraft II/Banks); needed with --mission-objectives")
    parser.add_argument("--mission-difficulty", choices=["Casual", "Normal", "Hard", "Brutal"], default="Normal",
                        help="Campaign difficulty the --map was prepared for (recorded with the objectives)")
    args = parser.parse_args()
    if args.max_requests < 1:
        parser.error("--max-requests must be positive")
    if args.max_planner_requests < 1:
        parser.error("--max-planner-requests must be positive")
    if args.planner_model is None:
        args.planner_model = {"codex": "gpt-6-astra", "claude": "claude-opus-5-5"}.get(args.planner)
    try:
        key = load_api_key(args.config_file)
    except ValueError as exc:
        parser.error(str(exc))
    if args.sc2_path:
        os.environ["SC2PATH"] = str(args.sc2_path.resolve())
    elif not os.environ.get("SC2PATH") and Path(r"C:\game\StarCraft II").is_dir():
        os.environ["SC2PATH"] = r"C:\game\StarCraft II"

    output = args.output_dir or repo / "jev_runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never silently overwrite another run.
    settings = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                if k != "config_file"}
    contract = CONTRACTS[args.race]
    if args.race == "Terran" and args.difficulty.startswith("Cheat"):
        # A mid-game attack at ~50 supply is a coin flip against the cheating AIs; wait for a big army.
        contract = dataclasses.replace(contract, min_attack_army=90, maxed_attack_army=60)
    settings.update(realtime=True, player_race=args.race, output_dir=str(output), macro_contract=VERSION,
                    attack_floor={"min_ready_army": contract.min_attack_army,
                                  "at_190_supply": contract.maxed_attack_army or contract.min_attack_army})
    source_dir = Path(__file__).resolve().parent
    sources = [source_dir / name for name in (
        "agent/astra_planner.py", "agent/jev_agent.py", "agent/strategic_policy.py", "agent/macro_contract.py",
        "env/bot/Protoss_bot.py", "env/bot/jev_protoss_bot.py", "env/bot/hierarchical_protoss_bot.py",
        "env/bot/jev_macro_bot.py", "env/bot/hierarchical_bot.py", "env/bot/jev_terran_bot.py",
        "env/bot/hierarchical_terran_bot.py", "env/bot/mission_objectives.py",
        "env/bot/macro_execution.py", "env/bot/macro_navigation.py", "run_jev.py", "utils/run_logging.py",
        "utils/sc2_runtime.py", "utils/action_info.py")]
    atomic_json(output / "source-fingerprints.json", {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    log = RunLog(output, settings, secrets=(key,), console=sys.stdout)
    client = planner_client = bot = None
    result_name, status = "interrupted", "interrupted"
    try:
        # Captures legacy prints and SDK stderr, including startup/import failures.
        with log.capture_engine():
            try:
                # --help, report rebuilding and argument checks need no SC2 installation.
                from sc2 import maps
                from sc2.data import AIBuild, Difficulty, Race
                from .utils.sc2_runtime import run_windowed_game
                from sc2.player import Bot, Computer
                if args.race == "Terran":
                    from .env.bot.jev_terran_bot import JevTerranBot as FlatBot
                    from .env.bot.hierarchical_terran_bot import HierarchicalTerranBot as PlannedBot
                    instructions = (TERRAN_INSTRUCTIONS, TERRAN_PLAN_INSTRUCTIONS)
                else:
                    from .env.bot.jev_protoss_bot import JevProtossBot as FlatBot
                    from .env.bot.hierarchical_protoss_bot import HierarchicalProtossBot as PlannedBot
                    instructions = (INSTRUCTIONS, PLAN_INSTRUCTIONS)

                game_map = maps.get(args.map)
                log("environment", map_path=str(game_map.path), map_sha256=hashlib.sha256(game_map.data).hexdigest(),
                    macro_contract=VERSION)
                client = JevClient(key, args.model, args.request_timeout, instructions=instructions[0],
                                   plan_instructions=instructions[1])
                if args.planner == "codex":
                    from .agent.astra_planner import CodexPlannerClient
                    planner_client = CodexPlannerClient(output, args.codex_path, args.planner_model,
                                                       args.planner_timeout, args.planner_effort,
                                                       contract=contract)
                elif args.planner == "claude":
                    from .agent.astra_planner import ClaudePlannerClient
                    planner_client = ClaudePlannerClient(output, args.claude_path, args.planner_model,
                                                        args.planner_timeout, args.planner_effort,
                                                        contract=contract)
                    bot = PlannedBot(client, output, args.decision_interval, args.max_decision_age,
                                                 args.max_requests, planner_client=planner_client, run_log=log,
                                                 planner_interval=args.planner_interval, plan_ttl=args.plan_ttl,
                                                 planner_min_interval=args.planner_min_interval,
                                                 planner_event_cooldown=args.planner_event_cooldown,
                                                 planner_execution_window=args.planner_execution_window,
                                                 max_plan_age=args.max_plan_age, max_planner_requests=args.max_planner_requests)
                else:
                    bot = FlatBot(client, output, args.decision_interval, args.max_decision_age,
                                       args.max_requests, run_log=log)
                if args.difficulty in CAUTIOUS_DIFFICULTIES and not args.mission_objectives:
                    bot.cautious_attacks = True
                    if planner_client is not None:
                        planner_client.instructions += "\n\n" + CAUTIOUS_PLANNER_TEXT
                if args.mission_objectives:
                    from .env.bot.mission_objectives import MissionObjectives
                    if not args.bank_directory:
                        parser.error("--mission-objectives needs --bank-directory")
                    bot.mission = MissionObjectives(args.mission_objectives, args.bank_directory,
                                                    args.mission_difficulty)
                    bot.mission.clear_bank()
                    if planner_client is not None:
                        planner_client.instructions += "\n\n" + bot.mission.planner_text()
                log.phase = "launching"
                bot.contract = contract
                players = [Bot(Race[args.race], bot)]
                if not args.mission_objectives:
                    players.append(Computer(Race[args.opponent_race], Difficulty[args.difficulty],
                                            AIBuild[args.ai_build]))
                # A campaign mission's enemies are run by its own scripts. A built-in computer would take over the
                # enemy's slot, and its quitting would end the game as a Victory with no objective met.
                # The first interrupt (the panel's Stop) asks the bot to save the replay and stop at its next step;
                # a second one, or none handled within STOP_GRACE seconds, interrupts at once as before.
                def request_stop(signum, frame):
                    bot.stop_requested = True
                    signal.signal(signal.SIGINT, signal.default_int_handler)
                    timer = threading.Timer(STOP_GRACE, os.kill, (os.getpid(), signal.SIGINT))
                    timer.daemon = True
                    timer.start()

                try:
                    result = run_windowed_game(game_map, players,
                                               realtime=True, game_time_limit=args.game_time_limit,
                                               random_seed=args.seed, save_replay_as=str(output / "game.SC2Replay"),
                                               event_sink=log, on_interrupt=request_stop)
                finally:
                    signal.signal(signal.SIGINT, signal.default_int_handler)
                result_name, status = result.name, "completed"
            except (Exception, KeyboardInterrupt) as exc:
                log.fail(exc)
            finally:
                # The legacy bot imports nest_asyncio; run_game and cleanup share its loop.
                try:
                    if bot is not None:
                        asyncio.run(bot.shutdown(result_name))
                    else:
                        if planner_client is not None:
                            asyncio.run(planner_client.close())
                        if client is not None:
                            asyncio.run(client.close())
                except Exception as exc:
                    log.fail(exc)
        log.finish(status, result_name)
        from .run_report import build_report
        try:
            build_report(output)
        except Exception as exc:
            # Original events/summary remain usable and the report can be rebuilt.
            log("report_error", error=type(exc).__name__)
            log.write_summary(log.summary)
            print(f"Report generation failed; rebuild with run_report. Raw logs: {output}", flush=True)
        else:
            print(f"Report: {output / 'report.html'}", flush=True)
        return 0 if log.status == "completed" else 130 if log.status == "interrupted" else 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
