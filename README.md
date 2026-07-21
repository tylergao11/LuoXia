# LuoXia · 落霞引擎

事件驱动世界模拟：**引擎与内容分离**。落霞宗是第一个世界包，不是引擎本身。

## 文档

| 文档 | 内容 |
|------|------|
| [docs/architecture.md](docs/architecture.md) | 引擎分层与硬契约 |
| [docs/luoxia.md](docs/luoxia.md) | 落霞世界包设定（内容真相源） |
| [AGENTS.md](AGENTS.md) | Agent 约定（禁测试 / 文档纪律） |

```
backend/app/
  core/      领域 · 端口 · 服务 · 图
  content/   luoxia · qingxi · …
  infra/     存档 · Mock/LLM
  api/       HTTP DTO（可换 3D 网关）
frontend/    Web 试玩壳
```

## 本地启动

推荐本机 Ollama **`qwen3:8b`**。

```powershell
# 可选一键
powershell -File scripts/run_local.ps1
```

手动：

```powershell
# 终端 1：模型
ollama serve

# 终端 2：API
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # USE_LLM + Ollama 默认
uvicorn app.main:app --reload --port 8000

# 终端 3：前端
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173  

### Mock（不调模型）

`backend/.env`：

```env
USE_LLM=false
```

### LLM（Ollama）

```env
USE_LLM=true
LLM_API_KEY=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3:8b
```

`/api/health`：模型是否在线、JSON 模式、检查点等。

## 能力一览

| 能力 | 说明 |
|------|------|
| 双轨因果 | 无为走劫数 / 有为改 flags |
| WorldPack | 换世界 = 注册内容包 |
| 同构事件包 | 线索/意图/钩子统一落地 |
| 传谣 | 延迟、跳数、失真 |
| 多客户端 | SessionView DTO；Web 可换 3D |
