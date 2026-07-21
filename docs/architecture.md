# 引擎架构（硬契约）

> **引擎与故事分离。落霞是第一个 WorldPack，不是引擎。**  
> **换 3D 客户端 = 换适配层；不改 core / content 契约。**

## 边界

| 层 | 可以 | 禁止 |
|----|------|------|
| **core/** | 回合、AP、MOVE、裁决管道、StateApplier、通用置灰 | 剧情、NPC 名、落霞 flag 语义、`import content`、`get_container` |
| **content/\<world\>/** | 种子、钩子、线索包、投影 | 改 Graph；直改 `session` 权威字段（只回同构包） |
| **infra/** | Mock / LLM / 存档 | 写死某世界剧情分支 |
| **api · frontend · 3D** | 适配与表现 | 业务权威；按 `world_id` 开剧情 UI |

**唯一写入**：`ContentPacket` / `AdjudicationResult` → `apply_packet` → `StateApplier`。  
**一条线索 = 一次同构包**：`events` + `state_ops` / `belief_ops` / `world_flag_ops`。

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
infra/        存档 · Mock · LLM
```

## WorldPack 插座

内容总入口。引擎只：`pack = registry.get(session.world_id)`。

| 钩子 / 端口 | 职责 |
|-------------|------|
| 地图 · 角色 · 种子 | 开局数据 |
| `on_new_game` / `on_day_end` / `on_day_rollover` / `after_flags_refresh` | **只返回包**，引擎 apply |
| `on_dialogue` | 对话后同构包 |
| `project_session_extra` | 案线 / 灰字等 DTO 投影 |
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

- `USE_LLM` 装配；失败抛错，不静默回 Mock  
- 世界特有 prompt 段只来自 pack  

## 3D

- 权威与 DTO 已客户端无关  
- 换网关 + 场景即可；角色资产绑 `art_key` / `actor_id`（内容包，不进 core）  

验证：手玩 + `/api/health`。无测试套件、无 smoke（见 `AGENTS.md`）。
