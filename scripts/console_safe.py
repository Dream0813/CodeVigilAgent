"""控制台编码兜底。

背景：中文 Windows 的 cmd 默认代码页是 GBK（cp936），很多符号不在里面 ——
✓ ✗ ⚠ ❯ ✦ ✅ ❌ … 一旦 print 到这些字符，Python 会抛 UnicodeEncodeError
并直接退出，用户看到的是 Traceback，而不是"某个符号显示不出来"。

这里做两件事：

1. harden_console()：把 stdout/stderr 的错误处理改成 replace。
   编码不了的字符变成 '?'，程序继续跑。这是**兜底**，应该在入口最先调用。

2. glyph(fancy, safe)：在打印前先问一句"这个字符当前编码能不能表示"，
   不能就换成 ASCII 等价物。这是**首选**，因为能保持界面好看。

两者关系：glyph 负责好看，harden 负责不崩。只做 harden 的话，
GBK 用户会看到一堆 '?'；只做 glyph 的话，漏掉一处就崩。
"""
from __future__ import annotations

import sys

_HARDENED = False


def harden_console() -> None:
    """把标准输出/错误流设为「编码不了就替换」，避免 UnicodeEncodeError 直接退出。

    幂等：重复调用无副作用。测试里 stdout 被替换成 StringIO 时，
    没有 reconfigure 方法，静默跳过。
    """
    global _HARDENED
    if _HARDENED:
        return
    _HARDENED = True
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors='replace')
        except Exception:
            pass


def current_encoding() -> str:
    """当前输出流的编码名，例如 'utf-8' / 'gbk' / 'cp936'。"""
    return getattr(sys.stdout, 'encoding', None) or 'utf-8'


def can_encode(text: str) -> bool:
    """当前输出流能不能表示这段文本。"""
    try:
        text.encode(current_encoding())
        return True
    except Exception:
        return False


def glyph(fancy: str, safe: str) -> str:
    """编码支持就用 fancy（好看），不支持退回 safe（纯 ASCII / GBK 安全）。

    例：glyph('❯', '>')  —— UTF-8 终端看到 ❯，GBK 终端看到 >
    """
    return fancy if can_encode(fancy) else safe


# 常用符号的成对写法，统一放这里，避免各处各写一套。
# safe 一律选「显示宽度 1 列」的 ASCII，这样替换前后不会改变整行宽度，
# 边框不会因为这个开关而错位。
PROMPT = ('❯', '>')
CHECK = ('✓', 'v')
CROSS = ('✗', 'x')
WARN = ('⚠', '!')
STAR = ('✦', '*')
DOT = ('•', '*')


def prompt(default: str = '> ') -> str:
    """输入提示符：UTF-8 下是 ❯，GBK 下是 >"""
    return glyph(*PROMPT) + ('' if default.endswith(' ') else '')


def check() -> str:
    return glyph(*CHECK)


def cross() -> str:
    return glyph(*CROSS)


def warn() -> str:
    return glyph(*WARN)
