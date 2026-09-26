# JEV-Star

[English](#english) | [简体中文](#简体中文)

**StarCraft II macro (Protoss or Terran) and micromanagement with JEV action selection and optional GPT-6 Astra planning.**

**由 JEV 选择动作、可选 GPT-6 Astra 规划的星际争霸 II 宏观控制（Protoss 或 Terran）与微操。**

[Read the paper / 在线阅读论文](paper/PAPER.md) · [PDF](paper/JEV-Star.pdf) · [Video gallery / 视频展示](media/README.md) · [Citation / 引用](#citation)

## Videos / 视频

Play the full winning games directly below. **22.4 fps, original speed, complete matches.**

点击下方播放器即可观看完整胜局，**22.4 fps、原速播放**。

### M01 · Macro VeryHard / Elite victory / 宏观最高非作弊难度胜局

macro-v2.1 / Astra + JEV · 12:47.90

https://github.com/user-attachments/assets/5cab5e0a-e8c4-43b8-a504-96f916f73e2a

### M02 · Macro Easy victory / 宏观 Easy 胜局

earlier Astra + JEV macro · 15:04.20

https://github.com/user-attachments/assets/2beaa558-67d5-4b7f-8a8d-c29f4359ab36

### U01 · Micro mmmt victory / 微观 mmmt 胜局

C / P0 Astra + JEV / schema 7 · 00:21.43

https://github.com/user-attachments/assets/48b26ba0-63be-45c4-82a5-f4bb6814f73e

## English

JEV-Star brings full-game macro control and SMAC-Hard micromanagement into one repository. Each module has its own environment, action space, and experiment records:

| Module | Game interface | Model responsibilities | Current implementation |
| --- | --- | --- | --- |
| [Macro](macro/README.md#english) | LLM Play SC2 / BurnySC2 | Astra plans strategic phases; JEV selects economy, technology, production, and army actions | `macro-v2.3.0`; Protoss (73 actions) or Terran (71 actions) against the built-in AI of any race; real-time games |
| [Micro](micro/README.md#english) | PySC2 bundled with SMAC-Hard | Astra creates one plan per map; JEV selects actions for living units | `p0-v1`; 35 maps; fixed stepping with `realtime=False` |

```mermaid
flowchart LR
    A[Astra planning] --> M[JEV macro decisions]
    A --> U[JEV unit decisions]
    M --> B[BurnySC2 executor]
    U --> P[SMAC-Hard / PySC2]
    B --> G[StarCraft II]
    P --> G
```

### Videos and replays

The players at the top of this README show three complete winning games. [Media details and 22 original winning replays](media/README.md#english). Selected victories are shown separately from the complete evaluation results below.

### Quick start

The validated setup is **Windows, Python 3.10, and SC2 5.0.16.97563 installed for the Asia region (`kr`)**. Install the SC2 client separately; matches are created through the local SC2 API. The two modules use separate virtual environments to keep their SC2 SDK dependencies isolated.

Jev requests go to OpenRouter's TypeSafe-compatible endpoint, `https://openrouter.ai/api/v1/systemone`, model `typesafe/jev-1.13`. Set `OPENROUTER_API_KEY`, or an `openrouter:` line in `config.md`. Override the URL with `JEV_API_ENDPOINT` if needed.

```powershell
git clone https://github.com/sc2musa/Jev_Star.git
cd Jev_Star
py -3.10 scripts/setup_environment.py macro
py -3.10 scripts/setup_environment.py micro --video

$env:SC2PATH = 'C:\game\StarCraft II'
$env:OPENROUTER_API_KEY = '<your OpenRouter key>'
py -3.10 scripts/install_maps.py all
```

Alternatively, copy [config.example.md](config.example.md) to a local `config.md`. Git ignores the real key file. Astra planning uses an authenticated native Codex CLI installation; use `--codex-path` to specify its executable explicitly.

Before running macro games, launch the installed SC2 client once to generate `stableid.json`, then synchronize the BurnySC2 enums. Use the version of your installed client:

```powershell
& .\.venvs\macro\Scripts\python.exe -B scripts/sync_sc2_ids.py --game-version 5.0.16.97563
```

Run one macro game (Protoss by default; add `--race Terran` to play Terran):

```powershell
py -3.10 jev_star.py macro --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy --game-time-limit 1200
py -3.10 jev_star.py macro --race Terran --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy --game-time-limit 1200
```

#### Control panel

`scripts/live_view.py` serves a local page at <http://127.0.0.1:8765/> for starting and watching macro games without the command line. Choose race, opponent, difficulty, map, Astra effort, and time limit, then press **Start game**; **Stop game** interrupts the match and still writes its logs. The page shows Astra's current plan, Jev's recent choices, economy, the match result, and a notice when StarCraft II stops updating. On Linux, `scripts/jev-star-panel` starts the panel in the background (if needed) and opens it in the browser. The panel only accepts start/stop requests from its own page.

#### Linux (Wine/Proton)

Macro games also run on Linux with the Windows SC2 client under Wine or Proton. Point BurnySC2 at the Wine prefix and a launcher that runs `SC2_x64.exe` directly (BurnySC2's default `wine start` returns immediately, so the bot loses the process):

```bash
export SC2PF=WineLinux
export WINE=/path/to/wine-sc2   # script that execs Proton/Wine's wine binary on SC2_x64.exe
export SC2PATH="$HOME/Games/battlenet/drive_c/Program Files (x86)/StarCraft II"
python3 jev_star.py macro --race Terran --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy
```

The control panel fills in these variables when it finds `.tools/wine-sc2` and the Battle.net prefix above. Run StarCraft II fullscreen: a large tiled window under Xwayland can flicker and stall the game on integrated graphics.

Run three micro episodes on `3m`:

```powershell
py -3.10 jev_star.py micro --map 3m --episodes 3 --planner codex --planner-effort medium --planner-timeout 180 --request-timeout 15 --max-requests 10000
```

Use `py -3.10 jev_star.py macro --help` or `micro --help` for all options. Relative paths in forwarded arguments are resolved inside `macro/` or `micro/`.

### Experiment status

Each micro version was evaluated on 35 maps with three episodes per map. JEV alone achieved **3 wins, 2 draws, and 100 losses**; the earlier Astra + JEV version achieved **6 wins, 1 draw, and 98 losses**; P0 Astra + JEV achieved **7 wins and 98 losses**. Excluding the two development maps, the three versions achieved **3/99, 3/99, and 7/99 wins**, respectively.

Earlier macro versions won two games against the non-cheating VeryHard/Elite AI. The subsequent version with expanded action coverage lost one game each against CheatVision and CheatMoney. `macro-v2.2.1` added termination on permanent billing errors. The current `macro-v2.3.0` adds Terran; its results are below. Macro has passed **212 offline regression tests** (Protoss behavior is unchanged) and micro **37**. These are small samples, not estimates of a stable win rate.

Jev calls cost about **$0.04 per million tokens** through OpenRouter (blended rate); a 10-minute macro game uses roughly 1.6M tokens, about $0.06. Astra planning runs on the Codex CLI subscription and is not included.

#### Terran results (`macro-v2.3.0`)

All games: Terran against the built-in Zerg AI, Astra planning at `medium` effort, Linux with the SC2 client under Proton. Games run on Altitude LE unless noted, with a 20-minute limit through T14 and 30 minutes afterwards. Each game ran with the fixes made after the one before it.

| Game | Opponent | Result | Game time | Jev input tokens | Changes in effect |
| --- | --- | --- | --- | --- | --- |
| T1 | Easy | Victory | 9:36 | 1.57M | First Terran executor |
| T2 | VeryHard | Victory | 13:58 | 2.33M | Batched building placement |
| T3 | VeryHard | Victory | 13:25 | 2.36M | Rejected spots and add-on slots kept free; spending a large bank |
| T4 | VeryHard | Victory | 10:17 | 1.79M | Bunker, SCV repair, supply reserve, Zerg guidance for Astra |
| T5 | **CheatVision** | **Victory** | 10:21 | 1.76M | Baneling dodging for Marines and SCVs; no gas workers as builders |
| T6 | **CheatVision** | **Victory** | 11:46 | 2.11M | None (test plan phase 1, commit `ddd0970`) |
| T7 | CheatVision | Defeat | 12:28 | 2.32M | None (test plan phase 1, commit `ddd0970`) |
| T8 | **CheatVision** | **Victory** | 12:21 | 2.18M | Gas balancing, 40-supply attack floor, Changeling targeting (restarted phase 1, game 1; commit `164e70b`) |
| T9 | **CheatVision** | **Victory** | 10:22 | 1.74M | None (restarted phase 1, game 2; commit `164e70b`) |
| T10 | **CheatVision** | **Victory** | 10:20 | 1.79M | None (restarted phase 1, game 3; commit `164e70b`) |
| T11 | **CheatVision** | **Victory** | 15:51 | 2.78M | Barracks recommended when minerals bank (phase 2, game 1, **Ancient Cistern LE**; commit `cb65b50`) |
| T12 | **CheatVision** | **Victory** | 11:33 | 1.90M | Batch training and four concurrent production buildings while banked (restarted phase 2, game 1, **Ancient Cistern LE**; commit `d9206cb`) |
| T13 | CheatVision | Tie (time limit) | 19:59 | 3.53M | None (restarted phase 2, game 2, **Ancient Cistern LE**; commit `d9206cb`) |
| T14 | CheatVision | Tie (time limit) | 19:59 | 3.68M | Scans against Lurkers, holding an attacked base, expansion recovery (restarted phase 2, game 1, **Ancient Cistern LE**; commit `b361c1b`) |
| T15 | CheatVision | Defeat | 17:01 | 2.97M | Reinforcements gather before joining an attack; army-mix guidance; 30-minute limit (**Ancient Cistern LE**; commit `2ca1641`, later reverted) |
| T16 | CheatVision | Defeat | 17:24 | 2.88M | None (**Ancient Cistern LE**; commit `2ca1641`, later reverted) |
| T17 | CheatVision | Defeat | 19:23 | 3.21M | Reinforcement grouping reverted (phase 2, game 1, **Ancient Cistern LE**; bot code `b361c1b`, commit `a9ef6e2`) |
| T18 | **CheatVision** | **Victory** | 15:01 | 2.41M | Attack only with 90 ready army supply, or 60 once maxed, against the cheating AIs (phase 2, game 1, **Ancient Cistern LE**; commit `fbe1a59`) |
| T19 | **CheatVision** | **Victory** | 21:53 | 3.87M | None (phase 2, game 2, **Ancient Cistern LE**; commit `fbe1a59`) |
| T20 | CheatVision | Defeat | 24:17 | 4.08M | None (phase 2, game 3, **Babylon LE**; commit `fbe1a59`) |
| T21 | CheatVision | Defeat | 21:26 | 3.61M | Builder path check; access-error retry (phase 2, game 4, **Babylon LE**; commit `d3b6bb2`) |
| T22 | CheatVision | Defeat | 17:56 | 3.09M | Home guard and recall; Engineering Bay, Armory and infantry upgrades on schedule (phase 3, game 1, **Babylon LE**; commit `c0f92cc`) |

One further VeryHard game was stopped by hand after the SC2 window stalled and is not counted. A CheatVision game on Ancient Cistern LE (commit `b361c1b`) was won in 10:01 but is also not counted: the Codex login stopped working mid-game (Astra's requests failed with authentication errors from 6:38), so Jev played mostly without plans; the control panel now shows "Astra unavailable" when this happens. A game on the reverted code (Ancient Cistern LE, commit `a9ef6e2`) was stopped at 12:29 when the Jev provider started refusing requests (HTTP 403, "RBAC: access denied"); it is not counted. A Babylon LE game on commit `1bae3ec` stopped the same way at 6:36 (HTTP 404) and is not counted either. OpenRouter began listing a new `typesafe/jev-router` the evening before; requests for `typesafe/jev-1.13` were still answered by `jev-1.13-20260917`, the version used in every game, but the provider briefly refused access twice. Access errors (401, 403, 404) are now retried for up to 60 seconds before a run stops. For comparison, the Protoss runs on the same machine the day before won three games against MediumHard and lost one against VeryHard.

T5 is the first win above VeryHard recorded in this repository; the earlier Protoss version lost its CheatVision and CheatMoney games. It is still a single game on one map against one race, so it is evidence, not a win rate.

T7 was lost: an early Zergling–Baneling attack (at least 25 Zerglings and 7 Banelings around 4:00–5:30) destroyed the Bunker, all Marines, and the natural; while rebuilding, 4 of 13–17 SCVs stayed on gas and 400–800 gas went unspent while minerals stayed under 100; and a 9:03 attack with about 30 army supply died, after which both bases fell. The fixes that followed (gas balancing, a 40-supply attack floor, and targeting Changelings) restart phase 1 of the test plan.

What changed the outcome: T2–T3 won despite losing bases to Zergling–Baneling pressure and banking minerals. After the Bunker, supply reserve, and Zerg guidance (T4), the bot kept both bases, never retreated, and grew to 48 SCVs by 10:00. With Baneling dodging (T5, 403 dodges) it lost no base against CheatVision and reached 60 SCVs and 161 supply by 10:00, with no failed orders.

#### Test plan for the cheating AIs

Before testing other opponent races, confirm the Zerg results. Keep settings and code fixed within a phase (record the commit of each game), play fullscreen on an otherwise idle machine, and do not count games stopped by hand or by a stall. If a bug forces a code change, fix it and restart that phase's count.

| Phase | Games | Goal |
| --- | --- | --- |
| 1. Repeat CheatVision | 5 against CheatVision Zerg on Altitude LE | At least 3 of 5 wins shows T5 was not luck. On commit `ddd0970` it went 2–1 (T5–T7); after the T7 fixes, 3–0 on `164e70b` (T8–T10), which meets the goal, so the remaining two games were skipped for phase 2 |
| 2. Other maps | 2 each on Ancient Cistern LE and Babylon LE against CheatVision Zerg | Placement and Bunker position work beyond one map. **Completed with the 90-supply attack rule: 2–2** (T18–T19 won on Ancient Cistern, T20–T21 lost on Babylon). On `cb65b50` it went 1–0 (T11); on `d9206cb` one win and one tie (T12–T13); on `b361c1b` one tie (T14); on `2ca1641` two defeats (T15–T16), then reverted to `b361c1b`. Restarted on the reverted code with a 30-minute limit and no further code changes during the phase |
| 3. Home defense and upgrades | 2 each on Babylon LE and Ancient Cistern LE against CheatVision Zerg, code frozen | Babylon losses fixed without losing Ancient Cistern. On `c0f92cc` one defeat on Babylon (T22); restarted after the anti-Baneling schedule below |
| 4. CheatMoney | 3 against CheatMoney Zerg on Altitude LE | Extra enemy income; expect larger armies earlier |
| 5. CheatInsane | 3 against CheatInsane Zerg on Altitude LE | Extra income and full vision; the hardest built-in AI |

Before phase 2, T8–T10 still banked 600–1,600 minerals late in the game: Jev rarely chose an offered Barracks, and the plan's Barracks ceiling applied until 800 minerals. The large-bank override now starts at 600 minerals and recommends another Barracks to Jev.

T11 (Ancient Cistern LE) placed every building without an engine error, but banked up to 2,615 minerals between 9:00 and 12:00: only two production buildings could be under construction at once (Barracks was refused as already pending in 105 of 111 decisions), and one decision per second trains one unit, too few for about 14 production slots. With 600 or more minerals banked, a Marine, Marauder, Siege Tank, or Medivac choice now fills every free producer, and up to four production buildings may be under construction at once.

T13 reached 200/200 supply by 15:00 but did not finish Zerg before the 20-minute limit. Its attacks stalled against burrowed Lurkers with one Raven for detection and no scans; at 16:21 it retreated from an attacked base with 110 ready army supply under a defend plan; and it retried unreachable expansion sites (seven "couldn't reach target" failures), with two builders taken from gas. Orbital Commands now scan ahead of a fighting army when Lurkers were seen recently, a defend plan no longer retreats from an attacked base while the army is above the retreat threshold, and expansions skip rejected sites and use mineral workers.

T14 used every new fix (6 scans against Lurkers, retreat refused 144 times while holding a base, 175 batch-trained units) but ended in a second tie: five attacks each lost about half the army and turned back, while CheatVision rebuilt. New units walked to the fight one at a time, and by 19:00 the army was 18 Siege Tanks and 6 Marines. The next version made new units gather near home during an attack and leave in groups of about 8 supply, and asked Astra for about three Marines or Marauders per Siege Tank. It lost both games (T15–T16): first attacks of the same size as before ended with 15–21 ready army supply instead of 25–47, because the fighting army no longer received a steady stream of reinforcements, and Zerg counter-attacked into a weak home. Both changes were reverted, returning the bot to the T14 code (`b361c1b`). The remaining games keep the 30-minute limit, since a 20-minute tie with a maxed, five-base army says little about the result.

T15–T17 were lost the same way on two code versions, so the reinforcement change was not the cause. Replaying 40 logged decisions from the T12 win gave Jev's original choice every time, and Astra's latency, output size, and plans were unchanged, so neither model had changed. Before 8:00 the Zerg army looked alike in every game; what differed was the bot's first attack, at about 7:20–8:15 with 40–57 ready army supply: after it the army kept 25–47 supply in the wins and ties but 15–21 in the losses, and Zerg then reached Infestors, Lurkers, and Ultralisks. Against the cheating AIs the Terran bot now attacks only with at least 90 ready army supply (60 once total supply reaches 190), defending behind the Bunker and sieged Tanks and expanding until then. Phase 2 restarts on this version.

On Babylon LE (T20) the bot kept its bases through 20 minutes, but six buildings failed with "couldn't reach target": free spots walled in by terrain or its own buildings. All three Armory attempts failed, so it had no level 2–3 upgrades or Thors when 7 Ultralisks and 12 Mutalisks destroyed its Marine army at about 20:50. Placement now also checks, in one batched query, that the builder can walk to the spot. As a bug fix this does not restart phase 2.

Phase 2 showed what the 90-supply rule fixes and what it leaves open. Both Babylon losses followed the same pattern: while the army attacked, Zerg raided a base behind it (about 30 SCVs lost in T20, a base and 14 SCVs in T21), and the army fought the late game without level 2–3 upgrades (T20's Armory failed to build; T21 never planned one), losing about 60 supply in single fights. Two Siege Tanks now stay home during an attack, a raid on a base far from the army brings the army back, and an Engineering Bay, an Armory and infantry upgrades are recommended on a fixed schedule.

In T22 the upgrades came on time (Engineering Bay 5:37, Armory 6:45), but the army never reached the attack size: CheatVision brought 19 Banelings before 10:00 on Babylon (17–20 in T20–T21 as well) and destroyed a mostly-Marine defense with one or two Siege Tanks at 9:00 and again at 13:30. The schedule now also asks for a Factory with a Tech Lab by 5:30, two Siege Tanks by 6:30, and four Widow Mines by 7:00, and for a Planetary Fortress at the most exposed base once Banelings are seen; sieged Tanks and burrowed Mines now count toward those numbers.

For each game, record the result, game time, Jev tokens, the review items (failed orders, supply blocks, banked minerals, base losses, Baneling dodges), and any code change. After these phases, repeat phases 1–2 against Terran and Protoss opponents at VeryHard and then CheatVision.

[Experiments and version boundaries](docs/experiments.md) · [Architecture and data flow](docs/architecture.md) · [Logs and replays](docs/logs-and-replays.md) · [Paper PDF](paper/JEV-Star.pdf) · [Paper source and data](paper/README.md#english)

### Repository layout

```text
macro/       Macro controller, tests, and six ladder maps
micro/       Micro controller, PySC2/SMAC-Hard runtime, tests, and 35 maps
scripts/     Environment setup, map installation, SC2 enum synchronization, and the control panel
docs/        Architecture, experiments, cleanup notes, and source manifest
paper/       Current paper, LaTeX source, figures, and fixed analysis data
licenses/    Upstream licenses
jev_star.py  Unified command entry point for the two isolated environments
```

Run outputs are stored under each module's `jev_runs/` directory. Full events, generated replays and videos, virtual environments, credentials, and machine diagnostics are excluded from Git; the original research archives remain in the local workspace. Reviewed full-length videos under `media/videos/` and original winning replays under `media/replays/` are included. The README uses GitHub's native inline video players; original higher-bitrate recordings are also archived in Releases. The repository also includes the paper's fixed statistical tables. Excerpts do not replace complete original logs.

### Tests

```powershell
Push-Location macro
& ..\.venvs\macro\Scripts\python.exe -B -m unittest discover -s tests -p 'test_jev*.py'
Pop-Location
Push-Location micro
& ..\.venvs\micro\Scripts\python.exe -B -m unittest discover -s tests -p 'test_jev*.py'
Pop-Location
```

Tests use mocked interfaces and do not launch the game or call paid models. GitHub Actions runs the same two offline test suites. See the [cleanup record](docs/repository-cleanup.md) for the scope of the initial publication checks.

### Upstream sources

Macro is based on [LLM Play SC2](https://github.com/sc2musa/Large-Language-Models-play-StarCraftII). Micro is based on [SMAC-Hard](https://github.com/devindeng94/smac-hard) and its bundled PySC2. Original source notices and applicable licenses are retained; see [third-party notices](THIRD_PARTY_NOTICES.md) and the [source manifest](docs/source-manifest.json).

## 简体中文

JEV-Star 将完整对局的宏观控制与 SMAC-Hard 微操放在同一个仓库中维护。两个模块各有独立环境、动作空间和实验记录：

| 模块 | 游戏接口 | 模型职责 | 当前实现 |
| --- | --- | --- | --- |
| [宏观 macro](macro/README.md#简体中文) | LLM Play SC2 / BurnySC2 | Astra 阶段规划，JEV 选择经济、科技、生产和军队动作 | `macro-v2.3.0`；Protoss（73 个动作）或 Terran（71 个动作），对手为任意种族内置 AI；实时对局 |
| [微观 micro](micro/README.md#简体中文) | SMAC-Hard 自带的 PySC2 | Astra 每图一份计划，JEV 为存活单位选择动作 | `p0-v1`；35 张图；固定步进 `realtime=False` |

```mermaid
flowchart LR
    A[Astra planning] --> M[JEV macro decisions]
    A --> U[JEV unit decisions]
    M --> B[BurnySC2 executor]
    U --> P[SMAC-Hard / PySC2]
    B --> G[StarCraft II]
    P --> G
```

### 胜局视频与回放

本页上方可直接播放 3 场完整胜局。[视频说明与 22 份原始胜局 replay](media/README.md#简体中文)。这里展示选定胜局，完整实验成绩见下文。

### 快速开始

已验证环境为 **Windows、Python 3.10、SC2 5.0.16.97563 亚服 kr 安装**。SC2 客户端需自行安装；对局通过本地 SC2 API 创建。使用两个虚拟环境，避免不同 SC2 SDK 的依赖互相覆盖。

```powershell
git clone https://github.com/sc2musa/Jev_Star.git
cd Jev_Star
py -3.10 scripts/setup_environment.py macro
py -3.10 scripts/setup_environment.py micro --video

$env:SC2PATH = 'C:\game\StarCraft II'
$env:OPENROUTER_API_KEY = '<your OpenRouter key>'
py -3.10 scripts/install_maps.py all
```

也可将 [config.example.md](config.example.md) 复制为本地 `config.md`。实际密钥文件已被 Git 忽略。Astra 规划使用已登录的原生 Codex CLI；通过 `--codex-path` 可以显式指定它的路径。

宏观实战前，应启动一次安装好的 SC2 以生成 `stableid.json`，再同步 BurnySC2 枚举；版本号以实际客户端为准：

```powershell
& .\.venvs\macro\Scripts\python.exe -B scripts/sync_sc2_ids.py --game-version 5.0.16.97563
```

宏观一局（默认 Protoss；加 `--race Terran` 使用 Terran）：

```powershell
py -3.10 jev_star.py macro --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy --game-time-limit 1200
py -3.10 jev_star.py macro --race Terran --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy --game-time-limit 1200
```

#### 控制面板

`scripts/live_view.py` 在 <http://127.0.0.1:8765/> 提供本地页面，无需命令行即可开始和观看宏观对局。选择种族、对手、难度、地图、Astra 推理强度和时限后点击 **Start game**；**Stop game** 中断对局并照常写出日志。页面显示 Astra 当前计划、Jev 最近的选择、经济数据、比赛结果，以及 StarCraft II 停止更新时的提示。Linux 上可用 `scripts/jev-star-panel` 在后台启动面板（如尚未运行）并在浏览器中打开。面板只接受来自自身页面的开始/停止请求。

#### Linux（Wine/Proton）

宏观对局也可在 Linux 上通过 Wine 或 Proton 运行 Windows 版 SC2 客户端。需让 BurnySC2 使用 Wine 前缀，并提供直接运行 `SC2_x64.exe` 的启动脚本（BurnySC2 默认的 `wine start` 会立即返回，Bot 将失去进程）：

```bash
export SC2PF=WineLinux
export WINE=/path/to/wine-sc2   # 用 Proton/Wine 的 wine 直接执行 SC2_x64.exe 的脚本
export SC2PATH="$HOME/Games/battlenet/drive_c/Program Files (x86)/StarCraft II"
python3 jev_star.py macro --race Terran --planner codex --planner-effort medium --map 'Altitude LE' --opponent-race Zerg --difficulty Easy
```

控制面板在找到 `.tools/wine-sc2` 和上述 Battle.net 前缀时会自动设置这些变量。请全屏运行 StarCraft II：在集成显卡上，Xwayland 下的大尺寸平铺窗口可能闪烁并使游戏卡顿。

微观 `3m` 三局：

```powershell
py -3.10 jev_star.py micro --map 3m --episodes 3 --planner codex --planner-effort medium --planner-timeout 180 --request-timeout 15 --max-requests 10000
```

所有参数可通过 `py -3.10 jev_star.py macro --help` 或 `micro --help` 查看。转发参数中的相对路径以 `macro/` 或 `micro/` 为基准。

### 实验状态

微观每版 35 图 × 3 局：纯 JEV 为 **3 胜、2 平、100 负**，旧 Astra＋JEV 为 **6 胜、1 平、98 负**，P0 Astra＋JEV 为 **7 胜、98 负**。排除两张开发地图后，三版分别为 **3/99、3/99、7/99 胜**。

宏观历史版本已在非作弊的 VeryHard/Elite 难度取得两局胜利；随后动作补全版本在 CheatVision、CheatMoney 各一局失利。`macro-v2.2.1` 增加永久计费错误的停止机制。当前 `macro-v2.3.0` 新增 Terran，成绩见下文。宏观已有 **212 项离线回归通过**（Protoss 行为不变），微观 **37 项**。这些是有限样本，不是稳定胜率估计。

经 OpenRouter 调用 Jev 约 **每百万 token 0.04 美元**（综合费率）；10 分钟的宏观对局约 160 万 token，约 0.06 美元。Astra 规划使用 Codex CLI 订阅，不计入其中。

#### Terran 成绩（`macro-v2.3.0`）

全部对局：Terran 对内置 Zerg AI，Astra 规划强度 `medium`，Linux 上通过 Proton 运行 SC2 客户端。除注明外地图为 Altitude LE；T14 及之前时限 20 分钟，之后为 30 分钟。每局都包含上一局之后的修复。

| 对局 | 对手 | 结果 | 游戏时间 | Jev 输入 token | 生效的改动 |
| --- | --- | --- | --- | --- | --- |
| T1 | Easy | 胜 | 9:36 | 157 万 | 首个 Terran 执行器 |
| T2 | VeryHard | 胜 | 13:58 | 233 万 | 批量建筑选址 |
| T3 | VeryHard | 胜 | 13:25 | 236 万 | 避开被拒位置、保留附属建筑位置；积存矿物时继续花费 |
| T4 | VeryHard | 胜 | 10:17 | 179 万 | Bunker、SCV 修理、补给预留、Astra 对 Zerg 策略 |
| T5 | **CheatVision** | **胜** | 10:21 | 176 万 | Marine 与 SCV 躲避 Baneling；不再派采气 SCV 建造 |
| T6 | **CheatVision** | **胜** | 11:46 | 211 万 | 无（测试计划第 1 阶段，提交 `ddd0970`） |
| T7 | CheatVision | 负 | 12:28 | 232 万 | 无（测试计划第 1 阶段，提交 `ddd0970`） |
| T8 | **CheatVision** | **胜** | 12:21 | 218 万 | 瓦斯平衡、40 人口进攻下限、攻击 Changeling（重新计数的第 1 阶段第 1 局；提交 `164e70b`） |
| T9 | **CheatVision** | **胜** | 10:22 | 174 万 | 无（重新计数的第 1 阶段第 2 局；提交 `164e70b`） |
| T10 | **CheatVision** | **胜** | 10:20 | 179 万 | 无（重新计数的第 1 阶段第 3 局；提交 `164e70b`） |
| T11 | **CheatVision** | **胜** | 15:51 | 278 万 | 积存矿物时推荐 Barracks（第 2 阶段第 1 局，**Ancient Cistern LE**；提交 `cb65b50`） |
| T12 | **CheatVision** | **胜** | 11:33 | 190 万 | 积存时批量生产、最多同时建造四座生产建筑（重新计数的第 2 阶段第 1 局，**Ancient Cistern LE**；提交 `d9206cb`） |
| T13 | CheatVision | 平（时限） | 19:59 | 353 万 | 无（重新计数的第 2 阶段第 2 局，**Ancient Cistern LE**；提交 `d9206cb`） |
| T14 | CheatVision | 平（时限） | 19:59 | 368 万 | 扫描 Lurker、坚守受攻击基地、分矿恢复（重新计数的第 2 阶段第 1 局，**Ancient Cistern LE**；提交 `b361c1b`） |
| T15 | CheatVision | 负 | 17:01 | 297 万 | 新单位集结后再加入进攻；兵种比例建议；30 分钟时限（**Ancient Cistern LE**；提交 `2ca1641`，之后已撤回） |
| T16 | CheatVision | 负 | 17:24 | 288 万 | 无（**Ancient Cistern LE**；提交 `2ca1641`，之后已撤回） |
| T17 | CheatVision | 负 | 19:23 | 321 万 | 撤回援军集结（第 2 阶段第 1 局，**Ancient Cistern LE**；Bot 代码 `b361c1b`，提交 `a9ef6e2`） |
| T18 | **CheatVision** | **胜** | 15:01 | 241 万 | 对作弊 AI 仅在就绪部队 90 人口（满人口时 60）时进攻（第 2 阶段第 1 局，**Ancient Cistern LE**；提交 `fbe1a59`） |
| T19 | **CheatVision** | **胜** | 21:53 | 387 万 | 无（第 2 阶段第 2 局，**Ancient Cistern LE**；提交 `fbe1a59`） |
| T20 | CheatVision | 负 | 24:17 | 408 万 | 无（第 2 阶段第 3 局，**Babylon LE**；提交 `fbe1a59`） |
| T21 | CheatVision | 负 | 21:26 | 361 万 | 建造路径检查；访问错误重试（第 2 阶段第 4 局，**Babylon LE**；提交 `d3b6bb2`） |
| T22 | CheatVision | 负 | 17:56 | 309 万 | 留守坦克与回防；按时间表建造 Engineering Bay、Armory 并研究步兵升级（第 3 阶段第 1 局，**Babylon LE**；提交 `c0f92cc`） |

另有一局 VeryHard 因 SC2 窗口卡顿被手动停止，不计入。另一局 Ancient Cistern LE 上的 CheatVision 对局（提交 `b361c1b`）以 10:01 获胜，但同样不计入：对局中 Codex 登录失效（6:38 起 Astra 请求出现认证错误），Jev 基本在没有计划的情况下作战；控制面板现在会在这种情况下显示“Astra unavailable”。另一局在撤回后的代码上（Ancient Cistern LE，提交 `a9ef6e2`）于 12:29 因 Jev 服务开始拒绝请求（HTTP 403，“RBAC: access denied”）而停止，不计入。提交 `1bae3ec` 上的一局 Babylon LE 于 6:36 以同样方式停止（HTTP 404），同样不计入。OpenRouter 在前一晚开始列出新的 `typesafe/jev-router`；对 `typesafe/jev-1.13` 的请求仍由各局所用的 `jev-1.13-20260917` 应答，但服务两次短暂拒绝访问。现在访问错误（401、403、404）会重试最多 60 秒后才停止运行。作为对照，前一天同一台机器上的 Protoss 对局三胜 MediumHard、一负 VeryHard。

T5 是本仓库记录中首次在 VeryHard 以上难度获胜；早先的 Protoss 版本在 CheatVision 和 CheatMoney 各负一局。但这只是一张地图、一个种族的一局，属于证据，不是胜率。

T7 失利：4:00–5:30 前后的 Zergling–Baneling 进攻（至少 25 只 Zergling、7 只 Baneling）摧毁了 Bunker、全部 Marine 和分矿；重建期间 13–17 个 SCV 中有 4 个仍在采气，积存 400–800 瓦斯而矿物始终低于 100；9:03 以约 30 人口部队进攻并全灭，随后两个基地都被摧毁。之后的修复（瓦斯平衡、40 人口进攻下限、攻击 Changeling）使测试计划第 1 阶段重新计数。

改变结果的因素：T2–T3 虽然获胜，但被 Zergling–Baneling 压制拆掉基地，并积存矿物。加入 Bunker、补给预留和对 Zerg 策略后（T4），Bot 保住两个基地、没有撤退，10:00 时达到 48 个 SCV。加入躲避 Baneling 后（T5，躲避 403 次），面对 CheatVision 没有损失基地，10:00 时达到 60 个 SCV 和 161 人口，且没有失败的指令。

#### 作弊难度测试计划

在测试其他对手种族之前，先确认对 Zerg 的成绩。同一阶段内保持设置和代码不变（记录每局的提交），全屏运行且机器保持空闲；手动停止或因卡顿中断的对局不计入。如果必须修改代码修复问题，修复后重新开始该阶段的计数。

| 阶段 | 对局 | 目标 |
| --- | --- | --- |
| 1. 重复 CheatVision | 在 Altitude LE 打 5 局 CheatVision Zerg | 5 局至少 3 胜，说明 T5 不是偶然。提交 `ddd0970` 上为 2 胜 1 负（T5–T7）；T7 修复后在 `164e70b` 上 3 胜 0 负（T8–T10），已达目标，其余两局跳过，进入第 2 阶段 |
| 2. 其他地图 | Ancient Cistern LE 和 Babylon LE 各 2 局 CheatVision Zerg | 选址和 Bunker 位置在其他地图同样有效。**采用 90 人口进攻规则后完成：2 胜 2 负**（T18–T19 在 Ancient Cistern 获胜，T20–T21 在 Babylon 失利）。`cb65b50` 上 1 胜 0 负（T11）；`d9206cb` 上 1 胜 1 平（T12–T13）；`b361c1b` 上 1 平（T14）；`2ca1641` 上 2 负（T15–T16），随后撤回至 `b361c1b`。在撤回后的代码上重新计数，时限 30 分钟，阶段内不再修改代码 |
| 3. 基地防守与升级 | Babylon LE 和 Ancient Cistern LE 各 2 局 CheatVision Zerg，代码冻结 | 修复 Babylon 的失利，同时不丢掉 Ancient Cistern 的胜局。`c0f92cc` 上 Babylon 1 负（T22）；下述反 Baneling 时间表后重新计数 |
| 4. CheatMoney | 在 Altitude LE 打 3 局 CheatMoney Zerg | 敌方额外收入，预计更早出现更大部队 |
| 5. CheatInsane | 在 Altitude LE 打 3 局 CheatInsane Zerg | 额外收入加全图视野，最难的内置 AI |

进入第 2 阶段前，T8–T10 在后期仍积存 600–1,600 矿物：Jev 很少选择已提供的 Barracks，而计划的 Barracks 上限要到 800 矿物才解除。现在积存矿物的放宽从 600 开始，并会向 Jev 推荐再建一座 Barracks。

T11（Ancient Cistern LE）所有建筑均未出现引擎错误，但 9:00–12:00 积存了多达 2,615 矿物：同时只能建造两座生产建筑（111 次决策中有 105 次 Barracks 因“已在建造”被拒），且每秒一次决策只能训练一个单位，不足以让约 14 个生产位忙碌。现在矿物积存达到 600 以上时，一次 Marine、Marauder、Siege Tank 或 Medivac 选择会让所有空闲的对应生产建筑同时生产，并最多可同时建造四座生产建筑。

T13 在 15:00 前达到 200/200 人口，但在 20 分钟时限内未能消灭 Zerg。进攻被钻地 Lurker 拖住，而侦测只有一台 Raven、没有扫描；16:21 在防守计划下、就绪部队 110 人口时从受攻击的基地撤退；并反复尝试无法到达的分矿位置（七次“无法到达目标”），其中两次选了采气 SCV。现在最近见过 Lurker 时 Orbital Command 会在交战部队前方扫描，防守计划下部队高于撤退阈值时不会从受攻击的基地撤退，分矿会跳过被拒位置并使用采矿 SCV。

T14 用上了全部新修复（6 次扫描 Lurker、坚守基地时 144 次拒绝撤退、175 个批量生产单位），但仍为平局：五次进攻每次损失约一半部队后撤回，而 CheatVision 不断补兵。新单位逐个走向战场，到 19:00 部队变成 18 辆 Siege Tank 和 6 个 Marine。下一个版本让新单位在进攻期间于基地附近集结、约 8 人口一组出发，并要求 Astra 保持约每辆 Siege Tank 三个 Marine 或 Marauder。该版本两局皆负（T15–T16）：规模相同的首次进攻结束时只剩 15–21 就绪人口（之前为 25–47），因为交战部队不再持续获得援军，随后 Zerg 反攻空虚的基地。这两项改动已撤回，Bot 回到 T14 的代码（`b361c1b`）。其余对局保留 30 分钟时限，因为满人口、五矿的 20 分钟平局难以说明结果。

T15–T17 在两个代码版本上以相同方式失利，说明援军改动并非原因。重放 T12 胜局中记录的 40 次决策，Jev 每次都给出原来的选择；Astra 的延迟、输出长度和计划也没有变化，因此两个模型都未改变。8:00 前各局的 Zerg 部队相似；差别在于 Bot 在约 7:20–8:15、以 40–57 就绪人口发起的首次进攻：胜局和平局在进攻后仍保有 25–47 人口，败局只剩 15–21，随后 Zerg 出现 Infestor、Lurker 和 Ultralisk。现在对作弊 AI，Terran Bot 只有在就绪部队至少 90 人口（总人口达到 190 后为 60）时才进攻，此前依靠 Bunker 和架起的坦克防守并继续扩张。第 2 阶段在此版本上重新计数。

在 Babylon LE（T20）上，Bot 在前 20 分钟保住了基地，但有六座建筑因“无法到达目标”失败：这些空位被地形或自己的建筑围住。三次 Armory 全部失败，因此当 7 只 Ultralisk 和 12 只 Mutalisk 在约 20:50 消灭其 Marine 部队时，它没有 2–3 级攻防升级，也没有 Thor。现在选址还会在同一批查询中确认建造的 SCV 能走到该位置。这属于错误修复，不会使第 2 阶段重新计数。

第 2 阶段显示了 90 人口规则解决了什么、还留下什么。两局 Babylon 失利模式相同：部队进攻时，Zerg 袭击其身后的基地（T20 损失约 30 个 SCV，T21 损失一个基地和 14 个 SCV）；而且部队在没有 2–3 级升级的情况下进入后期（T20 的 Armory 未能建成，T21 从未计划建造），单次交战损失约 60 人口。现在进攻期间两辆 Siege Tank 留守，远离部队的基地遭袭时部队回防，Engineering Bay、Armory 和步兵升级按固定时间表推荐。

T22 中升级按时到位（Engineering Bay 5:37、Armory 6:45），但部队始终没有达到进攻规模：CheatVision 在 Babylon 上 10:00 前带来 19 只 Baneling（T20–T21 也是 17–20 只），在 9:00 和 13:30 两次击溃以 Marine 为主、只有一两辆 Siege Tank 的防线。现在时间表还会要求 5:30 前有带 Tech Lab 的 Factory、6:30 前两辆 Siege Tank、7:00 前四个 Widow Mine，并在发现 Baneling 后于最暴露的基地变形 Planetary Fortress；架起的坦克和钻地的地雷也计入这些数量。

每局记录结果、游戏时间、Jev token、复查项（失败指令、补给卡住、矿物积存、基地损失、躲避 Baneling 次数）以及任何代码改动。完成这些阶段后，对 Terran 和 Protoss 对手先在 VeryHard、再在 CheatVision 重复第 1–2 阶段。

[实验与版本边界](docs/experiments.md) · [架构与数据流](docs/architecture.md) · [日志和回放](docs/logs-and-replays.md) · [论文 PDF](paper/JEV-Star.pdf) · [论文源码及统计表](paper/README.md#简体中文)

### 目录

```text
macro/       宏观控制代码、测试和六张梯图
micro/       微操代码、PySC2/SMAC-Hard 运行底层、测试和 35 张地图
scripts/     环境安装、地图安装、SC2 枚举同步和控制面板
docs/        架构、实验、整理说明和源文件清单
paper/       当前论文、LaTeX 源码、图表和固定统计数据
licenses/    上游许可证
jev_star.py  两个独立环境的统一命令入口
```

运行结果保存在各模块的 `jev_runs/` 下。完整事件、新生成的 replay 和视频、虚拟环境、密钥和本机诊断文件默认不进入 Git；已有原始研究档案保留在本地工作区。已核验的完整视频收录在 `media/videos/`，胜局 replay 收录在 `media/replays/`。README 使用 GitHub 原生播放器，原始高码率录像另存于 Releases。仓库也包含论文的固定统计表，完整原始日志不以节选代替。

### 测试

```powershell
Push-Location macro
& ..\.venvs\macro\Scripts\python.exe -B -m unittest discover -s tests -p 'test_jev*.py'
Pop-Location
Push-Location micro
& ..\.venvs\micro\Scripts\python.exe -B -m unittest discover -s tests -p 'test_jev*.py'
Pop-Location
```

测试使用模拟接口，不启动游戏或付费模型。GitHub Actions 使用同样的两组离线测试。首次公开整理的验证范围见 [整理记录](docs/repository-cleanup.md)。

### 上游来源

宏观基于 [LLM Play SC2](https://github.com/sc2musa/Large-Language-Models-play-StarCraftII)；微观基于 [SMAC-Hard](https://github.com/devindeng94/smac-hard) 及其 PySC2。保留对应源代码声明与许可证，详见 [第三方说明](THIRD_PARTY_NOTICES.md) 和 [源文件清单](docs/source-manifest.json)。

<a id="citation"></a>

## Citation / 引用

If you use JEV-Star in your research, please cite the paper below. You can also use **Cite this repository** in the GitHub sidebar to copy an APA or BibTeX citation.

如果本项目对你的研究有帮助，请引用以下论文；也可以点击 GitHub 侧栏的 **Cite this repository**，复制 APA 或 BibTeX 引用。

Weiyu Ma, Liangbing Zhao, Yongcheng Zeng, and Jian Zhao. 2026. *JEV-Star: Fast, Low-Cost StarCraft II Control with Language-Model Planning*. Preprint.

```bibtex
@misc{ma2026jevstar,
  title = {{JEV-Star}: Fast, Low-Cost {StarCraft II} Control with Language-Model Planning},
  author = {Ma, Weiyu and Zhao, Liangbing and Zeng, Yongcheng and Zhao, Jian},
  year = {2026},
  month = sep,
  note = {Preprint},
  url = {https://github.com/sc2musa/Jev_Star/blob/main/paper/PAPER.md}
}
```

[BibTeX file / BibTeX 文件](CITATION.bib) · [Citation metadata / 引用元数据](CITATION.cff) · [Read the paper / 在线阅读论文](paper/PAPER.md)
