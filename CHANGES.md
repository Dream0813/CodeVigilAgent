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

## 二、边框对齐

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

## 三、其他修复

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

## 四、新增的实用工具

| 文件 | 用途 |
|---|---|
| `python -m scripts.frame_doctor` | 边框体检，不需要 API Key、不联网。打印 4 个盒子和每行的显示宽度 |
| `python -m scripts.frame_doctor --anchor` | 演示定位渲染效果 |
| `python scripts/env_matrix.py` | 48 组环境矩阵（编码 × 终端宽度 × 开关），检查边框是否仍然对齐 |
| `start-framecheck.bat` | 双击跑体检 |
| `start-fresh.bat` | 全新用户模式，用独立配置目录，不碰你已有的 API Key |

## 五、怎么验证

```bash
# 1. 边框体检：四个盒子都出现，且每个盒子内每行宽度数字相同
python -m scripts.frame_doctor

# 2. 全量测试
python -m unittest discover -s tests
```

当前状态：**286 项测试全部通过**；48 组环境矩阵全部通过；
边框在「汉字按 1.0 / 1.66 / 2.0 / 2.4 格渲染」四种假设下都能对齐（有对应单测）。

## 六、跑起来

Windows：

```cmd
cd CodeVigilAgent
node bin\reviewagent.js
```

或双击 `start-reviewagent.bat`。首次使用需要在「模型设置」里填 API 配置
（默认读 `~/.reviewagent/ai_config.json`）。

macOS：`chmod +x desktop-app/build-mac.sh && ./desktop-app/build-mac.sh`

## 七、已知限制

- 定位渲染需要 ANSI / VT 支持：Windows 10+ 控制台、Windows Terminal、
  所有 Unix 终端都行；Windows 7 的 conhost 不行（会自动退回补空格）。
- macOS 桌面版（Swift）无法在 Windows 上编译验证，只做了静态结构检查。
- Linux / macOS 真机未实测：本机无 WSL（被安全策略禁用）、无 mac 设备。
  代码层面所有平台分支都有保护，但「跑过」这一点没法声称。
