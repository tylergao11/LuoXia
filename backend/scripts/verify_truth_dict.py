"""真相字典 + 投影契约验收。

在 backend 目录运行:
  python scripts/verify_truth_dict.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["SESSION_STORE"] = "memory"
os.environ["USE_LLM"] = "false"
os.environ["USE_GRAPH_CHECKPOINTER"] = "false"


def main() -> None:
    from app.container import get_container
    from app.core.domain.truth_dict import TRUTH_KEYS, assert_snapshot_keys, snapshot
    from app.core.domain.models import (
        AdjudicationResult,
        BeliefOp,
        StateOp,
        WorldEvent,
    )
    from app.core.domain.enums import BeliefSource, EventKind, Severity, TruthRel
    from app.core.services.effect_summary import summarize_adjudication
    from app.core.services import chat_log
    from app.core.services.state_applier import StateApplier
    from app.api.views import to_session_view

    get_container.cache_clear()
    c = get_container()
    sess = c.factory.create("luoxia")
    c.repo.save(sess)

    snap = snapshot(sess)
    assert_snapshot_keys(snap)
    assert set(snap.keys()) == set(TRUTH_KEYS)
    print("OK snapshot keys")

    # 多事件 + belief：effect 不含心生见闻；dialogue effect ≤ 1
    pid = sess.player_id()
    adj = AdjudicationResult(
        ok=True,
        ap_cost=1,
        state_ops=[
            StateOp(
                actor_id=pid,
                path="inventory",
                op="add",
                value={"name": "旧铁剑", "qty": 1, "item_id": "old_sword"},
            )
        ],
        belief_ops=[
            BeliefOp(
                holder_id=pid,
                op="upsert",
                belief_id="b_test",
                proposition="大师兄当众质问你来历",
                source=BeliefSource.WITNESS,
                truth_rel=TruthRel.MATCHES_AUTHORITY,
            )
        ],
        events=[
            WorldEvent(
                event_id=f"e{i}",
                kind=EventKind.SOCIAL,
                severity=Severity.MINOR,
                title=f"事{i}",
                summary=f"场面{i}",
                card_headline=f"事{i}",
                card_body=f"叙事正文{i}",
                day=1,
                actor_ids=[pid, "da_shi_xiong"],
                known_to=[pid],
                involves_player=True,
            )
            for i in range(3)
        ],
    )
    created = StateApplier().apply(sess, adj)
    assert len(created) == 3
    for ev in created:
        assert "——局势——" not in (ev.card_body or "")
        assert "心生见闻" not in (ev.card_body or "")

    fx = summarize_adjudication(sess, adj, focus_other_id="da_shi_xiong")
    assert "心生见闻" not in (fx.get("full_text") or ""), fx
    assert "获物" in (fx.get("full_text") or ""), fx

    chat_log.record_talk_turn(
        sess,
        npc_id="da_shi_xiong",
        player_text="在下有礼",
        npc_text="嗯。",
        events=created,
        effects=fx,
    )
    assert "da_shi_xiong" in sess.dialogue
    assert "chat_by_actor" not in (sess.graph_meta or {})
    msgs = chat_log.get_messages(sess, "da_shi_xiong")
    effects = [m for m in msgs if m.get("role") == "effect"]
    cards = [m for m in msgs if m.get("role") == "event_card"]
    assert len(cards) == 3, cards
    assert len(effects) <= 1, effects
    if effects:
        assert "心生见闻" not in effects[0].get("text", "")
    print("OK multi-event effect ownership + dialogue field")

    # 旧仓迁移：graph_meta.chat_by_actor → dialogue
    s_legacy = c.factory.create("luoxia")
    s_legacy.dialogue = {}
    s_legacy.graph_meta["chat_by_actor"] = {
        "_scene": {
            "actor_id": "_scene",
            "messages": [{"role": "sys", "text": "legacy_guide", "id": "old"}],
        }
    }
    store = chat_log.chat_store(s_legacy)
    assert "_scene" in store
    assert "chat_by_actor" not in s_legacy.graph_meta
    assert s_legacy.dialogue["_scene"]["messages"][0]["text"] == "legacy_guide"
    print("OK dialogue migrate from graph_meta")

    view = to_session_view(sess)
    assert "situation_rows" in (view.player or {})
    assert "memory_digest" not in (view.player.get("flags") or {})
    # settlement_summary 可为投影空串
    assert isinstance(view.settlement_text, str)
    print("OK session view projections")

    # 信念在字典 + 线索包挂 belief_ids
    assert any(b.belief_id == "b_test" for b in sess.beliefs.get(pid, []))

    from app.content.luoxia.clues import collect_trigger_packets

    s2 = c.factory.create("luoxia")
    pkt = collect_trigger_packets(
        s2, kind="talk", player_id=s2.player_id(), npc_id="da_shi_xiong", location="square"
    )
    assert pkt.get("events"), pkt
    ev0 = pkt["events"][0]
    meta = ev0.meta if hasattr(ev0, "meta") else ev0.get("meta")
    assert meta and meta.get("belief_ids"), meta
    print("OK clue belief_ids link")
    print("ALL PASS")


if __name__ == "__main__":
    main()
