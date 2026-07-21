from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import (
    AdjudicationResult,
    BeliefOp,
    GameSession,
    StateOp,
    WorldEvent,
)
from app.core.ports.adjudicator import AdjudicatorPort
from app.core.services.world_registry import WorldRegistry


class ScriptedAdjudicator(AdjudicatorPort):
    """
    无 LLM 时的可运行裁决器。
    不扫台词：线索用 material.simulate_clues；意图用 material.simulate_intents /
    npc_wants_action / npc_intent_tags（与天道事件同构）。
    """

    last_source: str = "scripted"

    def __init__(self, registry: WorldRegistry | None = None) -> None:
        self.registry = registry

    REALM_POWER = {
        "凡人": 0,
        "炼气": 1,
        "筑基": 2,
        "结丹": 3,
        "元婴": 4,
        "化神": 5,
    }

    def adjudicate(
        self,
        session: GameSession,
        *,
        actor_ids: list[str],
        current_material: dict[str, Any],
        phase: str = "player_action",
    ) -> AdjudicationResult:
        self.last_source = "scripted"
        mtype = current_material.get("type")
        if mtype == "dialogue":
            return self._dialogue(session, actor_ids, current_material, phase)
        if mtype == "npc_action":
            return self._npc_action(session, actor_ids, current_material)
        return AdjudicationResult(
            narrative_summary="无显著变化",
            ap_cost=1 if phase == "player_action" else 0,
        )

    def _collect_intents(self, material: dict[str, Any]) -> set[str]:
        out: set[str] = set()
        raw = material.get("simulate_intents") or material.get("intents") or []
        if isinstance(raw, list):
            out.update(str(x) for x in raw)
        for tag in material.get("npc_intent_tags") or []:
            t = str(tag)
            if t.startswith("intent:"):
                out.add(t.split(":", 1)[1])
            else:
                out.add(t)
        wa = material.get("npc_wants_action")
        if isinstance(wa, dict) and wa.get("type"):
            out.add(str(wa["type"]))
        # 线索包也可带意图别名
        for c in material.get("simulate_clues") or []:
            if str(c) in ("proclamation_request", "rumor_seed", "attack", "attack_lethal"):
                out.add(str(c))
        return out

    def _dialogue(
        self,
        session: GameSession,
        actor_ids: list[str],
        material: dict[str, Any],
        phase: str,
    ) -> AdjudicationResult:
        player = session.player_id()
        npc = next((a for a in actor_ids if a != player), actor_ids[-1])
        utter = material.get("player_utterance") or ""
        npc_line = material.get("npc_utterance") or ""
        loc = material.get("location")
        npc_name = session.profiles[npc].display_name
        intents = self._collect_intents(material)

        events: list[WorldEvent] = [
            WorldEvent(
                kind=EventKind.SOCIAL,
                severity=Severity.TRIVIAL,
                title=f"与{npc_name}交谈",
                summary=f"你：「{utter[:40]}」／对方：「{npc_line[:40]}」",
                actor_ids=[player, npc],
                location=loc,
                day=session.day,
                known_to=[player, npc],
                card_headline="一席话",
                card_body=f"{utter}\n——\n{npc_line}",
                involves_player=True,
                tags=["dialogue"],
            )
        ]
        belief_ops: list[BeliefOp] = [
            BeliefOp(
                holder_id=npc,
                op="upsert",
                belief_id=f"met_{player}_d{session.day}_{uuid4().hex[:6]}",
                proposition=f"今日与{session.profiles[player].display_name}交谈：{utter[:36]}",
                source=BeliefSource.WITNESS,
                truth_rel=TruthRel.MATCHES_AUTHORITY,
                confidence=0.8,
                day=session.day,
            ),
            BeliefOp(
                holder_id=player,
                op="upsert",
                belief_id=f"talk_{npc}_d{session.day}_{uuid4().hex[:6]}",
                proposition=f"{npc_name}对你说：{npc_line[:36]}",
                source=BeliefSource.TOLD_BY,
                source_detail=npc_name,
                truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                confidence=0.6,
                day=session.day,
            ),
        ]
        state_ops: list[StateOp] = []
        proclamation = None
        narrative = "对话已留下痕迹。"
        world_flag_ops: dict[str, Any] = {}
        game_flags: dict[str, Any] = {}

        # 模拟天道线索事件包（WorldPack 可拔插）
        sim = material.get("simulate_clues") or []
        if isinstance(sim, list) and sim and self.registry is not None:
            pack = self.registry.get(session.world_id)
            chunk = pack.merge_clue_packets(
                session,
                [
                    str(x)
                    for x in sim
                    if str(x)
                    not in ("proclamation_request", "rumor_seed", "attack", "attack_lethal")
                ],
                player_id=player,
                npc_id=npc,
                location=loc if isinstance(loc, str) else None,
            )
            state_ops.extend(chunk.get("state_ops") or [])
            belief_ops.extend(chunk.get("belief_ops") or [])
            events.extend(chunk.get("events") or [])
            world_flag_ops.update(chunk.get("world_flag_ops") or {})
            if chunk.get("notes"):
                narrative = " ".join(chunk["notes"])

        prof = session.profiles.get(npc)
        can_proc = bool(prof and prof.can_proclaim) or bool(
            session.states.get(npc) and session.states[npc].identity.get("can_proclaim")
        )
        if can_proc and ("proclamation" in intents or "proclamation_request" in intents):
            content = (material.get("proclamation_content") or utter or "即日起加强巡查，勿信妄言。").strip()
            if len(content) > 80:
                content = content[:80]
            proclamation = {
                "by": npc,
                "content": content,
                "scope": "sect",
                "truth_rel": "unknown_to_authority",
                "confidence": 0.8,
            }
            narrative = f"{npc_name}采纳言辞，准备通告全宗。"
            events.append(
                WorldEvent(
                    kind=EventKind.LAW,
                    severity=Severity.MAJOR,
                    title="请求通告",
                    summary=f"你请求{npc_name}发布通告。",
                    actor_ids=[player, npc],
                    location=loc,
                    day=session.day,
                    known_to=[player, npc],
                    card_headline="通告将出",
                    card_body=content,
                    involves_player=True,
                    tags=["proclamation_request"],
                )
            )

        if "rumor_seed" in intents or "rumor" in intents:
            belief_ops.append(
                BeliefOp(
                    holder_id=npc,
                    op="upsert",
                    belief_id=f"rumor_from_{player}_{uuid4().hex[:6]}",
                    proposition=f"听{session.profiles[player].display_name}说：{utter[:40]}",
                    source=BeliefSource.RUMOR,
                    source_detail=player,
                    truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                    confidence=0.4,
                    day=session.day,
                )
            )
            narrative = "言语如风，或将再传。"
            events[0].tags.append("rumor_seed")

        if "attack" in intents or "attack_lethal" in intents or "combat" in intents:
            combat = self._resolve_combat(
                session,
                attacker_id=player,
                defender_id=npc,
                lethal="attack_lethal" in intents or "lethal" in intents,
                location=loc,
            )
            state_ops.extend(combat["state_ops"])
            belief_ops.extend(combat["belief_ops"])
            events.extend(combat["events"])
            narrative = combat["narrative"]
            game_flags.update(combat.get("game_flags") or {})
            ap = 2
        else:
            ap = 1 if utter else 0

        if phase != "player_action":
            ap = 0
        return AdjudicationResult(
            narrative_summary=narrative,
            ap_cost=ap,
            state_ops=state_ops,
            belief_ops=belief_ops,
            events=events,
            proclamation=proclamation,
            game_flags=game_flags,
            world_flag_ops=world_flag_ops,
        )

    def _npc_action(
        self, session: GameSession, actor_ids: list[str], material: dict[str, Any]
    ) -> AdjudicationResult:
        intent = material.get("intent") or {}
        npc_id = material.get("npc_id") or (actor_ids[0] if actor_ids else "")
        name = (
            session.profiles[npc_id].display_name if npc_id in session.profiles else npc_id
        )
        goal = intent.get("goal_summary") or "行事"
        action = intent.get("action") or {}
        at = action.get("type", "idle")
        if at == "idle":
            return AdjudicationResult(narrative_summary=f"{name}今日无事", ap_cost=0)

        state_ops: list[StateOp] = []
        belief_ops: list[BeliefOp] = []
        loc = action.get("location")
        cur = session.states.get(npc_id).location if npc_id in session.states else None

        if at == "move" and loc and loc in session.map.nodes:
            state_ops.append(StateOp(actor_id=npc_id, op="set", path="location", value=loc))
            cur = loc

        # 搜查：若世界有阴谋 flags，小概率写 has_evidence（通用）
        if at == "search" and session.world_flags.get("fake_secret_realm_letter"):
            state_ops.append(
                StateOp(actor_id=npc_id, op="set", path="flags.has_evidence", value=True)
            )
            belief_ops.append(
                BeliefOp(
                    holder_id=npc_id,
                    op="upsert",
                    belief_id=f"evidence_d{session.day}",
                    proposition="查到一些蹊跷痕迹，尚不敢轻易示人",
                    source=BeliefSource.INFERENCE,
                    truth_rel=TruthRel.MATCHES_AUTHORITY,
                    confidence=0.5,
                    day=session.day,
                )
            )

        # 社交/传谣：同地扩散一条模糊见闻
        known = [npc_id]
        if cur:
            known = list({npc_id, *session.actors_at(cur)})
        if at in ("talk", "rumor", "search") and cur:
            rumor = f"{name}在{session.map.nodes[cur].name}活动：{goal[:24]}"
            for hid in known:
                if hid == npc_id:
                    continue
                belief_ops.append(
                    BeliefOp(
                        holder_id=hid,
                        op="upsert",
                        belief_id=f"saw_{npc_id}_d{session.day}_{hid}",
                        proposition=rumor,
                        source=BeliefSource.RUMOR,
                        source_detail=npc_id,
                        truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                        confidence=0.35,
                        day=session.day,
                    )
                )

        # 有通告权且意图 proclaim
        proclamation = None
        if at == "proclaim" and self._can_proclaim(session, npc_id):
            content = str(action.get("detail") or goal or "宗门有令，各自安心修炼。")
            proclamation = {
                "by": npc_id,
                "content": content[:80],
                "scope": "sect",
                "truth_rel": "unknown_to_authority",
            }

        ev = WorldEvent(
            kind=EventKind.WORLD,
            severity=Severity.MINOR,
            title=f"{name}的行动",
            summary=goal,
            actor_ids=[npc_id],
            location=cur,
            day=session.day,
            known_to=known,
            card_headline=name,
            card_body=goal,
            involves_player=session.player_id() in known,
            tags=["world_evolve", at],
        )

        return AdjudicationResult(
            narrative_summary=f"{name}：{goal}",
            ap_cost=0,
            state_ops=state_ops,
            belief_ops=belief_ops,
            events=[ev],
            proclamation=proclamation,
        )

    def _can_proclaim(self, session: GameSession, actor_id: str) -> bool:
        prof = session.profiles.get(actor_id)
        if prof and prof.can_proclaim:
            return True
        st = session.states.get(actor_id)
        return bool(st and st.identity.get("can_proclaim"))

    def _power(self, session: GameSession, actor_id: str) -> int:
        st = session.states.get(actor_id)
        if not st:
            return 0
        realm = str((st.cultivation or {}).get("realm") or "凡人")
        base = 0
        for k, v in self.REALM_POWER.items():
            if k in realm:
                base = max(base, v)
        layer = (st.cultivation or {}).get("layer") or 0
        try:
            layer_i = int(layer)
        except (TypeError, ValueError):
            layer_i = 0
        return base * 10 + min(layer_i, 9)

    def _resolve_combat(
        self,
        session: GameSession,
        *,
        attacker_id: str,
        defender_id: str,
        lethal: bool,
        location: str | None,
    ) -> dict[str, Any]:
        atk = session.profiles[attacker_id].display_name
        dfn = session.profiles[defender_id].display_name
        pa, pb = self._power(session, attacker_id), self._power(session, defender_id)
        diff = pa - pb
        state_ops: list[StateOp] = []
        belief_ops: list[BeliefOp] = []
        events: list[WorldEvent] = []
        game_flags: dict[str, Any] = {}
        known = list(
            {
                attacker_id,
                defender_id,
                *session.actors_at(location or ""),
            }
        )

        # 结果：大优可致死；小优重伤；劣势受伤/失败；均势互伤
        if diff >= 8 and lethal:
            outcome = "kill"
            narrative = f"冲突陡生。以你的修为，{dfn}不敌，当场陨落。"
            state_ops.append(StateOp(actor_id=defender_id, op="set", path="alive", value=False))
            state_ops.append(
                StateOp(
                    actor_id=attacker_id,
                    op="set",
                    path="flags.recent_deed",
                    value=f"击杀{dfn}",
                )
            )
            severity = Severity.CRITICAL
            kind = EventKind.DEATH
            title = f"{dfn}身亡"
            body = f"{atk}与{dfn}冲突，{dfn}死于非命。"
        elif diff >= 3:
            outcome = "wound_def"
            narrative = f"冲突陡生。{dfn}受伤退避，尚未致命。"
            state_ops.append(
                StateOp(actor_id=defender_id, op="set", path="body.wounded", value=True)
            )
            state_ops.append(
                StateOp(
                    actor_id=defender_id,
                    op="set",
                    path="flags.last_assailant",
                    value=attacker_id,
                )
            )
            severity = Severity.MAJOR
            kind = EventKind.CONFLICT
            title = f"与{dfn}冲突"
            body = f"{atk}占上风，{dfn}负伤。"
        elif diff <= -8 and lethal:
            outcome = "kill_fail_dead"
            narrative = f"你妄动杀机，却远非{dfn}之敌，反遭反噬，身死当场。"
            state_ops.append(StateOp(actor_id=attacker_id, op="set", path="alive", value=False))
            game_flags["player_dead"] = True
            game_flags["reason"] = f"与{dfn}冲突身死"
            severity = Severity.CRITICAL
            kind = EventKind.DEATH
            title = f"{atk}身亡"
            body = f"{atk}挑衅{dfn}失败，死于反杀。"
        elif diff <= -3:
            outcome = "wound_atk"
            narrative = f"冲突陡生。你并非{dfn}对手，带伤而退。"
            state_ops.append(
                StateOp(actor_id=attacker_id, op="set", path="body.wounded", value=True)
            )
            severity = Severity.MAJOR
            kind = EventKind.CONFLICT
            title = f"冲突失利"
            body = f"{atk}不敌{dfn}，负伤。"
        else:
            outcome = "clash"
            narrative = f"双方动手，未分生死，各自忌惮。"
            state_ops.append(
                StateOp(actor_id=attacker_id, op="set", path="body.bruised", value=True)
            )
            state_ops.append(
                StateOp(actor_id=defender_id, op="set", path="body.bruised", value=True)
            )
            severity = Severity.MINOR
            kind = EventKind.CONFLICT
            title = f"激烈冲突"
            body = f"{atk}与{dfn}交手，暂且罢手。"

        # 目击者见闻
        for hid in known:
            prop = body
            if outcome == "kill" and hid not in (attacker_id, defender_id):
                prop = f"听说{dfn}死了，现场曾有冲突"
            belief_ops.append(
                BeliefOp(
                    holder_id=hid,
                    op="upsert",
                    belief_id=f"combat_{outcome}_{hid}_{uuid4().hex[:6]}",
                    proposition=prop,
                    source=BeliefSource.WITNESS
                    if hid in (attacker_id, defender_id)
                    else BeliefSource.RUMOR,
                    truth_rel=TruthRel.MATCHES_AUTHORITY
                    if outcome in ("kill", "kill_fail_dead")
                    else TruthRel.UNKNOWN_TO_AUTHORITY,
                    confidence=0.9 if hid in (attacker_id, defender_id) else 0.5,
                    day=session.day,
                )
            )

        events.append(
            WorldEvent(
                kind=kind,
                severity=severity,
                title=title,
                summary=body,
                actor_ids=[attacker_id, defender_id],
                location=location,
                day=session.day,
                known_to=known,
                card_headline=title,
                card_body=narrative,
                involves_player=session.player_id() in (attacker_id, defender_id),
                tags=["combat", outcome],
            )
        )
        return {
            "narrative": narrative,
            "state_ops": state_ops,
            "belief_ops": belief_ops,
            "events": events,
            "game_flags": game_flags,
        }
