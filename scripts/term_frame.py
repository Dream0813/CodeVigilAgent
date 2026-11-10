"""统一的终端盒子渲染。

为什么要单独一个模块：原来的三个盒子（输入框 / 思考面板 / Agent 回复）
各自算各自的宽度，而且都不给正文补右边框，导致：

1. 同一个盒子的上下边框宽度不一样（思考面板顶部 41 列、底部 44 列）；
2. 正文比边框宽时直接把文字顶出框外（HTTP 400 那串 JSON 就是）；
3. 中文按 1 个字符算，实际占 2 列，右边框永远对不齐。

这里统一成：同一个终端里所有盒子 **同宽**，正文按显示宽度折行并补齐，
所以所有竖线都落在同一列上。宽度计算规则：

- ASCII 可打印字符 = 1 列
- 中文 / 全角 / 需要回退到中文字体的符号 = 2 列
- 制表符 ─│╭╮╰╯ = 1 列（单宽字体自带这些字形，实测 1 列）

中点 · 、箭头 → 、菱形 ◆ 这类"模糊宽度"字符（EAW=A）在不同终端下不一致：
中文控制台回退宋体时按 2 列画，部分终端按 1 列画。默认按 2 列算；
如果反而偏移了，设 REVIEWAGENT_AMBIGUOUS=0 让它按 1 列算。

更稳的做法是在框内别用它们 —— `frame_safe()` 会把 `· ● ◆ → …` 换成
等宽 ASCII，宽度确定是 1 列，物理上不可能歪。top_border / bottom_border /
row_lines 默认都过一遍 frame_safe，`REVIEWAGENT_FRAME_SAFE=0` 可关。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata
from typing import List

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def strip_ansi(text: str) -> str:
    """去掉 ANSI 颜色序列（宽度计算前必须做）。"""
    return ANSI_RE.sub('', text or '')


def _ambiguous_wide() -> bool:
    """EAW=A 的字符按几列算。默认 2（中文控制台回退到宋体）。"""
    v = (os.environ.get('REVIEWAGENT_AMBIGUOUS') or '').strip().lower()
    if v in ('0', 'narrow', 'false', 'no'):
        return False
    return True


_AMB_WIDE = _ambiguous_wide()

# 单宽字体里必然有的非 ASCII 字符：按 1 列
# 注意：`·`(U+00B7) 不在这里！它是 EAW=A，中文控制台按全角 2 列画。
# 曾经把它算成 1 列，导致 `AI调换->日常 · /skill · /mcp · /exit` 这类
# 带 3 个中点的行比边框宽 3 列，右边框被顶到框外 —— 就是这一条惹的祸。
_NARROW_CHARS = frozenset('\u2018\u2019\u201c\u201d')


def char_width(ch: str) -> int:
    o = ord(ch)
    if ch == '\t':
        return 4
    if o < 0x20 or o == 0x7F:
        return 0
    if o < 0x7F:
        return 1
    if 0x2500 <= o <= 0x257F:  # ─ │ ╭ ╮ ╰ ╯ ├ ┤ ┼ 等制表符
        return 1
    if ch in _NARROW_CHARS:  # 常见引号
        return 1
    # 组合记号（重音符号等）/ 格式控制符（零宽连接符等）不占列。
    # 它们的 EAW 常是 A，不加这一条会和 Node 侧算得不一样。
    if unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
        return 0
    eaw = unicodedata.east_asian_width(ch)
    if eaw in ('W', 'F'):
        return 2
    if eaw == 'A':
        return 2 if _AMB_WIDE else 1
    return 1


def display_width(text: str) -> int:
    """字符串在终端里占几列（忽略 ANSI 颜色码）。"""
    return sum(char_width(ch) for ch in strip_ansi(text))


def pad_display(text: str, width: int) -> str:
    """右侧补空格到指定显示宽度；超宽时原样返回（由调用方先折行）。"""
    gap = width - display_width(text)
    return text + ' ' * gap if gap > 0 else text


def truncate_display(text: str, width: int, ellipsis: str = '…') -> str:
    """按显示宽度截断，ANSI 序列不占宽度也不被切断。"""
    if display_width(text) <= width:
        return text
    budget = max(width - char_width(ellipsis), 0)
    out: List[str] = []
    acc = 0
    pos = 0
    for m in ANSI_RE.finditer(text):
        for ch in text[pos:m.start()]:
            w = char_width(ch)
            if acc + w > budget:
                return ''.join(out) + ellipsis
            out.append(ch)
            acc += w
        out.append(m.group(0))
        pos = m.end()
    for ch in text[pos:]:
        w = char_width(ch)
        if acc + w > budget:
            return ''.join(out) + ellipsis
        out.append(ch)
        acc += w
    return ''.join(out)


def _tokens(text: str):
    """切成 (片段, 宽度) —— ANSI 序列宽度记 0。"""
    pos = 0
    for m in ANSI_RE.finditer(text):
        for ch in text[pos:m.start()]:
            yield ch, char_width(ch)
        yield m.group(0), 0
        pos = m.end()
    for ch in text[pos:]:
        yield ch, char_width(ch)


def wrap_display(text: str, width: int) -> List[str]:
    """按显示宽度折行，ANSI 颜色码零宽且不会被切断。

    优先在空格处断行；一整个长 token（比如 URL、JSON）放不下时硬断。
    """
    width = max(1, width)
    if not text:
        return ['']
    lines: List[str] = []
    cur: List[tuple] = []
    cur_w = 0
    for tok, w in _tokens(text):
        if w == 0:
            cur.append((tok, w))
            continue
        if cur_w + w <= width:
            cur.append((tok, w))
            cur_w += w
            continue
        # 放不下了：先从当前行里找最后一个空格作为断点
        space_at = None
        for i in range(len(cur) - 1, -1, -1):
            if cur[i][0] == ' ':
                space_at = i
                break
        if space_at is not None and space_at > 0:
            head = cur[:space_at]
            tail = cur[space_at + 1:]
            lines.append(''.join(t for t, _ in head).rstrip())
            # 注意：tail 之后的那个 token 还没放进去，必须接上，否则会吞字
            cur = tail + [(tok, w)]
            cur_w = sum(x for _, x in tail) + w
            continue
        if cur:
            lines.append(''.join(t for t, _ in cur).rstrip())
            cur, cur_w = [(tok, w)], w
            continue
        # 单字符就超宽（宽度设得太小）—— 硬塞，避免死循环
        cur.append((tok, w))
        cur_w += w
    if cur:
        lines.append(''.join(t for t, _ in cur).rstrip())
    return lines or ['']


# ---------------------------------------------------------------------------
# 盒子几何
# ---------------------------------------------------------------------------

MIN_TOTAL = 44
MAX_TOTAL = 76


# 模糊宽度字符 -> 等宽 ASCII。
# 为什么要换：`· ● ◆ → …` 在不同终端/字体下，一个按 1 列画、一个按 2 列画，
# 没有任何算法能同时满足两边。换成 ASCII 后宽度**确定是 1 列**，边框不可能歪。
# 颜色不动，所以观感还在。REVIEWAGENT_FRAME_SAFE=0 可关掉（关掉有歪的风险）。
_SAFE_MAP = (
    ('\u00b7', '|'),      # ·
    ('\u2022', '|'),      # •
    ('\u25cf', '*'),      # ●
    ('\u25c6', '*'),      # ◆
    ('\u25c7', '*'),      # ◇
    ('\u258c', '|'),      # ▌
    ('\u2192', '->'),     # →
    ('\u2190', '<-'),     # ←
    ('\u2026', '...'),    # …
    ('\u2014', '-'),      # —
    ('\u2013', '-'),      # –
    ('\u201c', '"'), ('\u201d', '"'),
    ('\u2018', "'"), ('\u2019', "'"),
    ('\u2460', '(1)'), ('\u2461', '(2)'), ('\u2462', '(3)'),
    ('\u2463', '(4)'), ('\u2464', '(5)'), ('\u2465', '(6)'),
    ('\u2466', '(7)'), ('\u2467', '(8)'), ('\u2468', '(9)'),
    ('\u00d7', 'x'),      # ×
    ('\u2605', '*'), ('\u2606', '*'),   # ★ ☆
    ('\u2726', '*'), ('\u2727', '*'),   # ✦ ✧
    ('\u2191', '^'), ('\u2193', 'v'),   # ↑ ↓
    ('\u2139', 'i'),      # ℹ
    ('\u26a0', '!'),      # ⚠
)


def _frame_safe_on() -> bool:
    v = (os.environ.get('REVIEWAGENT_FRAME_SAFE') or '').strip().lower()
    return v not in ('0', 'off', 'false', 'no')


_FRAME_SAFE = _frame_safe_on()


def frame_safe(text: str) -> str:
    """把框内文字里的模糊宽度字符换成等宽 ASCII，保证右边框不会歪。"""
    if not _FRAME_SAFE:
        return text or ''
    out = text or ''
    for a, b in _SAFE_MAP:
        out = out.replace(a, b)
    return out


def check_frame(title: str, lines: List[str], total: int = 0) -> bool:
    """自检：一个盒子的所有行宽度必须相等。

    REVIEWAGENT_FRAME_DEBUG=1 时，不齐就把实际宽度打到 stderr ——
    以后再出现歪的边框，打开这个开关就能立刻定位是哪个盒子、哪一行。
    """
    total = total or total_width()
    bad = [display_width(ln) for ln in lines]
    off = [(i, w) for i, w in enumerate(bad) if w != total]
    if off and (os.environ.get('REVIEWAGENT_FRAME_DEBUG') or '') == '1':
        sys.stderr.write(f'[frame] 宽度不齐 title={title!r} 应为 {total}，实际 {bad}\n')
    return not off


def total_width() -> int:
    """盒子总宽度（含左右边框）。所有盒子共用，竖线才能对齐。"""
    try:
        cols = shutil.get_terminal_size(fallback=(80, 24)).columns
    except OSError:
        cols = 80
    if not cols:
        cols = 80
    return max(MIN_TOTAL, min(cols - 2, MAX_TOTAL))


def content_width(total: int = 0) -> int:
    """盒子内部可用宽度：`│ ` + 正文 + ` │`，所以比总宽少 4 列。"""
    return max(10, (total or total_width()) - 4)


def _clip_title(title: str, limit: int) -> str:
    return truncate_display(title, max(4, limit))


def top_border(title: str = '', total: int = 0, paint=None) -> str:
    """`╭─ 标题 ──────╮`"""
    total = total or total_width()
    inner = total - 2
    if not title:
        line = '╭' + '─' * inner + '╮'
    else:
        seg = ' ' + _clip_title(frame_safe(title), inner - 8) + ' '
        dashes = max(2, inner - 3 - display_width(seg))
        line = '╭─' + seg + '─' * dashes + '╮'
        # 标题被裁过之后仍可能差一列，用补/删兜底
        diff = total - display_width(line)
        if diff > 0:
            line = line[:-1] + '─' * diff + line[-1]
        elif diff < 0:
            line = line[:len(line) - 1 + diff] + line[-1]
    return paint(line) if paint else line


def bottom_border(note: str = '', total: int = 0, paint=None) -> str:
    """`╰──────╯`；带 note 时写成 `╰─ note ─────╯`"""
    total = total or total_width()
    inner = total - 2
    if not note:
        line = '╰' + '─' * inner + '╯'
    else:
        seg = ' ' + _clip_title(frame_safe(note), inner - 8) + ' '
        dashes = max(2, inner - 3 - display_width(seg))
        line = '╰─' + seg + '─' * dashes + '╯'
        diff = total - display_width(line)
        if diff > 0:
            line = line[:-1] + '─' * diff + line[-1]
        elif diff < 0:
            line = line[:len(line) - 1 + diff] + line[-1]
    return paint(line) if paint else line


def row_lines(text: str = '', total: int = 0, paint=None, indent: str = '') -> List[str]:
    """把一段正文包成盒子里的行：自动折行 + 右侧补齐到边框列。

    默认对正文做 frame_safe（把 · ● ◆ → … 换成等宽 ASCII），因为正文
    和边框必须同宽；`safe=False` 可原样输出（自己确定内容里没有模糊字符时）。
    """
    total = total or total_width()
    avail = content_width(total)
    body_width = max(1, avail - display_width(indent))
    out: List[str] = []
    parts = wrap_display(text or '', body_width)
    for i, part in enumerate(parts):
        lead = indent if i == 0 else ' ' * display_width(indent)
        body = frame_safe(lead + part)
        if display_width(body) > avail:  # 防御性截断，正常折行不会走到
            body = truncate_display(body, avail)
        line = '│ ' + pad_display(body, avail) + ' │'
        out.append(paint(line) if paint else line)
    if not out:
        line = '│ ' + ' ' * avail + ' │'
        out.append(paint(line) if paint else line)
    return out


def blank_row(total: int = 0, paint=None) -> str:
    total = total or total_width()
    line = '│ ' + ' ' * content_width(total) + ' │'
    return paint(line) if paint else line


def hr(total: int = 0) -> str:
    total = total or total_width()
    return '─' * (total - 2)


# ---------------------------------------------------------------------------
# 光标绝对定位（CUP）渲染 —— 唯一能绕开字体差异的方案
#
# 补空格对齐的前提是「一个汉字正好占 2 个西文格」。这取决于终端**字体**：
#   宋体 / 新宋体 —— ASCII 半角、汉字全角，严格 1:2，所以 Windows 控制台能对齐
#   Linux 默认（DejaVu Sans Mono 0.6em + Noto CJK 1em）—— 约 1.66 格，会歪
#   macOS 默认（Menlo 0.6em + 苹方 1em）—— 同样约 1.66 格，会歪
#
# 宽度是字体画的，程序改不了，所以「算法再准也压不住」。CUP 换了个思路：
# 每行先把光标移到第 1 列画左边框和内容，再移到第 total 列画右边框。
# 右边框落在**指定列号**上，不再依赖「内容占了多宽」—— 任何字体都对得齐。
#
# 代价（也是它的适用条件）：
#   1. 需要 ANSI / VT 支持。Windows 10+ 控制台、Windows Terminal、所有 Unix 终端都行
#   2. 内容若超过可用宽度会盖住右边框，所以截断必须按最坏情况（每字符 2 格）算
#   3. 输出被重定向到文件时是一堆控制符，所以只在 isatty 时启用
# ---------------------------------------------------------------------------

_CUP_TEMPLATE = '\x1b[{};{}H'
_CUF_TEMPLATE = '\x1b[{}C'


def cup(row: int, col: int) -> str:
    """把光标移到第 row 行、第 col 列（都从 1 开始）。"""
    return _CUP_TEMPLATE.format(max(1, int(row)), max(1, int(col)))


def cuf(cols: int) -> str:
    """光标向右移动 cols 列（不换行）。"""
    return _CUF_TEMPLATE.format(max(0, int(cols)))


def cup_supported() -> bool:
    """绝对定位只在真终端里有意义；输出重定向或没有 ANSI 时老老实实补空格。"""
    try:
        if not (hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()):
            return False
    except Exception:
        return False
    mode = (os.environ.get('REVIEWAGENT_RENDER') or '').strip().lower()
    return mode != 'pad'


_ANSI_SEQ = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def safety_truncate(text: str, width: int) -> str:
    """按「每个字符最多占 2 格」截断。

    这是定位渲染的关键：不猜字体，直接按最坏情况留余量，
    保证内容无论被画成多宽都不会盖到右边框那一列。

    颜色码（ANSI 转义）宽度记 0 且原样保留 —— 按普通字符截会把
    `\\x1b[38;5;37m` 切成两半，终端就会吐出乱码。
    如果截断时有未闭合的颜色，末尾补一个 RESET。
    """
    if width <= 0:
        return ''
    used = 0
    out: List[str] = []
    i = 0
    n = len(text)
    cut = False
    while i < n:
        m = _ANSI_SEQ.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = text[i]
        w = 2 if ord(ch) > 0x7F else 1
        if used + w > width:
            cut = True
            break
        out.append(ch)
        used += w
        i += 1
    result = ''.join(out)
    if cut and '\x1b[' in result:
        result += '\x1b[0m'
    return result


def box_rows(top: str, bodies: List[str], bottom: str,
             total: int = 0) -> List[str]:
    """生成「右边框按列定位」的盒子行。

    三段都用同一招：画到差不多，然后 `\\r` 回行首、右移 (total-1) 列，
    再补上收尾字符。

        上/下边框：`╭─ 标题 ──────` → 回车 → 右移 → 清行尾 → `╮`
        正文行  ：`│ 内容`       → 回车 → 右移 → `│`

    为什么边框也要这么做：
        边框字符串是按「中文占 2 格」拼出来的，若字体把汉字画成 1.66 格，
        含中文标题的上边框就会比正文短 2 格，`╮` 落不到正文的右边框上。
        先多画几段 `─` 再清行尾，右端就精确落在第 total 列。

    为什么用 `\\r` + 右移，而不是 `\\x1b[row;colH` 绝对定位：
        绝对定位要知道当前行号，输出一旦让屏幕滚动，行号就错了。
        「回到行首再右移固定列数」只关心列，和行号、滚动都无关。

    返回的列表每项都带换行，可以逐项 write。
    """
    total = total or total_width()
    inner = max(1, total - 3)          # 第 1 列 │、第 2 列空格、内容从第 3 列起
    tail = total - 1                    # 收尾字符所在列
    out: List[str] = []

    # 上边框：多画 12 个 ─ 保证一定盖过目标列，再用 \x1b[K 把多余的清掉
    if top:
        out.append(top[:-1] + '─' * 12)
        out.append('\r' + cuf(tail) + '\x1b[K' + top[-1] + '\n')

    for body in bodies:
        out.append('│ ' + safety_truncate(body, inner))
        out.append('\r' + cuf(tail) + '│\n')

    # 下边框同理
    if bottom:
        out.append(bottom[:-1] + '─' * 12)
        out.append('\r' + cuf(tail) + '\x1b[K' + bottom[-1] + '\n')

    return out


def box_anchor(top: str, bodies: List[str], bottom: str,
               total: int = 0) -> str:
    """同 box_rows，但直接返回一整段字符串，方便一次 write。"""
    return ''.join(box_rows(top, bodies, bottom, total))


def anchor_line(body: str, total: int = 0, paint=None) -> str:
    """生成「一行内容 + 定位右边框 + 换行」—— 供流式输出（思考面板）逐行用。"""
    total = total or total_width()
    inner = max(1, total - 3)
    p = paint if paint else (lambda s: s)
    return (p('│ ') + safety_truncate(body, inner - 1) + ' '
            + p('\r' + cuf(total - 1) + '│') + '\n')


def border_line(text: str, total: int = 0) -> str:
    """生成「一条边框 + 结束换行」，右端用定位钉在第 total 列。

    含中文标题时，边框字符串按「中文 2 格」拼出来，若字体只画 1.66 格
    就会短一截；多画几段横线再清行尾，可以保证右端精确落位。
    """
    total = total or total_width()
    inner = max(1, total - 3)
    if not text:
        return '─' * (total - 2) + '\n'
    return (text[:-1] + '─' * 12
            + '\r' + cuf(total - 1) + '\x1b[K' + text[-1] + '\n')


DIVIDER = '\x00divider\x00'


def emit_box(title: str = '', bodies: Optional[List[str]] = None, note: str = '',
             total: int = 0, paint=None, stream=None) -> None:
    """按当前终端能力画一个盒子并直接输出。

    能定位就定位（右边框钉在固定列，换字体也不会歪）；
    不能定位（输出被重定向、或设了 REVIEWAGENT_RENDER=pad）就退回补空格。

    bodies 里放一个 `DIVIDER` 会在那个位置画一条 `├──┤` 分隔线。
    """
    total = total or total_width()
    bodies = bodies or []
    p = paint if paint else (lambda s: s)
    out = stream if stream is not None else sys.stdout
    top = top_border(title, total)
    bottom = bottom_border(note, total)
    inner = max(1, total - 3)
    tail = total - 1

    if not cup_supported():
        out.write(p(top) + '\n')
        avail = content_width(total)
        for body in bodies:
            if body == DIVIDER:
                out.write(p('├' + '─' * (total - 2) + '┤') + '\n')
                continue
            out.write(p('│ ' + pad_display(frame_safe(body), avail) + ' │') + '\n')
        out.write(p(bottom) + '\n')
        try:
            out.flush()
        except Exception:
            pass
        return

    chunks = [p(top[:-1] + '─' * 12),
              p('\r' + cuf(tail) + '\x1b[K' + top[-1]) + '\n']
    for body in bodies:
        if body == DIVIDER:
            # 分隔线：中间接一竖，右端是 ┤
            chunks.append(p('├' + '─' * (total - 2 + 10)))
            chunks.append(p('\r' + cuf(tail) + '\x1b[K┤') + '\n')
            continue
        # 内容自己带颜色，只给左右边框套 paint —— 整行包一层会把内容的
        # RESET 提前吃掉，右边框就变色了。末尾留 1 空格保持右边距。
        chunks.append(p('│ ') + safety_truncate(frame_safe(body), inner - 1) + ' ')
        chunks.append(p('\r' + cuf(tail) + '│') + '\n')
    chunks.append(p(bottom[:-1] + '─' * 12))
    chunks.append(p('\r' + cuf(tail) + '\x1b[K' + bottom[-1]) + '\n')
    out.write(''.join(chunks))
    try:
        out.flush()
    except Exception:
        pass


def _self_test() -> None:  # pragma: no cover - 手动排查用
    """终端宽度自检：找不到问题在哪时跑 `python -m scripts.term_frame`。

    会打印一串被盒子包起来的样例，如果哪行的右边框对不齐，就说明
    那个字符的宽度判断和你的终端不一致 —— 换字体或设
    REVIEWAGENT_AMBIGUOUS=1 再试。
    """
    total = total_width()
    print(f'终端列数推断宽度 = {total}（可用 REVIEWAGENT_AMBIGUOUS=0/1 调整模糊字符）\n')
    print(top_border('宽度自检', total))
    for s in ('纯 ASCII 测试 123',
              '中文与英文混排 mixed 测试',
              '箭头 → 与中点 · 与省略号 …',
              '制表符 ─ │ ╭ ╮ ╰ ╯ 与菱形 ◆',
              '超长内容 ' + 'x' * 120):
        for line in row_lines(s, total):
            print(line)
    print(bottom_border('右边框应全部对齐', total))


if __name__ == '__main__':  # pragma: no cover
    _self_test()
