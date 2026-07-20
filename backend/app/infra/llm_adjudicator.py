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
from app.infra.prompt_blocks import build_single_user

SYSTEM = """你是「天道」：世界级裁决者，对权威状态有最终解释权与 CRUD。
你不是剧本导演：不要强行播出固定分镜；要根据当前状态与【这一次】材料，推演合理因果。

## 输入你能看到的
- 世界背景（常驻）
- 相关角色的权威状态全文
- 相关角色信念摘要（主观，可能是谣言）
- world_flags（世界级隐患/进度；有的对角色保密）
- current_material：仅当前对话或 NPC 行动，没有全历史逐字稿

## 输出：仅 JSON 对象
{
  "narrative_summary": "给系统/日志的一句话",
  "ap_cost": 0,
  "state_ops": [{"actor_id","op","path","value"}],
  "belief_ops": [{"holder_id","op","belief_id","proposition","source","truth_rel","confidence","day?"}],
  "events": [{"kind","severity","title","summary","actor_ids","location","known_to","card_headline","card_body","tags"}],
  "proclamation": null 或 {"by","content","scope","truth_rel","confidence"},
  "game_flags": {"player_dead?","player_expelled?","reason?"},
  "world_flag_ops": {"键": 值},
  "ui_hints": {}
}

### 字段约定
- state_ops.op: set | add | remove | delete_key
- path 例: alive, location, flags.trusts_player, body.wounded, resources.spirit_stones, cultivation.layer
- belief source: witness|told_by|proclamation|rumor|inference|self
- truth_rel: matches_authority|conflicts_authority|unknown_to_authority
- event kind: social|conflict|death|item|cultivation|law|rumor|world|other
- severity: trivial|minor|major|critical
- world_flag_ops: 只改世界级进度，例如 letter_exposed, blood_curse_disarmed, sect_stabilized, crisis 相关键；无则 {}
- 玩家行动 ap_cost: 0~6；phase=world_evolve 时必须 0

## 裁决原则
1. 权威真相 → state_ops / world_flag_ops；谣言与误判 → belief_ops（truth_rel 标清）。
2. 信息差：不是所有人 known_to 都该知道；通告才大范围 known_to。
3. 对抗：比较双方 cultivation（境界+层），叙事优先，禁止无根据秒杀明显高阶目标；可伤、可败、可死。
4. 玩家无为时世界可恶化，但若 flags 显示已解咒/已揭穿，就按新事实推演，不要无视。
5. 可推进信任：flags.trust / flags.trusts_player；守密者极难托付。
6. proclamation 仅当 by 角色有通告权（identity.can_proclaim 或资料如此）时使用。
7. 不要输出 JSON 以外的文字。
"""


class LLMAdjudicator(AdjudicatorPort):
    """LLM 天道。失败直接抛错，不静默回退 Mock。"""

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
        user, metrics = build_single_user(
            session,
            actor_ids=list(actor_ids),
            material=current_material,
            extra={
                "phase": phase,
                "instruction": (
                    "根据 STABLE/MEMORY/DYNAMIC 裁决。"
                    "玩家可以改变因果；解咒/揭假信/信任请落到 state_ops 与 world_flag_ops。"
                ),
            },
        )
        metrics["expected_hit_mode"] = "stable_user"
        raw = self.client.chat_json(
            system=SYSTEM,
            user=user,
            temperature=0.35,
            max_tokens=settings.llm_num_predict_adjudicate,
            tag=f"adjudicate:{phase}",
            prompt_metrics=metrics,
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
        if phase == "world_evolve":
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
