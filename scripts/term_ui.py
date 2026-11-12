"""终端表现层：颜色、字形、盒子绘制。

从 chat_v2.py 抽出来（原来 1008 行的文件里，约 240 行是纯样式）。
分层意义：
    chat_v2.py 只管「对话流程」；
    本模块只管「怎么画」；
    宽度计算唯一出处仍是 scripts/term_frame.py。

对外名称不变：chat_v2 仍 re-export Style / G / UI / colored / bold / dim，
所以 `from chat_v2 import UI` 这类旧写法继续可用。
"""
from __future__ import annotations

import io
import os
import re
import sys

try:
    from scripts import term_frame as tf
except ImportError:                                     # 直接以脚本方式运行时的兜底
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts import term_frame as tf


class Style:
    """终端样式"""

    # ANSI 颜色代码
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # 前景色
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    # 品牌色（与启动画面的青 #00C2A8 / 粉 #FF8FAB 对齐）
    # 用 256 色而不是 24-bit，兼容旧版 Windows conhost
    BRAND = '\033[38;5;37m'    # 主色 青绿
    ACCENT = '\033[38;5;212m'  # 强调 粉
    GLOW = '\033[38;5;80m'     # 高亮 浅青
    FAINT = '\033[38;5;240m'   # 极弱 灰

    # 亮色版本
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'

    @staticmethod
    def strip(text: str) -> str:
        """移除样式代码"""
        return re.sub(r'\033\[[0-9;]+m', '', text)

    @staticmethod
    def enabled() -> bool:
        """检测是否支持颜色"""
        if sys.platform == 'win32':
            # Windows 10+ 支持 ANSI
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except Exception:                           # noqa: BLE001
                return False
        return True


# 全局样式开关
USE_COLORS = Style.enabled()


# ---------------------------------------------------------------------------
# 字形表：Windows 传统控制台（conhost）用的是宋体，不含 ❯ ✓ ✕ ✎ ✦ › 这些符号，
# 直接输出会显示成方块 □。这里按终端能力自动降级到 GBK 里一定有的字符，
# 也可以用环境变量 REVIEWAGENT_GLYPHS=fancy|safe 强制指定。
# ---------------------------------------------------------------------------
def _unicode_glyphs() -> bool:
    override = os.environ.get('REVIEWAGENT_GLYPHS', '').lower()
    if override == 'fancy':
        return True
    if override == 'safe':
        return False
    if sys.platform != 'win32':
        return True
    # Windows 一律保守：终端类型（conhost / Windows Terminal）判断不可靠，
    # 用户也可能给 WT 配了宋体。宁可朴素，也不要满屏方块。
    # 想用花哨符号：set REVIEWAGENT_GLYPHS=fancy
    return False


class G:
    """字形表。

    下面这些在 GBK 里本来就有，宋体也能渲染，两种终端都能用，故不做降级：
      圆角边框 ╭ ╮ ╰ ╯ 、竖色块 ▌ 、列表符号 ◆ 、箭头 ←
    只有 GBK 真的没收、字体也画不出来的才降级：
      ❯ ✕ ✎ ✦ › ✓ ✗ ⚠ ℹ ◐ • 盲文转轮
    """

    _f = _unicode_glyphs()

    TL = '╭'
    TR = '╮'
    BL = '╰'
    BR = '╯'
    BAR = '▌'
    BULLET = '◆'
    PROMPT = '❯' if _f else '>'
    OK = '✓' if _f else '√'
    BAD = '✗' if _f else '×'
    WARN = '⚠' if _f else '!'
    INFO = 'ℹ' if _f else 'i'
    WORKING = '◐' if _f else '●'


def colored(text: str, color: str) -> str:
    """添加颜色"""
    if not USE_COLORS:
        return text
    return f"{color}{text}{Style.RESET}"


def bold(text: str) -> str:
    """加粗"""
    if not USE_COLORS:
        return text
    return f"{Style.BOLD}{text}{Style.RESET}"


def dim(text: str) -> str:
    """变暗"""
    if not USE_COLORS:
        return text
    return f"{Style.DIM}{text}{Style.RESET}"


class UI:
    """UI 工具类

    宽度只有一个出处：`scripts.term_frame`。以前这里自己实现了一套
    _w/_tokens/_wrap/_pad，把 EAW=A 的字符（· ◆ →）算成 1 列，而
    term_frame 算 2 列 —— 同一个程序两套算法，右边框必然对不上。
    """

    @staticmethod
    def _w(text: str) -> int:
        """按终端显示宽度计数：中文/全角算 2 列，ANSI 码不计"""
        return tf.display_width(text)

    @staticmethod
    def _tokens(text: str):
        return list(tf._tokens(text))

    @staticmethod
    def _wrap(text: str, width: int):
        """按终端显示宽度折行（保留颜色码，中文不会被劈坏）"""
        return tf.wrap_display(text, width)

    @staticmethod
    def _pad(text: str, target: int) -> str:
        """按显示宽度右侧补空格"""
        return tf.pad_display(text, target)

    @staticmethod
    def box(title: str = "", content: str = "", width: int = 0):
        """绘制圆角边框盒子（品牌色边线）。

        width=0 表示跟随 term_frame.total_width()，与输入框、思考面板
        用同一个宽度 —— 这样同一屏里所有竖线才落在同一列。

        走 tf.emit_box：终端支持定位时把右边框钉在固定列，换字体也不会歪；
        不支持时自动退回补空格。
        """
        total = width or tf.total_width()
        bodies = []
        border = lambda s: colored(s, Style.BRAND)   # noqa: E731

        # 标题居中 + 分隔线
        if title:
            safe = tf.frame_safe(title)
            # 调用方已上色就不再包一层，避免嵌套 RESET 把颜色吃掉
            rendered = safe if '\033[' in safe else bold(colored(safe, Style.BRAND))
            tw = tf.display_width(rendered)
            left = max((total - 4 - tw) // 2, 0)
            bodies.append(' ' * left + rendered)
            bodies.append(tf.DIVIDER)

        # 内容
        if content:
            for line in content.split('\n'):
                for wrapped in tf.wrap_display(line, tf.content_width(total)):
                    bodies.append(wrapped)

        buf = io.StringIO()
        tf.emit_box('', bodies, total=total, paint=border, stream=buf)
        return buf.getvalue().rstrip('\n')

    @staticmethod
    def section(title: str, width: int = 0):
        """章节标题：`▌ 标题 ──────`，横线补到与盒子同宽

        这一行没有右边框，所以就算 `▌` 的宽度判断和终端差 1 列也看不出来，
        保留 `▌` 的观感比换成 `|` 划算。
        """
        total = width or tf.total_width()
        safe = tf.frame_safe(title)
        bar = '─' * max(total - tf.display_width(safe) - 4, 3)
        return f"\n{colored(G.BAR, Style.ACCENT)} {bold(safe)} {colored(bar, Style.FAINT)}\n"

    @staticmethod
    def bullet(text: str, symbol: str = G.BULLET) -> str:
        """带符号的列表项"""
        return f"  {colored(symbol, Style.BRAND)} {text}"

    @staticmethod
    def status(text: str, status_type: str = "info") -> str:
        """状态消息（无方括号，图标直接带色）"""
        icons = {
            'success': (G.OK, Style.GREEN),
            'error': (G.BAD, Style.RED),
            'warning': (G.WARN, Style.YELLOW),
            'info': (G.INFO, Style.GLOW),
            'working': (G.WORKING, Style.BRAND),
        }

        icon, color = icons.get(status_type, ('·', Style.WHITE))
        return f"{colored(icon, color)} {text}"

    @staticmethod
    def spinner(text: str) -> str:
        """进度指示（盲文字符宋体没有，降级成 ASCII 转轮）"""
        frames = "⣾⣽⣻⢿⡿⣟⣯⣷" if G._f else "|/-\\"
        return colored(frames, Style.BRAND) + f" {text}"

    @staticmethod
    def code_block(code: str, language: str = "") -> str:
        """代码块"""
        lines = []
        lines.append(colored("```" + language, Style.DIM))
        for line in code.split('\n'):
            lines.append(colored("│", Style.DIM) + f" {line}")
        lines.append(colored("```", Style.DIM))
        return '\n'.join(lines)
