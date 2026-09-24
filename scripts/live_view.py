#!/usr/bin/env python3
"""Live view of the newest JEV-Star run: Astra's plan and Jev's choices."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "macro" / "jev_runs"

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>JEV-Star live</title>
<style>
  body { margin: 0; background: #10140f; color: #e7f0d8; font: 18px/1.4 sans-serif; }
  main { max-width: 820px; margin: 0 auto; padding: 28px 24px 48px; }
  h1 { font-size: 15px; letter-spacing: .14em; text-transform: uppercase; color: #8ea36a; margin: 0 0 8px; }
  .clock { font-size: 42px; font-weight: 650; margin: 0 0 6px; }
  .stats { color: #c5d4ae; margin-bottom: 22px; }
  h2 { font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: #8ea36a; margin: 26px 0 8px; }
  .plan { background: #1a2216; border-left: 4px solid #b6e36a; padding: 14px 16px; }
  .choice { font-size: 28px; font-weight: 650; }
  .conf { color: #b6e36a; }
  ol { padding-left: 1.2em; }
  li { margin: 4px 0; }
  .err { color: #ffb4a2; }
  .muted { color: #8b977c; }
  .result { font-size: 32px; font-weight: 700; margin: 0 0 12px; }
  .result.win { color: #b6e36a; }
  .result.loss { color: #ffb4a2; }
</style>
<main>
  <h1>JEV-Star</h1>
  <p class="result" id="result"></p>
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
async function tick() {
  try {
    const r = await fetch("/state");
    const s = await r.json();
    const result = document.getElementById("result");
    result.textContent = s.result || "";
    result.className = "result " + (s.result === "Victory" ? "win" : s.result === "Defeat" ? "loss" : "");
    document.getElementById("clock").textContent = s.clock || "waiting for a match";
    document.getElementById("stats").textContent = s.stats || "";
    document.getElementById("plan").textContent = s.plan || "No plan yet.";
    document.getElementById("choice").textContent = s.choice || "—";
    document.getElementById("conf").textContent = s.confidence || "";
    document.getElementById("recent").innerHTML = (s.recent || []).map(x => `<li>${x}</li>`).join("");
    document.getElementById("err").textContent = s.error || "";
  } catch (e) {
    document.getElementById("err").textContent = "Live feed disconnected.";
  }
}
tick();
setInterval(tick, 1000);
</script>
"""


def newest_run():
    runs = [p for p in RUNS.iterdir() if p.is_dir()]
    return max(runs, key=lambda p: p.stat().st_mtime) if runs else None


def load_state():
    run = newest_run()
    if run is None:
        return {"clock": "waiting for a match"}
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
    clock = economy.get("game_time") or "starting"
    bits = []
    if economy:
        bits.append(f"{economy.get('worker_supply', 0)} workers")
        bits.append(f"{economy.get('mineral', 0)} minerals")
        bits.append(f"{economy.get('gas', 0)} gas")
        bits.append(f"supply {economy.get('supply_used', 0)}/{economy.get('supply_cap', 0)}")
        bits.append(f"army {economy.get('army_supply', 0)}")
    return {
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

    def do_GET(self):
        if self.path.startswith("/state"):
            body = json.dumps(load_state()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        page = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
