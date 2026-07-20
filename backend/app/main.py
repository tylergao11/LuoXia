from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.schemas import ActionBody, CreateGameBody
from app.api.views import to_session_view
from app.config import settings
from app.container import get_container
from app.core.domain.models import ActionRequest
from app.infra import llm_cache_log

# 控制台可见 LLM / 缓存命中日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logging.getLogger("luoxia.llm").setLevel(logging.INFO)
logging.getLogger("luoxia.llm.cache").setLevel(logging.INFO)

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    c = get_container()
    ollama_ok = False
    ollama_models: list[str] = []
    if "11434" in settings.llm_base_url or "ollama" in settings.llm_base_url.lower():
        try:
            import httpx

            base = settings.llm_base_url.replace("/v1", "").rstrip("/")
            with httpx.Client(timeout=1.5) as client:
                r = client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    ollama_ok = True
                    data = r.json()
                    ollama_models = [m.get("name", "") for m in data.get("models") or []]
        except Exception:
            ollama_ok = False

    llm = getattr(c, "llm", None)
    last_meta = getattr(llm, "last_meta", None) or {}
    return {
        "ok": True,
        "app": settings.app_name,
        "llm_mode": c.llm_mode,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
        "use_llm": settings.use_llm,
        "llm_think": settings.llm_think,
        "llm_provider": (
            "deepseek"
            if getattr(llm, "is_deepseek", False)
            else ("ollama" if getattr(llm, "is_ollama", False) else "openai")
        ),
        "llm_reachable": bool(getattr(llm, "available", False)),
        "llm_last": last_meta,
        "llm_cache": llm_cache_log.snapshot(),
        "ollama_ok": ollama_ok,
        "ollama_models": ollama_models,
        "store_mode": c.store_mode,
        "graph_checkpointer": bool(getattr(c.actions, "_checkpointer", None)),
    }


@app.get("/api/games")
def list_games(limit: int = 20):
    c = get_container()
    return {"games": c.repo.list_meta(limit=limit)}


@app.get("/api/worlds")
def list_worlds():
    c = get_container()
    return {"worlds": c.registry.list_worlds()}


@app.post("/api/games")
def create_game(body: CreateGameBody):
    c = get_container()
    try:
        session = c.factory.create(body.world_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    c.repo.save(session)
    return {"session": to_session_view(session).model_dump()}


@app.get("/api/games/{session_id}")
def get_game(session_id: str):
    c = get_container()
    session = c.repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session": to_session_view(session).model_dump()}


@app.post("/api/games/{session_id}/actions")
def post_action(session_id: str, body: ActionBody):
    c = get_container()
    req = ActionRequest(
        type=body.type,
        target_id=body.target_id,
        location_id=body.location_id,
        utterance=body.utterance,
        payload=body.payload,
    )
    result = c.actions.handle(session_id, req)
    if not result.ok and result.error_code == "NO_SESSION":
        raise HTTPException(status_code=404, detail=result.message)
    adj_src = getattr(c.adjudicator, "last_source", None)
    return {
        "ok": result.ok,
        "message": result.message,
        "error_code": result.error_code,
        "npc_utterance": result.npc_utterance,
        "new_events": [e.model_dump(mode="json") for e in (result.new_events or [])],
        "effects": result.effects or {},
        "session": to_session_view(result.session).model_dump() if result.session else None,
        "adjudicator_source": adj_src,
        "llm_mode": c.llm_mode,
    }


@app.get("/")
def root():
    return {
        "name": settings.app_name,
        "docs": "/docs",
        "architecture": {
            "core": "domain + ports + services",
            "content": "WorldPack plugins (luoxia, ...)",
            "infra": "repo / adjudicator / mind adapters",
        },
    }
