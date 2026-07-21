"""Teacher trajectory logger for Mini-LLM / distillation.

Only writes jsonl. Does not touch GameSession authority or ContentPacket.
Thread-safe append; one file per day + role.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("luoxia.llm.trace")

_lock = threading.Lock()


def _infer_role_task(tag: str) -> tuple[str, str]:
    t = (tag or "").strip()
    if t.startswith("mind:reply"):
        return "mind", "reply"
    if "night_batch" in t or "intend_night" in t:
        return "mind", "night_batch"
    if "intend" in t:
        return "mind", "intend"
    if "dialogue" in t:
        return "mind", "dialogue_turn"
    if t.startswith("adjudicate") or t.startswith("adj:"):
        return "adjudicator", "adjudicate"
    return "unknown", t or "generic"


def enabled() -> bool:
    return bool(getattr(settings, "llm_trace_enabled", False))


def trace_dir() -> Path:
    raw = getattr(settings, "llm_trace_dir", "") or ""
    if raw.strip():
        return Path(raw).expanduser()
    # default: backend/data/llm_traces
    return Path(__file__).resolve().parents[2] / "data" / "llm_traces"


def record(
    *,
    tag: str,
    system: str,
    messages: list[dict[str, str]],
    output: dict[str, Any],
    teacher_model: str,
    prompt_metrics: dict[str, Any] | None = None,
    call_meta: dict[str, Any] | None = None,
    role: str | None = None,
    task: str | None = None,
) -> Path | None:
    """Append one trainable sample. Returns path written or None if disabled."""
    if not enabled():
        return None

    r, t = _infer_role_task(tag)
    if role:
        r = role
    if task:
        t = task

    # Training messages: system + user/assistant turns as sent to the model API
    train_messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *[{"role": str(m.get("role")), "content": str(m.get("content") or "")} for m in messages],
    ]

    meta: dict[str, Any] = {
        "tag": tag,
        "teacher_model": teacher_model,
        "ok_schema": True,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if prompt_metrics:
        for k in (
            "thread_key",
            "world_id",
            "day",
            "phase",
            "actor_ids",
            "kind",
            "stable_chars",
            "dynamic_chars",
        ):
            if k in prompt_metrics:
                meta[k] = prompt_metrics[k]
    if call_meta:
        for k in ("latency_ms", "path", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
            if k in call_meta:
                meta[k] = call_meta[k]

    row = {
        "role": r,
        "task": t,
        "messages": train_messages,
        "output": output,
        "meta": meta,
    }

    day = datetime.now().strftime("%Y%m%d")
    out_dir = trace_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{day}_{r}.jsonl"
    line = json.dumps(row, ensure_ascii=False) + "\n"

    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    logger.info("[llm.trace] wrote role=%s task=%s path=%s", r, t, path)
    return path
