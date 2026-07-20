from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.config import settings
from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import (
    AdjudicationResult,
    BeliefOp,
    GameSession,
    NpcIntent,
    NpcReply,
    StateOp,
    WorldEvent,
)
from app.core.ports.agent_mind import AgentMindPort
from app.infra.llm_client import LLMClient
from app.infra.prompt_blocks import (
    append_assistant,
    build_dialogue_api_messages,
    build_single_user,
)

REPLY_SYSTEM = """你是游戏中的一个 NPC，不是旁白，不是天道。
## 认知边界
- 只有：人设、drives、tags、自己的权威状态摘要、自己的信念。
- 看不到未写入信念的「权威阴谋」。
- 守密/冷淡时极难交心；trusts_player 才可吐露部分秘密。

## 输出仅 JSON
{
  "utterance": "对白",
  "tone": "短标签",
  "engagement": "willing|tolerant|annoyed|refusing|leaving",
  "private_thought": "内心独白",
  "intent_tags": ["..."],
  "wants_action": null 或 {"type":"attack|flee|report|give_item|leave","target_id"?,"detail"?}
}
不要改世界状态。不要输出 JSON 外文字。
"""

INTEND_SYSTEM = """你是游戏中的 NPC，决定今天自主做什么。
只根据人设、信念、自身状态与公开感受。
输出仅 JSON：
{
  "goal_summary": "一句话",
  "action": {
    "type": "talk|move|search|report|proclaim|idle|other",
    "target_id": "可选",
    "location": "地图 id 可选",
    "utterance": "可选",
    "detail": "可选"
  },
  "priority": "low|normal|high",
  "based_on_beliefs": ["..."]
}
- can_proclaim 为 true 时才可 proclaim。
- 无事则 idle。
- 不要输出 JSON 外文字。
"""

DIALOGUE_TURN_SYSTEM = """你同时完成两件事，且只输出一个 JSON：
1) 扮演 NPC 对玩家说话（认知边界：只有人设与自身信念，不知未写入的阴谋）
2) 以「天道」轻裁决本轮对话对世界的影响

输出仅 JSON：
{
  "utterance": "NPC 对白",
  "tone": "短标签",
  "engagement": "willing|tolerant|annoyed|refusing|leaving",
  "private_thought": "内心独白（玩家听不见）",
  "intent_tags": [],
  "wants_action": null,
  "ap_cost": 0到6整数,
  "narrative_summary": "给日志的一句话",
  "state_ops": [{"actor_id","op","path","value"}],
  "belief_ops": [{"holder_id","op","belief_id","proposition","source","truth_rel","confidence"}],
  "events": [{"kind","severity","title","summary","actor_ids","location","known_to","card_headline","card_body","tags"}],
  "world_flag_ops": {},
  "game_flags": {},
  "proclamation": null
}

裁决原则（简）：
- 闲聊 ap_cost 多为 1；重大揭秘/冲突可 2~3。
- 信任用 flags.trust / flags.trusts_player；解咒/揭假信用 world_flag_ops。
- 信息差：known_to 不要乱给全员。
- 不要输出 JSON 外文字。
"""


class LLMAgentMind(AgentMindPort):
    """LLM 心智。失败直接抛错，不静默回退 Mock。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()
        self.last_source: str = "llm"

    def _require_client(self) -> None:
        if not self.client.available:
            raise RuntimeError("LLM 不可用")

    def reply(
        self,
        session: GameSession,
        *,
        speaker_id: str,
        player_utterance: str,
        listener_id: str = "player",
    ) -> NpcReply:
        self._require_client()
        user, metrics = build_single_user(
            session,
            actor_ids=[speaker_id, listener_id],
            material={
                "type": "dialogue",
                "player_utterance": player_utterance,
                "speaker_id": speaker_id,
                "listener_id": listener_id,
            },
        )
        raw = self.client.chat_json(
            system=REPLY_SYSTEM,
            user=user,
            temperature=0.7,
            max_tokens=settings.llm_num_predict_reply,
            tag="mind:reply",
            prompt_metrics=metrics,
        )
        self.last_source = "llm"
        return NpcReply(
            speaker_id=speaker_id,
            utterance=str(raw.get("utterance") or "……"),
            tone=str(raw.get("tone") or ""),
            intent_tags=list(raw.get("intent_tags") or []),
            private_thought=str(raw.get("private_thought") or ""),
            wants_action=raw.get("wants_action"),
            engagement=str(raw.get("engagement") or "willing"),
        )

    def intend(self, session: GameSession, *, npc_id: str) -> NpcIntent:
        self._require_client()
        user, metrics = build_single_user(
            session,
            actor_ids=[npc_id, session.player_id()],
            material={"type": "intend", "npc_id": npc_id},
            extra={"task": "daily_intent"},
        )
        raw = self.client.chat_json(
            system=INTEND_SYSTEM,
            user=user,
            temperature=0.55,
            max_tokens=settings.llm_num_predict_intend,
            tag="mind:intend",
            prompt_metrics=metrics,
        )
        action = raw.get("action") if isinstance(raw.get("action"), dict) else {"type": "idle"}
        self.last_source = "llm"
        return NpcIntent(
            npc_id=npc_id,
            goal_summary=str(raw.get("goal_summary") or ""),
            action=action,
            priority=str(raw.get("priority") or "normal"),
            based_on_beliefs=list(raw.get("based_on_beliefs") or []),
        )

    def intend_many(self, session: GameSession, npc_ids: list[str]) -> dict[str, NpcIntent]:
        """并行意图（共用同一会话快照，只读）。"""
        if not npc_ids:
            return {}
        self._require_client()

        jobs = []
        for nid in npc_ids:
            user, metrics = build_single_user(
                session,
                actor_ids=[nid, session.player_id()],
                material={"type": "intend", "npc_id": nid},
                extra={"task": "daily_intent"},
            )
            jobs.append(
                {
                    "npc_id": nid,
                    "system": INTEND_SYSTEM,
                    "user": user,
                    "temperature": 0.55,
                    "max_tokens": settings.llm_num_predict_intend,
                    "tag": f"mind:intend:{nid}",
                    "prompt_metrics": metrics,
                }
            )

        out: dict[str, NpcIntent] = {}
        workers = min(len(jobs), int(settings.llm_parallel_workers))
        errors: list[str] = []

        def one(job: dict[str, Any]) -> tuple[str, NpcIntent | None, str | None]:
            nid = job["npc_id"]
            try:
                raw = self.client.chat_json(
                    system=job["system"],
                    user=job["user"],
                    temperature=job["temperature"],
                    max_tokens=job["max_tokens"],
                    tag=str(job.get("tag") or f"mind:intend:{nid}"),
                    prompt_metrics=job.get("prompt_metrics"),
                )
                action = raw.get("action") if isinstance(raw.get("action"), dict) else {"type": "idle"}
                return (
                    nid,
                    NpcIntent(
                        npc_id=nid,
                        goal_summary=str(raw.get("goal_summary") or ""),
                        action=action,
                        priority=str(raw.get("priority") or "normal"),
                        based_on_beliefs=list(raw.get("based_on_beliefs") or []),
                    ),
                    None,
                )
            except Exception as e:  # noqa: BLE001
                return nid, None, f"{nid}:{e}"

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(one, j) for j in jobs]
            for f in as_completed(futs):
                nid, intent, err = f.result()
                if err:
                    errors.append(err)
                elif intent is not None:
                    out[nid] = intent

        if errors:
            raise RuntimeError("intend_many 失败: " + "; ".join(errors[:3]))

        self.last_source = "llm_parallel"
        return out

    def dialogue_turn(
        self,
        session: GameSession,
        *,
        speaker_id: str,
        player_utterance: str,
        listener_id: str = "player",
    ) -> tuple[NpcReply, AdjudicationResult]:
        """
        单次 LLM：NPC 对白 + 轻裁决。
        失败抛错；Mock 模式不走此类。
        """
        self._require_client()
        msgs, metrics = build_dialogue_api_messages(
            session,
            speaker_id=speaker_id,
            player_utterance=player_utterance,
            listener_id=listener_id,
        )
        raw = self.client.chat_json(
            system=DIALOGUE_TURN_SYSTEM,
            messages=msgs,
            temperature=0.55,
            max_tokens=settings.llm_num_predict_dialogue,
            tag="mind:dialogue_turn",
            prompt_metrics=metrics,
        )
        append_assistant(
            session,
            metrics.get("thread_key") or f"dlg:{speaker_id}",
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        reply = NpcReply(
            speaker_id=speaker_id,
            utterance=str(raw.get("utterance") or "……"),
            tone=str(raw.get("tone") or ""),
            intent_tags=list(raw.get("intent_tags") or []),
            private_thought=str(raw.get("private_thought") or ""),
            wants_action=raw.get("wants_action"),
            engagement=str(raw.get("engagement") or "willing"),
        )
        adj = self._parse_adj_from_dialogue(raw, session)
        self.last_source = "llm_dialogue_turn"
        return reply, adj

    def _parse_adj_from_dialogue(
        self, raw: dict[str, Any], session: GameSession
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
            events.append(
                WorldEvent(
                    kind=kind_e,
                    severity=sev_e,
                    title=str(x.get("title") or "言谈"),
                    summary=str(x.get("summary") or raw.get("narrative_summary") or ""),
                    actor_ids=list(x.get("actor_ids") or []),
                    location=x.get("location"),
                    day=int(x.get("day") or session.day),
                    known_to=list(x.get("known_to") or []),
                    card_headline=str(x.get("card_headline") or x.get("title") or ""),
                    card_body=str(x.get("card_body") or x.get("summary") or ""),
                    tags=list(x.get("tags") or ["dialogue"]),
                )
            )

        ap = max(0, min(6, int(raw.get("ap_cost") if raw.get("ap_cost") is not None else 1)))
        wfo = raw.get("world_flag_ops") or {}
        if not isinstance(wfo, dict):
            wfo = {}
        proc = raw.get("proclamation")
        if proc is not None and not isinstance(proc, dict):
            proc = None

        return AdjudicationResult(
            narrative_summary=str(raw.get("narrative_summary") or ""),
            ap_cost=ap,
            state_ops=state_ops,
            belief_ops=belief_ops,
            events=events,
            game_flags=dict(raw.get("game_flags") or {}),
            world_flag_ops=dict(wfo),
            ui_hints={},
            proclamation=proc,
        )
