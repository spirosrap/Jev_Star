"""Play a batch of scripted (no-LLM) games faster than real time, several at once, and tabulate the results.

usage: batch_scripted.py NAME [--parallel 3] [--hosts local:3 dell-pc:1 ...] [--minutes 45] [--games MAP:BUILD ...] [--seeds 1 2 ...]

Each game runs `run_jev --policy scripted --fast` into macro/jev_runs/batch-NAME/NN-map-build/ (replay, events and
summary as usual). results.csv in the batch folder gets one row per finished game.

--hosts spreads games over other machines (HOST:GAMES_AT_ONCE; "local" is this one). A remote host needs the same
layout as this checkout at ~/src/Jev_Star-batch (.venvs, .tools, the Wine prefix and an X display :0); the batch
first copies this checkout's bot code there, so every game in a batch plays the same code, and copies each game's
folder back when it ends.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
import queue
import shlex
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "macro"
PYTHON = ROOT / ".venvs" / "macro" / "bin" / "python"
STAGGER = 20  # seconds between game starts in a batch
DEFAULT_GAMES = [f"{m}:{b}" for m in ("Ancient Cistern LE", "Babylon LE", "Altitude LE", "Neohumanity LE",
                                         "Gresvan LE", "Dragon Scales LE") for b in ("Macro",)] + \
                [f"Ancient Cistern LE:{b}" for b in ("Rush", "Timing", "Power", "Air")]


REMOTE_ROOT = "src/Jev_Star-batch"  # relative to the remote home
REMOTE_ENVIRONMENT = ('DISPLAY=:0 WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/1000 SC2PF=WineLinux '
                      'WINE="$HOME/{root}/.tools/wine-sc2" '
                      'SC2PATH="$HOME/Games/battlenet/drive_c/Program Files (x86)/StarCraft II" PYTHONPATH="$PWD"')


def environment():
    env = os.environ.copy()
    env.setdefault("SC2PATH", str(Path.home() / "Games/battlenet/drive_c/Program Files (x86)/StarCraft II"))
    wine = ROOT / ".tools" / "wine-sc2"
    if wine.is_file():
        env.setdefault("SC2PF", "WineLinux")
        env.setdefault("WINE", str(wine))
    env["PYTHONPATH"] = str(MACRO)
    return env


def run_command(host, command, out, log):
    """Play one game on HOST into OUT (a local folder); a remote game's folder is copied back."""
    if host == "local":
        subprocess.run(command + [str(out)], cwd=MACRO, env=environment(), stdout=log, stderr=subprocess.STDOUT)
        return
    remote_out = f"jev_runs/{out.parent.name}/{out.name}"
    remote = (f"cd {REMOTE_ROOT}/macro && {REMOTE_ENVIRONMENT.format(root=REMOTE_ROOT)} "
              f"../.venvs/macro/bin/python {shlex.join(command[1:] + [remote_out])}")
    subprocess.run(["ssh", host, remote], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    subprocess.run(["rsync", "-a", f"{host}:{REMOTE_ROOT}/macro/{remote_out}/", f"{out}/"], stdout=log,
                   stderr=subprocess.STDOUT)


def play(host, index, spec, folder, minutes, difficulty, game_step, seed=1):
    game_map, build = spec.split(":")
    out = folder / (f"{index:02d}-{game_map.split()[0].lower()}-{build.lower()}" + ("" if seed == 1 else f"-s{seed}"))
    command = [str(PYTHON), "-m", "sc2_rl_agent.starcraftenv_test.run_jev", "--race", "Terran",
               "--map", game_map, "--opponent-race", "Zerg", "--difficulty", difficulty, "--ai-build", build,
               "--game-time-limit", str(minutes * 60), "--seed", str(seed), "--policy", "scripted", "--fast",
               "--game-step", str(game_step),
               "--output-dir"]
    started = time.time()
    # Several SC2s starting at once under Wine can miss the connection timeout: retry once.
    for attempt in range(2):
        target = out if attempt == 0 else out.with_name(out.name + "-retry")
        with open(folder / f"{target.name}.log", "w") as log:
            run_command(host, command, target, log)
        summary = target / "summary.json"
        data = json.loads(summary.read_text()) if summary.exists() else {}
        if data.get("game_seconds", 0) > 60:
            break
    out = target
    row = {"game": out.name, "map": game_map, "build": build, "seed": seed, "host": host,
           "result": data.get("result", "no summary"), "game_time": round(data.get("game_seconds", 0) / 60, 1),
           "wall_minutes": round((time.time() - started) / 60, 1)}
    print(f"{row['game']:40s} {row['result']:10s} game {row['game_time']:5.1f} min  wall {row['wall_minutes']:5.1f} min"
          f"  on {host}", flush=True)
    return row


def sync_code(host):
    """Copy this checkout's bot code to HOST, so remote games play the same code as local ones."""
    subprocess.run(["rsync", "-a", "--delete", "--exclude", "__pycache__", f"{MACRO}/sc2_rl_agent",
                    f"{host}:{REMOTE_ROOT}/macro/"], check=True)


def slots(hosts):
    """[(host, n), ...] from HOST:N entries, ordered so the first games spread over the hosts."""
    counts = [(h.rsplit(":", 1)[0], int(h.rsplit(":", 1)[1]) if ":" in h else 1) for h in hosts]
    return [(host, n) for n in range(max(c for _, c in counts)) for host, c in counts if n < c]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--parallel", type=int, default=3, help="games at once on this machine (without --hosts)")
    parser.add_argument("--hosts", nargs="*", help="HOST:GAMES_AT_ONCE entries, e.g. local:3 dell-pc:1")
    parser.add_argument("--minutes", type=int, default=45, help="game minutes before a game counts as a tie")
    parser.add_argument("--difficulty", default="CheatMoney")
    parser.add_argument("--game-step", type=int, default=4)
    parser.add_argument("--games", nargs="*", default=DEFAULT_GAMES, help="MAP:BUILD entries")
    parser.add_argument("--seeds", nargs="*", type=int, default=[1],
                        help="play every game once per seed; games are deterministic for a given seed")
    args = parser.parse_args()
    folder = MACRO / "jev_runs" / f"batch-{args.name}"
    folder.mkdir(parents=True, exist_ok=False)
    hosts = args.hosts or [f"local:{args.parallel}"]
    for host in {h.rsplit(":", 1)[0] for h in hosts} - {"local"}:
        sync_code(host)
    games = queue.Queue()
    for item in enumerate(((spec, seed) for seed in args.seeds for spec in args.games), 1):
        games.put(item)
    rows, lock = [], threading.Lock()

    def worker(host, start_delay):
        # Several SC2s starting at once under Wine can miss the connection timeout: stagger the first starts.
        time.sleep(start_delay)
        while True:
            try:
                index, (spec, seed) = games.get_nowait()
            except queue.Empty:
                return
            row = play(host, index, spec, folder, args.minutes, args.difficulty, args.game_step, seed)
            with lock:
                rows.append((index, row))

    threads = [threading.Thread(target=worker, args=(host, STAGGER * n)) for host, n in slots(hosts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rows = [row for _, row in sorted(rows, key=lambda item: item[0])]
    with open(folder / "results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    wins = sum(r["result"] == "Victory" for r in rows)
    print(f"BATCH {args.name}: {wins}/{len(rows)} wins", flush=True)


if __name__ == "__main__":
    sys.exit(main())
