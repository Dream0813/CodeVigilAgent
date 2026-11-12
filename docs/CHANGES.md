# 本次改动说明

> 分支：`codex/desktop-agent-chat-review`
> 仓库：https://github.com/Dream0813/CodeVigilAgent
> 基线：`enternalna-Koh/CodeVigilAgent` 的 `codex/desktop-agent-chat-review`

本次工作集中在**终端界面的可读性**和**几个会直接崩掉的问题**上，没有改动审查逻辑本身。

---

## 一、修掉的 3 个必崩问题

| 位置 | 现象 | 原因 |
|---|---|---|
| `bin/ui-colors.js` | 没装 chalk 时启动即崩 | 降级用的 Proxy 只实现了 `get`，`c.brand` 拿到的是函数对象而不是调用结果 |
| `chat_v2.py` | 走 `fetch_url` 分支时报 `NameError` | 分支里引用了未定义变量 `entities` |
| `chat_v2.py` | 调用 `handle_fetch_and_review()` 必崩 | 方法根本没实现，只有调用点 |

另修一处隐蔽问题：`chat_v2.py` 与 `smart_reviewer.py` 在**被 import 时**修改
`sys.stdout`，会让调用方此前没 flush 的输出整段丢失（体检工具因此只显示得出 1/4 个盒子）。

## 二、配置向导：填完还能退回上一步

原来的向导有个体验问题：**填完 API Key 就直接写盘**。发现服务商或模型选错了，
只能整体重跑（`reviewagent config -w`），已经填的 Key 也白填了。

现在改成：

| 步骤 | 怎么退 |
|---|---|
| 选服务商 | 第一步，无上一步 |
| 选模型 | 列表里有「← 返回上一步（重选服务商）」，或直接输入 `<` |
| 填自定义模型 ID | 输入 `<` |
| 填 base_url | 输入 `<` |
| 填 API Key | 输入 `<` |
| **保存前的确认页（新增）** | `← 改 API Key` / `← 改模型` / `← 改服务商`，或选「保存并启动」 |

确认页会先列出摘要（服务商、模型、base_url、密钥已填写），确认无误再落盘。
从确认页退回重选服务商时，上一轮填的模型和 base_url 会被清空 ——
否则新服务商不需要 base_url 时，旧值会被一起写进配置。

验证：`node tests/test_wizard_confirm.js`（5 个场景、9 项断言）

## 三、边框对齐

终端里画盒子要靠「一个字符占几格」算宽度，但**汉字占几格是字体决定的**：

| 字体 | 汉字 / 西文格 |
|---|---|
| 宋体 / 新宋体（Windows 控制台默认） | 2.00 |
| Linux 默认（DejaVu Sans Mono + Noto CJK） | 约 1.66 |
| macOS 默认（Menlo + 苹方） | 约 1.66 |

代码按 2 格算，字体只画 1.66 格，右边框就歪。做法分两层：

1. **补空格层**（原有）：新增 `scripts/term_frame.py` 与 `bin/term-frame.js`，
   统一 Python / Node 两侧的宽度算法，宽度表由 Python 生成（`bin/width-table.js`），
   BMP 逐码点比对一致。框内禁用「模糊宽度」字符（`· ● ◆ → …` 自动换成等宽 ASCII）。
2. **定位渲染层**（新增）：每行写完内容后回车到行首、右移固定列数再画右边框，
   边框落在指定列，**与字体无关**。上下边框的右端同样定位（含中文标题时会被字体拉短）。

已接入 4 处：输入提示框、思考面板、Agent 回复框、启动欢迎卡。

不支持 ANSI 的终端会自动退回补空格；也可以手动退回：

| 方式 | 操作 |
|---|---|
| **双击**（推荐） | `start-reviewagent-pad.bat` —— 兼容模式，界面上会提示已关闭定位渲染 |
| 命令行 | 先 `set REVIEWAGENT_RENDER=pad`，再启动（只对当前窗口有效） |

什么时候需要退回：右边框位置乱跳、屏幕上出现 `^[` 之类的控制符、或用的是
Windows 7 这类不支持光标定位的老终端。

## 四、其他修复

- **终端退格**：删中文只删掉半个字的残影。原因是擦除固定发 1 个退格符，
  而汉字占 2 列。改为按字符真实显示宽度擦除。
- **控制台编码**：GBK 环境下 `✅ ❌ ⚠ ❯ ✦` 等符号编码不了，`print` 直接抛
  `UnicodeEncodeError` 退出。新增 `scripts/console_safe.py`：
  打印前按当前编码选字形（UTF-8 保留原符号，GBK 退回 `> v !`），并把输出流设为
  「编码不了就替换」兜底。
- **启动脚本**：3 个 `.bat` 原来写死 `D:\UAV\scratch\...`，改成 `%~dp0`，
  clone 到任意路径都能跑。
- **macOS 桌面版**：输出区由比例字体改为等宽字体，汉字按两格宽渲染并锁定行高，
  修复中文与框线重叠；新增 `desktop-app/build-mac.sh` 一键打包成 `.app`。

## 五、新增的实用工具

| 文件 | 用途 |
|---|---|
| `python -m scripts.frame_doctor` | 边框体检，不需要 API Key、不联网。打印 4 个盒子和每行的显示宽度 |
| `python -m scripts.frame_doctor --anchor` | 演示定位渲染效果 |
| `python scripts/env_matrix.py` | 48 组环境矩阵（编码 × 终端宽度 × 开关），检查边框是否仍然对齐 |
| `start-framecheck.bat` | 双击跑体检 |
| `start-fresh.bat` | 全新用户模式，用独立配置目录，不碰你已有的 API Key |

## 六、怎么验证

```bash
# 1. 边框体检：四个盒子都出现，且每个盒子内每行宽度数字相同
python -m scripts.frame_doctor

# 2. Python 全量测试
python -m unittest discover -s tests

# 3. 配置向导的退回逻辑（5 个场景，用 mock 模拟按键，不碰真实配置）
node tests/test_wizard_confirm.js
```

当前状态：**286 项测试全部通过**；48 组环境矩阵全部通过；
边框在「汉字按 1.0 / 1.66 / 2.0 / 2.4 格渲染」四种假设下都能对齐（有对应单测）。

## 七、跑起来

### Windows 桌面版（双击即用）

双击根目录的 **`启动桌面版.bat`**。

打开一个原生窗口：选仓库目录 → 点「审查当前改动」，或在底部输入框直接提问。
输出带颜色、可滚动；`模型设置` 里填服务商 / 模型 / base_url / API Key。

几个实现上的决定：

| 决定 | 原因 |
|---|---|
| 用 tkinter（Python 标准库） | 不下载任何依赖。注意 PATH 里可能有精简版 Python 不带 tkinter，启动器会自动挑一个能用的 |
| 输出区字体用**新宋体** | 它是「ASCII 半角 + 汉字全角」，宽度严格 1:2，CLI 那套补空格对齐才成立。换 Consolas 中文走回退字体，比例不是 2，框线会歪 |
| 子进程强制 `REVIEWAGENT_RENDER=pad` | 文本框里没有终端光标，「定位渲染」的控制序列只会显示成乱码 |
| 启动即最大化 | 4K / 高 DPI 屏上窗口高度会被系统压到逻辑 700 以内，底部输入行会被裁掉 |

### Windows 终端版

```cmd
cd CodeVigilAgent
node bin\reviewagent.js
```

或双击 `start-reviewagent.bat`。

### macOS

```bash
chmod +x desktop-app/build-mac.sh && ./desktop-app/build-mac.sh
```

## 八、已知限制

- 定位渲染需要 ANSI / VT 支持：Windows 10+ 控制台、Windows Terminal、
  所有 Unix 终端都行；Windows 7 的 conhost 不行（会自动退回补空格）。
- macOS 桌面版（Swift）无法在 Windows 上编译验证，只做了静态结构检查。
- Linux / macOS 真机未实测：本机无 WSL（被安全策略禁用）、无 mac 设备。
  代码层面所有平台分支都有保护，但「跑过」这一点没法声称。

---

## 九、结构调整（2026-11-12）

> 起因：评审意见「整体结构上有点拥挤，如果后面加新的功能会影响」。
> 详细设计见 [ARCHITECTURE.md](ARCHITECTURE.md)，操作步骤见 [ADDING-FEATURES.md](ADDING-FEATURES.md)。

### 9.1 根目录：30+ 项 → 精简

| 处理 | 对象 |
|------|------|
| 移到 `legacy/` | `chat.py`、`test_chat.py`、`chat_v2.bat`、`run_test.bat`、`diagnose.bat`（后三个原来硬编码 `D:\Agent-ReviewAgent`，早已失效） |
| 移到 `launchers/` | `ascend.bat`、`chat.bat`、`start-fresh.bat`、`start-reviewagent-pad.bat`、`start-framecheck.bat`，路径改为 `%~dp0..`，仓库可整体搬动 |
| 移到 `docs/` | 5 份散落文档（`CHANGES`/`FINAL_SUMMARY`/`MANUAL_EXECUTION_GUIDE`/`PROJECT_STRUCTURE`/`NPM_README` 等），README 链接同步更新 |
| 保留 | `ascend_cli.py`、`chat_v2.py`、`review.py`、`review_cli.py`（文档引用 56 次）、主入口 bat |

### 9.2 桌面版：383 行单类 → 分层包

```
desktop-app/win/
├── app.py            20 行，只做入口
└── cvapp/
    ├── shell.py      窗口骨架：**左侧分组侧边栏**（原来 5 个按钮挤成一排）
    ├── theme.py      颜色/字体/尺寸唯一来源
    ├── widgets.py    按钮、输出面板
    ├── runner.py     子进程 + 队列 + 取消
    ├── config.py     配置读写
    └── features/     功能注册表：加功能只加一个文件，自动出现在侧边栏
```

加一个功能现在只写一个新文件，不用改布局、不用改 shell、不用登记（`pkgutil` 自动发现）。

### 9.3 `chat_v2.py`：1008 行 → 768 行

把颜色 / 字形 / 盒子绘制（约 240 行）抽到 `scripts/term_ui.py`。
`chat_v2` 仍 re-export `Style` / `G` / `UI` / `colored` / `bold` / `dim`，
旧写法 `from chat_v2 import UI` 继续有效。

### 9.4 故意没拆的地方

- `ascend_cli.py`（1510 行）：286 项测试里有 50+ 处 `patch('ascend_cli.xxx')`，
  它是测试接缝；拆包会让补丁失效，收益只是行数变少。
- `review_cli.py`：文档引用 56 次，移走会让文档大面积失效。

### 9.5 验证

| 项 | 结果 |
|---|---|
| Python 回归 | 286 项全部通过 |
| JS 向导回退 | 9 项全部通过 |
| CLI 冒烟 | `--version` / `doctor` 正常 |
| 边框体检 | 4 块全部对齐 |
| 桌面版 | 新布局截图核对：侧边栏、输出区、输入行均完整可见 |

---

## 十、新增四个能力（2026-11-12 下午）

> 做法：先看同类 Agent 有什么，再挑本项目真正缺的。
> 参考对象：Claude Code（自定义命令 / `/cost`）、Cursor（`@文件`）、
> aider（`/read`、lint 钩子）、CodeRabbit（pre-merge checks）。

| 功能 | 参考 | 实现 | 为什么值得加 |
|------|------|------|-------------|
| 自定义斜杠命令 | Claude Code `.claude/commands` | `scripts/custom_commands.py` + `.reviewagent/commands/` | 常用提问不用每次重打；随仓库共享，团队复用 |
| `@文件` 引用 | Cursor / aider `/read` | `scripts/file_mentions.py` | 审查对话时能精确指文件，比"贴一大段代码"省 token |
| 提交前门禁 | CodeRabbit pre-merge checks | `review --fail-on` + `scripts/git_hooks.py` + `install-hook` | 把"审一遍"从人工动作变成 git 流程的一部分 |
| 会话用量估算 | Claude Code `/cost`、aider `/tokens` | `scripts/usage_meter.py` + `/cost` | 长会话心里有数，避免无意烧 token |

### 10.1 自定义命令

```
.reviewagent/commands/并发.md     → /并发 <文件>
.reviewagent/commands/db/slow.md  → /db:slow
```

- frontmatter 支持 `description` / `argument-hint`
- `$ARGUMENTS` / `${ARGUMENTS}` 占位符；没有占位符时参数附在末尾
- 项目级覆盖用户级；内置命令优先，不会被同名自定义命令抢占
- 单文件 64 KB、最多 200 个命令，解析失败只警告不崩

仓库内已带 3 个示例：`/并发`、`/报错`、`/补测试`。

### 10.2 `@文件` 引用

```
这个函数为什么会泄漏？@src/server.py
对比 @src/old.py 和 @src/new.py
@scripts/ 目录里有哪些入口？
```

- 只允许仓库内路径（`..` 越界、绝对路径越界都拒绝）
- 单文件 ≤64 KB，一次 ≤8 个，目录最多列 100 项
- 二进制（含 NUL）跳过；找不到只警告，不中断对话
- 中文标点紧跟路径也能正确识别（`@a.py，` → `a.py`）

### 10.3 提交前门禁

```bash
python ascend_cli.py install-hook --severity high
python ascend_cli.py review --staged --offline --fail-on high
```

- 钩子带固定标记，重复安装只更新；卸载只删自己写的
- 遇到第三方钩子默认拒绝覆盖，`--force` 会先备份
- 兼容 worktree / `core.hooksPath`（用 `git rev-parse --git-path hooks` 定位）
- `--fail-on` 默认 `none`，**不改变既有行为**；只有显式指定才影响退出码

### 10.4 `/cost`

```
/cost  →  调用次数 / 输入输出 token 估算 / 合计
```

中英文分开估算（中文 1 字≈1 token，其它 4 字符≈1 token）。
不显示金额：各网关单价差异太大，报假数字比不报更糟。

### 10.5 验证

| 项 | 结果 |
|---|---|
| 新增测试 | 31 项（4 个功能 + CLI 集成） |
| 全量回归 | **317 项全部通过**（原 286 + 新 31） |
| 端到端门禁 | 临时仓库装钩子 → 提交含 `bare except` 的文件 → **退出码 1，提交被阻止**，HEAD 未前进 |
| 自定义命令 | `/commands` 列出 3 个项目级命令；`/并发 src/foo.py` 正确展开 |
| 文件引用 | `@scripts/usage_meter.py` 实际附带 2.5 KB 正文 |
| 用量 | `/cost` 输出调用次数与 token 估算 |
