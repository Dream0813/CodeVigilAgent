"""提问功能：底部输入框提交。"""
from __future__ import annotations

import os

from .. import ROOT
from .base import Feature


def send(app, text: str) -> None:
    text = (text or '').strip()
    if not text:
        return
    args = [
        app.runner.python(), os.path.join(ROOT, 'ascend_cli.py'),
        'chat', '--message', text, '--network', 'auto',
    ]
    repo = app.current_repo()
    if repo and os.path.isdir(repo):
        args += ['--repository', repo]
    app.run_cli(args, cwd=ROOT, label='提问')


FEATURES = [
    Feature(
        id='chat.send', group='会话', label='发送', handler=send,
        placement='input', order=10,
        hint='把输入框里的问题发给 Agent（可带仓库上下文）',
    ),
]
