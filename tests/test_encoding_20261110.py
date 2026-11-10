"""控制台编码的回归测试。

三件事必须成立，否则中文 Windows 用户会直接看到 Traceback：

1. GBK 控制台下跑体检不能崩，而且要画出全部 4 个盒子
2. import chat_v2 不能替换 sys.stdout（否则调用方未 flush 的输出会丢）
3. 符号要走 glyph()：UTF-8 下保留 ❯ ✓，GBK 下退回 > v
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_py(code: str, encoding: str = 'utf-8', module: str = None):
    """在子进程里跑一段代码或一个模块，返回 (解码后的输出, 退出码)。"""
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = encoding
    env['PYTHONPATH'] = str(ROOT)
    args = [sys.executable, '-m', module] if module else [sys.executable, '-c', code]
    proc = subprocess.run(args, cwd=str(ROOT), env=env, capture_output=True, timeout=180)
    raw = (proc.stdout or b'') + (proc.stderr or b'')
    return raw.decode(encoding, errors='replace'), proc.returncode


class TestGbkConsole(unittest.TestCase):
    def test_frame_doctor_does_not_crash_on_gbk(self):
        """GBK 下 ✅ ❌ ⚠ 这些字符曾经让程序抛 UnicodeEncodeError 直接退出。"""
        text, code = run_py('', encoding='gbk', module='scripts.frame_doctor')
        self.assertNotIn('Traceback', text, f'GBK 下崩溃了：\n{text[:1200]}')
        self.assertNotIn('UnicodeEncodeError', text)
        self.assertEqual(code, 0, '体检应该以 0 退出')

    def test_frame_doctor_draws_all_four_boxes_on_gbk(self):
        """四个盒子都要画出来 —— 曾经因为模块导入时改 stdout 只剩一个。"""
        text, _ = run_py('', encoding='gbk', module='scripts.frame_doctor')
        self.assertEqual(text.count('目标宽度'), 4,
                         f'只画出 {text.count("目标宽度")}/4 个盒子')

    def test_gbk_output_is_single_encoding(self):
        """整份输出必须是同一种编码，不能前半段 GBK 后半段 UTF-8。"""
        text, _ = run_py('', encoding='gbk', module='scripts.frame_doctor')
        # 用 GBK 解码后不该出现替换符成片的乱码块
        self.assertLess(text.count('\ufffd'), 40,
                        '输出里有大量无法解码的字节，说明中途换了编码')


class TestImportSideEffects(unittest.TestCase):
    def test_import_chat_v2_does_not_replace_stdout(self):
        """chat_v2 曾在模块级把 sys.stdout 换成新的 TextIOWrapper。

        那会让调用方此前没 flush 的内容整段消失，frame_doctor 因此只显示
        得到最后 1 个盒子。现在编码设置移进了 main()。
        """
        code = (
            'import sys\n'
            'before = id(sys.stdout)\n'
            'import chat_v2\n'
            'after = id(sys.stdout)\n'
            'print("SAME" if before == after else "REPLACED")\n'
        )
        out, _ = run_py(code)
        self.assertIn('SAME', out, 'import chat_v2 把 sys.stdout 换掉了')

    def test_import_smart_reviewer_keeps_encoding(self):
        """smart_reviewer 曾在模块级 reconfigure 成 UTF-8。

        结果是同一份输出前半段 GBK、后半段 UTF-8，混在一起变乱码。
        """
        code = (
            'import sys\n'
            'from scripts import smart_reviewer  # noqa: F401\n'
            'print("ENC=" + (sys.stdout.encoding or "?"))\n'
        )
        out, _ = run_py(code, encoding='gbk')
        self.assertIn('ENC=gbk', out, f'导入后编码被改了：{out.strip()[:200]}')


class TestGlyphFallback(unittest.TestCase):
    def test_utf8_keeps_fancy_glyphs(self):
        code = (
            'from scripts.console_safe import glyph\n'
            'print("P=" + glyph("\\u276f", ">"))\n'
            'print("C=" + glyph("\\u2713", "v"))\n'
        )
        out, _ = run_py(code, encoding='utf-8')
        self.assertIn('P=\u276f', out, 'UTF-8 下应保留 ❯')
        self.assertIn('C=\u2713', out, 'UTF-8 下应保留 ✓')

    def test_gbk_falls_back_to_ascii(self):
        code = (
            'from scripts.console_safe import glyph\n'
            'print("P=" + glyph("\\u276f", ">"))\n'
            'print("C=" + glyph("\\u2713", "v"))\n'
        )
        out, _ = run_py(code, encoding='gbk')
        self.assertIn('P=>', out, 'GBK 下应退回 >')
        self.assertIn('C=v', out, 'GBK 下应退回 v')
        self.assertNotIn('\u276f', out)

    def test_glyph_keeps_width_one(self):
        """替换前后显示宽度必须都是 1，否则整行会短一格、边框错位。"""
        code = (
            'import sys\n'
            'sys.path.insert(0, r"' + str(ROOT) + '")\n'
            'from scripts.console_safe import PROMPT, CHECK, CROSS, WARN\n'
            'from scripts.term_frame import display_width as w\n'
            'for pair in (PROMPT, CHECK, CROSS, WARN):\n'
            '    a, b = pair\n'
            '    print(f"{w(a)} {w(b)}")\n'
        )
        out, _ = run_py(code, encoding='utf-8')
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit():
                self.assertEqual(parts[0], parts[1],
                                 f'替换前后宽度不一致：{line}')


if __name__ == '__main__':
    unittest.main()
