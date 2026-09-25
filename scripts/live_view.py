#!/usr/bin/env python3
"""JEV-Star control panel: start or stop a macro game and watch Astra's plan and Jev's choices."""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "macro" / "jev_runs"
LAUNCH_LOG = RUNS / "launcher.log"
HOST, PORT = "127.0.0.1", int(os.environ.get("JEV_PANEL_PORT", "8765"))

RACES = ["Terran", "Protoss"]
OPPONENTS = ["Zerg", "Terran", "Protoss", "Random"]
DIFFICULTIES = ["VeryEasy", "Easy", "Medium", "MediumHard", "Hard", "Harder", "VeryHard",
                "CheatVision", "CheatMoney", "CheatInsane"]
EFFORTS = ["none", "low", "medium", "high", "xhigh"]

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JEV-Star</title>
<style>
  body { margin: 0; background: #10140f; color: #e7f0d8; font: 18px/1.4 sans-serif; }
  main { max-width: 820px; margin: 0 auto; padding: 28px 24px 48px; }
  h1 { font-size: 15px; letter-spacing: .14em; text-transform: uppercase; color: #8ea36a; margin: 0 0 16px; }
  .clock { font-size: 42px; font-weight: 650; margin: 0 0 6px; }
  .stats { color: #c5d4ae; margin-bottom: 22px; }
  h2 { font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: #8ea36a; margin: 26px 0 8px; }
  .plan { background: #1a2216; border-left: 4px solid #b6e36a; padding: 14px 16px; }
  .choice { font-size: 28px; font-weight: 650; }
  ol { padding-left: 1.2em; }
  li { margin: 4px 0; }
  .err { color: #ffb4a2; }
  .muted { color: #8b977c; }
  .result { font-size: 32px; font-weight: 700; margin: 0 0 12px; }
  .result.win { color: #b6e36a; }
  .result.loss { color: #ffb4a2; }
  form { background: #1a2216; padding: 16px; display: grid; gap: 12px;
         grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  label { display: grid; gap: 4px; font-size: 13px; color: #8ea36a; text-transform: uppercase; letter-spacing: .08em; }
  select, input { font: 16px sans-serif; background: #10140f; color: #e7f0d8; border: 1px solid #3a4a2c;
                  padding: 6px 8px; min-width: 0; }
  .actions { grid-column: 1 / -1; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  button { font: 600 16px sans-serif; padding: 10px 22px; border: 0; cursor: pointer; }
  #start { background: #b6e36a; color: #10140f; }
  #stop { background: #ffb4a2; color: #10140f; }
  button:disabled { opacity: .35; cursor: default; }
  .match { color: #c5d4ae; margin: 0 0 4px; }
</style>
<main>
  <h1>JEV-Star</h1>
  <form id="launch">
    <label>Race <select name="race"></select></label>
    <label>Opponent <select name="opponent_race"></select></label>
    <label>Difficulty <select name="difficulty"></select></label>
    <label>Map <select name="map"></select></label>
    <label>Astra effort <select name="planner_effort"></select></label>
    <label>Time limit (min) <input name="minutes" type="number" min="1" max="60" value="20"></label>
    <div class="actions">
      <button id="start" type="submit">Start game</button>
      <button id="stop" type="button">Stop game</button>
      <span class="muted" id="status"></span>
    </div>
  </form>
  <h2>Match</h2>
  <p class="result" id="result"></p>
  <p class="match" id="match"></p>
  <p class="clock" id="clock">waiting</p>
  <p class="stats" id="stats"></p>
  <h2>Astra plan</h2>
  <div class="plan" id="plan">No plan yet. Astra writes one after it has seen the opening.</div>
  <h2>Jev now</h2>
  <p class="choice" id="choice">—</p>
  <p class="muted" id="conf"></p>
  <h2>Recent choices</h2>
  <ol id="recent"></ol>
  <p class="err" id="err"></p>
</main>
<script>
const form = document.getElementById("launch");
const status = document.getElementById("status");

function fill(name, values, chosen) {
  const select = form.elements[name];
  select.innerHTML = values.map(v => `<option>${v}</option>`).join("");
  if (values.includes(chosen)) select.value = chosen;
}

async function options() {
  const o = await (await fetch("/options")).json();
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("jev-launch") || "{}"); } catch (e) {}
  fill("race", o.races, saved.race || "Terran");
  fill("opponent_race", o.opponents, saved.opponent_race || "Zerg");
  fill("difficulty", o.difficulties, saved.difficulty || "Easy");
  fill("map", o.maps, saved.map || "Altitude LE");
  fill("planner_effort", o.efforts, saved.planner_effort || "medium");
  if (saved.minutes) form.elements.minutes.value = saved.minutes;
}

async function post(path, body) {
  const r = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"},
                               body: JSON.stringify(body || {})});
  const data = await r.json();
  status.textContent = data.message || "";
}

form.addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(form));
  try { localStorage.setItem("jev-launch", JSON.stringify(body)); } catch (e) {}
  status.textContent = "Starting StarCraft II…";
  await post("/start", body);
  tick();
});
document.getElementById("stop").addEventListener("click", async () => {
  if (!confirm("Stop the running game? It is recorded as interrupted.")) return;
  await post("/stop");
  tick();
});

async function tick() {
  try {
    const s = await (await fetch("/state")).json();
    document.getElementById("start").disabled = s.running;
    document.getElementById("stop").disabled = !s.running;
    if (s.running && !status.textContent) status.textContent = "Game running";
    if (!s.running && status.textContent === "Game running") status.textContent = "";
    const result = document.getElementById("result");
    result.textContent = s.result || "";
    result.className = "result " + (s.result === "Victory" ? "win" : s.result === "Defeat" ? "loss" : "");
    document.getElementById("match").textContent = s.match || "";
    document.getElementById("clock").textContent = s.clock || "waiting for a match";
    document.getElementById("stats").textContent = s.stats || "";
    document.getElementById("plan").textContent = s.plan || "No plan yet.";
    document.getElementById("choice").textContent = s.choice || "—";
    document.getElementById("conf").textContent = s.confidence || "";
    const recent = document.getElementById("recent");
    recent.replaceChildren(...(s.recent || []).map(x => Object.assign(document.createElement("li"), {textContent: x})));
    document.getElementById("err").textContent = s.error || "";
  } catch (e) {
    document.getElementById("err").textContent = "Live feed disconnected.";
  }
}
options();
tick();
setInterval(tick, 1000);
</script>
"""


def sc2_path():
    configured = os.environ.get("SC2PATH")
    if configured:
        return Path(configured)
    for candidate in (Path.home() / "Games/battlenet/drive_c/Program Files (x86)/StarCraft II",
                      Path(r"C:\game\StarCraft II"), Path(r"C:\Program Files (x86)\StarCraft II")):
        if candidate.is_dir():
            return candidate
    return None


def maps():
    folders = [ROOT / "macro" / "Maps"]
    if sc2_path():
        folders.append(sc2_path() / "Maps")
    names = {p.stem for folder in folders if folder.is_dir() for p in folder.glob("*.SC2Map")}
    return sorted(names) or ["Altitude LE"]


def game_pids():
    """PIDs of running macro games, including ones started outside this panel."""
    pids = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            cmdline = (proc / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"sc2_rl_agent.starcraftenv_test.run_jev" in cmdline:
            pids.append(int(proc.name))
    return pids


def launch_environment():
    environment = os.environ.copy()
    path = sc2_path()
    if path:
        environment["SC2PATH"] = str(path)
    wine = ROOT / ".tools" / "wine-sc2"
    if os.name != "nt" and wine.is_file():
        environment.setdefault("SC2PF", "WineLinux")
        environment.setdefault("WINE", str(wine))
    return environment


def start_game(request):
    if game_pids():
        return 409, "A game is already running."
    try:
        race, opponent = request["race"], request["opponent_race"]
        difficulty, game_map = request["difficulty"], request["map"]
        effort, minutes = request["planner_effort"], int(request["minutes"])
    except (KeyError, TypeError, ValueError):
        return 400, "Incomplete launch settings."
    if (race not in RACES or opponent not in OPPONENTS or difficulty not in DIFFICULTIES
            or effort not in EFFORTS or game_map not in maps() or not 1 <= minutes <= 60):
        return 400, "Invalid launch settings."
    command = [sys.executable, str(ROOT / "jev_star.py"), "macro", "--race", race, "--map", game_map,
               "--opponent-race", opponent, "--difficulty", difficulty,
               "--game-time-limit", str(minutes * 60)]
    if effort != "none":
        command += ["--planner", "codex", "--planner-effort", effort]
    RUNS.mkdir(parents=True, exist_ok=True)
    with LAUNCH_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n{datetime.now().isoformat(timespec='seconds')} {' '.join(command)}\n")
        log.flush()
        subprocess.Popen(command, cwd=ROOT, env=launch_environment(), stdin=subprocess.DEVNULL,
                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return 200, f"Starting {race} vs {difficulty} {opponent} on {game_map}."


def stop_game():
    pids = game_pids()
    if not pids:
        return 409, "No game is running."
    for pid in pids:
        # Interrupting lets the runner close model clients and write its summary.
        os.kill(pid, signal.SIGINT)
    return 200, "Stopping the game."


def newest_run():
    runs = [p for p in RUNS.iterdir() if p.is_dir()] if RUNS.is_dir() else []
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def load_state():
    running = bool(game_pids())
    run = newest_run()
    if run is None:
        return {"clock": "waiting for a match", "running": running}
    events_path = run / "events.jsonl"
    criteria = {}
    recent = []
    choice = None
    confidence = ""
    error = ""
    economy = {}
    plan_text = ""
    result = ""
    if events_path.exists():
        for line in events_path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("event")
            if kind == "request":
                questions = (event.get("payload") or {}).get("questions") or {}
                if questions:
                    criteria = next(iter(questions.values())).get("criteria") or {}
            elif kind == "response" and not event.get("stale"):
                answer = event.get("answer") or {}
                picked = str(answer.get("choice"))
                label = criteria.get(picked, picked)
                conf = answer.get("confidence")
                choice = label
                confidence = f"confidence {conf:.0%}" if isinstance(conf, (int, float)) else ""
                recent.append(f"{event.get('game_seconds', 0):.0f}s  {label}")
            elif kind == "plan_accepted":
                plan_text = event.get("guidance") or event.get("objective") or plan_text
            elif kind == "heartbeat":
                economy = event.get("economy") or economy
            elif kind == "run_failure":
                failure = event.get("failure") or {}
                error = f"Match stopped: {failure.get('type', 'error')} {failure.get('message', '')}"
            elif kind == "run_end":
                result = event.get("result") or result
                if event.get("economy"):
                    economy = event["economy"]
    plans = sorted((run / "planner").glob("plan-*.json")) if (run / "planner").is_dir() else []
    if plans:
        try:
            plan = json.loads(plans[-1].read_text())
            plan_text = plan.get("guidance") or plan.get("objective") or plan_text
        except (OSError, json.JSONDecodeError):
            pass
    summary_path = run / "summary.json"
    if not result and summary_path.exists():
        try:
            result = json.loads(summary_path.read_text()).get("result") or ""
        except (OSError, json.JSONDecodeError):
            pass
    match = ""
    try:
        settings = json.loads((run / "run.json").read_text())
        match = (f"{settings.get('player_race', 'Protoss')} vs {settings.get('difficulty')} "
                 f"{settings.get('opponent_race')} · {settings.get('map')}")
    except (OSError, json.JSONDecodeError):
        pass
    if running and events_path.exists():
        # StarCraft under Wine sometimes stops simulating; say so instead of showing a frozen page.
        quiet = time.time() - events_path.stat().st_mtime
        if quiet > 15 and not error:
            error = f"No game updates for {quiet:.0f} s: StarCraft II has paused (the game is still running)."
    clock = economy.get("game_time") or ("starting" if running else "")
    bits = []
    if economy:
        bits.append(f"{economy.get('worker_supply', 0)} workers")
        bits.append(f"{economy.get('mineral', 0)} minerals")
        bits.append(f"{economy.get('gas', 0)} gas")
        bits.append(f"supply {economy.get('supply_used', 0)}/{economy.get('supply_cap', 0)}")
        bits.append(f"army {economy.get('army_supply', 0)}")
    return {
        "running": running,
        "match": match,
        "clock": clock,
        "stats": " · ".join(str(b) for b in bits),
        "plan": plan_text,
        "choice": choice,
        "confidence": confidence,
        "recent": recent[-8:][::-1],
        "result": result,
        "error": error,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _json(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/state"):
            self._json(200, load_state())
        elif self.path.startswith("/options"):
            self._json(200, {"races": RACES, "opponents": OPPONENTS, "difficulties": DIFFICULTIES,
                             "efforts": EFFORTS, "maps": maps()})
        else:
            page = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

    def do_POST(self):
        # Only this page may start games: other sites cannot send a same-origin JSON request.
        origin = self.headers.get("Origin")
        allowed = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}
        if (origin not in allowed or self.headers.get("Host") not in {f"{HOST}:{PORT}", f"localhost:{PORT}"}
                or not self.headers.get("Content-Type", "").startswith("application/json")):
            self._json(403, {"message": "Forbidden."})
            return
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 4096)
            request = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json(400, {"message": "Invalid request."})
            return
        if self.path == "/start":
            status, message = start_game(request)
        elif self.path == "/stop":
            status, message = stop_game()
        else:
            status, message = 404, "Unknown action."
        self._json(status, {"message": message})


if __name__ == "__main__":
    print(f"JEV-Star panel: http://{HOST}:{PORT}/", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
