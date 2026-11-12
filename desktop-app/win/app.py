"""CodeVigil Agent — Windows 桌面版入口。

双击「启动桌面版.bat」或桌面快捷方式，最终都执行这个文件。
真正的实现在 cvapp/ 包里（分层说明见 cvapp/__init__.py 与 docs/ARCHITECTURE.md）。

显式把本目录加进 sys.path：
    用 pythonw.exe 启动时 sys.path[0] 就是脚本目录，一般没问题；
    但被其他解释器/打包器拉起时不一定，写死更稳。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from cvapp.shell import main  # noqa: E402

if __name__ == '__main__':
    main()
