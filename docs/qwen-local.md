# 本地 Qwen 推荐配置

## 你机器上已有的模型（Ollama）

| 模型 | 用途 | 建议 |
|------|------|------|
| **qwen3:8b** | 文本对话/天道/NPC | **首选**：中文叙事与 JSON 结构化够用，8B 量化本机友好 |
| **qwen3-vl:8b** | 多模态视觉 | 本游戏暂无图像输入需求，**不必用于天道** |

## 推荐

**日常开发 / 试玩：`qwen3:8b`（Ollama）**

理由：
1. 已在本机安装，零下载成本  
2. 中文与指令跟随在 8B 档位里很强  
3. 支持 tools/thinking，后续可接更复杂工具调用  
4. 天道每次裁决要吐 JSON，8B 比更小模型稳定，比 32B 省显存  

若以后显存充裕、要更高叙事质量：再考虑 `qwen2.5:14b` / `qwen2.5:32b` 或云端 API。

## backend/.env

```env
USE_LLM=true
LLM_API_KEY=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=qwen3:8b
```

## 启动顺序

```powershell
# 1. Ollama（若未运行）
ollama serve

# 2. 确认模型
ollama list

# 3. 游戏
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# 4. 前端
cd frontend
npm run dev
```

或根目录：`powershell -File scripts/run_local.ps1`

## 仅 Mock（不调模型）

```env
USE_LLM=false
```

## 稳定性：强制 JSON 即可（已做）

1. 请求里 **`response_format: json_object`**，Ollama 另加 **`format: json`**  
2. 提示词硬性要求只输出 `{...}`  
3. 清洗 markdown / `<think>`  
4. 解析失败 **自动重试 1 次**  
5. 仍失败 → **Mock 回退**，不崩局  

对本地 Qwen，**强制 JSON 是主手段**，不必先上复杂 schema 流水线。

## 说明

- 游戏走 **OpenAI 兼容** `/v1/chat/completions`，Ollama 原生支持。  
- `LLM_API_KEY` 填任意非空字符串即可（如 `ollama`）。  
- 顶栏「裁决 llm / mock」可确认是否打到模型。  
