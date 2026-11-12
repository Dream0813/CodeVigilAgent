"""把带 ANSI 颜色的终端输出，切成 tkinter 能着色的片段。

CLI 的输出里有 `\\x1b[38;5;37m` 这类颜色码，还有光标移动、清屏等控制序列。
Text 组件不认这些，所以要先把它们「翻译」成 (文本, 颜色) 列表。

设计取舍：只处理 SGR（颜色/粗体），其余控制序列一律丢弃 ——
桌面版不需要在文本框里做光标定位，留着只会显示成乱码。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

SGR = re.compile(r'\x1b\[([0-9;]*)m')
# 其他 CSI（光标移动、清屏）与 OSC（设置标题）直接丢掉
OTHER_CSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
OSC = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)')

# 基础 16 色，按深色背景挑的一组柔和配色
BASE = {
    0: '#3b4048',
    1: '#e06c75',
    2: '#98c379',
    3: '#e5c07b',
    4: '#61afef',
    5: '#c678dd',
    6: '#56b6c2',
    7: '#dcdfe4',
    8: '#5c6370',
    9: '#ff7b86',
    10: '#b5e890',
    11: '#ffd68a',
    12: '#7cc0ff',
    13: '#d98ee8',
    14: '#6fd3de',
    15: '#ffffff',
}


def color256(n: int) -> str:
    """xterm-256 色号 → #rrggbb。"""
    n = max(0, min(255, int(n)))
    if n < 8:
        return BASE[n]
    if n < 16:
        return BASE[n]
    if n < 232:
        n -= 16
        r, g, b = n // 36, (n % 36) // 6, n % 6
        step = lambda v: 0 if v == 0 else 55 + v * 40  # noqa: E731
        return '#%02x%02x%02x' % (step(r), step(g), step(b))
    v = 8 + (n - 232) * 10
    return '#%02x%02x%02x' % (v, v, v)


# 片段类型：(文本, 前景色, 是否粗体)
Segment = Tuple[str, Optional[str], bool]


def parse(text: str) -> List[Segment]:
    """把一段带 ANSI 的文本切成片段列表。

    默认前景色用 None 表示「跟随主题」，由调用方决定用哪个颜色。
    """
    text = OSC.sub('', text)
    text = OTHER_CSI.sub('', text)

    out: List[Segment] = []
    fg: Optional[str] = None
    bold = False
    pos = 0

    for m in SGR.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], fg, bold))

        args = [a for a in m.group(1).split(';') if a != '']
        codes = [int(a) for a in args] if args else [0]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                fg, bold = None, False
            elif c == 1:
                bold = True
            elif c == 22:
                bold = False
            elif 30 <= c <= 37:
                fg = BASE[c - 30]
            elif 90 <= c <= 97:
                fg = BASE[c - 90 + 8]
            elif c == 39:
                fg = None
            elif c in (38, 48):
                # 扩展色：38;5;N 或 38;2;R;G;B
                if i + 1 < len(codes):
                    mode = codes[i + 1]
                    if mode == 5 and i + 2 < len(codes):
                        if c == 38:
                            fg = color256(codes[i + 2])
                        i += 3
                        continue
                    if mode == 2 and i + 4 < len(codes):
                        if c == 38:
                            fg = '#%02x%02x%02x' % (codes[i + 2], codes[i + 3], codes[i + 4])
                        i += 5
                        continue
                i += 1
                continue
            i += 1
        pos = m.end()

    if pos < len(text):
        out.append((text[pos:], fg, bold))

    return [seg for seg in out if seg[0]]


def strip(text: str) -> str:
    """去掉所有 ANSI 序列，只留纯文本（用于复制、日志）。"""
    text = OSC.sub('', text)
    text = OTHER_CSI.sub('', text)
    return SGR.sub('', text)
