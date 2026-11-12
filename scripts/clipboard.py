"""把文本放进系统剪贴板（跨平台，零第三方依赖）。

    Windows  ctypes 调 user32/kernel32（不依赖 pyperclip）
    macOS    pbcopy
    Linux    wl-copy（Wayland）→ xclip → xsel，按可用性挑一个

失败时返回原因，不抛异常——复制不了也不该让程序崩。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import Callable, Optional, Tuple

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


def _copy_windows(text: str) -> None:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    if not user32.OpenClipboard(None):
        raise OSError('无法访问剪贴板（可能被其它程序占用）')
    try:
        user32.EmptyClipboard()
        data = text.encode('utf-16-le') + b'\x00\x00'
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise OSError('分配剪贴板内存失败')
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise OSError('锁定剪贴板内存失败')
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise OSError('写入剪贴板失败')
    finally:
        user32.CloseClipboard()


def _copy_macos(text: str) -> None:
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)


def _copy_linux(text: str) -> None:
    candidates = (
        (['wl-copy'], ['wl-copy']),
        (['xclip', '-selection', 'clipboard'], ['xclip']),
        (['xsel', '--clipboard', '--input'], ['xsel']),
    )
    for command, lookup in candidates:
        if shutil.which(lookup[0]):
            subprocess.run(command, input=text.encode('utf-8'), check=True)
            return
    raise FileNotFoundError('没有找到 wl-copy / xclip / xsel')


def _default_backend() -> Callable[[str], None]:
    if os.name == 'nt':
        return _copy_windows
    if sys.platform == 'darwin':
        return _copy_macos
    return _copy_linux


def copy_text(text: str, backend: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """复制文本；返回 (是否成功, 提示)。空文本视为无需复制。"""
    if not text:
        return False, '没有可复制的文本'
    try:
        (backend or _default_backend())(text)
    except Exception as exc:                        # noqa: BLE001
        return False, f'复制失败：{exc}（可以手动选中复制）'
    return True, f'已复制 {len(text)} 个字符到剪贴板'
