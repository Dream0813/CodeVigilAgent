# launchers/ — 次要启动脚本

**主入口不在这里**，在仓库根目录：

- `启动桌面版.bat` —— 打开 Windows 桌面版
- `start-reviewagent.bat` —— 打开终端版 Agent

这里放的是只在特定场景才用的脚本：

| 脚本 | 什么时候用 |
|------|-----------|
| `start-fresh.bat` | 想模拟「全新用户」：用独立配置目录，绝不碰你真实的 API Key |
| `start-reviewagent-pad.bat` | 兼容模式：关闭「光标定位」渲染，退回补空格对齐（老终端 / 出现 `^[` 乱码时） |
| `start-framecheck.bat` | 只查边框对齐，不联网、不需要 API Key |
| `ascend.bat` | 等价于 `python ascend_cli.py %*` |
| `chat.bat` | 等价于 `python ascend_cli.py chat` |

## 路径约定

每个脚本都用 `%~dp0..` 回到仓库根目录再执行，
所以**整个仓库可以搬到任意路径**（U 盘、其他电脑）都能继续用。

从根目录调用也可以，例如：

```bat
launchers\ascend.bat review --offline
```
