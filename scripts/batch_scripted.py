"""Play a batch of scripted (no-LLM) games faster than real time, several at once, and tabulate the results.

usage: batch_scripted.py NAME [--parallel 3] [--minutes 45] [--games MAP:BUILD ...]

Each game runs `run_jev --policy scripted --fast` into macro/jev_runs/batch-NAME/NN-map-build/ (replay, events and
summary as usual). results.csv in the batch folder gets one row per finished game.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "macro"
PYTHON = ROOT / ".venvs" / "macro" / "bin" / "python"
STAGGER = 20  # seconds between game starts in a batch
DEFAULT_GAMES = [f"{m}:{b}" for m in ("Ancient Cistern LE", "Babylon LE", "Altitude LE", "Neohumanity LE",
                                         "Gresvan LE", "Dragon Scales LE") for b in ("Macro",)] + \
                [f"Ancient Cistern LE:{b}" for b in ("Rush", "Timing", "Power", "Air")]


def environment():
    env = os.environ.copy()
    env.setdefault("SC2PATH", str(Path.home() / "Games/battlenet/drive_c/Program Files (x86)/StarCraft II"))
    wine = ROOT / ".tools" / "wine-sc2"
    if wine.is_file():
        env.setdefault("SC2PF", "WineLinux")
        env.setdefault("WINE", str(wine))
    env["PYTHONPATH"] = str(MACRO)
    return env


def play(index, spec, folder, minutes, difficulty, game_step):
    game_map, build = spec.split(":")
    out = folder / f"{index:02d}-{game_map.split()[0].lower()}-{build.lower()}"
    command = [str(PYTHON), "-m", "sc2_rl_agent.starcraftenv_test.run_jev", "--race", "Terran",
               "--map", game_map, "--opponent-race", "Zerg", "--difficulty", difficulty, "--ai-build", build,
               "--game-time-limit", str(minutes * 60), "--policy", "scripted", "--fast", "--game-step", str(game_step),
               "--output-dir", str(out)]
    started = time.time()
    # Several SC2s starting at once under Wine can miss the connection timeout: stagger starts, retry once.
    time.sleep(STAGGER * (index % 16))
    for attempt in range(2):
        target = out if attempt == 0 else out.with_name(out.name + "-retry")
        with open(folder / f"{target.name}.log", "w") as log:
            subprocess.run(command[:-1] + [str(target)], cwd=MACRO, env=environment(), stdout=log,
                           stderr=subprocess.STDOUT)
        summary = target / "summary.json"
        data = json.loads(summary.read_text()) if summary.exists() else {}
        if data.get("game_seconds", 0) > 60:
            break
    out = target
    row = {"game": out.name, "map": game_map, "build": build, "result": data.get("result", "no summary"),
           "game_time": round(data.get("game_seconds", 0) / 60, 1), "wall_minutes": round((time.time() - started) / 60, 1)}
    print(f"{row['game']:40s} {row['result']:10s} game {row['game_time']:5.1f} min  wall {row['wall_minutes']:5.1f} min",
          flush=True)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--parallel", type=int, default=3)
    parser.add_argument("--minutes", type=int, default=45, help="game minutes before a game counts as a tie")
    parser.add_argument("--difficulty", default="CheatMoney")
    parser.add_argument("--game-step", type=int, default=4)
    parser.add_argument("--games", nargs="*", default=DEFAULT_GAMES, help="MAP:BUILD entries")
    args = parser.parse_args()
    folder = MACRO / "jev_runs" / f"batch-{args.name}"
    folder.mkdir(parents=True, exist_ok=False)
    with ThreadPoolExecutor(args.parallel) as pool:
        rows = list(pool.map(lambda item: play(item[0], item[1], folder, args.minutes, args.difficulty,
                                                  args.game_step),
                             enumerate(args.games, 1)))
    with open(folder / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    wins = sum(r["result"] == "Victory" for r in rows)
    print(f"BATCH {args.name}: {wins}/{len(rows)} wins", flush=True)


if __name__ == "__main__":
    sys.exit(main())
