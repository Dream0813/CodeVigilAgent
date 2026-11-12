"""用系统默认程序打开文件/目录（跨平台）。

为什么不用 shell 命令：
    Windows 的 start、macOS 的 open、Linux 的 xdg-open 各管一摊，
    拼字符串调用还会碰到空格/中文路径被拆开的问题。
    这里用「程序 + 参数列表」的方式，路径原样传，不经过 shell。

失败不抛异常，返回 (False, 原因)，由调用方决定怎么提示。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional, Tuple


def _launch(path: Path) -> Tuple[bool, str]:
    """按当前系统选择打开方式。"""
    if os.name == 'nt' and hasattr(os, 'startfile'):
        os.startfile(str(path))                     # type: ignore[attr-defined]
        return True, '已交给系统默认程序打开'

    if sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, '已用 open 打开'

    opener = shutil.which('xdg-open')
    if not opener:
        return False, '找不到 xdg-open：请安装 xdg-utils，或手动打开这个路径'
    subprocess.Popen([opener, str(path)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True, '已用 xdg-open 打开'


def open_path(target, launcher: Optional[Callable[[Path], Tuple[bool, str]]] = None
              ) -> Tuple[bool, str]:
    """打开路径；target 可以是文件或目录。失败返回原因，不抛异常。"""
    raw = str(target or '').strip()
    if not raw:
        return False, '没有指定要打开的路径'
    path = Path(raw).expanduser()
    if not path.exists():
        return False, f'路径不存在：{path}'
    try:
        ok, detail = (launcher or _launch)(path.resolve())
    except Exception as exc:                        # noqa: BLE001
        return False, f'打开失败：{exc}'
    return ok, f'{detail}：{path}'
