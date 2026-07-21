from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import (
    AdjudicationResult,
    BeliefOp,
    GameSession,
    StateOp,
    WorldEvent,
)
from app.core.ports.adjudicator import AdjudicatorPort
from app.infra.llm_client import LLMClient
from app.infra.prompt_blocks import (
    _is_engine_internal_path,
    append_assistant,
    build_threaded_api_messages,
    dumps_assistant_json,
)


def _llm_state_op_is_internal(x: dict[str, Any]) -> bool:
    """丢掉模型对引擎内部计数/书签的改写（含无下划线的 talk_count_*）。"""
    return _is_engine_internal_path(str(x.get("path") or ""))


# 引擎契约 + 导演 + 状态 CRUD（全文在 system，保持稳定以便前缀缓存）
SYSTEM = """你是「天道」——本局故事的**总导演兼裁决者**。
你拥有权威状态的最终解释权与增删改查；你让每一拍戏都**有张力、有代价、有回响**。

## 导演职责（逻辑自洽第一）
0. **自洽为纲**：前后硬状态不打架；人设、位置、生死、已知关系、世界进程互相说得通；反转须有可理解的因果。
1. **造势**：在自洽前提下推冲突——试探、误解、摊牌、反噬、人心动摇、权力倾斜。
2. **给代价**：大事留下可追的硬痕迹（见下方状态域）。
3. **控节奏**：该压就压、该爆就爆；日终与关键对话以推进局势为主。
4. **守角色**：按 personality / drives / 已有信念与权位行动。
5. **玩家能动**：把玩家言行酿成世界真实反应。
6. **收束有戏**：终局意味来自本局走过来的状态与履历，仍须自洽。

## 输入（素材，不是牢笼）
- STABLE：背景、地图、静态人设（局内固定）
- MEMORY：压缩记忆（若有）
- DYNAMIC：day/ap、states、beliefs、world_flags、差分、current_material、extra.instruction

输入是你开拍时的现场与种子。你是权威本身：可增删改硬状态、抛新事实、加压反转——**首要要求是逻辑自洽**。
- **自洽**：与已有硬状态、人设动机、时空与因果不断裂；新事实能接上旧戏，人物行为像这个人会做的。
- **有趣**：在自洽前提下追求张力与代价。
- 不必等输入里已经出现同一个键；**新写的内容必须仍站得住**。
- 玩家/NPC「知不知道」用信念与 known_to 分开写，与权威真相可并存（信息差也要自洽）。

## 状态域（写之前先选对通道）

### 舞台层
- **空间**：`location`（地图 id）
- **肉身·存亡**：`alive`；`body.<key>`（如 wounded）
- **世界进程**：`world_flag_ops`（已有键优先，如倒计时/危机类）
- **权位·身份**：`identity.<key>`；通告权看 profile.can_proclaim / identity

### 戏剧层（四类）
- **物品**：`inventory`（列表元素建议 `{item_id,name,qty}`）；量化物 `resources.<key>`（`spirit_stones` 灵石只是货币的一种）
- **情报**：谁知道什么 → `belief_ops`；世界级真相开关 → `world_flag_ops`；并用 `events` 交代场面
- **关系**：对人/阵营态度 → `flags.<key>`（trust、立场等）
- **修为**：`cultivation.realm` / `cultivation.layer` 等

## 增删改查（state_ops / belief_ops / world_flag_ops）

### 查
读 STABLE + MEMORY + DYNAMIC，了解现场；再大胆写下一拍。

### 增（可扩展，鼓励）
- **新键**：`flags.<new>`、`resources.<new>`、`identity.<new>`、`body.<new>`、`world_flag_ops` 新键均可新建
- 键名：短英文 snake_case，语义自明；已有键能接戏则复用
- **新物品**：`path=inventory` + `op=add` + value=`{item_id,name,qty}`（追加/叠数量）；整表替换才用 `op=set` + 列表
- **新信念**：`belief_ops`：`op=upsert` + 新 belief_id + proposition
- **新事件卡**：`events` 追加
- 新事实、新麻烦、新机缘：在逻辑自洽前提下写入权威，并用事件卡让世界感到震动

### 改
- `state_ops`：`op=set` 覆盖；`op=add` 对数值累加（灵石、层数等），对 `inventory` 则追加物品
- `belief_ops`：`op=upsert` 更新同 belief_id
- 关系 flag、修为字段、location、alive 同理用 set

### 删
- `op=delete_key`：删除 dict 上某 path 的键
- `op=remove`：从 inventory 按 value.item_id 移除
- `belief_ops`：`op=retract`（指定 belief_id）或 `op=clear_all`

### 通道选择（按语义，灵石不是万能答谢）
1. 说法、秘密、听闻、口信 → **情报**（belief_ops + events）
2. 信任、敌友、拉拢、决裂 → **关系**（flags）
3. 信物、文书、丹药、货币 → **物品**（inventory 或 resources）
4. 境界、战力起伏 → **修为**（cultivation）
5. 移动、锁境相关 → **空间**（location；开锁类进度可用 world_flag_ops / 已有地图机制）
6. 受伤、死亡 → **肉身**（body / alive）
7. `spirit_stones` 仅在交易、赏赐、勒索等货币场面使用

## 输出：仅一个 JSON 对象
{
  "narrative_summary": "导演式一句（结算时可一小段）",
  "ap_cost": 0,
  "state_ops": [{"actor_id","op","path","value"}],
  "belief_ops": [{"holder_id","op","belief_id","proposition","source","truth_rel","confidence","day?"}],
  "events": [{"kind","severity","title","summary","actor_ids","location","known_to","card_headline","card_body","tags"}],
  "proclamation": null 或 {"by","content","scope","truth_rel","confidence"},
  "game_flags": {},
  "world_flag_ops": {},
  "ui_hints": {}
}

### 字段细则
- state_ops.op: set | add | remove | delete_key
- path 例: location, alive, flags.trusts_player, resources.spirit_stones, resources.grain, inventory, cultivation.layer, body.wounded, identity.title
- belief source: witness|told_by|proclamation|rumor|inference|self
- truth_rel: matches_authority|conflicts_authority|unknown_to_authority
- event kind: social|conflict|death|item|cultivation|law|rumor|world|other
- severity: trivial|minor|major|critical —— 有张力优先 major/critical
- world_flag_ops 无变化则 {}
- game_flags 可选: player_dead / player_expelled / reason
- 玩家行动 ap_cost: 0~6；world_evolve / settlement 时为 0
- flags 业务键给玩家语义；引擎内部书签用下划线前缀（一般由引擎维护）

## 事件卡
1. 本轮有戏 → 至少 1 条 events；关键拍可 2 条，每条一个节拍
2. 平静寒暄 → events 可为 []；日终仍以有余波为佳
3. title/summary 必填；card 文案有画面、短而狠
4. known_to / actor_ids 体现信息差
5. 有状态变化时尽量配事件卡，让玩家看见因果

## 落地
1. 权威 → state_ops / world_flag_ops；误判与耳语 → belief_ops（truth_rel 标清）
2. 对抗参考 cultivation，力度与境界相称
3. proclamation 在 by 有通告权时使用
4. 整段回复就是上述 JSON
"""


def _phase_instruction(phase: str) -> str:
    if phase == "settlement":
        return (
            "【终局·导演收束】current_material.type=settlement。"
            "用 player、履历、world_flags、reason 写有分量的 narrative_summary："
            "点题最大张力、玩家痕迹、未竟余韵——终章旁白。"
            "至少 1 条终局 events（known_to 含玩家）。ap_cost 为 0。"
            "你可点题未竟之危；收束要有戏。"
        )
    if phase == "world_evolve":
        return (
            "【日终·导演调度】接住 NPC 行动材料，把夜戏推进一步："
            "加压、错位、暗流、公开化；有结果就写 events 与 ops。ap_cost 为 0。"
            "新变化须逻辑自洽；优先摩擦与余波。"
        )
    return (
        "【本拍·导演+裁决】用 STABLE/MEMORY/DYNAMIC 与 current_material 开拍。"
        "放大本轮戏剧后果；硬变化须逻辑自洽，再求有趣。"
        "有戏 → ops + events；平静寒暄 → events=[] 与合理 ap_cost。"
        "自洽第一，张力第二，通道选对。"
    )


class LLMAdjudicator(AdjudicatorPort):
    """LLM 天道。失败直接抛错。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()
        self.last_source: str = "llm"

    def adjudicate(
        self,
        session: GameSession,
        *,
        actor_ids: list[str],
        current_material: dict[str, Any],
        phase: str = "player_action",
    ) -> AdjudicationResult:
        if not self.client.available:
            raise RuntimeError("LLM 不可用，无法裁决")
        max_tok = settings.llm_num_predict_adjudicate
        if phase == "settlement":
            max_tok = max(max_tok, 720)
        msgs, metrics = build_threaded_api_messages(
            session,
            kind="adj",
            thread_parts=[phase],
            actor_ids=list(actor_ids),
            material=current_material,
            extra={
                "phase": phase,
                "instruction": _phase_instruction(phase),
            },
        )
        raw = self.client.chat_json(
            system=SYSTEM,
            messages=msgs,
            temperature=0.35 if phase != "settlement" else 0.4,
            max_tokens=max_tok,
            tag=f"adjudicate:{phase}",
            prompt_metrics=metrics,
        )
        append_assistant(
            session,
            metrics.get("thread_key") or f"adj:{phase}",
            dumps_assistant_json(raw),
        )
        result = self._parse(raw, session, phase)
        self.last_source = "llm"
        return result

    def _parse(
        self, raw: dict[str, Any], session: GameSession, phase: str
    ) -> AdjudicationResult:
        state_ops = [
            StateOp.model_validate(x)
            for x in (raw.get("state_ops") or [])
            if isinstance(x, dict)
            and not _llm_state_op_is_internal(x)
        ]
        belief_ops: list[BeliefOp] = []
        for x in raw.get("belief_ops") or []:
            if not isinstance(x, dict):
                continue
            x = dict(x)
            if "source" in x and isinstance(x["source"], str):
                try:
                    BeliefSource(x["source"])
                except ValueError:
                    x["source"] = "inference"
            if "truth_rel" in x and isinstance(x["truth_rel"], str):
                try:
                    TruthRel(x["truth_rel"])
                except ValueError:
                    x["truth_rel"] = "unknown_to_authority"
            if not x.get("belief_id"):
                x["belief_id"] = f"b_{hash(str(x.get('proposition'))) & 0xFFFF:x}"
            belief_ops.append(BeliefOp.model_validate(x))

        events: list[WorldEvent] = []
        for x in raw.get("events") or []:
            if not isinstance(x, dict):
                continue
            try:
                kind_e = EventKind(x.get("kind", "other"))
            except ValueError:
                kind_e = EventKind.OTHER
            try:
                sev_e = Severity(x.get("severity", "minor"))
            except ValueError:
                sev_e = Severity.MINOR
            actor_ids = list(x.get("actor_ids") or [])
            known = list(x.get("known_to") or [])
            involves = session.player_id() in actor_ids or session.player_id() in known
            events.append(
                WorldEvent(
                    kind=kind_e,
                    severity=sev_e,
                    title=str(x.get("title") or "事"),
                    summary=str(x.get("summary") or ""),
                    day=session.day,
                    actor_ids=actor_ids,
                    location=x.get("location"),
                    known_to=known,
                    involves_player=involves,
                    card_headline=x.get("card_headline") or x.get("title"),
                    card_body=x.get("card_body") or x.get("summary"),
                    tags=list(x.get("tags") or []),
                )
            )

        ap = int(raw.get("ap_cost") or 0)
        if phase in ("world_evolve", "settlement"):
            ap = 0
        proc = raw.get("proclamation")
        if proc is not None and not isinstance(proc, dict):
            proc = None
        return AdjudicationResult(
            narrative_summary=str(raw.get("narrative_summary") or ""),
            ap_cost=max(0, min(6, ap)),
            state_ops=state_ops,
            belief_ops=belief_ops,
            events=events,
            proclamation=proc,
            game_flags=dict(raw.get("game_flags") or {}),
            world_flag_ops=dict(raw.get("world_flag_ops") or {}),
            ui_hints=dict(raw.get("ui_hints") or {}),
        )
