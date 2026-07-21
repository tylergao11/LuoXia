from __future__ import annotations

import hashlib
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import BeliefOp, GameSession, WorldEvent
from app.core.services.content_packet import apply_packet, empty_packet


class RumorPass:
    """
    日终传谣：延迟 + 跳数上限 + 随跳数失真增强。
    产出同构包 → apply_packet，不直写 session.beliefs / events。
    """

    def __init__(
        self,
        *,
        max_spreads: int = 5,
        delay_days: int = 1,
        max_hops: int = 3,
        cooldown_days: int = 1,
    ) -> None:
        self.max_spreads = max_spreads
        self.delay_days = delay_days
        self.max_hops = max_hops
        self.cooldown_days = cooldown_days

    def run(self, session: GameSession) -> list[WorldEvent]:
        packet = empty_packet()
        spreads = 0
        by_loc: dict[str, list[str]] = {}
        for aid, st in session.states.items():
            if not st.alive or not st.location:
                continue
            by_loc.setdefault(st.location, []).append(aid)

        for loc, actors in by_loc.items():
            if spreads >= self.max_spreads:
                break
            if len(actors) < 2:
                continue
            spreaders = [
                a
                for a in actors
                if self._is_spreader(session, a) and session.beliefs.get(a)
            ]
            for sp in spreaders:
                if spreads >= self.max_spreads:
                    break
                seed = self._pick_belief(session, sp, session.day)
                if not seed:
                    continue
                receivers = [a for a in actors if a != sp]
                if not receivers:
                    continue
                h = int(
                    hashlib.md5(
                        f"{session.day}:{sp}:{loc}:{seed.belief_id}".encode()
                    ).hexdigest()[:8],
                    16,
                )
                recv = receivers[h % len(receivers)]
                new_hop = (seed.hop or 0) + 1
                if new_hop > self.max_hops:
                    continue
                distorted = self._distort(
                    seed.proposition, salt=session.day + h, hop=new_hop
                )
                existing = {b.proposition for b in session.beliefs.get(recv, [])}
                if distorted in existing:
                    continue

                # 接收方新见闻 + 场面事件（源信念冷却在 apply 后戳元数据）
                new_bid = f"rumor_{sp}_{recv}_d{session.day}_{uuid4().hex[:6]}"
                packet["belief_ops"].append(
                    BeliefOp(
                        holder_id=recv,
                        op="upsert",
                        belief_id=new_bid,
                        proposition=distorted,
                        source=BeliefSource.RUMOR,
                        source_detail=sp,
                        truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                        confidence=max(0.15, (seed.confidence or 0.5) * (0.75**new_hop)),
                        day=session.day,
                    )
                )

                sp_name = (
                    session.profiles[sp].display_name if sp in session.profiles else sp
                )
                recv_name = (
                    session.profiles[recv].display_name
                    if recv in session.profiles
                    else recv
                )
                loc_name = (
                    session.map.nodes[loc].name if loc in session.map.nodes else loc
                )
                packet["events"].append(
                    WorldEvent(
                        kind=EventKind.RUMOR,
                        severity=Severity.TRIVIAL if new_hop < 2 else Severity.MINOR,
                        title=f"传语·{loc_name}",
                        summary=f"{sp_name}向{recv_name}传了一句闲话（第{new_hop}跳）。",
                        actor_ids=[sp, recv],
                        location=loc,
                        day=session.day,
                        known_to=[sp, recv],
                        card_headline="闲话",
                        card_body=distorted,
                        involves_player=session.player_id() in (sp, recv),
                        tags=["rumor_pass", "auto", f"hop_{new_hop}"],
                        meta={
                            "hop": new_hop,
                            "from_belief": seed.belief_id,
                            "belief_ids": [new_bid],
                            "rumor_seed_id": seed.belief_id,
                            "rumor_seed_holder": sp,
                            "rumor_cooldown_day": session.day + self.cooldown_days,
                            "rumor_hop": new_hop,
                        },
                    )
                )
                spreads += 1

        created = apply_packet(session, packet)
        self._stamp_rumor_meta(session, packet)
        return created

    def _stamp_rumor_meta(self, session: GameSession, packet: dict) -> None:
        for ev in packet.get("events") or []:
            meta = getattr(ev, "meta", None) or {}
            if not isinstance(meta, dict):
                continue
            hop = int(meta.get("rumor_hop") or meta.get("hop") or 0)
            cool = meta.get("rumor_cooldown_day")
            cool_i = int(cool) if cool is not None else session.day + self.cooldown_days
            seed_id = meta.get("rumor_seed_id") or meta.get("from_belief")
            seed_holder = meta.get("rumor_seed_holder")
            for bid in meta.get("belief_ids") or []:
                for blist in (session.beliefs or {}).values():
                    for b in blist:
                        if b.belief_id == bid:
                            b.hop = hop
                            b.planted_day = session.day
                            b.next_spread_day = cool_i
            if seed_id:
                holders = (
                    [seed_holder]
                    if seed_holder
                    else list((session.beliefs or {}).keys())
                )
                for holder in holders:
                    for b in session.beliefs.get(holder) or []:
                        if b.belief_id == seed_id:
                            b.next_spread_day = cool_i
                            if b.planted_day is None:
                                b.planted_day = b.day
                            break

    def _is_spreader(self, session: GameSession, actor_id: str) -> bool:
        prof = session.profiles.get(actor_id)
        if not prof or prof.is_player:
            return False
        tags = set(prof.tags or [])
        if "gossip" in tags or "social" in tags:
            return True
        if "热心" in prof.personality or "碎嘴" in prof.personality:
            return True
        return False

    def _pick_belief(self, session: GameSession, actor_id: str, day: int):
        from app.core.domain.models import Belief

        beliefs = list(session.beliefs.get(actor_id) or [])
        if not beliefs:
            return None
        candidates: list[Belief] = []
        for b in beliefs:
            planted = b.planted_day if b.planted_day is not None else b.day
            if day - planted < self.delay_days:
                continue
            if (b.hop or 0) >= self.max_hops:
                continue
            if b.next_spread_day is not None and day < b.next_spread_day:
                continue
            if b.source in (
                BeliefSource.RUMOR,
                BeliefSource.TOLD_BY,
                BeliefSource.INFERENCE,
                BeliefSource.WITNESS,
            ):
                candidates.append(b)
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x.day, -(x.hop or 0)), reverse=True)
        return candidates[0]

    def _distort(self, text: str, *, salt: int, hop: int) -> str:
        _ = salt
        out = (text or "").strip()
        if hop >= 1 and not out.startswith("听说") and not out.startswith("有人说"):
            out = f"听说{out}"
        if hop >= 2:
            if out.startswith("听说"):
                out = f"有人说{out[2:]}"
            elif not out.startswith("有人说"):
                out = f"有人说{out}"
        if hop >= 3:
            cut = max(8, len(out) // 2)
            out = out[:cut] + "……（记不清了）"
        elif hop >= 2 and len(out) > 28:
            out = out[: max(16, len(out) - hop * 3)] + "……"
        return out
