"""退格擦除的回归测试。

背景：终端里一个字符占的列数不等于 1 —— 汉字和全角标点占 2 列。
原来退格固定发 '\\b \\b'（只擦 1 列），删完汉字后屏幕上剩半个字，
用户看到的就是「按退格只能撤回一部分文字」。

这里用「虚拟屏幕」验证：把字符画上去，再执行擦除序列，屏幕必须干净。
"""
import sys
import unittest

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.chat_input import erase_sequence  # noqa: E402
from scripts import term_frame as tf  # noqa: E402

BS = '\b'


class Screen:
    """极简终端屏幕模型：只关心「某一列有没有字符」。

    pos 必须跨操作保持 —— 退格是靠光标移动实现的，每次调用都重置光标
    就模拟不出连续退格。
    """

    def __init__(self):
        self.cells = []      # 每个元素是一个显示列的内容
        self.pos = 0         # 当前光标所在的列

    def write_text(self, text):
        """写入一段文字（按显示宽度占位）。"""
        for ch in text:
            w = tf.display_width(ch)
            if w == 0:
                continue
            self.cells.append(ch)
            for _ in range(w - 1):
                self.cells.append('')      # 宽字符的右半格
        self.pos = len(self.cells)

    def apply(self, seq):
        """执行控制序列：退格左移、空格覆盖、其他字符照写。"""
        for ch in seq:
            if ch == BS:
                self.pos = max(0, self.pos - 1)
            elif ch == ' ':
                if self.pos < len(self.cells):
                    self.cells[self.pos] = ' '
                else:
                    self.cells.append(' ')
                self.pos += 1
            else:
                if self.pos < len(self.cells):
                    self.cells[self.pos] = ch
                else:
                    self.cells.append(ch)
                self.pos += 1

    def tail_blank(self):
        """从尾部往前，连续空白的列数。"""
        n = 0
        for cell in reversed(self.cells):
            if cell in ('', ' '):
                n += 1
            else:
                break
        return n

    def visible(self):
        return ''.join(c for c in self.cells if c not in ('', ' '))


class TestEraseSequence(unittest.TestCase):
    def test_ascii_erases_one_column(self):
        """ASCII 占 1 列，序列应为 左移1 + 空格 + 左移1。"""
        self.assertEqual(erase_sequence('a'), '\b \b')

    def test_chinese_erases_two_columns(self):
        """汉字占 2 列，必须擦 2 列 —— 这是本次修复的核心。"""
        self.assertEqual(erase_sequence('中'), '\b\b  \b\b')
        self.assertEqual(erase_sequence('你'), '\b\b  \b\b')

    def test_fullwidth_punctuation_erases_two_columns(self):
        for ch in '，。！？（）【】':
            self.assertEqual(erase_sequence(ch), '\b\b  \b\b', f'{ch} 应擦 2 列')

    def test_zero_width_char_still_erases_something(self):
        """组合记号宽度为 0，也不能发出空序列，否则光标不动。"""
        self.assertEqual(len(erase_sequence('\u0301')), 3)

    def test_sequence_is_balanced(self):
        """左移总格数必须是空格推进格数的两倍（前半左移 + 后半回退）。"""
        for text in ['a', '中', '，', '●', '1']:
            seq = erase_sequence(text)
            back = seq.count('\b')
            spaces = seq.count(' ')
            self.assertEqual(back, 2 * spaces, f'{text!r} 的移动格数不对称')
            self.assertEqual(spaces, max(tf.display_width(text), 1))
            self.assertEqual(back, 2 * max(tf.display_width(text), 1))


class TestScreenAfterBackspace(unittest.TestCase):
    def _type_then_backspace_all(self, text):
        screen = Screen()
        screen.write_text(text)
        for ch in reversed(text):
            screen.apply(erase_sequence(ch))
        return screen

    def test_chinese_leaves_no_residue(self):
        screen = self._type_then_backspace_all('你好世界')
        self.assertEqual(screen.visible(), '',
                         '退格后屏幕上残留了文字（旧实现只擦 1 列会留下右半格）')

    def test_mixed_leaves_no_residue(self):
        screen = self._type_then_backspace_all('你好abc，世界123！')
        self.assertEqual(screen.visible(), '')

    def test_partial_backspace_keeps_prefix(self):
        """删掉最后两个汉字后，前面的内容必须完整保留。"""
        text = '分析这个仓库'
        screen = Screen()
        screen.write_text(text)
        for _ in range(2):
            screen.apply(erase_sequence(text[-1]))
            text = text[:-1]
        self.assertEqual(screen.visible(), '分析这个')

    def test_old_implementation_would_leave_residue(self):
        """把旧实现（固定擦 1 列）跑一遍，确认它能复现 bug。

        这条是「反证」：如果哪天有人把逻辑改回 '\\b \\b'，上面几条会失败，
        而这一条会说明 —— 旧写法只把光标左移一格，擦掉的是汉字的**右半格**，
        左边半个字留在屏幕上，看起来就是「只撤回了一部分」。
        """
        text = '你'
        screen = Screen()
        screen.write_text(text)
        screen.apply('\b \b')          # 旧写法
        self.assertEqual(len(screen.cells), 2, '汉字应占 2 列')
        self.assertEqual(screen.cells[0], '你', '左半格没被擦掉 —— 残影来源')
        self.assertEqual(screen.cells[1], ' ', '旧写法只盖住了右半格')
        self.assertNotEqual(screen.visible(), '', '旧写法擦不干净')


if __name__ == '__main__':
    unittest.main()
