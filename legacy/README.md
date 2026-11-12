# legacy/ — 已退役入口（仅留档）

这里的文件不参与日常流程，也不要再往这里加新功能。
保留原因：历史记录 + 万一需要对照旧行为。

| 文件 | 原用途 | 为什么退役 |
|------|--------|-----------|
| `chat.py` | 最早的终端对话实现 | 已被 `chat_v2.py` + `ascend_cli.py chat` 取代 |
| `test_chat.py` | 旧对话的手工测试脚本 | 已被 `tests/` 下的自动化回归取代 |
| `chat_v2.bat` | 启动 `chat_v2.py` 独立对话 | 主流程走 `start-reviewagent.bat`；原脚本还硬编码了 `D:\Agent-ReviewAgent` |
| `run_test.bat` | 手动跑 `smart_reviewer.py` | 同上，路径硬编码；测试请用 `python -m unittest discover -s tests` |
| `diagnose.bat` | 旧环境诊断 | 检查的是已退役文件；环境自检请用 `python ascend_cli.py doctor` |

## 现在应该用什么

| 想做的事 | 用这个 |
|----------|--------|
| 打开桌面版 | 根目录 `启动桌面版.bat` |
| 打开终端 Agent | 根目录 `start-reviewagent.bat` |
| 环境自检 | `python ascend_cli.py doctor` |
| 边框/宽度体检 | `launchers/start-framecheck.bat` |
| 跑测试 | `python -m unittest discover -s tests` |

> 这些旧脚本里的路径已改成相对路径（`%~dp0..`），所以移动整个仓库后仍能用，
> 但不再保证与当前 CLI 参数兼容。
