#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""边框体检：不需要 API Key，把三处盒子各画一遍并逐行量宽度。

用法：
    python -m scripts.frame_doctor
    python -m scripts.frame_doctor --plain     # 不用制表符，改用 ASCII 边框

每一行右边打印「显示宽度」。只要同一块的所有行宽度相同，竖线就对齐；
出现红色 ▸ 的行就是歪的那一行。
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import console_safe
from scripts import term_frame as tf

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def _plain_mode() -> bool:
    return '--plain' in sys.argv


def _anchor_mode() -> bool:
    return '--anchor' in sys.argv


def _anchor_demo() -> int:
    """定位渲染演示：右边框按列固定，不依赖字体宽度。

    普通模式靠「补空格把右边框推到第 N 列」，补多少取决于算出来的宽度；
    字体把汉字画成 1.66 格而不是 2 格时，右边框就会往右跑。
    这里改成每行画完内容后 `\\r` 回行首、右移固定列数再画 `│`，
    边框落在指定列上，跟字体无关。
    """
    total = tf.total_width()
    print('=' * 60)
    print(' 定位渲染演示（--anchor）')
    print('=' * 60)
    print(f' 目标宽度 : {total} 列')
    print(' 原理：每行画完内容后回车到行首，右移固定列数再画右边框')
    print()

    cases = [
        ('短行', ['短']),
        ('中英混排', ['这是一行中文与 English 混排的内容']),
        ('含符号', ['日常对话 · 读取 review.py · 命中 733 条记录']),
        ('超长行（会自动截断）',
         ['这一行故意写得非常长，用来验证截断不会盖住右边框，'
          '即使字体把汉字画得比预期更宽也一样安全']),
    ]
    for title, bodies in cases:
        sys.stdout.write(tf.box_anchor(
            tf.top_border(title, total), bodies,
            tf.bottom_border('', total), total=total))
        print()

    print('=' * 60)
    print(' 判读方法：上面每个盒子的右边框应当都在同一条竖线上。')
    print(' 如果都在 —— 说明这个方案不受字体影响，换系统也不用改设置。')
    print(' 如果出现乱码控制符 —— 说明终端不支持 ANSI，改用普通模式。')
    print('=' * 60)
    return 0


def _capture(fn, *a, **kw) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **kw)
    return buf.getvalue()


def report(name: str, block: str) -> bool:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        print(f'  {name}: 没有输出')
        return False
    widths = [tf.display_width(ln) for ln in lines]
    target = max(set(widths), key=widths.count)
    ok = len(set(widths)) == 1
    print(f'\n{name}  目标宽度 = {target}')
    for ln, w in zip(lines, widths):
        mark = '  ' if w == target else '▸ '
        print(f'  {mark}{w:3d} |{ANSI.sub("", ln)}|')
    print(f'  → {"OK  全部对齐" if ok else "NG  有 %d 行不齐" % sum(1 for w in widths if w != target)}')
    return ok


def main() -> int:
    # 先兜住编码：GBK 控制台里 ✅ ❌ 这类字符会让 Python 直接抛
    # UnicodeEncodeError 退出，连体检报告都看不到。
    console_safe.harden_console()
    if _anchor_mode():
        return _anchor_demo()
    total = tf.total_width()
    print('=' * 60)
    print(' ReviewAgent 边框体检')
    print('=' * 60)
    print(f' 终端列数推断宽度 : {total}')
    print(f' 模糊宽度策略     : {"2 列" if tf._AMB_WIDE else "1 列"}'
          f'  (REVIEWAGENT_AMBIGUOUS)')
    print(f' 框内 ASCII 化    : {"开" if tf._FRAME_SAFE else "关"}'
          f'  (REVIEWAGENT_FRAME_SAFE)')

    results = []

    # 1) 输入框
    if _plain_mode():
        import scripts.chat_input as ci
        old = ci._can_box
        ci._can_box = lambda: False
        try:
            block = _capture(ci.print_input_frame, network='auto',
                             chat_mode='auto', session_lane='chat')
        finally:
            ci._can_box = old
    else:
        import scripts.chat_input as ci
        old = ci._can_box
        ci._can_box = lambda: True
        try:
            block = _capture(ci.print_input_frame, network='auto',
                             chat_mode='auto', session_lane='chat')
        finally:
            ci._can_box = old
    results.append(report('① 输入提示框', block))

    # 2) 思考面板（整段捕获：开场 + 进度 + 收尾，否则只看得到最后两行）
    from scripts.think_ui import begin_think, end_think, think_progress

    def _think():
        begin_think('思考中')
        think_progress('日常对话（跳过 Infra 工具）· 读取 review.py · 命中 733 条知识库记录')
        think_progress('组装上下文')
        end_think('回答就绪')

    block = _capture(_think)
    results.append(report('② 思考面板', block))

    # 3) Agent 回复框（带长 URL，最容易把边框顶破）
    from scripts.md_term import print_markdown_box
    body = (
        'AI 调用失败，已保留获取的上下文，可以重试。\n'
        'Error: HTTP 400 Bad Request — {"error":{"message":"The supported API model names are '
        'deepseek-flash, deepseek-v4-pro, but you passed deepseek-v3.2."}}（常见原因：模型 ID 不支持）'
    )
    block = _capture(print_markdown_box, body, title='Agent')
    results.append(report('③ Agent 回复框', block))

    # 4) chat_v2 的欢迎卡（曾经硬编码 70 列）
    try:
        # 先 flush：某些模块在导入时会动 sys.stdout，未刷出的内容会丢
        sys.stdout.flush()
        import chat_v2
        block = _capture(lambda: print(chat_v2.UI.box(
            '能做什么',
            chat_v2.UI.bullet('粘贴代码 -> 直接审查') + '\n'
            + chat_v2.UI.bullet('发 GitHub 链接 -> 分析 PR / Issue'),
        )))
        results.append(report('④ 欢迎卡（chat_v2.UI.box）', block))
    except Exception as exc:                       # noqa: BLE001
        print(f'\n④ 欢迎卡: 跳过（{exc}）')

    print('\n' + '=' * 60)
    if all(results):
        print(f' 结论：{len(results)} 块全部对齐')
    else:
        print(f' 结论：{sum(results)}/{len(results)} 块对齐，其余需排查')
        print(' 排查建议：')
        print('   1) 右框偏右 → 终端把某个字符画得比代码估计的宽，')
        print('      试着设 REVIEWAGENT_AMBIGUOUS=0 再跑一次')
        print('   2) 只有中文行歪 → 换等宽字体（推荐 NSimSun / 新宋体）')
    print('=' * 60)
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
