from __future__ import annotations

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
from app.infra.night_batch import build_night_batch_messages, parse_night_batch
from app.infra.prompt_blocks import (
    append_assistant,
    build_dialogue_api_messages,
    build_threaded_api_messages,
    dumps_assistant_json,
)

REPLY_SYSTEM = """你就是 DYNAMIC / STABLE 里正在开口的那个人（display_name 与人设即你）。
用第一人称活在场景里：呼吸、语气、好恶都是你的；你只作为此人说话与感受。

## 你此刻知道什么
- 自己的人设、drives、tags、自己的权威状态、自己的信念。
- DYNAMIC.extra.tendencies（若有）是你对外可感的公开印象，可影响态度。
- 你的世界仅由已进入你信念与感官的信息构成；你已听说/看见的，才进入你的判断。
- 天性守密/冷淡时，交心来得极慢；flags 里 trusts_player 为真时，你才可能吐露压箱底的事。

## 输出：仅如下 JSON
{
  "utterance": "你说出口的话",
  "tone": "短标签",
  "engagement": "willing|tolerant|annoyed|refusing|leaving",
  "private_thought": "你心里真正在想什么",
  "intent_tags": ["..."],
  "wants_action": null 或 {"type":"attack|flee|report|give_item|leave","target_id"?,"detail"?}
}
你的职责是对白与当下冲动；世界状态的修改由天道另场完成。整段回复就是上述 JSON。
"""

INTEND_SYSTEM = """你就是当前角色本人，在想：今天我要做什么。
依据：自己的人设、信念、自身状态与公开感受；DYNAMIC.extra.tendencies（若有）可作态度参考。

输出：仅如下 JSON
{
  "goal_summary": "一句话（用你的动机说）",
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
- can_proclaim 为真时，你可以使用 proclaim。
- 无事则 action 为 idle。
- 整段回复就是上述 JSON。
"""

NIGHT_BATCH_SYSTEM = """你在编排一夜群戏：为多名角色各自生成今夜意图，并排出落地顺序，使暗流与碰撞成为可能。

## 每位角色
- STABLE 有全员人设；**每人仅依据自己 ### SLOT 里可见的信息**做决定。
- 意图与动机锚定该 SLOT 已有内容。
- 按各自 personality / drives / tags / self_beliefs / public_tendency 分化行动，每人一条独特路数。

## 张力
- 优先能产生摩擦的行动：试探、查证、游说、监视、夺先、自保、传谣、对峙前就位。
- 可协调公开冲突（同往一处、互为目标）；play_order 表达谁先谁后。
- play_order 恰好覆盖 roster 全体、各出现一次。

## 输出：仅一个 JSON
{
  "play_order": ["npc_id", "..."],
  "conflicts_resolved": ["可选：一句话"],
  "intents": [
    {
      "npc_id": "必须是 roster 成员",
      "goal_summary": "一句话（带动机）",
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
  ]
}
- roster 每人恰好一条 intent；can_proclaim 为真者方可 proclaim。
- 整段回复就是上述 JSON。
"""

DIALOGUE_TURN_SYSTEM = """你同时完成两件事，且只输出一个 JSON：
1) **你就是对方那个人**：用其人设与信念回话；角色所知以自己信念与场景为界。
2) 以「天道」导演落地：硬状态可增删改，**逻辑自洽第一**，再求张力与代价；通道选对。

## 落地通道（可新建键；短英文 snake_case）
- **情报** → belief_ops + events
- **关系** → flags.<key>（可新建）
- **物品** → inventory 或 resources.<key>（spirit_stones 作货币时用）
- **修为** → cultivation.*
- **空间/肉身** → location / alive / body.*
- **世界进程** → world_flag_ops
增删改查：set / add / delete_key / remove(item_id) / upsert / retract；新事实须接得上已有状态与人设，并用 events 让人感到。

输出：仅如下 JSON
{
  "utterance": "你（该角色）说出口的话，可有潜台词",
  "tone": "短标签",
  "engagement": "willing|tolerant|annoyed|refusing|leaving",
  "private_thought": "你心里所想（对方听不见）",
  "intent_tags": [],
  "wants_action": null,
  "ap_cost": 0到6整数,
  "narrative_summary": "本拍戏剧一句",
  "state_ops": [{"actor_id","op","path","value"}],
  "belief_ops": [{"holder_id","op","belief_id","proposition","source","truth_rel","confidence"}],
  "events": [{"kind","severity","title","summary","actor_ids","location","known_to","card_headline","card_body","tags"}],
  "world_flag_ops": {},
  "game_flags": {},
  "proclamation": null,
  "ui_hints": {}
}

原则：
- 对白贴人设，语气鲜活。
- 有戏 → 至少 1 条 events + 必要 ops；平静寒暄才可 events=[]。
- 玩家约战/单挑/动手 → 必须 events；可 ui_hints.propose_encounter={"kind":"duel","foe_id":"<id>","reason":"..."}（引擎投影应战，禁止 world_flag_ops.active_encounter）。
- known_to 体现信息差。闲聊 ap 约 1；摊牌/冲突可 2~3。
- 整段回复就是上述 JSON；自洽第一，张力第二，通道选对。
"""


class LLMAgentMind(AgentMindPort):
    """LLM 心智。失败直接抛错。"""

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
        msgs, metrics = build_threaded_api_messages(
            session,
            kind="reply",
            thread_parts=[speaker_id],
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
            messages=msgs,
            temperature=0.7,
            max_tokens=settings.llm_num_predict_reply,
            tag="mind:reply",
            prompt_metrics=metrics,
        )
        append_assistant(
            session,
            metrics.get("thread_key") or f"reply:{speaker_id}",
            dumps_assistant_json(raw),
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
        msgs, metrics = build_threaded_api_messages(
            session,
            kind="intend",
            thread_parts=[npc_id],
            actor_ids=[npc_id, session.player_id()],
            material={"type": "intend", "npc_id": npc_id},
            extra={"task": "daily_intent"},
        )
        raw = self.client.chat_json(
            system=INTEND_SYSTEM,
            messages=msgs,
            temperature=0.55,
            max_tokens=settings.llm_num_predict_intend,
            tag="mind:intend",
            prompt_metrics=metrics,
        )
        append_assistant(
            session,
            metrics.get("thread_key") or f"intend:{npc_id}",
            dumps_assistant_json(raw),
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
        """并行意图：先串行建 thread（各 NPC 独立键），再并行调模型，最后串行写回 assistant。"""
        if not npc_ids:
            return {}
        self._require_client()

        jobs = []
        for nid in npc_ids:
            msgs, metrics = build_threaded_api_messages(
                session,
                kind="intend",
                thread_parts=[nid],
                actor_ids=[nid, session.player_id()],
                material={"type": "intend", "npc_id": nid},
                extra={"task": "daily_intent"},
            )
            jobs.append(
                {
                    "npc_id": nid,
                    "system": INTEND_SYSTEM,
                    "messages": msgs,
                    "temperature": 0.55,
                    "max_tokens": settings.llm_num_predict_intend,
                    "tag": f"mind:intend:{nid}",
                    "prompt_metrics": metrics,
                    "thread_key": metrics.get("thread_key") or f"intend:{nid}",
                }
            )

        out: dict[str, NpcIntent] = {}
        raw_by_nid: dict[str, dict[str, Any]] = {}
        workers = min(len(jobs), int(settings.llm_parallel_workers))
        errors: list[str] = []

        def one(job: dict[str, Any]) -> tuple[str, NpcIntent | None, dict[str, Any] | None, str | None]:
            nid = job["npc_id"]
            try:
                raw = self.client.chat_json(
                    system=job["system"],
                    messages=job["messages"],
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
                    raw,
                    None,
                )
            except Exception as e:  # noqa: BLE001
                return nid, None, None, f"{nid}:{e}"

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(one, j) for j in jobs]
            for f in as_completed(futs):
                nid, intent, raw, err = f.result()
                if err:
                    errors.append(err)
                elif intent is not None and raw is not None:
                    out[nid] = intent
                    raw_by_nid[nid] = raw

        if errors:
            raise RuntimeError("intend_many 失败: " + "; ".join(errors[:3]))

        # 串行写回，避免并行改 graph_meta
        for job in jobs:
            nid = job["npc_id"]
            raw = raw_by_nid.get(nid)
            if raw is None:
                continue
            append_assistant(session, str(job["thread_key"]), dumps_assistant_json(raw))

        self.last_source = "llm_parallel"
        return out

    def intend_night_batch(
        self, session: GameSession, npc_ids: list[str]
    ) -> tuple[dict[str, NpcIntent], list[str]]:
        """
        日终一次协商：密封分栏意图 + play_order。
        失败则全员规则意图 + 驱动序。
        """
        queue = [nid for nid in npc_ids if nid in session.profiles]
        if not queue:
            return {}, []
        self._require_client()
        msgs, metrics = build_night_batch_messages(session, queue)
        raw = self.client.chat_json(
            system=NIGHT_BATCH_SYSTEM,
            messages=msgs,
            temperature=0.45,
            max_tokens=settings.llm_num_predict_night_batch,
            tag="mind:intend_night_batch",
            prompt_metrics=metrics,
        )
        append_assistant(
            session,
            metrics.get("thread_key") or "intend_batch:night",
            dumps_assistant_json(raw),
        )
        intents, order = parse_night_batch(session, queue, raw)
        self.last_source = "llm_night_batch"
        return intents, order

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
        失败抛错。
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
            dumps_assistant_json(raw),
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
        else:
            wfo = dict(wfo)
            wfo.pop("active_encounter", None)
        proc = raw.get("proclamation")
        if proc is not None and not isinstance(proc, dict):
            proc = None
        hints = raw.get("ui_hints") if isinstance(raw.get("ui_hints"), dict) else {}

        return AdjudicationResult(
            narrative_summary=str(raw.get("narrative_summary") or ""),
            ap_cost=ap,
            state_ops=state_ops,
            belief_ops=belief_ops,
            events=events,
            game_flags=dict(raw.get("game_flags") or {}),
            world_flag_ops=wfo,
            ui_hints=dict(hints),
            proclamation=proc,
        )
