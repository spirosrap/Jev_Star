#!/usr/bin/env python3
"""Prepare StarCraft II campaign missions for the Jev bots.

A mission is read from the game's own CASC storage (read-only) with .tools/casc_tool, its objectives are read from
its script and English strings, a small reporter trigger is added that saves every objective's state to the
JevObjectives bank once per game second, and the result is packed with .tools/mpq_pack into
<SC2PATH>/Maps/Campaign/<map id>-<difficulty>.SC2Map, with the objectives in .tools/campaign/<map id>.json.

    python3 scripts/campaign/campaign.py list
    python3 scripts/campaign/campaign.py prepare TRaynor02 --difficulty Hard

Build the two tools once with scripts/campaign/build_tools.sh.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / ".tools"
PREPARED = TOOLS / "campaign"
# Raise when the injected script changes, so maps prepared by an older version are rebuilt.
PREPARE_VERSION = 5
DIFFICULTIES = {"Casual": 1, "Normal": 2, "Hard": 3, "Brutal": 4}  # PlayerDifficulty values the missions read

# Wings of Liberty in the usual story order. fit: "yes" base-building and ends by destroying targets or surviving;
# "partial" base-building with a special objective; "no" hero-only, special mechanics, or another race.
WINGS_OF_LIBERTY = [
    ("TRaynor01", "Liberation Day", "no", "Raynor and a few units, no base"),
    ("TRaynor02", "The Outlaws", "yes", "Destroy the Dominion base; rescue the rebels"),
    ("TRaynor03", "Zero Hour", "yes", "Survive until the evacuation"),
    ("THanson01", "The Evacuation", "partial", "Protect the colonist convoys"),
    ("THanson02", "Outbreak", "yes", "Destroy the infested buildings"),
    ("THanson03a", "Safe Haven", "yes", "Destroy the Protoss purifiers (choice with Haven's Fall)"),
    ("THanson03b", "Haven's Fall", "yes", "Destroy the infested colony (choice with Safe Haven)"),
    ("TTychus01", "Smash and Grab", "yes", "Destroy the Protoss and take the artifact"),
    ("TTychus02", "The Dig", "partial", "Defend the drill"),
    ("TTychus03", "The Moebius Factor", "partial", "Capture the data consoles"),
    ("TTychus04", "Supernova", "partial", "Stay ahead of the fire wall"),
    ("TTychus05", "Maw of the Void", "yes", "Destroy the Protoss structures"),
    ("TTosh01", "The Devil's Playground", "partial", "Collect minerals around the lava"),
    ("TTosh02", "Welcome to the Jungle", "partial", "Collect Terrazine canisters"),
    ("TTosh03a", "Breakout", "no", "Hero mission (choice with Ghost of a Chance)"),
    ("TTosh03b", "Ghost of a Chance", "no", "Hero mission (choice with Breakout)"),
    ("THorner01", "The Great Train Robbery", "partial", "Destroy the passing trains"),
    ("THorner02", "Cutthroat", "yes", "Destroy the rival base"),
    ("THorner03", "Engine of Destruction", "partial", "Escort the Odin"),
    ("THorner04", "Media Blitz", "partial", "Hold the broadcast"),
    ("THorner05s", "Piercing the Shroud", "no", "Secret hero mission"),
    ("TZeratul01", "Whispers of Doom", "no", "Protoss (Zeratul)"),
    ("TZeratul02", "A Sinister Turn", "no", "Protoss (Zeratul)"),
    ("TZeratul03", "Echoes of the Future", "no", "Protoss (Zeratul)"),
    ("TZeratul04", "In Utter Darkness", "no", "Protoss (Zeratul)"),
    ("TValerian01", "Gates of Hell", "yes", "Build a base and destroy the Nydus Worms"),
    ("TValerian02a", "Belly of the Beast", "no", "Hero mission (choice with Shatter the Sky)"),
    ("TValerian02b", "Shatter the Sky", "yes", "Destroy the platforms (choice with Belly of the Beast)"),
    ("TValerian03", "All In", "yes", "Defend the artifact"),
]
CAMPAIGNS = {"liberty": {"title": "Wings of Liberty", "race": "Terran", "missions": WINGS_OF_LIBERTY}}

REPORTER = '''
//--------------------------------------------------------------------------------------------------
// Jev-Star objective reporter: saves every objective's state to the JevObjectives bank each second.
//--------------------------------------------------------------------------------------------------
bool[65] gv_jevObjectiveSeen;
string[65] gv_jevObjectiveKey;
void JevRecordObjective (string key, int id) {
    if ((id >= 1) && (id <= 64)) {
        gv_jevObjectiveSeen[id] = true;
        gv_jevObjectiveKey[id] = key;
    }
}
// In a game created through the API, the engine ends the whole game as soon as any objective is set to
// completed (Victory) or failed (Defeat), even a secondary one. The mission's own calls go through these two
// functions instead: they keep the real state for the mission's logic and the reporter, and never hand
// completed or failed to the engine, so the game ends only when the mission itself declares victory or defeat.
int[65] gv_jevObjectiveState;
void JevSaveObjectives ();
int JevObjectiveGetState (int lp_objective) {
    if ((lp_objective >= 1) && (lp_objective <= 64) && (gv_jevObjectiveState[lp_objective] != 0)) {
        return gv_jevObjectiveState[lp_objective] - 10;
    }
    return ObjectiveGetState(lp_objective);
}
void JevObjectiveSetState (int lp_objective, int lp_state) {
    if ((lp_objective >= 1) && (lp_objective <= 64)) {
        gv_jevObjectiveState[lp_objective] = lp_state + 10;
    }
    if ((lp_state != c_objectiveStateCompleted) && (lp_state != c_objectiveStateFailed)) {
        ObjectiveSetState(lp_objective, lp_state);
    }
    JevSaveObjectives();
}
// On victory the campaign library shows its score screen and waits for the player to click Continue, which never
// happens in an API game, and GameOver itself does not end an API game cleanly either. The engine's objective rule
// does: when the mission really ends, complete (victory) or fail (defeat) one extra, hidden objective.
void JevEndMission (int lp_player, int lp_type) {
    int lv_end;
    JevSaveObjectives();
    lv_end = ObjectiveCreate(StringToText("Mission over"), StringToText(""), c_objectiveStateHidden, true);
    if (lp_type == c_gameOverVictory) {
        ObjectiveSetState(lv_end, c_objectiveStateCompleted);
    }
    else {
        ObjectiveSetState(lv_end, c_objectiveStateFailed);
    }
}
// The campaign difficulty the missions read with PlayerDifficulty(1). An API game gives every slot Normal and the
// game does not read hand-written banks, so each difficulty is its own prepared map.
// Lasting pings the mission shows (objective and rescue markers), so the bot knows where to go.
int[33] gv_jevPing;
string[33] gv_jevPingModel;
void JevRecordPing (int lp_ping, string lp_model) {
    int i;
    for (i = 1; i <= 32; i += 1) {
        if (gv_jevPing[i] == 0) {
            gv_jevPing[i] = lp_ping;
            gv_jevPingModel[i] = lp_model;
            return;
        }
    }
}
void JevPingDestroy (int lp_ping) {
    int i;
    for (i = 1; i <= 32; i += 1) {
        if ((gv_jevPing[i] == lp_ping) && (lp_ping != 0)) {
            gv_jevPing[i] = 0;
        }
    }
    PingDestroy(lp_ping);
}
void JevPingDestroyAll () {
    int i;
    for (i = 1; i <= 32; i += 1) {
        gv_jevPing[i] = 0;
    }
    PingDestroyAll();
}
void JevApplySettings () {
    PlayerSetDifficulty(1, JEV_DIFFICULTY);
}
void JevSaveObjectives () {
    int i;
    bank b;
    BankLoad("JevObjectives", 1);
    b = BankLastCreated();
    for (i = 1; i <= 64; i += 1) {
        if (gv_jevObjectiveSeen[i]) {
            BankValueSetFromString(b, "key", IntToString(i), gv_jevObjectiveKey[i]);
            BankValueSetFromInt(b, "state", IntToString(i), JevObjectiveGetState(i));
            if (ObjectiveGetPrimary(i)) {
                BankValueSetFromInt(b, "primary", IntToString(i), 1);
            }
            else {
                BankValueSetFromInt(b, "primary", IntToString(i), 0);
            }
        }
    }
    BankSectionRemove(b, "ping");
    for (i = 1; i <= 32; i += 1) {
        if ((gv_jevPing[i] != 0) && (gv_jevPing[i] != c_invalidPingId)) {
            BankValueSetFromString(b, "ping", IntToString(i), FixedToString(PointGetX(PingGetPosition(gv_jevPing[i])), 1) + " " + FixedToString(PointGetY(PingGetPosition(gv_jevPing[i])), 1) + " " + gv_jevPingModel[i]);
        }
    }
    BankValueSetFromInt(b, "clock", "seconds", FixedToInt(GameGetMissionTime()));
    BankValueSetFromInt(b, "clock", "difficulty", PlayerDifficulty(1));
    BankSave(b);
}
trigger gt_JevObjectiveReporter;
bool gt_JevObjectiveReporter_Func (bool testConds, bool runActions) {
    JevSaveObjectives();
    return true;
}
'''
OBJECTIVE_START = re.compile(r'\bObjectiveCreate(?:ForPlayers)?\(')
# Pings the mission puts on the minimap (objective and rescue markers). Only lasting ones (duration 0) are recorded.
PING_START = re.compile(r'^[ \t]*(?:libNtve_gf_CreatePingFacingAngle|PingCreate)\(', re.M)
PING_DESTROY = re.compile(r'\b(PingDestroy(?:All)?)\(')
OBJECTIVE_STATE = re.compile(r'\b(Objective[GS]etState)\(')
STRING_KEY = re.compile(r'StringExternal\("(Param/Value/[0-9A-F]+)"\)')


def objective_calls(script):
    """Every ObjectiveCreate statement as (end offset, [arguments]); names may be built from several strings."""
    return calls(script, OBJECTIVE_START)


def calls(script, start_pattern):
    """Every statement calling start_pattern's function, as (end offset of the statement, [arguments])."""
    for match in start_pattern.finditer(script):
        depth, start, args, i, quoted = 1, match.end(), [], match.end(), False
        while depth:
            c = script[i]
            if c == '"' and script[i - 1] != "\\":
                quoted = not quoted
            elif not quoted:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                elif c == "," and depth == 1:
                    args.append(script[start:i].strip())
                    start = i + 1
            i += 1
        args.append(script[start:i - 1].strip())
        end = script.index(";", i) + 1
        yield end, args


def text_of(expression, strings):
    """An objective name or description as shown: its strings joined, without the counters filled in at run time."""
    text = "".join(strings.get(key, "") for key in STRING_KEY.findall(expression))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"%\w+%", "", text)  # placeholders the mission fills in at run time
    text = re.sub(r"\(\s+", "(", re.sub(r"\s+", " ", text))
    text = re.sub(r"\s*\([\s/#]*\)", "", text)  # counters the mission fills in at run time
    return text.strip() or expression[:60]


def sc2_path():
    path = os.environ.get("SC2PATH")
    if path:
        return Path(path)
    return Path.home() / "Games/battlenet/drive_c/Program Files (x86)/StarCraft II"


def mission_entry(map_id):
    for campaign, info in CAMPAIGNS.items():
        for entry in info["missions"]:
            if entry[0].lower() == map_id.lower():
                return campaign, info, entry
    raise SystemExit(f"Unknown mission {map_id}")


def storage_folder(campaign, map_id):
    return f"campaigns\\{campaign}.sc2campaign\\base.sc2maps\\maps\\campaign\\{map_id.lower()}.sc2map\\"


def list_components(game_dir, campaign, map_id):
    folder = storage_folder(campaign, map_id)
    listing = subprocess.run([str(TOOLS / "casc_tool"), "list", str(game_dir), folder + "*"],
                             capture_output=True, text=True, check=True).stdout
    return [line.split("\t")[0] for line in listing.splitlines() if line.lower().startswith(folder)]


def read_strings(path):
    strings = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                strings[key] = value
    return strings


def map_name(map_id, difficulty):
    """The prepared map's name, as --map takes it: one map per mission and difficulty."""
    return f"{map_id}-{difficulty}"


def prepared_versions(objectives_path):
    try:
        return json.loads(objectives_path.read_text(encoding="utf-8")).get("maps", {})
    except (OSError, json.JSONDecodeError):
        return {}


def is_prepared(game_dir, map_id, difficulty):
    return ((Path(game_dir) / "Maps" / "Campaign" / f"{map_name(map_id, difficulty)}.SC2Map").exists()
            and prepared_versions(PREPARED / f"{map_id}.json").get(difficulty) == PREPARE_VERSION)


def prepare(map_id, game_dir=None, force=False, difficulty="Normal"):
    campaign, info, (map_id, title, fit, note) = mission_entry(map_id)
    if difficulty not in DIFFICULTIES:
        raise SystemExit(f"Unknown difficulty {difficulty}; choose one of {', '.join(DIFFICULTIES)}")
    game_dir = Path(game_dir or sc2_path())
    target = game_dir / "Maps" / "Campaign" / f"{map_name(map_id, difficulty)}.SC2Map"
    objectives_path = PREPARED / f"{map_id}.json"
    if is_prepared(game_dir, map_id, difficulty) and not force:
        return target, objectives_path
    for tool in ("casc_tool", "mpq_pack"):
        if not (TOOLS / tool).exists():
            raise SystemExit(f"{TOOLS / tool} is missing; run scripts/campaign/build_tools.sh first")
    components = list_components(game_dir, campaign, map_id)
    if not components:
        raise SystemExit(f"No components found for {map_id} in the game data")
    folder = storage_folder(campaign, map_id)
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        lines = []
        for name in components:
            relative = name[len(folder):].replace("\\", "/")
            (work / relative).parent.mkdir(parents=True, exist_ok=True)
            lines.append(f"{name}\t{work / relative}\n")
        subprocess.run([str(TOOLS / "casc_tool"), "extract", str(game_dir)], input="".join(lines),
                       text=True, check=True)
        script_path = work / "mapscript.galaxy"
        script = script_path.read_text(encoding="utf-8", errors="replace")
        strings = read_strings(work / "enus.sc2data/localizeddata/gamestrings.txt")
        objectives, seen, insertions = [], set(), []
        for end, args in objective_calls(script):
            keys = STRING_KEY.findall(args[0])
            if len(args) < 4 or not keys:
                continue
            key = keys[0].rsplit("/", 1)[-1]
            insertions.append((end, key))
            if key in seen:
                continue
            seen.add(key)
            objectives.append({"key": key, "name": text_of(args[0], strings),
                               "description": text_of(args[1], strings), "primary": args[3] == "true"})
        # Record each objective's id when the mission creates it, then report states every second.
        for end, key in reversed(insertions):
            script = script[:end] + f' JevRecordObjective("{key}", ObjectiveLastCreated());' + script[end:]
        # The mission's own state calls go through the shim (before the shim itself is added).
        script = OBJECTIVE_STATE.sub(r"Jev\1(", script)
        script = re.sub(r"\blibCamp_gf_EndCampaignMission\(", "JevEndMission(", script)
        script = PING_DESTROY.sub(r"Jev\1(", script)
        for end, args in reversed(list(calls(script, PING_START))):
            duration = args[4] if len(args) > 4 else ""
            if re.fullmatch(r"0(\.0+)?", duration):
                model = args[1] if re.fullmatch(r'"[A-Za-z0-9_]*"', args[1]) else '""'
                script = script[:end] + f" JevRecordPing(PingLastCreated(), {model});" + script[end:]
        includes = list(re.finditer(r'^include "[^"]+"\n', script, re.M))
        reporter = REPORTER.replace("JEV_DIFFICULTY", str(DIFFICULTIES[difficulty]))
        script = script[:includes[-1].end()] + reporter + script[includes[-1].end():]
        init = "    InitTriggers();\n}"
        if init not in script or "void InitMap () {\n" not in script:
            raise SystemExit(f"{map_id}: InitMap not found; objective reporting cannot be added")
        script = script.replace("void InitMap () {\n", "void InitMap () {\n    JevApplySettings();\n", 1)
        script = script.replace(init, "    InitTriggers();\n"
                                      "    gt_JevObjectiveReporter = TriggerCreate(\"gt_JevObjectiveReporter_Func\");\n"
                                      "    TriggerAddEventTimePeriodic(gt_JevObjectiveReporter, 1.0, c_timeGame);\n}", 1)
        script_path.write_text(script, encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(TOOLS / "mpq_pack"), str(target), str(work)], check=True)
    PREPARED.mkdir(parents=True, exist_ok=True)
    versions = {d: v for d, v in prepared_versions(objectives_path).items() if v == PREPARE_VERSION}
    versions[difficulty] = PREPARE_VERSION
    objectives_path.write_text(json.dumps({
        "maps": versions, "campaign": info["title"], "race": info["race"], "map": map_id, "title": title,
        "fit": fit, "note": note, "objectives": objectives}, indent=2, ensure_ascii=False), encoding="utf-8")
    return target, objectives_path


def catalog(game_dir=None):
    game_dir = Path(game_dir or sc2_path())
    return [{"campaign": info["title"], "race": info["race"], "order": number, "map": map_id, "title": title,
             "fit": fit, "note": note,
             "prepared": [d for d in DIFFICULTIES if is_prepared(game_dir, map_id, d)]}
            for info in CAMPAIGNS.values()
            for number, (map_id, title, fit, note) in enumerate(info["missions"], 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    prep = sub.add_parser("prepare")
    prep.add_argument("map_id")
    prep.add_argument("--force", action="store_true", help="Rebuild even if the mission is already prepared")
    prep.add_argument("--difficulty", choices=list(DIFFICULTIES), default="Normal")
    args = parser.parse_args()
    if args.command == "list":
        for m in catalog():
            print(f"{m['order']:2d}. {m['title']:<26} {m['map']:<13} {m['fit']:<8} "
                  f"{','.join(m['prepared']):<14} {m['note']}")
    else:
        target, objectives = prepare(args.map_id, force=args.force, difficulty=args.difficulty)
        data = json.loads(objectives.read_text(encoding="utf-8"))
        print(f"Prepared {data['title']}: {target}")
        for o in data["objectives"]:
            print(f"  {'Primary' if o['primary'] else 'Secondary'}: {o['name']}")


if __name__ == "__main__":
    sys.exit(main())
