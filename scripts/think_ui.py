"""Pretty thinking / progress steps for chat (Claude Code–ish)."""
from __future__ import annotations

import time
from typing import List, Optional, Sequence, Union

from scripts import console_safe
from scripts import term_frame as tf
from scripts.term_style import accent, brand, c, enable_windows_ansi, mute, ok


class ThinkPanel:
    """Collects progress steps and renders a colored thinking block.

    盒子宽度取自 term_frame，和输入提示框、Agent 回复框同宽，
    所以三者的左右竖线落在同一列。
    """

    def __init__(self):
        self.steps: List[str] = []
        self._open = False
        self._started = 0.0
        self._total = 0

    def start(self, title: str = '思考中') -> None:
        enable_windows_ansi()
        self.steps.clear()
        self._open = True
        self._started = time.time()
        self._total = tf.total_width()
        print()
        print(brand(tf.top_border(title, self._total)))

    def step(self, message: Union[str, Sequence[str]]) -> None:
        enable_windows_ansi()
        if not self._open:
            self.start()
        # 老版本可能把 message 当列表传进来，统一成一行
        if isinstance(message, (list, tuple)):
            text = ' · '.join(str(x) for x in message)
        else:
            text = str(message)
        self.steps.append(text)
        n = len(self.steps)
        # alternating accent for rhythm
        diamond = accent('◆') if n % 2 else brand('◇')
        for line in tf.row_lines(c('97', text), self._total, paint=brand, indent=diamond + ' '):
            print(line)

    def close(self, ok_msg: str = '完成') -> None:
        if not self._open:
            return
        elapsed = time.time() - self._started
        # ✓ 不在 GBK 里，按当前编码退回等宽的 v，避免 GBK 控制台抛编码错误
        body = ok(console_safe.glyph('✓', 'v') + ' ') + mute(f'{ok_msg} · {elapsed:.1f}s')
        for line in tf.row_lines(body, self._total, paint=brand):
            print(line)
        print(brand(tf.bottom_border('', self._total)))
        self._open = False


# Module-level panel used by chat()
_PANEL: Optional[ThinkPanel] = None


def begin_think(title: str = '思考中') -> ThinkPanel:
    global _PANEL
    _PANEL = ThinkPanel()
    _PANEL.start(title)
    return _PANEL


def think_progress(message: str) -> None:
    global _PANEL
    if _PANEL is None or not _PANEL._open:
        begin_think()
    assert _PANEL is not None
    _PANEL.step(message)


def end_think(ok_msg: str = '完成') -> None:
    global _PANEL
    if _PANEL is not None:
        _PANEL.close(ok_msg)
        _PANEL = None
