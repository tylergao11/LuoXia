from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

import httpx

from app.config import settings
from app.infra import llm_cache_log

logger = logging.getLogger("luoxia.llm")

# 稳定 JSON 硬性尾缀：固定字符串利于 DeepSeek 前缀缓存
_JSON_HARD_TAIL = (
    "\n\n【硬性】只输出一个合法 JSON 对象。"
    "不要 markdown、不要思考过程、不要解释。"
    "首字符 { ，末字符 } 。"
)
_JSON_USER_TAIL = "\n\n直接输出 JSON。"


class LLMClient:
    """
    OpenAI 兼容 Chat（DeepSeek 主路径）/ Ollama 原生 Chat。
    DeepSeek：磁盘上下文缓存默认开启；从 usage 打 cache hit 日志。
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.timeout = float(timeout if timeout is not None else settings.llm_timeout)
        self._avail_lock = threading.Lock()
        self._avail_cache: tuple[float, bool] | None = None
        self._avail_ttl = float(settings.llm_available_cache_sec)
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()
        self.call_count = 0
        self.last_meta: dict[str, Any] = {}

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _http(self) -> httpx.Client:
        with self._client_lock:
            if self._client is None or self._client.is_closed:
                self._client = httpx.Client(
                    timeout=self.timeout,
                    limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
                )
            return self._client

    @property
    def ollama_root(self) -> str:
        return self.base_url.replace("/v1", "").rstrip("/")

    @property
    def is_ollama(self) -> bool:
        return "11434" in self.base_url or "ollama" in self.base_url.lower()

    @property
    def is_deepseek(self) -> bool:
        return "deepseek" in self.base_url.lower() or "deepseek" in (self.model or "").lower()

    @property
    def available(self) -> bool:
        if not (self.api_key and self.api_key.strip()):
            return False
        if self.api_key.strip() in ("ollama", "none", "mock"):
            # 仅本地 ollama 哨兵；DeepSeek key 正常
            if self.is_ollama:
                return self._probe_cached()
            return False
        if self.is_ollama:
            return self._probe_cached()
        # DeepSeek / 远程：有 key 即认为可试；失败再回落
        return True

    def _probe_cached(self) -> bool:
        now = time.monotonic()
        with self._avail_lock:
            if self._avail_cache is not None:
                ts, ok = self._avail_cache
                if now - ts < self._avail_ttl:
                    return ok
        ok = self._probe()
        with self._avail_lock:
            self._avail_cache = (now, ok)
        return ok

    def invalidate_available(self) -> None:
        with self._avail_lock:
            self._avail_cache = None

    def _probe(self) -> bool:
        if self.is_ollama:
            try:
                r = self._http().get(self.ollama_root + "/api/tags", timeout=1.5)
                return r.status_code == 200
            except Exception:
                return False
        return True

    def chat_json(
        self,
        *,
        system: str,
        user: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        tag: str = "generic",
        messages: list[dict[str, str]] | None = None,
        prompt_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        messages: 可选多轮（仅 user/assistant），system 单独传入。
        用于 DeepSeek 多轮前缀命中：历史 messages 必须字节级复用。
        """
        if not self.available:
            raise RuntimeError("LLM API key 未配置或服务不可用")

        max_tokens = int(max_tokens or settings.llm_num_predict_default)
        system_forced = system.rstrip() + _JSON_HARD_TAIL
        # 关思考：Ollama 用 /no_think；DeepSeek 用 API thinking.disabled（见 _complete_openai）
        if not settings.llm_think:
            if self.is_ollama:
                system_forced += "\n/no_think"
            elif self.is_deepseek:
                system_forced += "\n【速度】禁止思考链；禁止 reasoning；只吐最终 JSON。"

        if messages is not None:
            # 多轮：不改历史；仅给最后一条 user 补 JSON 尾（若还没有）
            api_msgs = [dict(m) for m in messages]
            if api_msgs and api_msgs[-1].get("role") == "user":
                c = api_msgs[-1].get("content") or ""
                if _JSON_USER_TAIL.strip() not in c[-40:]:
                    api_msgs[-1]["content"] = c + _JSON_USER_TAIL
            user_for_log = api_msgs[-1]["content"] if api_msgs else ""
            try:
                content = self._complete_messages(
                    system_forced,
                    api_msgs,
                    temperature,
                    max_tokens,
                    tag=tag,
                    prompt_metrics=prompt_metrics,
                )
                return parse_json_object(content)
            except Exception as e:
                logger.warning("[llm] chat_json multi fail tag=%s err=%s ; retry", tag, e)
                content = self._complete_messages(
                    "只输出合法 JSON 对象，无其它字符。\n" + system_forced,
                    api_msgs,
                    min(temperature, 0.1),
                    max_tokens,
                    tag=f"{tag}:retry",
                    prompt_metrics=prompt_metrics,
                )
                return parse_json_object(content)

        if user is None:
            raise ValueError("user or messages required")
        user_forced = user + _JSON_USER_TAIL
        try:
            content = self._complete(
                system_forced,
                user_forced,
                temperature,
                max_tokens,
                tag=tag,
                prompt_metrics=prompt_metrics,
            )
            return parse_json_object(content)
        except Exception as e:
            logger.warning("[llm] chat_json fail tag=%s err=%s ; retry", tag, e)
            content = self._complete(
                "只输出合法 JSON 对象，无其它字符。\n" + system_forced,
                user_forced + "\n再次强调：仅 JSON。",
                min(temperature, 0.1),
                max_tokens,
                tag=f"{tag}:retry",
                prompt_metrics=prompt_metrics,
            )
            return parse_json_object(content)

    def _complete(
        self,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        *,
        tag: str = "generic",
        prompt_metrics: dict[str, Any] | None = None,
    ) -> str:
        self.call_count += 1
        msgs = [{"role": "user", "content": user}]
        if self.is_ollama:
            return self._complete_ollama_native(
                system, msgs, temperature, max_tokens, tag=tag, prompt_metrics=prompt_metrics
            )
        return self._complete_openai(
            system, msgs, temperature, max_tokens, tag=tag, prompt_metrics=prompt_metrics
        )

    def _complete_messages(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        *,
        tag: str = "generic",
        prompt_metrics: dict[str, Any] | None = None,
    ) -> str:
        self.call_count += 1
        if self.is_ollama:
            return self._complete_ollama_native(
                system, messages, temperature, max_tokens, tag=tag, prompt_metrics=prompt_metrics
            )
        return self._complete_openai(
            system, messages, temperature, max_tokens, tag=tag, prompt_metrics=prompt_metrics
        )

    def _complete_ollama_native(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        *,
        tag: str = "generic",
        prompt_metrics: dict[str, Any] | None = None,
    ) -> str:
        url = f"{self.ollama_root}/api/chat"
        full_msgs = [{"role": "system", "content": system}, *messages]
        body: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": full_msgs,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        body["think"] = bool(settings.llm_think)
        think_flag = bool(body.get("think"))
        t0 = time.perf_counter()
        client = self._http()
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        latency = (time.perf_counter() - t0) * 1000
        msg = data.get("message") or {}
        content = msg.get("content") or ""
        thinking = msg.get("thinking") or msg.get("reasoning") or ""
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        user_blob = "\n".join(m.get("content") or "" for m in messages)
        meta = {
            "path": "ollama_native_/api/chat",
            "think_sent": think_flag,
            "json_forced": True,
            "content_len": len(str(content)),
            "thinking_len": len(str(thinking)),
            "think_leaked": bool(str(thinking).strip()) and not think_flag,
            "model": self.model,
            "tag": tag,
            "messages_count": len(full_msgs),
        }
        if prompt_metrics:
            meta.update(prompt_metrics)
        if settings.llm_cache_log:
            cache_meta = llm_cache_log.record_usage(
                tag=tag,
                model=self.model,
                system=system,
                user=user_blob,
                usage=usage,
                latency_ms=latency,
                path=meta["path"],
                extra=prompt_metrics,
            )
            meta.update(cache_meta)
        self.last_meta = meta
        # 关思考时禁止用 thinking 字段顶替 JSON 正文
        if not str(content).strip():
            if think_flag and thinking:
                content = str(thinking)
                self.last_meta["fell_back_to_thinking_field"] = True
            else:
                content = ""
        return str(content)

    def _complete_openai(
        self,
        system: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        *,
        tag: str = "generic",
        prompt_metrics: dict[str, Any] | None = None,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        full_msgs = [{"role": "system", "content": system}, *messages]
        think_on = bool(settings.llm_think)
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "stream": False,
            "messages": full_msgs,
            "max_tokens": max_tokens,
            # 强制 JSON（DeepSeek / OpenAI 兼容）
            "response_format": {"type": "json_object"},
        }
        # DeepSeek 思考默认 enabled，必须显式关掉；其它兼容端点一并尝试
        body["thinking"] = {"type": "enabled" if think_on else "disabled"}

        t0 = time.perf_counter()
        client = self._http()
        resp = client.post(url, headers=headers, json=body)
        if resp.status_code >= 400:
            err_txt = (resp.text or "")[:500]
            logger.error(
                "[llm] openai fail status=%s tag=%s body=%s",
                resp.status_code,
                tag,
                err_txt,
            )
        resp.raise_for_status()
        data = resp.json()
        latency = (time.perf_counter() - t0) * 1000

        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content and isinstance(msg.get("parsed"), dict):
            content = json.dumps(msg["parsed"], ensure_ascii=False)

        reasoning_blob = ""
        for k in ("reasoning_content", "reasoning", "thinking"):
            if msg.get(k):
                reasoning_blob = str(msg.get(k) or "")
                break

        # 关思考：禁止用 reasoning 当正文
        fell_back = False
        if not str(content).strip():
            if think_on and reasoning_blob.strip():
                content = reasoning_blob
                fell_back = True
            else:
                content = ""

        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        details = usage.get("prompt_tokens_details") if isinstance(usage, dict) else None
        if isinstance(details, dict):
            if usage.get("prompt_cache_hit_tokens") is None and details.get("cached_tokens") is not None:
                usage = dict(usage)
                usage["prompt_cache_hit_tokens"] = int(details.get("cached_tokens") or 0)

        path = "deepseek_/chat/completions" if self.is_deepseek else "openai_/chat/completions"
        user_blob = "\n".join(m.get("content") or "" for m in messages)
        think_sent = body.get("thinking")
        meta: dict[str, Any] = {
            "path": path,
            "model": self.model,
            "tag": tag,
            "content_len": len(str(content)),
            "latency_ms": round(latency, 1),
            "messages_count": len(full_msgs),
            "think_sent": think_sent,
            "think_enabled": think_on,
            "json_forced": True,
            "reasoning_len": len(reasoning_blob),
            "think_leaked": bool(reasoning_blob.strip()) and not think_on,
            "fell_back_to_thinking_field": fell_back,
        }
        if prompt_metrics:
            meta.update(prompt_metrics)
        if settings.llm_cache_log:
            cache_meta = llm_cache_log.record_usage(
                tag=tag,
                model=self.model,
                system=system,
                user=user_blob,
                usage=usage,
                latency_ms=latency,
                path=path,
                extra=prompt_metrics,
            )
            meta.update(cache_meta)
        else:
            meta["usage"] = usage
        self.last_meta = meta
        logger.info(
            "[llm] done tag=%s model=%s latency_ms=%.0f msgs=%s content_len=%s "
            "think=%s reasoning_len=%s json=%s hit=%s miss=%s",
            tag,
            self.model,
            latency,
            len(full_msgs),
            len(str(content)),
            think_sent,
            len(reasoning_blob),
            meta.get("json_forced"),
            meta.get("prompt_cache_hit_tokens"),
            meta.get("prompt_cache_miss_tokens"),
        )
        return str(content)


def parse_json_object(text: str) -> dict[str, Any]:
    if not text or not str(text).strip():
        raise ValueError("empty model content")

    raw = str(text).strip()

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()

    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<thinking>[\s\S]*?</thinking>", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"<reasoning>[\s\S]*?</reasoning>", "", raw, flags=re.IGNORECASE)
    raw = raw.strip()

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
        raise ValueError("JSON root is not object")
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        chunk = raw[start : end + 1]
        obj = json.loads(chunk)
        if isinstance(obj, dict):
            return obj

    raise ValueError(f"cannot parse JSON from model output: {raw[:200]!r}")
