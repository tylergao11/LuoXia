# 本地试玩清单

## 当前模型

- **主模型**：Ollama `qwen3:8b`
- 配置：`backend/.env`
- Ollama 在线且模型已装时：天道/NPC 走 LLM（强制 JSON）
- 连不上时：自动 Mock，不崩

## 启动（两个终端）

```powershell
# 终端 1：确认 Ollama
ollama serve
# 已有 qwen3:8b 可跳过 pull

# 终端 2：后端
cd C:\Ai\LuoXia\backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# 终端 3：前端
cd C:\Ai\LuoXia\frontend
npm run dev
```

浏览器打开：**http://localhost:5173**  
建议 F12 → 设备工具栏 → **390×844** 竖屏。

## 开局页应看到

- 存储 sqlite · 图检查点 开 · 强制 JSON 是  
- Ollama 在线 (`qwen3:8b` …)  
- 裁决会显示 `llm` 或失败时 `mock_fallback`

## 建议第一局测什么（10 分钟）

1. **落霞宗** 新开一局 → 看「客卿须知」与帮助  
2. **人物** → 白问舟 → 对话「请多指教」  
3. **地图** → 落霞广场 → 执法堂 → 沈监察  
4. 对沈监察：「请长老通告：近日严查细作」  
5. 藏经阁找明镜：假信 / 解咒相关话  
6. 后山找洛晴：多次「你可以信我」  
7. **结束今天** → 看世界事件 / 传谣  
8. 刷新页 → **继续上次** 是否还在  

## 强制 Mock（对照）

`.env` 里设 `USE_LLM=false`，重启后端。

## 自检命令

```powershell
cd C:\Ai\LuoXia\backend
python -m pytest tests -q
python scripts\smoke.py
curl http://127.0.0.1:8000/api/health
```
