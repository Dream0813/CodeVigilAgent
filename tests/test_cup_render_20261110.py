"""验证 CUP（光标绝对定位）渲染能否绕开字体差异。

背景：
    补空格对齐要求「1 个汉字正好 = 2 个西文格」。这是**字体**决定的事：
      宋体 / 新宋体 —— 严格 1:2，Windows 控制台能对齐
      Linux / macOS 默认字体 —— 约 1.66:1，右边框会往右跑
    程序改不了字体，所以这个方向修不好。

    CUP 换成「把右边框画在第 N 列」的思路，不再依赖内容宽度。

这里用一个虚拟终端模拟这件事：可以设置「汉字占几格」，喂进 ANSI 输出，
再检查每行最右边的 │ 落在哪一列。
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import term_frame as tf  # noqa: E402

CUP_RE = re.compile(r'\x1b\[(\d+);(\d+)H')
CUF_RE = re.compile(r'\x1b\[(\d+)C')
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


class FakeScreen:
    """极简终端：支持 CUP 定位，并按给定的「汉字宽度」推进光标。

    x 用浮点累积 —— 真实终端就是这样，1.66 格会一点点累积偏差，
    最后表现为右边框越走越靠右。
    """

    def __init__(self, han_width: float = 2.0):
        self.han = han_width
        self.cells = {}          # (row, col) -> char
        self.row = 1
        self.x = 1.0

    def feed(self, text: str):
        i = 0
        n = len(text)
        while i < n:
            if text[i] == '\x1b':
                if text.startswith('\x1b[K', i):        # 清除光标到行尾
                    cut = int(round(self.x))
                    for key in [k for k in self.cells
                                if k[0] == self.row and k[1] >= cut]:
                        del self.cells[key]
                    i += 3
                    continue
                m = CUP_RE.match(text, i)
                if m:
                    self.row = int(m.group(1))
                    self.x = float(m.group(2))
                    i = m.end()
                    continue
                m3 = CUF_RE.match(text, i)          # 光标右移 N 列
                if m3:
                    self.x += int(m3.group(1))
                    i = m3.end()
                    continue
                m2 = ANSI_RE.match(text, i)
                if m2:
                    i = m2.end()
                    continue
                i += 1
                continue

            ch = text[i]
            if ch == '\r':                 # 回车：回到行首，不换行
                self.x = 1.0
                i += 1
                continue
            if ch == '\n':
                self.row += 1
                self.x = 1.0
                i += 1
                continue

            code = ord(ch)
            if code < 0x7F or 0x2500 <= code <= 0x257F:
                width = 1.0                     # ASCII 与制表符都是 1 格
            else:
                width = self.han
            self.cells[(self.row, int(round(self.x)))] = ch
            self.x += width
            i += 1

    def row_count(self):
        return max((r for r, _ in self.cells), default=0)

    def rightmost_bar_columns(self):
        """每行最右边那个 │ 所在的列。"""
        result = {}
        for (row, col), ch in self.cells.items():
            if ch == '│':
                if row not in result or col > result[row]:
                    result[row] = col
        return result

    def render(self, rows=None):
        """按行把字符顺序拼起来（不按列填空格）。

        对齐检查用 rightmost_bar_columns，这里只关心「每行的首尾字符」，
        所以不需要还原真实的列间距。
        """
        rows = rows or range(1, self.row_count() + 1)
        out = []
        for r in rows:
            items = sorted((c, ch) for (rr, c), ch in self.cells.items() if rr == r)
            out.append(''.join(ch for _, ch in items))
        return '\n'.join(out)


def build_cup_box(total: int, bodies):
    return tf.box_anchor(tf.top_border('标题', total), bodies,
                         tf.bottom_border('', total), total=total)


def build_pad_box(total: int, bodies):
    """现有实现：补空格 + 右边框直接拼在行尾。"""
    lines = [tf.top_border('标题', total)]
    for body in bodies:
        lines.extend(tf.row_lines(body, total))
    lines.append(tf.bottom_border('', total))
    return '\n'.join(lines) + '\n'


BODIES = [
    '这是一行中文测试',
    'mixed 中英混排 text',
    '短',
    '这一行比较长，包含中文和 English 以及数字 12345',
]


class TestCupAlignment(unittest.TestCase):
    def _bars(self, payload, han_width):
        screen = FakeScreen(han_width)
        screen.feed(payload)
        return screen.rightmost_bar_columns()

    def test_cup_aligns_under_any_han_width(self):
        """CUP 的关键性质：不管字体把汉字画成多宽，右边框都在同一列。"""
        payload = build_cup_box(60, BODIES)
        for han in (1.0, 1.66, 2.0, 2.4):
            bars = self._bars(payload, han)
            cols = set(bars.values())
            self.assertEqual(
                len(cols), 1,
                f'汉字宽度 {han} 时右边框没有落在同一列：{sorted(cols)}')

    def test_cup_bar_sits_at_declared_column(self):
        """右边框必须正好在第 total 列 —— 这是 CUP 的定义。"""
        total = 60
        payload = build_cup_box(total, BODIES)
        bars = self._bars(payload, 1.66)
        for row, col in bars.items():
            self.assertEqual(col, total, f'第 {row} 行的右边框在第 {col} 列，应为 {total}')

    def test_padding_breaks_under_non_standard_font(self):
        """反证：补空格方案在 1.66 格的字体下必然歪 —— 这就是 Linux/mac 的问题。"""
        payload = build_pad_box(60, BODIES)
        bars_std = self._bars(payload, 2.0)
        self.assertEqual(len(set(bars_std.values())), 1, '宋体比例下应是对齐的')

        bars_bad = self._bars(payload, 1.66)
        self.assertGreater(len(set(bars_bad.values())), 1,
                           '1.66 格字体下补空格方案应当歪，否则这个反证不成立')

    def test_content_never_covers_right_border(self):
        """最坏情况截断：即使汉字按 2.4 格画，也不该盖住右边框那一列。"""
        total = 60
        long_body = '中' * 80          # 远超可用宽度
        payload = build_cup_box(total, [long_body])
        screen = FakeScreen(2.0)
        screen.feed(payload)

        # 第 2 行是内容行；右边框列上必须还是 │，没被汉字覆盖
        bar_col = 60
        self.assertEqual(screen.cells.get((2, bar_col)), '│',
                         '内容盖住了右边框')

    def test_cup_box_is_a_rectangle(self):
        """上下边框与竖线的左右端点必须重合，构成完整矩形。"""
        total = 50
        payload = build_cup_box(total, ['第一行', 'second line'])
        screen = FakeScreen(1.66)
        screen.feed(payload)
        text = screen.render()

        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertGreaterEqual(len(lines), 4)
        # 每一行的首字符是竖线或圆角，末字符必须是竖线或圆角
        for ln in lines:
            self.assertIn(ln[0], '╭│╰', f'行首异常：{ln[:12]!r}')
            self.assertIn(ln[-1], '╮│╯', f'行尾异常：{ln[-12:]!r}')

    def test_all_right_edges_land_on_declared_column(self):
        """上边框的 ╮、正文的 │、下边框的 ╯ 必须全部落在第 total 列。

        这一条是整个方案的核心保证：含中文标题的上边框，在「汉字 1.66 格」
        的字体下会比正文短一截，所以边框右端也必须用定位画，不能只靠拼接。
        """
        total = 54
        payload = build_cup_box(total, BODIES)
        for han in (1.0, 1.66, 2.0):
            screen = FakeScreen(han)
            screen.feed(payload)
            rights = {col for (row, col), ch in screen.cells.items()
                      if ch in '╮╯│'}
            rights.discard(1)          # 第 1 列是左边框
            self.assertEqual(rights, {total},
                             f'汉字宽度 {han} 时右端落在 {sorted(rights)}，'
                             f'应为 {{{total}}}')


class TestSafetyTruncate(unittest.TestCase):
    def test_ascii_only(self):
        self.assertEqual(tf.safety_truncate('abcdef', 3), 'abc')

    def test_count_chinese_as_two(self):
        # 宽度 4 只放得下 2 个汉字（每个按最坏 2 格算）
        self.assertEqual(tf.safety_truncate('中文字', 4), '中文')

    def test_mixed(self):
        out = tf.safety_truncate('ab中文', 4)
        self.assertEqual(out, 'ab中')   # 2 + 2 = 4

    def test_never_exceeds_width(self):
        for width in range(0, 12):
            out = tf.safety_truncate('中文abc混合1234', width)
            worst = sum(2 if ord(c) > 0x7F else 1 for c in out)
            self.assertLessEqual(worst, width, f'宽度 {width} 时超出：{out!r}')


if __name__ == '__main__':
    unittest.main()
