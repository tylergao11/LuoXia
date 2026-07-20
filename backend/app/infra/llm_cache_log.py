"""
上下文缓存命中日志与累计统计。

DeepSeek 磁盘 KV 缓存默认开启；响应 usage 含：
  - prompt_cache_hit_tokens
  - prompt_cache_miss_tokens

DeepSeek 磁盘 KV：cache prefix unit 整段匹配（非 OpenAI 显式 cache block）。
多轮 A+B 后 A+B+C 可命中；中间改写前缀会断命中。

优化原则：
  1. system 极稳
  2. STABLE 区（背景/人设/地图）字节不变
  3. 动态只 append（多轮 messages 或 diff 日志）
  4. 本轮材料在最末 user
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("luoxia.llm.cache")

_lock = threading.Lock()
_stats: dict[str, Any] = {
    "calls": 0,
    "hit_tokens": 0,
    "miss_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "by_tag": {},  # tag -> {calls, hit, miss}
    "last": None,
}


def _prefix_hash(text: str, n: int = 240) -> str:
    chunk = (text or "")[:n].encode("utf-8", errors="ignore")
    return hashlib.sha1(chunk).hexdigest()[:10]


def record_usage(
    *,
    tag: str,
    model: str,
    system: str,
    user: str,
    usage: dict[str, Any] | None,
    latency_ms: float,
    path: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """记录一次调用的缓存命中，返回本条 meta（便于 last_meta / health）。"""
    usage = usage or {}
    hit = int(usage.get("prompt_cache_hit_tokens") or usage.get("cache_read_input_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    # 部分实现只给 prompt_tokens，用 hit+miss 反推
    if prompt <= 0 and (hit or miss):
        prompt = hit + miss
    if miss <= 0 and prompt > 0 and hit >= 0:
        miss = max(0, prompt - hit)

    total_in = hit + miss if (hit or miss) else prompt
    ratio = (hit / total_in) if total_in > 0 else None

    meta = {
        "tag": tag,
        "model": model,
        "path": path,
        "latency_ms": round(latency_ms, 1),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "cache_hit_ratio": round(ratio, 4) if ratio is not None else None,
        "system_len": len(system or ""),
        "user_len": len(user or ""),
        "system_prefix_hash": _prefix_hash(system or ""),
        "user_prefix_hash": _prefix_hash(user or ""),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if extra:
        for k in (
            "stable_len",
            "memory_len",
            "dynamic_len",
            "messages_count",
            "expected_hit_mode",
            "thread_key",
        ):
            if k in extra:
                meta[k] = extra[k]

    with _lock:
        _stats["calls"] += 1
        _stats["hit_tokens"] += hit
        _stats["miss_tokens"] += miss
        _stats["prompt_tokens"] += prompt
        _stats["completion_tokens"] += completion
        bucket = _stats["by_tag"].setdefault(
            tag, {"calls": 0, "hit_tokens": 0, "miss_tokens": 0, "prompt_tokens": 0}
        )
        bucket["calls"] += 1
        bucket["hit_tokens"] += hit
        bucket["miss_tokens"] += miss
        bucket["prompt_tokens"] += prompt
        _stats["last"] = meta

    ratio_s = f"{ratio:.1%}" if ratio is not None else "n/a"
    logger.info(
        "[cache] tag=%s model=%s hit=%s miss=%s ratio=%s prompt=%s out=%s latency_ms=%.0f sys_h=%s usr_h=%s path=%s",
        tag,
        model,
        hit,
        miss,
        ratio_s,
        prompt,
        completion,
        latency_ms,
        meta["system_prefix_hash"],
        meta["user_prefix_hash"],
        path,
    )
    return meta


def snapshot() -> dict[str, Any]:
    with _lock:
        calls = _stats["calls"]
        hit = _stats["hit_tokens"]
        miss = _stats["miss_tokens"]
        total = hit + miss
        return {
            "calls": calls,
            "hit_tokens": hit,
            "miss_tokens": miss,
            "prompt_tokens": _stats["prompt_tokens"],
            "completion_tokens": _stats["completion_tokens"],
            "cache_hit_ratio": round(hit / total, 4) if total else None,
            "by_tag": {k: dict(v) for k, v in _stats["by_tag"].items()},
            "last": dict(_stats["last"]) if _stats["last"] else None,
        }


def reset() -> None:
    with _lock:
        _stats["calls"] = 0
        _stats["hit_tokens"] = 0
        _stats["miss_tokens"] = 0
        _stats["prompt_tokens"] = 0
        _stats["completion_tokens"] = 0
        _stats["by_tag"] = {}
        _stats["last"] = None
