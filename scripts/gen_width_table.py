#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Python 的 unicodedata 生成 JS 用的宽度区间表。

为什么要生成而不是手写：EAW 表有几千个码点，手写区间必然错。
实测手写版在 BMP 里有 8144 个码点和 Python 不一致 —— 也就是说
Node 画的框和 Python 画的框会差列，右边框照样歪。

用法（改了 term_frame 的宽度规则后重跑）：
    python scripts/gen_width_table.py

生成物：bin/width-table.js
一致性由 tests/test_frame_unified_20261110.py 的 parity 测试保证。
"""
from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'bin' / 'width-table.js'

FIRST = 0x20
LAST = 0x110000


def classify(cp: int) -> str:
    ch = chr(cp)
    if unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
        return 'z'          # 组合记号 / 格式控制符：0 列
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ('W', 'F'):
        return 'w'          # 中文、全角：2 列
    if eaw == 'A':
        return 'a'          # 模糊宽度：按策略 1 或 2 列
    return 'n'              # 其余：1 列


def ranges_for(tag: str, kinds: dict) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start = None
    prev = None
    for cp in range(FIRST, LAST):
        if kinds[cp] == tag:
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            out.append((start, prev))
            start = None
    if start is not None:
        out.append((start, prev))
    return out


def fmt(pairs) -> str:
    return '[' + ','.join(f'[0x{a:x},0x{b:x}]' for a, b in pairs) + ']'


def main() -> int:
    kinds = {cp: classify(cp) for cp in range(FIRST, LAST)}
    wide = ranges_for('w', kinds)
    amb = ranges_for('a', kinds)
    zero = ranges_for('z', kinds)

    # 制表符强制 1 列（虽然 EAW=A，但实测单宽字体里就是 1 列）
    box_drawing = [(0x2500, 0x257F)]
    # 常见引号强制 1 列
    narrow_override = [(0x2018, 0x2019), (0x201C, 0x201D)]

    js = (
        '/* eslint-disable */\n'
        '// 自动生成，请勿手改。生成器：scripts/gen_width_table.py\n'
        '// 数据源：Python unicodedata.east_asian_width\n'
        f'// 生成时 Python {sys.version.split()[0]} / Unicode {unicodedata.unidata_version}\n'
        f'// wide={len(wide)} 段, ambiguous={len(amb)} 段, zero={len(zero)} 段\n'
        'module.exports = {\n'
        f'  WIDE: {fmt(wide)},\n'
        f'  AMBIGUOUS: {fmt(amb)},\n'
        f'  ZERO: {fmt(zero)},\n'
        f'  BOX_DRAWING: {fmt(box_drawing)},\n'
        f'  NARROW_OVERRIDE: {fmt(narrow_override)},\n'
        '};\n'
    )
    OUT.write_text(js, encoding='utf-8')
    print(f'已写入 {OUT}（{len(js)} 字节）')
    print(f'  wide       {len(wide)} 段')
    print(f'  ambiguous  {len(amb)} 段（默认 2 列；REVIEWAGENT_AMBIGUOUS=0 时 1 列）')
    print(f'  zero       {len(zero)} 段')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
