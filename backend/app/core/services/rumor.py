from __future__ import annotations

import hashlib
from uuid import uuid4

from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
from app.core.domain.models import Belief, GameSession, WorldEvent


class RumorPass:
    """
    日终传谣：延迟 + 跳数上限 + 随跳数失真增强。

    规则（通用）：
    - 见闻需 planted_day 后至少 delay_days 天才可传
    - hop >= max_hops 不再传
    - 传出后 next_spread_day = day + cooldown
    - 失真次数随 hop 增加
    """

    DISTORTIONS = (
        ("一定", "可能"),
        ("就是", "好像是"),
        ("已死", "出事了"),
        ("身亡", "出了事"),
        ("内鬼", "可疑之人"),
        ("血阴", "邪术"),
        ("通告", "有人说上面发了话"),
        ("密信", "一封来信"),
        ("假信", "那封信不太对"),
        ("镇压", "好像压住了"),
        ("至宝", "要紧的东西"),
    )

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
        events: list[WorldEvent] = []
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
                    hashlib.md5(f"{session.day}:{sp}:{loc}:{seed.belief_id}".encode()).hexdigest()[
                        :8
                    ],
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

                # 标记源信念冷却
                seed.next_spread_day = session.day + self.cooldown_days
                if seed.planted_day is None:
                    seed.planted_day = seed.day

                b = Belief(
                    belief_id=f"rumor_{sp}_{recv}_d{session.day}_{uuid4().hex[:6]}",
                    holder_id=recv,
                    proposition=distorted,
                    source=BeliefSource.RUMOR,
                    source_detail=sp,
                    truth_rel=TruthRel.UNKNOWN_TO_AUTHORITY,
                    confidence=max(0.15, (seed.confidence or 0.5) * (0.75**new_hop)),
                    day=session.day,
                    planted_day=session.day,
                    hop=new_hop,
                    next_spread_day=session.day + self.cooldown_days,
                )
                session.beliefs.setdefault(recv, []).append(b)

                # 写回更新后的 seed（冷却）
                blist = session.beliefs.get(sp) or []
                for i, old in enumerate(blist):
                    if old.belief_id == seed.belief_id:
                        blist[i] = seed
                        break

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
                ev = WorldEvent(
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
                    meta={"hop": new_hop, "from_belief": seed.belief_id},
                )
                session.events.append(ev)
                events.append(ev)
                spreads += 1
        return events

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

    def _pick_belief(
        self, session: GameSession, actor_id: str, day: int
    ) -> Belief | None:
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
        out = text
        # 跳数越高，替换越多
        applied = 0
        target = min(1 + hop, len(self.DISTORTIONS))
        for i, (a, b) in enumerate(self.DISTORTIONS):
            if applied >= target:
                break
            if (salt + i + hop) % max(2, 4 - hop) == 0 and a in out:
                out = out.replace(a, b, 1)
                applied += 1
        if hop >= 2 and not out.startswith("听说") and not out.startswith("有人说"):
            out = f"有人说{out}"
        elif hop == 1 and not out.startswith("听说"):
            out = f"听说{out}"
        if hop >= 3 and "……" not in out:
            out = out[: max(8, len(out) // 2)] + "……（记不清了）"
        return out
