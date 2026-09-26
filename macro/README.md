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

Terran action IDs: 0–15 unit production; 16–25 and 70 (Bunker) buildings; 26–31 Tech Labs and Reactors; 32 Orbital Command and 33 Planetary Fortress; 34–62 research; 63–65 scouting; 66 attack, 67 retreat, 68 defend; 69 wait. Local Terran code distributes workers, calls down MULEs, lowers Supply Depots, sends an SCV to finish abandoned construction, places a Bunker in front of the base nearest the enemy, loads nearby Marines into it when ground enemies approach and unloads them to attack, sends two SCVs to repair a Bunker or Planetary Fortress under fire, has Marines and Marauders within 7 of a Baneling shoot the nearest one when their weapon is ready and step away while reloading, and moves mining SCVs away from Banelings (checked every step), moves SCVs from gas to minerals while banked gas exceeds 300 and twice the minerals, has the nearest soldiers shoot visible Changelings, scans ahead of a fighting army when Lurkers were seen in the last 90 seconds and no Raven is near (MULEs keep 50 energy back meanwhile), sieges and unsieges Siege Tanks, burrows Widow Mines near enemies, uses Stimpack in combat once researched, and keeps Medivacs and one Raven with the army. Research uses the ability the running game lists for the upgrade when the unit offers it, and an order the engine answers with NotSupported is blocked for 2 minutes. Building placement batches its engine queries, keeps add-on slots and pending build sites free, leaves a 2-cell lane between every new building except Supply Depots and the buildings and add-on slots already standing (so Siege Tanks can leave the production area), avoids spots the engine recently rejected, and checks in the same batch that the builder can walk to the spot; a producer without room for an add-on is not offered one. Up to two production buildings may be under construction at once, and with 600 or more minerals banked Jev may buy Barracks, Marines, Marauders, Siege Tanks, and Medivacs beyond the plan's lists and ceilings, and another Barracks is recommended to Jev. While banked, one Marine, Marauder, Siege Tank, or Medivac choice fills every free producer that can make it, and up to four production buildings may be under construction at once. When supply is nearly blocked and no Supply Depot is coming, other purchases keep enough minerals back for one. No attack starts below 40 ready army supply (90 against the cheating AIs, or 60 once total supply reaches 190), whatever the plan's threshold. During an attack the two Siege Tanks nearest the exposed base stay home, and a raid of 8 or more enemy supply on a base far from the army brings the army home and blocks attacking for 30 seconds. An attacking army compares the enemy units within 12 of it (away from its own bases, which the recall covers) with its own units near them; if that enemy is 1.4 times stronger and those units are at least 40% of the attacking army (so a skirmish at the front does not pull back everyone), or the attack has cost 35% of the army and that enemy is at least as strong, it moves away for 8 seconds, then defends, and cannot attack again for 45 seconds. On the way to a fight, Marines and Marauders that are not fighting and are more than 6 ahead of the leading Siege Tank walk back to it. Siege Tanks siege when ground enemies come within 15. A Factory (5:00) with a Tech Lab (5:30), two Siege Tanks (6:30), four Widow Mines (7:00), an Engineering Bay (6:30), Infantry Weapons and Armor (7:00), and an Armory with level 2–3 upgrades (8:00) are recommended to Jev on schedule even if the plan omits them, as is a Planetary Fortress at the most exposed base once Banelings have been seen and three bases exist, Vikings (two per Brood Lord, one per Corruptor, up to 12, while one was seen in the last 3 minutes) with a Starport (two for six or more Vikings), and while one of these scheduled or recommended purchases lacks only money, other purchases except SCVs and Supply Depots keep its cost back; and under a defend plan the army does not retreat from an attacked base while it is above the plan's retreat threshold. Expansion sites the engine rejected are skipped, and expansions use mineral workers as builders. Drops, Viking landing, Liberator zones, cloak, Yamato, and Raven spells are not implemented.

The planner does not directly emit per-unit commands. Micro skills are limited to the executor's implemented capabilities; writing an instruction in a plan does not add a new executable skill.

Use `--planner none` to run without planning. With planning enabled, the default Astra model is `gpt-6-astra`; you can explicitly set `--planner-effort medium`. The default planning interval is 60 game seconds, with earlier triggers for urgent events. Use `--help` to inspect model timeouts, minimum intervals, plan lifetimes, and request limits.

Logs default to `macro/jev_runs/<timestamp>/`, with an automatically generated offline `report.html`. Billing and malformed-request errors (HTTP 402, 400, 422) stop the run; access errors (401, 403, 404) are retried with backoff and stop the run only if they last more than 60 seconds. Original records retain the failure classification instead of reporting an ordinary game result. See [experiments](../docs/experiments.md) and [logging](../docs/logs-and-replays.md).

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

Terran 动作 ID：0–15 单位生产，16–25 及 70（Bunker）建筑，26–31 Tech Lab 与 Reactor，32 Orbital Command、33 Planetary Fortress，34–62 研究，63–65 侦察，66 进攻、67 撤退、68 防守，69 等待。Terran 本地代码负责分配工人、呼叫 MULE、降下补给站、派 SCV 续建无人施工的建筑、在离敌人最近的基地前方放置 Bunker，敌方地面部队接近时让附近 Marine 进入、进攻时卸下，并派两台 SCV 修理受攻击的 Bunker 或 Planetary Fortress，距 Baneling 7 以内的 Marine 和 Marauder 在武器就绪时射击最近的 Baneling、装填时后撤，采矿 SCV 躲避 Baneling（每一步检查），在积存瓦斯超过 300 且超过矿物两倍时把 SCV 从瓦斯调到矿物，让最近的士兵攻击可见的 Changeling，在过去 90 秒内见过 Lurker 且附近没有 Raven 时于交战部队前方扫描（期间 MULE 预留 50 能量），以及坦克架设与收起、Widow Mine 遇敌钻地、研究完成后在战斗中使用 Stimpack，并让 Medivac 和一台 Raven 跟随部队。研究优先使用正在运行的游戏为该升级列出且单位实际提供的技能；引擎回复 NotSupported 的命令会被阻止 2 分钟。建筑选址批量查询引擎，保留附属建筑位置和待建工地，除补给站外的新建筑与已有建筑及附属建筑位置之间保留 2 格通道（使 Siege Tank 能离开生产区），避开引擎近期拒绝的位置，并在同一批查询中确认建造的 SCV 能走到该位置；没有空间加装附属建筑的生产建筑不会被提供该动作。最多可同时建造两座生产建筑；矿物积存达到 600 以上时，Jev 可在计划列表和上限之外购买 Barracks、Marine、Marauder、Siege Tank 和 Medivac，并会向 Jev 推荐再建一座 Barracks。积存期间，一次 Marine、Marauder、Siege Tank 或 Medivac 选择会让所有空闲的对应生产建筑同时生产，最多可同时建造四座生产建筑。补给即将卡住且没有补给站在建时，其他购买会预留建造补给站所需的矿物。无论计划阈值如何，就绪部队人口低于 40 时不会发起进攻（对作弊 AI 为 90，总人口达到 190 后为 60）。进攻期间，离暴露基地最近的两辆 Siege Tank 留守；若有 8 人口以上的敌军袭击远离部队的基地，部队会回防并在 30 秒内不再进攻。进攻中的部队会比较其 12 范围内的敌军（不含自家基地附近的敌军，由回防处理）与这些敌军附近的我方单位；若该处敌军强 1.4 倍且这些我方单位至少占进攻部队的 40%（前方的小规模接触不会让整支部队撤退），或本次进攻已损失 35% 部队且该处敌军至少一样强，会先撤离 8 秒再转为防守，并在 45 秒内不能再次进攻。前往交战途中，未在交战且领先最前方 Siege Tank 超过 6 的 Marine 和 Marauder 会退回坦克处。地面敌人进入 15 范围时 Siege Tank 即架起。Factory（5:00）及其 Tech Lab（5:30）、两辆 Siege Tank（6:30）、四个 Widow Mine（7:00）、Engineering Bay（6:30）、步兵攻防（7:00）以及 Armory 和 2–3 级升级（8:00）会按时间表推荐给 Jev，即使计划中没有；发现 Baneling 且拥有三个基地后，还会推荐在最暴露的基地变形为 Planetary Fortress；过去 3 分钟内见过 Brood Lord 或 Corruptor 时推荐生产 Viking（每只 Brood Lord 2 架、每只 Corruptor 1 架，最多 12 架）及 Starport（六架以上时两座）；这些按时间表或推荐的购买只差资源时，除 SCV 和补给站外的其他购买会预留其费用；防守计划下，基地受攻击且部队高于计划撤退阈值时不会撤退。引擎拒绝过的分矿位置会被跳过，分矿由采矿 SCV 建造。空投、Viking 降落、Liberator 区域、隐形、Yamato 和 Raven 技能均未实现。

规划模型不直接输出逐单位命令。实际微操技能只覆盖已实现的执行能力，不能把文字计划当作额外技能接口。

不带规划时使用 `--planner none`。带规划时默认 Astra 为 `gpt-6-astra`，命令中可显式使用 `--planner-effort medium`。默认周期 60 游戏秒，紧急事件可提前触发；模型时限、最小间隔、计划寿命和请求上限均可通过 `--help` 查看。

日志默认写入 `macro/jev_runs/<timestamp>/`，并自动生成离线 `report.html`。计费和请求格式错误（HTTP 402、400、422）会停止该运行；访问错误（401、403、404）会退避重试，只有持续超过 60 秒才停止；原始记录保留失败分类，不伪装成正常对局结果。详见 [实验记录](../docs/experiments.md) 和 [日志说明](../docs/logs-and-replays.md)。

本目录移除了旧 Gym 注册、聊天模型、检索记忆及与 JEV 无关的脚本 Bot；保留的基础 `Protoss_Bot` 类及 JEV 行为实现通过原有回归测试，Terran 另有 [test_jev_terran.py](tests/test_jev_terran.py) 测试。
