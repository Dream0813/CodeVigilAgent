"""输出区操作：清空、取消当前任务。"""
from __future__ import annotations

from .base import Feature


def _clear(app) -> None:
    app.output.clear()
    app.set_status('就绪')


def _cancel(app) -> None:
    app.runner.cancel()


FEATURES = [
    Feature(
        id='output.clear', group='输出', label='清空输出',
        handler=_clear, order=10, shortcut='<Control-l>',
        hint='清空上方输出区（不影响正在运行的任务）',
    ),
    Feature(
        id='output.cancel', group='输出', label='取消任务',
        handler=_cancel, order=20, kind='danger', only_while_running=True,
        shortcut='<Escape>',
        hint='终止当前正在运行的任务',
    ),
]
