# Macro control / 宏观控制

[English](#english) | [简体中文](#简体中文)

## English

The current version, `macro-v2.3.0`, controls full Protoss or Terran games (`--race Protoss|Terran`) against the built-in AI of any race. It retains the LLM Play SC2 Protoss executor, adds a Terran executor, and provides native JEV Choice requests, asynchronous Astra phase planning, action precondition checks, order lifecycle management, and navigation on top of BurnySC2. Each race is described by a race contract (action IDs, kinds, limits, prompts); the Jev loop, Astra planner, plan policy, and logging are shared.

| Entry point / file | Responsibility |
| --- | --- |
| [run_jev.py](sc2_rl_agent/starcraftenv_test/run_jev.py) | Real-time game and model lifecycles; output directories |
| [jev_agent.py](sc2_rl_agent/starcraftenv_test/agent/jev_agent.py) | JEV HTTP client, timeouts, stale results, and termination on permanent errors |
| [astra_planner.py](sc2_rl_agent/starcraftenv_test/agent/astra_planner.py) | Codex invocation, plan validation, and periodic or event-based triggers |
| [macro_contract.py](sc2_rl_agent/starcraftenv_test/agent/macro_contract.py) | Race contracts: action IDs, kinds, limits, and the implementation version |
| [strategic_policy.py](sc2_rl_agent/starcraftenv_test/agent/strategic_policy.py) | Plan goals, budgets, and legal candidates |
| [macro_execution.py](sc2_rl_agent/starcraftenv_test/env/bot/macro_execution.py) | Production, research, abilities, and order feedback |
| [macro_navigation.py](sc2_rl_agent/starcraftenv_test/env/bot/macro_navigation.py) | Scouting and persistent army stances |
| [jev_macro_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_macro_bot.py) | Race-independent Jev decision loop, execution records, and shutdown |
| [hierarchical_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/hierarchical_bot.py) | Astra planning layer shared by both races |
| [jev_protoss_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_protoss_bot.py) | Protoss legality checks and actions |
| [jev_terran_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_terran_bot.py) | Terran legality checks, placement, add-ons, morphs, and local unit upkeep |

Run `python jev_star.py macro ...` from the repository root; see the [main README](../README.md#english) for setup. By default, the controller starts at most one JEV request per second through OpenRouter. A refused call waits, then the next decision uses a fresh observation. Games use `realtime=True` and continue advancing while the model is processing. JEV results are checked against the latest state and plan version; stale results are discarded. Planning runs in the background.

Protoss action IDs: 0–18 cover unit production and Archon merging; 19–33 buildings; 34–59 research; 60–63 scouting; 64 attack, 65 retreat, and 72 defend; 66–70 Chronoboost; 71 wait.

Terran action IDs: 0–15 unit production; 16–25 and 70 (Bunker) buildings; 26–31 Tech Labs and Reactors; 32 Orbital Command and 33 Planetary Fortress; 34–62 research; 63–65 scouting; 66 attack, 67 retreat, 68 defend; 69 wait. Local Terran code distributes workers, calls down MULEs, lowers Supply Depots, sends an SCV to finish abandoned construction, places a Bunker in front of the base nearest the enemy, loads nearby Marines into it when ground enemies approach and unloads them to attack, sends two SCVs to repair a Bunker or Planetary Fortress under fire, moves Marines and mining SCVs away from Banelings (checked every step), moves SCVs from gas to minerals while banked gas exceeds 300 and twice the minerals, has the nearest soldiers shoot visible Changelings, sieges and unsieges Siege Tanks, burrows Widow Mines near enemies, uses Stimpack in combat once researched, and keeps Medivacs and one Raven with the army. Building placement batches its engine queries, keeps add-on slots and pending build sites free, and avoids spots the engine recently rejected; a producer without room for an add-on is not offered one. Up to two production buildings may be under construction at once, and with 800 or more minerals banked Jev may buy Barracks, Marines, Marauders, Siege Tanks, and Medivacs beyond the plan's lists and ceilings. When supply is nearly blocked and no Supply Depot is coming, other purchases keep enough minerals back for one. No attack starts below 40 ready army supply, whatever the plan's threshold. Drops, Viking landing, Liberator zones, cloak, Yamato, Raven spells, and scans are not implemented.

The planner does not directly emit per-unit commands. Micro skills are limited to the executor's implemented capabilities; writing an instruction in a plan does not add a new executable skill.

Use `--planner none` to run without planning. With planning enabled, the default Astra model is `gpt-6-astra`; you can explicitly set `--planner-effort medium`. The default planning interval is 60 game seconds, with earlier triggers for urgent events. Use `--help` to inspect model timeouts, minimum intervals, plan lifetimes, and request limits.

Logs default to `macro/jev_runs/<timestamp>/`, with an automatically generated offline `report.html`. Permanent configuration or billing errors, such as HTTP 402, stop the run. Original records retain the failure classification instead of reporting an ordinary game result. See [experiments](../docs/experiments.md) and [logging](../docs/logs-and-replays.md).

This directory excludes legacy Gym registration, chat models, retrieval memory, and script bots unrelated to JEV. The retained `Protoss_Bot` base class and JEV behavior implementations pass the existing regression tests, alongside the Terran tests in [test_jev_terran.py](tests/test_jev_terran.py).

## 简体中文

当前为 `macro-v2.3.0`，控制 Protoss 或 Terran 完整对局（`--race Protoss|Terran`），对手为任意种族内置 AI。代码保留 LLM Play SC2 的 Protoss 执行器并新增 Terran 执行器，在 BurnySC2 上提供原生 JEV Choice、异步 Astra 阶段规划、动作条件检查、订单生命周期及导航。每个种族由种族契约描述（动作 ID、类别、上限、提示词）；Jev 循环、Astra 规划、计划策略和日志为两族共用。

| 入口 / 文件 | 职责 |
| --- | --- |
| [run_jev.py](sc2_rl_agent/starcraftenv_test/run_jev.py) | 实时游戏与模型生命周期、输出目录 |
| [jev_agent.py](sc2_rl_agent/starcraftenv_test/agent/jev_agent.py) | JEV HTTP 客户端、超时、过期结果、永久错误停止 |
| [astra_planner.py](sc2_rl_agent/starcraftenv_test/agent/astra_planner.py) | Codex 调用、计划校验、定时及事件触发 |
| [macro_contract.py](sc2_rl_agent/starcraftenv_test/agent/macro_contract.py) | 种族契约：动作 ID、类别、上限及实现版本 |
| [strategic_policy.py](sc2_rl_agent/starcraftenv_test/agent/strategic_policy.py) | 计划目标、预算及合法候选 |
| [macro_execution.py](sc2_rl_agent/starcraftenv_test/env/bot/macro_execution.py) | 生产、研究、能力、订单反馈 |
| [macro_navigation.py](sc2_rl_agent/starcraftenv_test/env/bot/macro_navigation.py) | 侦察与持续军队姿态 |
| [jev_macro_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_macro_bot.py) | 与种族无关的 Jev 决策循环、执行记录和关闭流程 |
| [hierarchical_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/hierarchical_bot.py) | 两族共用的 Astra 规划层 |
| [jev_protoss_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_protoss_bot.py) | Protoss 合法性检查与动作 |
| [jev_terran_bot.py](sc2_rl_agent/starcraftenv_test/env/bot/jev_terran_bot.py) | Terran 合法性检查、建筑选址、附属建筑、形态转换及本地单位维护 |

从仓库根目录运行 `python jev_star.py macro ...`；安装方法见 [总说明](../README.md#简体中文)。默认每秒最多发起一次 JEV 请求，经 OpenRouter 发送。请求被拒绝后会等待，下一次决策使用新的局面。游戏 `realtime=True`，模型等待期间继续推进。JEV 结果按最新状态和计划版本复核，过期结果丢弃；计划调用在后台执行。

Protoss 动作 ID：0–18 单位生产及 Archon，19–33 建筑，34–59 研究，60–63 侦察，64 进攻、65 撤退、72 防守，66–70 Chronoboost，71 等待。

Terran 动作 ID：0–15 单位生产，16–25 及 70（Bunker）建筑，26–31 Tech Lab 与 Reactor，32 Orbital Command、33 Planetary Fortress，34–62 研究，63–65 侦察，66 进攻、67 撤退、68 防守，69 等待。Terran 本地代码负责分配工人、呼叫 MULE、降下补给站、派 SCV 续建无人施工的建筑、在离敌人最近的基地前方放置 Bunker，敌方地面部队接近时让附近 Marine 进入、进攻时卸下，并派两台 SCV 修理受攻击的 Bunker 或 Planetary Fortress，让 Marine 和采矿 SCV 躲避 Baneling（每一步检查），在积存瓦斯超过 300 且超过矿物两倍时把 SCV 从瓦斯调到矿物，让最近的士兵攻击可见的 Changeling，以及坦克架设与收起、Widow Mine 遇敌钻地、研究完成后在战斗中使用 Stimpack，并让 Medivac 和一台 Raven 跟随部队。建筑选址批量查询引擎，保留附属建筑位置和待建工地，避开引擎近期拒绝的位置；没有空间加装附属建筑的生产建筑不会被提供该动作。最多可同时建造两座生产建筑；矿物积存达到 800 以上时，Jev 可在计划列表和上限之外购买 Barracks、Marine、Marauder、Siege Tank 和 Medivac。补给即将卡住且没有补给站在建时，其他购买会预留建造补给站所需的矿物。无论计划阈值如何，就绪部队人口低于 40 时不会发起进攻。空投、Viking 降落、Liberator 区域、隐形、Yamato、Raven 技能和扫描均未实现。

规划模型不直接输出逐单位命令。实际微操技能只覆盖已实现的执行能力，不能把文字计划当作额外技能接口。

不带规划时使用 `--planner none`。带规划时默认 Astra 为 `gpt-6-astra`，命令中可显式使用 `--planner-effort medium`。默认周期 60 游戏秒，紧急事件可提前触发；模型时限、最小间隔、计划寿命和请求上限均可通过 `--help` 查看。

日志默认写入 `macro/jev_runs/<timestamp>/`，并自动生成离线 `report.html`。HTTP 402 等永久配置/计费错误停止该运行；原始记录保留失败分类，不伪装成正常对局结果。详见 [实验记录](../docs/experiments.md) 和 [日志说明](../docs/logs-and-replays.md)。

本目录移除了旧 Gym 注册、聊天模型、检索记忆及与 JEV 无关的脚本 Bot；保留的基础 `Protoss_Bot` 类及 JEV 行为实现通过原有回归测试，Terran 另有 [test_jev_terran.py](tests/test_jev_terran.py) 测试。
