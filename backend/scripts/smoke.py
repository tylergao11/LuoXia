"""可重复冒烟：架构关键路径。在 backend 目录运行: python scripts/smoke.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.container import get_container
from app.core.domain.enums import ActionType
from app.core.domain.models import ActionRequest


def main() -> None:
    from app import config

    # 冒烟默认不打真模型，避免 Ollama 超时拖死
    config.settings.use_llm = False
    config.settings.use_graph_checkpointer = False
    config.settings.session_store = "memory"
    get_container.cache_clear()
    c = get_container()
    assert len(c.registry.list_worlds()) >= 2

    # 多世界
    s = c.factory.create("qingxi")
    c.repo.save(s)
    assert s.world_id == "qingxi"

    # 落霞对话 + 通告
    s = c.factory.create("luoxia")
    c.repo.save(s)
    sid = s.session_id
    c.actions.handle(sid, ActionRequest(type=ActionType.MOVE, location_id="square"))
    c.actions.handle(sid, ActionRequest(type=ActionType.MOVE, location_id="law"))
    r = c.actions.handle(
        sid,
        ActionRequest(
            type=ActionType.TALK,
            target_id="zhang_lao_fa",
            utterance="请长老通告：近日严查细作",
        ),
    )
    assert r.ok, r.message
    assert any(
        "通告" in (e.title or "") or "通告" in (e.card_headline or "")
        for e in r.session.events
    )

    # 对抗：对低修为目标（mock 玩家炼气 vs 需找更弱——马三已删，用对白杀伤测试 wound）
    # 白问舟炼气筑基初期 power ~20+，玩家炼气3 ~13 → 玩家可能失利
    s2 = r.session
    c.repo.save(s2)
    # 去客居找白问舟
    while s2.states["player"].location != "dorm_outer" and s2.ap > 0:
        # path law->square->dorm_outer
        loc = s2.states["player"].location
        nxt = "square" if loc == "law" else "dorm_outer"
        rr = c.actions.handle(sid, ActionRequest(type=ActionType.MOVE, location_id=nxt))
        s2 = rr.session
        if not rr.ok:
            break
    r3 = c.actions.handle(
        sid,
        ActionRequest(
            type=ActionType.TALK,
            target_id="ke_qing_yin",
            utterance="动手比试一番！",
        ),
    )
    assert r3.ok, r3.message
    print("combat narrative:", r3.message)

    # 日终
    r4 = c.actions.handle(sid, ActionRequest(type=ActionType.END_DAY))
    assert r4.session.day >= 2

    # 危机 tick：强制 countdown 0 且未解咒 → 异变
    s3 = r4.session
    s3.world_flags["xuanyin_countdown"] = 0
    s3.world_flags["blood_curse_planted"] = True
    s3.world_flags.pop("crisis_fired", None)
    s3.world_flags.pop("blood_curse_disarmed", None)
    s3.world_flags.pop("sect_stabilized", None)
    s3.world_flags.pop("crisis_averted_noted", None)
    c.repo.save(s3)
    r5 = c.actions.handle(sid, ActionRequest(type=ActionType.END_DAY))
    assert any("护山" in e.title or "crisis" in (e.tags or []) for e in r5.session.events), [
        e.title for e in r5.session.events[-5:]
    ]

    # 有为：已解咒时同一节点 → 化险为夷，不发悲剧危机
    s_ok = c.factory.create("luoxia")
    c.repo.save(s_ok)
    sid_ok = s_ok.session_id
    s_ok = c.repo.get(sid_ok)
    assert s_ok
    s_ok.world_flags["xuanyin_countdown"] = 0
    s_ok.world_flags["blood_curse_planted"] = True
    s_ok.world_flags["blood_curse_disarmed"] = True
    s_ok.world_flags.pop("crisis_fired", None)
    s_ok.world_flags.pop("crisis_averted_noted", None)
    c.repo.save(s_ok)
    r_ok = c.actions.handle(sid_ok, ActionRequest(type=ActionType.END_DAY))
    assert any("化险" in e.title for e in r_ok.session.events), [
        e.title for e in r_ok.session.events[-8:]
    ]
    assert not any(e.title == "护山异变" for e in r_ok.session.events), "disarmed should not fire tragedy"

    # 探索：假信 + 解咒（藏经阁）
    s6 = c.factory.create("luoxia")
    c.repo.save(s6)
    sid6 = s6.session_id
    for loc in ("square", "library"):
        c.actions.handle(sid6, ActionRequest(type=ActionType.MOVE, location_id=loc))
    r6 = c.actions.handle(
        sid6,
        ActionRequest(
            type=ActionType.TALK,
            target_id="cang_jing_guan",
            utterance="这封密信是假信骗局，旧录可有血阴阵眼解咒之法？",
        ),
    )
    assert r6.ok
    # 再解咒
    r7 = c.actions.handle(
        sid6,
        ActionRequest(
            type=ActionType.TALK,
            target_id="cang_jing_guan",
            utterance="请助我破阵解咒，镇压血阴！",
        ),
    )
    s7 = r7.session
    print(
        "investigate",
        "letter",
        s7.world_flags.get("letter_exposed"),
        "disarm",
        s7.world_flags.get("blood_curse_disarmed"),
        "evidence",
        s7.states["player"].flags.get("evidence_level"),
    )
    assert s7.states["player"].cultivation.get("realm") == "炼气"
    assert s7.states["ke_qing_yin"].cultivation.get("realm") == "筑基"

    # 持久化字段（同进程）
    loaded = c.repo.get(sid)
    assert loaded is not None
    # sqlite 跨进程：单独测
    from app.infra.sqlite_repo import SqliteSessionRepository
    import tempfile
    from pathlib import Path

    db = Path(tempfile.gettempdir()) / "luoxia_smoke.db"
    if db.exists():
        db.unlink()
    repo = SqliteSessionRepository(db)
    repo.save(loaded)
    loaded2 = repo.get(sid)
    assert loaded2 is not None and loaded2.day == loaded.day
    print("OK smoke", "events", len(loaded.events), "day", loaded.day, "sqlite ok")


if __name__ == "__main__":
    main()
