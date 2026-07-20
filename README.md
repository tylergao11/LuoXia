# 落霞宗 / LuoXia Engine

事件驱动世界模拟引擎 + 世界包「落霞宗」。**引擎与内容分离**。

## 架构

见 [docs/architecture.md](docs/architecture.md) · 本地 Qwen 见 [docs/qwen-local.md](docs/qwen-local.md)

```
core/     领域 · 端口 · 服务 · LangGraph(+Sqlite 检查点)
content/  luoxia · qingxi · 洛晴深度线
infra/    SQLite 存档 · Mock/LLM · Ollama 兼容
```

## 本地启动（推荐 Qwen3:8b）

你本机 Ollama 已有 **`qwen3:8b`**（首选）与 `qwen3-vl:8b`（视觉，游戏暂不用）。

```powershell
# 1. Ollama
ollama serve

# 2. 一键（测试 + API + 前端）
powershell -File scripts/run_local.ps1
```

或手动：

```powershell
cd backend
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # 默认已指向 Ollama qwen3:8b
uvicorn app.main:app --reload --port 8000

cd ..\frontend
npm install
npm run dev
```

打开 http://localhost:5173  

前端为 **竖版优先**（手机分辨率 / 桌面居中「手机框」max-width 430px，含安全区）。

### 强制 Mock（不调模型）

`.env` 设 `USE_LLM=false`

## 已具备

| 能力 | 说明 |
|------|------|
| 双轨因果 | 无为危局 / 有为改 flags（解咒→化险为夷） |
| Checkpointer | 图只存 id（可 msgpack）；`evolve_*` 每步落盘；默认可开 |
| 传谣 | 延迟、跳数、冷却、失真随 hop 加重 |
| 洛晴线 | 内容包阶段 trust→托付→同盟 |
| 测试 | `pytest tests` · `python scripts/smoke.py` |
| 多世界 | 落霞宗 / 青溪小驿 |

## 测试

```bash
cd backend
python -m pytest tests -q
python scripts/smoke.py
```

当前约 **15** 项自动化测试（含 checkpointer 开启路径）。

`/api/health` 可看：Ollama 是否在线、是否强制 JSON、图检查点是否开启。
