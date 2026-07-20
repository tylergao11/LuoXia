"""自动化测试：引擎通用规则 + 落霞内容钩子。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.container import get_container
from app.content.luoxia import LuoxiaWorldPack
from app.content.luoxia import shi_mei_arc
from app.core.domain.enums import ActionType, BeliefSource, TruthRel
from app.core.domain.models import ActionRequest, Belief
from app.core.services.crisis import CrisisTick
from app.core.services.rumor import RumorPass


@pytest.fixture()
def container(tmp_path, monkeypatch):
    get_container.cache_clear()
    monkeypatch.setenv("SESSION_STORE", "memory")
    monkeypatch.setenv("USE_LLM", "false")
    monkeypatch.setenv("USE_GRAPH_CHECKPOINTER", "false")
    # reload settings - Settings reads env at init; clear and re-get
    from app import config

    config.settings.session_store = "memory"
    config.settings.use_llm = False
    config.settings.use_graph_checkpointer = False
    get_container.cache_clear()
    c = get_container()
    yield c
    get_container.cache_clear()


def test_worlds_registered(container):
    ids = {w["world_id"] for w in container.registry.list_worlds()}
    assert "luoxia" in ids and "qingxi" in ids


def test_onboarding_event(container):
    s = container.factory.create("luoxia")
    assert any("guide" in (e.tags or []) for e in s.events)
    assert any(b.belief_id == "guide_day1" for b in s.beliefs.get("player", []))


def test_move_and_talk(container):
    s = container.factory.create("luoxia")
    container.repo.save(s)
    r = container.actions.handle(
        s.session_id,
        ActionRequest(type=ActionType.TALK, target_id="ke_qing_yin", utterance="请多指教"),
    )
    assert r.ok
    assert r.session.ap < 6 or r.session.day > 1


def test_rumor_delay_and_hop(container):
    s = container.factory.create("luoxia")
    s.day = 3
    s.states["huo_fang_tou"].location = "kitchen"
    s.states["ke_qing_yin"].location = "kitchen"
    # 新鲜见闻：planted 今天 → 延迟不足
    s.beliefs["huo_fang_tou"] = [
        Belief(
            belief_id="fresh",
            holder_id="huo_fang_tou",
            proposition="一定有内鬼",
            source=BeliefSource.RUMOR,
            day=3,
            planted_day=3,
            hop=0,
        )
    ]
    ev0 = RumorPass(delay_days=1).run(s)
    assert ev0 == [] or all("一定有内鬼" not in (e.card_body or "") for e in ev0)

    # 过期可传
    s.beliefs["huo_fang_tou"][0].planted_day = 1
    s.beliefs["huo_fang_tou"][0].day = 1
    s.beliefs["huo_fang_tou"][0].next_spread_day = None
    ev1 = RumorPass(delay_days=1, max_hops=3).run(s)
    assert len(ev1) >= 1
    # 接收者 hop=1
    recv_beliefs = [
        b
        for aid, bl in s.beliefs.items()
        if aid != "huo_fang_tou"
        for b in bl
        if b.hop >= 1
    ]
    assert recv_beliefs


def test_crisis_averted_vs_tragedy(container):
    s = container.factory.create("luoxia")
    s.world_flags["xuanyin_countdown"] = 0
    s.world_flags["blood_curse_planted"] = True
    s.world_flags["blood_curse_disarmed"] = True
    s.world_flags.pop("crisis_averted_noted", None)
    s.world_flags.pop("crisis_fired", None)
    ev = CrisisTick().run(s)
    assert any("化险" in e.title for e in ev)
    assert not any(e.title == "护山异变" for e in ev)

    s2 = container.factory.create("luoxia")
    s2.world_flags["xuanyin_countdown"] = 0
    s2.world_flags["blood_curse_planted"] = True
    s2.world_flags.pop("blood_curse_disarmed", None)
    s2.world_flags.pop("sect_stabilized", None)
    s2.world_flags.pop("crisis_fired", None)
    ev2 = CrisisTick().run(s2)
    assert any(e.title == "护山异变" for e in ev2)


def test_shi_mei_arc(container):
    s = container.factory.create("luoxia")
    st = s.states["shi_mei"]
    st.flags["trust_player"] = 3
    st.flags["trusts_player"] = True
    out = shi_mei_arc.advance_on_dialogue(s, utterance="你可以信我")
    assert out.get("events") or st.flags.get("arc_shi_mei_hint") or st.flags.get(
        "arc_shi_mei_warming"
    )


def test_session_persist_fields(container):
    s = container.factory.create("luoxia")
    s.evolve_queue = ["da_shi_xiong", "er_shi_xiong"]
    s.evolve_index = 1
    container.repo.save(s)
    s2 = container.repo.get(s.session_id)
    assert s2 is not None
    assert s2.evolve_queue == ["da_shi_xiong", "er_shi_xiong"]
    assert s2.evolve_index == 1


def _drain_night(container, session_id, max_steps=20):
    """方案 D：入夜步进，循环至离开 WORLD_EVOLVE。"""
    r = None
    for _ in range(max_steps):
        r = container.actions.handle(session_id, ActionRequest(type=ActionType.END_DAY))
        assert r.ok
        if r.session.phase.value != "WORLD_EVOLVE":
            return r
    return r


def test_end_day_clears_evolve(container):
    s = container.factory.create("luoxia")
    container.repo.save(s)
    r = _drain_night(container, s.session_id)
    assert r.session.phase.value == "PLAYER_TURN" or r.session.day >= 2
    assert r.session.evolve_queue == []


def test_end_day_one_step_stays_or_finishes(container):
    """单次 end_day 只推一步（或空队直接收日），不一次跑完全图。"""
    s = container.factory.create("luoxia")
    container.repo.save(s)
    day0 = s.day
    r = container.actions.handle(s.session_id, ActionRequest(type=ActionType.END_DAY))
    assert r.ok
    if r.session.phase.value == "WORLD_EVOLVE":
        assert r.session.evolve_queue
        assert r.session.evolve_index >= 1
        assert r.session.day == day0
    else:
        # 队空则同请求收日
        assert r.session.day >= day0 + 1
        assert r.session.evolve_queue == []


def test_talk_graph_session_id_only(container):
    """图只碰 session_id，结果从 repo 读回。"""
    s = container.factory.create("luoxia")
    container.repo.save(s)
    r = container.actions.handle(
        s.session_id,
        ActionRequest(type=ActionType.TALK, target_id="ke_qing_yin", utterance="你好"),
    )
    assert r.ok
    s2 = container.repo.get(s.session_id)
    assert s2 is not None
    assert len(s2.events) >= 1


def test_evolve_resume_fields(container):
    s = container.factory.create("luoxia")
    s.phase = __import__("app.core.domain.enums", fromlist=["GamePhase"]).GamePhase.WORLD_EVOLVE
    s.evolve_queue = ["da_shi_xiong", "er_shi_xiong", "shi_mei"]
    s.evolve_index = 1
    container.repo.save(s)
    # 单步只推进一人
    r = container.actions.handle(s.session_id, ActionRequest(type=ActionType.END_DAY))
    assert r.ok
    assert r.session.phase.value == "WORLD_EVOLVE"
    assert r.session.evolve_index == 2
    # 抽干夜色
    r2 = _drain_night(container, s.session_id)
    assert r2.session.evolve_queue == []
    assert r2.session.phase.value in ("PLAYER_TURN", "MONTH_END", "GAME_OVER")
