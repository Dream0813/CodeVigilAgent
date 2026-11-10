"""边框对齐的回归测试：所有盒子的每一行都必须是同一显示宽度。"""
import io
import contextlib
import unittest

from scripts import term_frame as tf
from scripts.md_term import print_markdown_box
from scripts.think_ui import begin_think, think_progress, end_think


class WidthRulesTests(unittest.TestCase):
    def test_ascii_is_one_column(self):
        self.assertEqual(tf.display_width('abc123'), 6)

    def test_cjk_is_two_columns(self):
        self.assertEqual(tf.display_width('中文'), 4)
        self.assertEqual(tf.display_width('中文abc'), 7)

    def test_box_drawing_is_one_column(self):
        self.assertEqual(tf.display_width('╭─╮│╰╯'), 6)

    def test_middle_dot_follows_ambiguous_policy(self):
        """`·` 是 EAW=A：中文控制台按 2 列画，所以默认算 2 列。

        曾经算成 1 列，导致 `AI调换->日常 · /skill · /mcp · /exit`
        这种带 3 个中点的行比边框宽 3 列，右边框被顶到框外。
        """
        self.assertEqual(tf.display_width('·'), 2)

    def test_frame_safe_removes_ambiguous_chars(self):
        """框内文字经过 frame_safe 后，每个字符的宽度都必须是确定的。

        「确定」= ASCII(1 列) / 中日韩全角(2 列) / 制表符(1 列)。
        剩下的一律是 EAW=A 的模糊字符，必须已被替换掉。
        """
        import unicodedata
        raw = '● 就绪 · /help ◆ → … 完成'
        safe = tf.frame_safe(raw)
        for ch in safe:
            o = ord(ch)
            eaw = unicodedata.east_asian_width(ch)
            ok = (o < 0x80) or (eaw in ('W', 'F')) or (0x2500 <= o <= 0x257F)
            self.assertTrue(ok, f'frame_safe 之后仍残留模糊字符 {ch!r}(U+{o:04X}, EAW={eaw})')
        # ASCII 部分必须严格 1 字节 1 列
        ascii_part = ''.join(c for c in safe if ord(c) < 0x80)
        self.assertEqual(tf.display_width(ascii_part), len(ascii_part))

    def test_frame_safe_can_be_disabled(self):
        import os
        old = os.environ.get('REVIEWAGENT_FRAME_SAFE')
        os.environ['REVIEWAGENT_FRAME_SAFE'] = '0'
        try:
            import importlib
            importlib.reload(tf)
            self.assertEqual(tf.frame_safe('·'), '·')
        finally:
            if old is None:
                os.environ.pop('REVIEWAGENT_FRAME_SAFE', None)
            else:
                os.environ['REVIEWAGENT_FRAME_SAFE'] = old
            import importlib
            importlib.reload(tf)

    def test_ansi_codes_are_zero_width(self):
        self.assertEqual(tf.display_width('\033[92m绿色\033[0m'), 4)


class WrapTests(unittest.TestCase):
    def test_wrap_keeps_every_character(self):
        text = '这段代码在昇腾 NPU 上会因 device 侧未同步导致精度问题，建议加 torch.npu.synchronize() 再取结果'
        lines = tf.wrap_display(text, 20)
        self.assertTrue(all(tf.display_width(l) <= 20 for l in lines))
        joined = ''.join(lines).replace(' ', '')
        self.assertEqual(joined, text.replace(' ', ''))

    def test_long_token_is_hard_broken_not_lost(self):
        token = 'x' * 50
        lines = tf.wrap_display('前缀 ' + token, 10)
        self.assertEqual(''.join(lines).replace(' ', ''), '前缀' + token)

    def test_no_character_is_dropped_at_space_boundary(self):
        lines = tf.wrap_display('aaaa bbbb cccc dddd', 9)
        self.assertEqual(''.join(lines).replace(' ', ''), 'aaaabbbbccccdddd')


class FrameGeometryTests(unittest.TestCase):
    def _assert_uniform(self, lines):
        total = tf.total_width()
        widths = {tf.display_width(l) for l in lines if l.strip()}
        self.assertEqual(widths, {total}, f'行宽不一致: {widths}')

    def test_borders_match_content_rows(self):
        total = tf.total_width()
        lines = [tf.top_border('标题', total)]
        lines += tf.row_lines('中文混排 mixed 测试', total)
        lines += tf.row_lines('x' * 300, total)
        lines.append(tf.bottom_border('备注', total))
        self._assert_uniform(lines)

    def test_markdown_box_rows_align(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            print_markdown_box(
                '### 标题\n\n中文正文 mixed text ' + 'y' * 200 + '\n\n- 列表项\n\n```py\nprint(1)\n```',
                'Agent',
            )
        self._assert_uniform(buf.getvalue().splitlines())

    def test_think_panel_rows_align(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            begin_think('思考中')
            think_progress('日常对话（跳过 Infra 工具）')
            think_progress('很长的步骤说明 ' + 'z' * 150)
            end_think('回答就绪')
        self._assert_uniform(buf.getvalue().splitlines())


if __name__ == '__main__':
    unittest.main()
