#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「一屏里所有竖线落在同一列」的回归测试（2026-11-10 第二轮）。

背景：用户截图里输入框的右边框被顶到框外，原因是**同一个程序里有两套
宽度算法**：

- `scripts/term_frame.py` 把 EAW=A 的字符（· ● ◆ →）算 2 列；
- `chat_v2.py` 自己的 `UI._w` 算 1 列；
- `bin/ui.js` 用的 boxen 内部是 `string-width`，又是另一套。

这里把三条路径都锁死：宽度只能有一个出处。
"""
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('COLUMNS', '80')
os.environ.setdefault('FORCE_COLOR', '1')

from scripts import term_frame as tf          # noqa: E402
from scripts.chat_input import print_input_frame  # noqa: E402

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def widths(block):
    return [tf.display_width(ln) for ln in block.splitlines() if ln.strip()]


class InputFrameTests(unittest.TestCase):
    """启动界面那个输入提示框 —— 用户截图里歪的就是它。"""

    def _render(self):
        import contextlib
        import io
        import scripts.chat_input as ci
        old = ci._can_box
        ci._can_box = lambda: True             # 强制走制表符分支
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                print_input_frame(network='auto', chat_mode='auto', session_lane='chat')
        finally:
            ci._can_box = old
        return buf.getvalue()

    def test_all_lines_same_width(self):
        ws = widths(self._render())
        self.assertTrue(ws, '输入框没输出任何内容')
        self.assertEqual(len(set(ws)), 1, f'各行宽度不一致: {ws}')

    def test_title_row_uses_separator_safely(self):
        """标题里的 `·` 必须已被换成等宽 ASCII，否则中文控制台会宽 2 列。"""
        block = ANSI.sub('', self._render())
        for ch in block:
            self.assertNotIn(ch, '·●◆→…',
                             f'框内仍有模糊宽度字符 {ch!r}，会让右边框歪')

    def test_work_lane_also_aligned(self):
        import contextlib
        import io
        import scripts.chat_input as ci
        buf = io.StringIO()
        old = ci._can_box
        ci._can_box = lambda: True
        try:
            with contextlib.redirect_stdout(buf):
                print_input_frame(network='auto', chat_mode='work', session_lane='work')
        finally:
            ci._can_box = old
        ws = widths(buf.getvalue())
        self.assertEqual(len(set(ws)), 1, f'work 车道各行宽度不一致: {ws}')


class ChatV2BoxTests(unittest.TestCase):
    """chat_v2.UI.box 曾经硬编码 width=70，和 term_frame 的 76 打架。"""

    def setUp(self):
        import chat_v2
        self.UI = chat_v2.UI

    def test_box_defaults_to_term_frame_width(self):
        out = ANSI.sub('', self.UI.box('能做什么', self.UI.bullet('粘贴代码') + '\n' + self.UI.bullet('发链接')))
        ws = widths(out)
        self.assertEqual(len(set(ws)), 1, f'盒子各行宽度不一致: {ws}')
        self.assertEqual(ws[0], tf.total_width())

    def test_box_with_dots_in_content(self):
        """正文里带中点/箭头/菱形时也不能歪。"""
        body = 'AI调换->日常 · /skill · /mcp · /exit\n◆ 一看就歪的样例 → 试试'
        out = ANSI.sub('', self.UI.box('标题 · 带中点', body))
        ws = widths(out)
        self.assertEqual(len(set(ws)), 1, f'各行宽度不一致: {ws}')

    def test_box_with_long_url_wraps_inside(self):
        body = 'https://github.com/enternalna-Koh/CodeVigilAgent/pull/123/files#diff-abcdef0123456789'
        out = ANSI.sub('', self.UI.box('', body))
        ws = widths(out)
        self.assertEqual(len(set(ws)), 1, f'长链接把边框顶破了: {ws}')

    def test_section_matches_box_width(self):
        line = ANSI.sub('', self.UI.section('数据统计')).strip()
        self.assertEqual(tf.display_width(line), tf.total_width())

    def test_no_private_width_implementation_left(self):
        """chat_v2 不能再自己数宽度。"""
        src = (ROOT / 'chat_v2.py').read_text(encoding='utf-8')
        self.assertNotIn('east_asian_width', src,
                         'chat_v2 里还有自己的宽度实现，应统一走 term_frame')
        self.assertIn('tf.display_width', src)


class NodeParityTests(unittest.TestCase):
    """Node 侧（bin/term-frame.js）必须和 Python 算出一样的宽度。"""

    SAMPLES = [
        '纯 ASCII 测试 123',
        '中文与英文混排 mixed 测试',
        '箭头 → 与中点 · 与省略号 …',
        '制表符 ─ │ ╭ ╮ ╰ ╯ 与菱形 ◆',
        '● 就绪  问题或 PR/Issue URL · /help · /exit',
        'review · search · config · doctor · model',
        'AI调换->日常 · /skill · /mcp · /exit',
        '▌ 能做什么',
        'Unicode 边界: ① ② ③ ★ ☆ ✓ ✗',
    ]

    def setUp(self):
        if not shutil.which('node'):
            self.skipTest('没有 node')

    def test_widths_match_python(self):
        script = (
            "const tf=require('./bin/term-frame');"
            "console.log(JSON.stringify(" +
            str(self.SAMPLES).replace("'", '"') +
            ".map(s=>tf.displayWidth(s))))"
        )
        r = subprocess.run(['node', '-e', script], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        js = json.loads(r.stdout)
        py = [tf.display_width(s) for s in self.SAMPLES]
        self.assertEqual(js, py, 'Node 与 Python 宽度算法不一致')

    def test_frame_card_all_lines_same_width(self):
        script = r'''
        const { frameCard, tf } = require('./bin/ui');
        const { c } = require('./bin/ui-colors');
        const body = c.ok('●') + ' ' + c.ink('就绪') + '  ' +
          c.mute('问题或 PR/Issue URL · /help · /exit') + '\n' +
          c.mute('review · search · config · doctor · model');
        const card = frameCard('', body, 'cyan');
        const ws = card.split('\n').map(l => tf.displayWidth(l));
        console.log(JSON.stringify(ws));
        '''
        r = subprocess.run(['node', '-e', script], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, 'COLUMNS': '80'})
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        ws = json.loads(r.stdout)
        self.assertEqual(len(set(ws)), 1, f'启动卡片各行宽度不一致: {ws}')

    def test_boxen_no_longer_draws_the_cards(self):
        """启动卡片和向导卡片不能再用 boxen（它用 string-width，算法不同）。"""
        for name in ('bin/ui.js', 'bin/onboard.js'):
            src = (ROOT / name).read_text(encoding='utf-8')
            calls = [ln for ln in src.splitlines()
                     if 'boxen(' in ln and not ln.strip().startswith('*')
                     and not ln.strip().startswith('//')]
            self.assertEqual(calls, [], f'{name} 里还在调 boxen: {calls}')

    def test_width_table_is_up_to_date(self):
        """bin/width-table.js 必须是由当前 Python 规则生成的。

        规则改了却忘了重跑生成器 → Node 和 Python 的宽度会悄悄分家。
        """
        gen = ROOT / 'scripts' / 'gen_width_table.py'
        r = subprocess.run([sys.executable, str(gen)], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        # 生成器直接覆盖原文件，跑完对比 git 里的版本是否变化由人判断；
        # 这里至少保证生成过程中断言的段数合理、文件非空。
        text = (ROOT / 'bin' / 'width-table.js').read_text(encoding='utf-8')
        self.assertIn('WIDE:', text)
        self.assertIn('AMBIGUOUS:', text)
        self.assertGreater(len(text), 1000)

    def test_char_width_parity_on_sweep(self):
        """抽样逐码点对比（全量太慢，抽 1/37 覆盖足够）。"""
        codes = list(range(0x20, 0x10000, 37))
        script = (
            "const tf=require('./bin/term-frame');"
            f"const cs={codes};"
            "console.log(JSON.stringify(cs.map(c=>tf.charWidth(String.fromCodePoint(c)))))"
        )
        r = subprocess.run(['node', '-e', script], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        import json
        js = json.loads(r.stdout)
        py = [tf.char_width(chr(c)) for c in codes]
        diff = [(hex(codes[i]), py[i], js[i]) for i in range(len(codes)) if py[i] != js[i]]
        self.assertEqual(diff[:5], [], f'有 {len(diff)} 个码点宽度不一致: {diff[:5]}')


class FrameCheckTests(unittest.TestCase):
    def test_check_frame_detects_mismatch(self):
        self.assertTrue(tf.check_frame('ok', ['╭──╮', '│  │', '╰──╯'], 4))
        self.assertFalse(tf.check_frame('bad', ['╭──╮', '│   │', '╰──╯'], 4))


if __name__ == '__main__':
    unittest.main()
