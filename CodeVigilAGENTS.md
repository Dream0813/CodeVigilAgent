# CodeVigil Agent — Agent 路由

| Agent | 何时用 |
|-------|--------|
| [cann-op-checker](.cursor/agents/cann-op-checker.md) | AscendC / 社区任务算子、design.md、ops-\*/asc-devkit MR、IT 五件套 |
| [cann-inference-advisor](.cursor/agents/cann-inference-advisor.md) | 模型迁移、torch-npu、推理优化、服务部署、vLLM-Ascend、API 一致性任务 |
| [opengauss-community-advisor](.cursor/agents/opengauss-community-advisor.md) | openGauss Plugin / examples / docs、师生审核对话、社区 CI |

含糊时先问：昇腾算子社区任务、昇腾推理部署，还是 openGauss？

## Skills

| Skill | 用途 |
|-------|------|
| `cann-ascendc-op-dev` | 算子开发/验收规范 |
| `common-issues-patterns` | 社区常见问题速查 |
| `model-migration` | 迁移与精度对齐 |
| `inference-optimization` | Profiling / 图优化 |
| `deployment-practices` | 服务化与容器 |
| `vllm-ascend-practices` | LLM 推理专项 |
| `api-consistency-community` | Ascend for PyTorch API 一致性任务导航 |
| `opengauss-community` | openGauss 社区审核要点 |

官方可装（对话 `/skill install`）：`torch-npu-pr-review` 等，见  
`https://gitcode.com/Ascend/pytorch-ecosystem/tree/master/01_tasks/resources/tools/agent_skills`

内置 MCP：`ascend-doc`（`npx -y ascend-doc-mcp@latest`），对话 `/mcp`。

镜像目录：`.cursor/`（Cursor）与 `.agents/`（通用）；Codex 见 `.codex/agents/*.toml`。

## 开发规则（加功能前必读）

评审明确反馈过：「整体结构上有点拥挤，如果后面加新的功能会影响」。
以下规则由 `tests/test_structure_guard.py` 自动检查，不是建议：

1. **先定层再写码**：入口 / 编排 / 能力 / 基础，只允许上层依赖下层
2. **新斜杠命令**放 `scripts/cli_commands/`，声明 `COMMANDS = {'/名字': 函数}`；
   **不要**再往 `handle_chat_slash()` 里加 if（该函数有行数预算）
3. **新桌面功能**放 `desktop-app/win/cvapp/features/`，不改 shell 布局
4. **单文件有行数预算**（见结构守卫）。超了先拆模块；确要加，改预算并在提交信息写理由
5. **`scripts/` 不许 import `ascend_cli`**，桌面层不许依赖 CLI 入口（分层不能反向）
6. **加功能必须加测试**，并跑 `python -m unittest discover -s tests`
7. **结构决策写进 `docs/ARCHITECTURE.md`**，不要只留在对话记录里

## CLI（本地）

```bash
python ascend_cli.py review --offline --json
python ascend_cli.py review --scenario opengauss --offline --json
python ascend_cli.py collect --community opengauss
python ascend_cli.py search "507049 HCCL"
python -m unittest discover -s tests -v
```
