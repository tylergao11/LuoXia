from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from app.config import settings


@lru_cache
def get_sqlite_checkpointer():
    """
    LangGraph Sqlite 检查点。
    thread_id 建议用 session_id 或 session_id:talk / session_id:evolve。
    """
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    path = Path(settings.graph_checkpoint_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # SqliteSaver 需要持久 connection；用 check_same_thread=False 供 FastAPI 线程
    conn = sqlite3.connect(str(path), check_same_thread=False)
    return SqliteSaver(conn)


def talk_thread_id(session_id: str) -> str:
    return f"{session_id}:talk"
