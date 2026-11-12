# 项目结构

> 分层理由与扩展点见 [ARCHITECTURE.md](ARCHITECTURE.md)；
> 加功能的具体步骤见 [ADDING-FEATURES.md](ADDING-FEATURES.md)。

```
CodeVigilAgent/
│
├── 启动桌面版.bat                     # 双击：打开 Windows 桌面版
├── start-reviewagent.bat              # 双击：打开终端版 Agent
│
├── ascend_cli.py                      # 主入口（review/chat/doctor/config/sessions/model）
├── chat_v2.py                         # 终端对话界面（样式层已抽到 scripts/term_ui.py）
├── review.py                          # npm 包 bin 的兼容入口
├── review_cli.py                      # 旧版 CLI（文档仍引用，保留）
├── review.bat                         # review_cli.py 的启动壳
│
├── bin/                               # Node 层 CLI
│   ├── reviewagent.js                 #   reviewagent 命令
│   ├── buddy.js / ui.js / onboard.js  #   对话 UI、启动向导
│   ├── term-frame.js / width-table.js #   终端宽度表（由 Python 生成）
│   └── ansi.js / ui-colors.js
│
├── scripts/                           # Python 业务层
│   ├── smart_reviewer.py              #   审查主流程
│   ├── term_frame.py                  #   宽度计算唯一出处（定位渲染 + 补空格）
│   ├── term_ui.py                     #   终端颜色 / 字形 / 盒子
│   ├── console_safe.py                #   编码兜底（GBK 不崩）
│   ├── conversation_agent.py          #   对话 Agent
│   ├── ai_adapter.py                  #   多模型适配
│   ├── github_fetcher.py              #   PR / Issue 抓取
│   ├── session_store.py               #   会话持久化
│   ├── custom_commands.py             #   自定义斜杠命令（.reviewagent/commands）
│   ├── file_mentions.py               #   @文件引用解析
│   ├── git_hooks.py                   #   pre-commit 钩子安装
│   ├── usage_meter.py                 #   /cost 用量估算
│   ├── system_open.py                 #   open 命令（跨平台打开目录）
│   ├── clipboard.py                   #   /copy 跨平台剪贴板
│   ├── config_backup.py               #   配置备份 / 回滚
│   ├── cli_commands/                  #   斜杠命令注册表（新命令放这里）
│   │   ├── __init__.py               #     自动发现 + dispatch
│   │   └── convenience.py            #     /copy /dir /cost /commands
│   ├── frame_doctor.py                #   边框体检（不需要 API Key）
│   └── ...                            #   知识库、MCP、数据采集
│
├── desktop-app/
│   ├── win/                           # Windows 桌面版
│   │   ├── app.py                     #   入口（20 行）
│   │   ├── make_shortcut.py           #   生成桌面快捷方式
│   │   └── cvapp/                     #   应用层（分层见 ARCHITECTURE.md）
│   │       ├── shell.py               #     窗口骨架：侧边栏 + 工作区
│   │       ├── theme.py               #     颜色 / 字体 / 尺寸
│   │       ├── widgets.py             #     按钮 / 输出面板
│   │       ├── runner.py              #     子进程执行器
│   │       ├── config.py              #     配置读写
│   │       ├── ansi_term.py           #     ANSI → tkinter tag
│   │       └── features/              #     ★ 功能注册表：加功能只动这里
│   │           ├── base.py            #       Feature 数据结构 + 分组
│   │           ├── review.py          #       审查当前改动 / 离线审查
│   │           ├── chat.py            #       底部输入提问
│   │           ├── output.py          #       清空 / 取消
│   │           └── settings.py        #       模型设置
│   ├── CodeVigilAgentApp.swift        # macOS 版（需在 macOS 上构建）
│   └── build-mac.sh
│
├── tests/                             # 回归测试（286 项 Python + 9 项 JS）
├── docs/                              # 设计、使用、架构文档
├── launchers/                         # 次要启动脚本（兼容模式 / 边框体检 / 新用户）
├── legacy/                            # 已退役入口，仅留档
├── .reviewagent/commands/             # 项目级自定义命令（/并发 /报错 /补测试）
├── config/                            # 默认配置模板
├── data/                              # 知识库与采集数据
│
├── .cursor/                           # 智能体与知识包（见下）
├── README.md                          # 项目主文档
├── CHANGELOG.md                       # 版本记录
├── SUMMARY.md                         # 项目概要
├── CodeVigilAGENTS.md                 # 智能体路由说明
├── LICENSE                            # Apache 2.0
├── package.json / package-lock.json   # npm 包
└── install.js                         # postinstall 脚本
```

## 入口一览

| 想要的 | 用什么 |
|--------|--------|
| 桌面窗口 | 根目录 `启动桌面版.bat` / 桌面快捷方式 |
| 终端 Agent | 根目录 `start-reviewagent.bat` |
| 命令行审查 | `python ascend_cli.py review` |
| 环境自检 | `python ascend_cli.py doctor` |
| 边框体检 | `launchers/start-framecheck.bat` |
| 跑测试 | `python -m unittest discover -s tests` |

## 文档地图

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 分层、依赖方向、扩展点、行为等价清单 |
| [ADDING-FEATURES.md](ADDING-FEATURES.md) | 加桌面功能 / CLI 子命令 / 斜杠命令 |
| [CLI_GUIDE.md](CLI_GUIDE.md) | 命令行详细教程 |
| [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) | 模型适配与知识库设计 |
| [INSTALLATION.md](INSTALLATION.md) | 安装步骤 |
| [WINDOWS_SETUP.md](WINDOWS_SETUP.md) | Windows 环境配置 |
| [NPM_PUBLISH.md](NPM_PUBLISH.md) | 发布到 npm 的流程 |

## 智能体 (Agents)

位于 `.cursor/agents/`，定义角色边界、知识依赖、检查维度、内置红线与报告模板：

- `cann-op-checker.md` —— AscendC 算子检查
- `cann-inference-advisor.md` —— 模型迁移与推理优化
- `opengauss-community-advisor.md` —— openGauss 社区任务

## 知识包 (Skills)

位于 `.cursor/skills/`，每个包含：

- `SKILL.md` —— 主知识文件，按 § 分节
- `README.md` —— 快速导航与使用场景
- 附录（官方文档摘录、示例代码、踩坑指南）

现有知识包：`cann-ascendc-op-dev`、`model-migration`、`inference-optimization`、
`deployment-practices`、`common-issues-patterns`、`vllm-ascend-practices`。

### 添加新知识包

1. 在 `.cursor/skills/` 创建目录 `<skill-name>/`
2. 编写 `SKILL.md`（主知识文件）与 `README.md`（快速导航）
3. 添加参考资料与示例
4. 更新相关智能体的知识依赖

## 维护清单

- [ ] 定期更新官方文档链接（CANN 版本升级）
- [ ] 收集社区新案例补充到 skill
- [ ] 新增目录时同步更新本文档与 `ARCHITECTURE.md`
- [ ] 每次加功能都补一条回归测试
