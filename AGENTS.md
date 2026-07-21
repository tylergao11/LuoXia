# Agent 约定

## 禁止

- **自动化测试**：禁止新建 `backend/tests`、`test_*.py`、pytest/jest 等套件与夹具。
- **冒烟脚本**：禁止恢复 `scripts/smoke.py` 或同类「假测试」。
- **垃圾文档**：禁止新建临时 plan、试玩备忘、重复启动说明、session 草稿文档。  
  需要写清的事 → 改下面「保留文档」之一，不要另开文件。

## 验证

- 手玩本地服务
- `GET /api/health`

## 保留文档（仅此）

| 路径 | 职责 |
|------|------|
| `README.md` | 项目入口、启动、能力表 |
| `AGENTS.md` | 本约定 |
| `docs/architecture.md` | 引擎硬契约（无剧情） |
| `docs/luoxia.md` | 落霞内容真相源（无引擎实现细节） |

改边界 → 同步 `architecture.md`。  
改落霞设定 → 同步 `docs/luoxia.md` 与 `content/luoxia/`。

## 架构纪律（摘要）

- 引擎不 import 内容包；内容钩子只回 ContentPacket，经 `apply_packet` 落地。
- 客户端只消费 SessionView DTO，不按 `world_id` 写剧情分支。
