# 引擎架构（硬契约）

> **引擎与故事分离。落霞是第一个 WorldPack，不是引擎。**  
> **换 3D 客户端 = 换适配层；不改 core / content 契约。**

## 边界

| 层 | 可以 | 禁止 |
|----|------|------|
| **core/** | 回合、AP、MOVE、裁决管道、StateApplier、通用置灰 | 剧情、NPC 名、落霞 flag 语义、`import content`、`get_container` |
| **content/\<world\>/** | 种子、钩子、线索包、投影 | 改 Graph；直改 `session` 权威字段（只回同构包） |
| **infra/** | LLM / 存档 | 写死某世界剧情分支；静默 Mock 回退 |
| **api · frontend · 3D** | 适配与表现 | 业务权威；按 `world_id` 开剧情 UI |

**唯一写入**：`ContentPacket` / `AdjudicationResult` → `apply_packet` → `StateApplier`。  
**一条线索 = 一次同构包**：`events` + `state_ops` / `belief_ops` / `world_flag_ops`。

## 真相字典 + 投影

权威键见 `core/domain/truth_dict.py`（`TRUTH_KEYS` / `snapshot`）：

| 键 | 职责 |
|----|------|
| `states` / `beliefs` / `world_flags` / `events` | 世界与履历硬状态 |
| `profiles` / `map` / `rules` | 静态设定 |
| `phase` / `day` / `ap` / `game_over_reason` | 进程 |
| `dialogue` | **对白权威**（`GameSession.dialogue`）：player/npc/sys + 事件封条引用 + 机械 effect 脚注；见闻/履历不在此 |

玩家可见文案一律投影：见闻←`beliefs`；隐情←`clue_flags`（含劫数）；事件卡←`mask_event`；情境←`situation_rows`；机械局势←`effect_summary`（禁止复述 `belief_ops`）；终局←`settlement_text`（settlement 事件投影）。

**禁止当玩家真相**：`last_effects`、`graph_meta.settlement_summary`、`narrative_summary` 持久化、`memory_digest` 进 UI、前端发明文案、劫数双轨（`world_flags_public.xuanyin_countdown`）。

## 分层

```
api/          HTTP（可整层换成 3D 网关）
container.py  组合根（唯一注册 WorldPack / ports）
core/
  domain/     模型与枚举
  ports/      可拔插抽象
  services/   用例 · content_packet · Applier
  graphs/     管道（registry 注入，无分镜）
content/      luoxia · qingxi · …
infra/        存档 · LLM
```

## WorldPack 插座

内容总入口。引擎只：`pack = registry.get(session.world_id)`。

| 钩子 / 端口 | 职责 |
|-------------|------|
| 地图 · 角色 · 种子 | 开局数据 |
| `on_new_game` / `on_day_end` / `on_day_rollover` / `after_flags_refresh` | **只返回包**，引擎 apply |
| `on_dialogue` / `on_move` | 条件线索固定包（非台词剧本） |
| `project_session_extra` | 见闻 / 隐情灰字等 DTO 投影 |
| `AdjudicatorPort` / `AgentMindPort` | 天道 · 心智 |
| `SessionRepositoryPort` | 存档 |
| `StateApplier` | 唯一落地 |

## 数据流

```
意图 (Web / 3D)
  → ActionService
      MOVE  → 拓扑 + pack.location_open（只读）
      TALK  → Mind + 天道 → on_dialogue → Applier → after_flags_refresh
      END_DAY → on_day_end → day++ → on_day_rollover
  → 存档
  → SessionView（visibility + project_session_extra）
```

## 禁止

- 台词关键词念咒推进硬状态  
- Graph 写死分镜  
- 内容包绕过 Applier 直写 session  
- core 依赖 UI / 3D / container  

## LLM

- LLM 必装；失败抛错，**不**静默回 Mock
- 世界特有 prompt 段只来自 pack  

## 遭遇 / 弹窗模块（表现）

- **遭遇权威**：开打、对拼结算、写回只走意图 → ContentPacket / Applier；前端不算胜负。  
- **动作**：`ActionType.encounter`（payload.`op` = `start` | `pick` | `confirm` | `cancel` | `dismiss_offer`）。  
- **状态**：`world_flags.active_encounter`（经 packet 写入；`None` 表示删除）；经 `SessionView.encounter` 投影。  
- **要约**：天道 `ui_hints.propose_encounter` → `graph_meta.encounter_offer` → `SessionView.encounter_offer`（应战/罢议）；**禁止**模型直写 `active_encounter`。  
- **小招目录**：开战时 `WorldPack.encounter_build_catalogs`（可 LLM + 校验回退）写入 `active_encounter.player_catalog` / `foe_catalog`；战斗中只用 blob，不再生成。  
- **弹窗「画」面**：通用 **stage 模块槽**（按 id 加载：交锋 / 奇遇 / 武学 / …）；模块只做表现与操作回传，不进 core。  
- 落霞交锋规则与词条表见 `docs/luoxia.md` §10；引擎不 import 内容包招式名（经 WorldPack.`encounter_*`）。

## 3D

- 权威与 DTO 已客户端无关  
- 换网关 + 场景即可；角色资产绑 `art_key` / `actor_id`（内容包，不进 core）  

## 终局

- `settle_if_needed` → 天道 `phase=settlement`（幂等）。  
- 禁止 `evaluate_ending_tags` 类程序员结局。  
- 天道 Prompt：**总导演 + 裁决**（张力、代价、事件卡）；不写具体剧本关键词/结局表。

验证：手玩 + `/api/health`。无测试套件（见 `AGENTS.md`）。
