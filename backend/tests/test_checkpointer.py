"""图 checkpointer：状态仅为简单类型时可安全开启。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.container import get_container
from app.core.domain.enums import ActionType, GamePhase
from app.core.domain.models import ActionRequest


@pytest.fixture()
def container(tmp_path, monkeypatch):
    get_container.cache_clear()
    from app import config

    config.settings.session_store = "memory"
    config.settings.use_llm = False
    config.settings.use_graph_checkpointer = True
    config.settings.graph_checkpoint_path = str(tmp_path / "ckpt.sqlite")
    get_container.cache_clear()
    c = get_container()
    yield c
    get_container.cache_clear()


def test_talk_with_checkpointer(container):
    assert container.actions._checkpointer is not None
    s = container.factory.create("luoxia")
    container.repo.save(s)
    r = container.actions.handle(
        s.session_id,
        ActionRequest(type=ActionType.TALK, target_id="ke_qing_yin", utterance="检查点测试"),
    )
    assert r.ok
    # 不应抛 msgpack 反序列化错误；会话仍可读
    s2 = container.repo.get(s.session_id)
    assert s2 is not None
    assert len(s2.events) >= 1


def _drain_night(container, session_id, max_steps=20):
    r = None
    for _ in range(max_steps):
        r = container.actions.handle(session_id, ActionRequest(type=ActionType.END_DAY))
        assert r.ok
        if r.session.phase != GamePhase.WORLD_EVOLVE:
            return r
    return r


def test_end_day_with_checkpointer(container):
    s = container.factory.create("luoxia")
    container.repo.save(s)
    r = _drain_night(container, s.session_id)
    assert r.ok
    assert r.session.day >= 2
    assert r.session.phase == GamePhase.PLAYER_TURN
    assert r.session.evolve_queue == []


def test_resume_mid_evolve(container):
    s = container.factory.create("luoxia")
    s.phase = GamePhase.WORLD_EVOLVE
    s.evolve_queue = ["da_shi_xiong", "er_shi_xiong", "shi_mei"]
    s.evolve_index = 1
    container.repo.save(s)
    r = _drain_night(container, s.session_id)
    assert r.ok
    assert r.session.evolve_queue == []
