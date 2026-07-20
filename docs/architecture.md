# 落霞宗 · 引擎架构

> **原则：引擎可扩展；落霞宗只是第一个世界包，不是写死的唯一故事程序。**

## 分层

```
api/          HTTP 适配（DTO、路由）
container.py  组合根（绑定实现）
core/
  domain/     纯领域模型与枚举（无 IO、无落霞专有逻辑）
  ports/      抽象端口（ABC）
  services/   用例服务（Day/Action/Factory/StateApplier）
content/
  luoxia/     落霞宗世界包
  qingxi/     青溪小驿（迷你第二包，验证扩展）
  <future>/   新世界包
infra/        端口实现（内存库、Mock/LLM 天道与心智）
```

## 关键抽象

| 抽象 | 职责 | 替换方式 |
|------|------|----------|
| `WorldPack` | 地图、角色、背景、种子 flags、规则 | 新子类 + `registry.register` |
| `AdjudicatorPort` | 天道裁决 CRUD 解释权 | Mock → LLMAdjudicator → LangGraph 节点 |
| `AgentMindPort` | NPC 主观回复/意图 | Mock → LLMAgentMind |
| `SessionRepositoryPort` | 存档 | Memory → SQLite/Postgres |
| `StateApplier` | 统一应用 state/belief/event patch | 引擎内唯一写路径 |
| `ActionService` | MOVE 规则 / TALK 链路 / END_DAY 演变 | 扩展 ActionType 或 custom→天道 |

## 继承 / 扩展点

1. **新世界**：`class FooPack(WorldPack)`，放入 `content/foo/`，在 `container` 注册。
2. **新裁决**：`class LLMAdjudicator(AdjudicatorPort)`，校验 `AdjudicationResult`。
3. **新心智**：`class LLMAgentMind(AgentMindPort)`。
4. **LangGraph**：把 `ActionService._talk` / `_end_day` 管道挂成 graph，**不**把剧情事件做成固定节点。
5. **权威状态**：`AuthorityState.flags` / `extra` 为开放字典；path patch 支持扩展字段。

## 可见性 / 通告 / 结局

| 服务 | 职责 |
|------|------|
| `VisibilityService` | 置灰：known_to / 信念 / 同地；敏感 flags 默认灰 |
| `ProclamationService` | `can_proclaim` 角色通告 → 全员信念 + 事件 |
| `EndingService` | 引擎通用标签 + `WorldPack.evaluate_ending_tags` |
| `SessionRepositoryPort` | `InMemory` / `SqliteSessionRepository` |
| `evolve_actor_scores` | 内容包日终加分；引擎 `drive_priority + bonus` 排序 |
| `RumorPass` | 日终同地传谣 + 轻度失真（通用） |
| `MemoryCompressor` | 信念条数裁剪 → `flags.memory_digest` |
| `InvestigationResolver` | 对话探索推进 world_flags（假信/咒/指认） |
| `CrisisTick` | 倒计时/危机事件（读 flags） |
| `world_flag_ops` | 天道结果补丁世界旗，经 StateApplier 写入 |
| Graph checkpointer | 图状态仅 `session_id`/index/queue；会话走 repo；可开 SqliteSaver |
| `WorldPack.on_dialogue/on_day_end` | 内容深度线（如洛晴） |
| RumorPass | delay / hop / cooldown / 失真 |
## 禁止

- 在 `core/services` 写死「林溯是内鬼」等剧情分支（应在 content 种子 + 天道/信念）。
- NPC 心智直接改 `session.states`（只能出 reply/intent，天道写权威）。
- 把玩法事件枚举成巨大 if/else 表。
- 在 Graph 节点写死剧本分镜（轨迹权重可放 content flags）。

## 数据流

```
Player Action
  → ActionService
      MOVE → MapGraph 规则 → 改 location/AP
      TALK → LangGraph player_action
            build_context → npc_reply → tiandao → persist(StateApplier)
      END_DAY → LangGraph world_evolve
            select_npcs → process_one* → rollover
  → Repository.save
  → api views（置灰/日志分流）
```

## LLM 接线

- `infra/llm_client.py`：OpenAI 兼容 API
- `LLMAdjudicator` / `LLMAgentMind` 实现端口，失败或无 key → Mock
- `container.py`：`USE_LLM` + `LLM_API_KEY` 决定模式
- **禁止**在 Graph 节点写死剧情分支；剧情在 content 种子 + 模型输出 schema
