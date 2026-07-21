from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "落霞宗"
    max_days: int = 21
    daily_ap: int = 6
    move_ap_cost: int = 1
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    # LLM：默认 DeepSeek（OpenAI 兼容）；本地可改回 Ollama
    llm_api_key: str = "ollama"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-flash"
    # 必须为 true；false 也不会再走任何非 LLM 玩法兜底
    use_llm: bool = True
    # 速度：关思考、限生成、探活缓存、并行意图
    llm_think: bool = False
    llm_timeout: float = 90.0
    llm_num_predict_default: int = 480
    llm_num_predict_reply: int = 360
    llm_num_predict_intend: int = 220
    llm_num_predict_night_batch: int = 900
    llm_num_predict_adjudicate: int = 480
    llm_num_predict_dialogue: int = 520
    llm_available_cache_sec: float = 30.0
    llm_parallel_workers: int = 4
    evolve_max_npcs: int = 5
    # 上下文缓存命中日志（DeepSeek: prompt_cache_hit/miss_tokens）
    llm_cache_log: bool = True

    session_store: str = "sqlite"
    sqlite_path: str = str(_BACKEND_ROOT / "data" / "luoxia.db")

    # 图状态仅为简单类型后，可安全默认开启
    graph_checkpoint_path: str = str(_BACKEND_ROOT / "data" / "graph_ckpt.sqlite")
    use_graph_checkpointer: bool = True


settings = Settings()
