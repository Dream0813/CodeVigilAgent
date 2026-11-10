"""Lightweight Markdown → ANSI for terminal replies (no external deps)."""
from __future__ import annotations

import re
from typing import Iterable, List

from scripts import term_frame as tf
from scripts.term_style import accent, brand, c, colors_enabled, mute, ok, warn


def _inline(text: str) -> str:
    """Bold / italic / code / links — order matters."""
    if not text:
        return text

    def code(m):
        return c('93', m.group(1))  # yellow inline code

    def bold(m):
        return c('1;97', m.group(1))  # bright bold white

    def italic(m):
        return c('3;96', m.group(1))

    def link(m):
        label, url = m.group(1), m.group(2)
        return f"{brand(label)}{mute(' (' + url + ')')}"

    text = re.sub(r'`([^`]+)`', code, text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, text)
    text = re.sub(r'\*\*([^*]+)\*\*', bold, text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', italic, text)
    text = re.sub(r'(?<!_)_([^_]+)_(?!_)', italic, text)
    return text


def _code_fence_top(label: str, inner: int) -> str:
    """`┌─ label ─────┐`，总宽刚好 inner。"""
    seg = f' {label} ' if label else ''
    if not seg:
        return mute('┌' + '─' * (inner - 2) + '┐')
    line = '┌─' + seg + '─' * max(1, inner - 3 - tf.display_width(seg)) + '┐'
    diff = inner - tf.display_width(line)
    if diff > 0:
        line = line[:-1] + '─' * diff + line[-1]
    elif diff < 0:
        line = line[:len(line) - 1 + diff] + line[-1]
    return mute(line)


def render_markdown(md: str, width: int = 0) -> List[str]:
    """Return list of ANSI-colored lines ready to print inside a box.

    行内不折行 —— 交给 term_frame.row_lines 统一按显示宽度折行并补齐，
    这样中文、英文、长 URL 都不会把右边框顶歪。
    """
    if not md:
        return ['(empty)']
    inner = width or tf.content_width()
    out: List[str] = []
    in_code = False
    code_lang = ''
    for raw in md.replace('\r\n', '\n').split('\n'):
        line = raw.rstrip()

        if line.startswith('```'):
            if not in_code:
                in_code = True
                code_lang = line[3:].strip()
                out.append(_code_fence_top(('code ' + code_lang).strip(), inner))
            else:
                in_code = False
                out.append(mute('└' + '─' * (inner - 2) + '┘'))
            continue

        if in_code:
            # 代码行在嵌套小框里按宽度折行，右侧也补上竖线
            for part in tf.wrap_display(line, max(1, inner - 4)):
                out.append(
                    mute('│ ') + c('92', tf.pad_display(part, inner - 3)) + mute('│')
                )
            continue

        # headings
        if line.startswith('### '):
            out.append('')
            out.append(accent('▸ ') + c('1;95', line[4:].strip()))
            out.append(mute('  ' + '─' * min(40, inner - 2)))
            continue
        if line.startswith('## '):
            out.append('')
            out.append(brand('◆ ') + c('1;96', line[3:].strip()))
            out.append(mute('  ' + '═' * min(44, inner - 2)))
            continue
        if line.startswith('# '):
            out.append('')
            out.append(ok('★ ') + c('1;92', line[2:].strip()))
            out.append(mute('  ' + '═' * min(48, inner - 2)))
            continue

        # hr
        if re.fullmatch(r'-{3,}|\*{3,}|_{3,}', line.strip()):
            out.append(mute('  ' + '─' * min(48, inner - 2)))
            continue

        # blockquote
        if line.startswith('> '):
            out.append(mute('  │ ') + c('90', _inline(line[2:])))
            continue

        # unordered list
        m = re.match(r'^(\s*)([-*+])\s+(.*)$', line)
        if m:
            indent, _, body = m.groups()
            pad = '  ' * (len(indent) // 2)
            out.append(f"{pad}{accent('•')} {_inline(body)}")
            continue

        # ordered list
        m = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
        if m:
            indent, num, body = m.groups()
            pad = '  ' * (len(indent) // 2)
            out.append(f"{pad}{brand(num + '.')} {_inline(body)}")
            continue

        if not line.strip():
            out.append('')
            continue

        out.append(_inline(line))

    # drop leading empties
    while out and out[0] == '':
        out.pop(0)
    return out or ['(empty)']


def print_markdown_box(md: str, title: str = 'Agent') -> None:
    """Print markdown inside a green rounded box with rendered formatting.

    盒子总宽取自 term_frame（和输入框、思考面板一致），
    每行都补齐到同一列，所以右边框是一条直线，长内容自动折行。
    """
    from scripts.term_style import enable_windows_ansi
    enable_windows_ansi()
    total = tf.total_width()
    lines = render_markdown(md, tf.content_width(total))
    print()
    try:
        print(ok(tf.top_border(title, total)))
        for line in lines:
            body = line if colors_enabled() else _strip_ansi(line)
            for wrapped in tf.row_lines(body, total, paint=ok):
                print(wrapped)
        print(ok(tf.bottom_border('', total)))
    except UnicodeEncodeError:
        print(ok(f'+-- {title} ' + '-' * max(4, total - 8 - len(title)) + '+'))
        for line in lines:
            print(_strip_ansi(line))
        print(ok('+' + '-' * (total - 2) + '+'))


_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s)
