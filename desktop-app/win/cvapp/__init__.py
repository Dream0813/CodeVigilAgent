"""CodeVigil Agent 桌面版的应用层。

分层（依赖只能从上往下，不能反向）：

    app.py（入口，30 行）
      └── cvapp.shell      窗口骨架：侧边栏 + 主区域
            ├── cvapp.features   功能注册表（加功能只改这一层）
            ├── cvapp.widgets    可复用控件
            ├── cvapp.runner     子进程执行器
            ├── cvapp.config     配置读写
            └── cvapp.theme      颜色 / 字体 / 间距

为什么这样分：
    原来 app.py 一个类同时管布局、按钮、子进程、配置、设置对话框，
    任何一处改动都要动同一个文件 —— 加功能必然互相影响。
    现在「功能」是独立文件，界面只负责把注册表里的功能摆出来。
"""
from __future__ import annotations

import os

__all__ = ['HERE', 'ROOT', 'VERSION']

# cvapp/__init__.py → cvapp → win
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# win → desktop-app → 仓库根
ROOT = os.path.dirname(os.path.dirname(HERE))


def _read_version() -> str:
    """从 package.json 读版本号；读不到就退回 unknown，不影响启动。"""
    try:
        import json

        with open(os.path.join(ROOT, 'package.json'), encoding='utf-8') as fh:
            return str(json.load(fh).get('version') or 'unknown')
    except Exception:                                   # noqa: BLE001
        return 'unknown'


VERSION = _read_version()
