"""`/undo`：回滚最近一次 /apply 写入的本地补丁。

命令放在 cli_commands 扩展点（结构守卫要求新命令不进 handle_chat_slash）。
安全检查全部在 scripts/patch_fix.py 的 apply_undo_bundle 里：内容一致性
校验、整批先验证再写入、失败恢复到 /apply 后状态。快照留在会话内存，
不落盘（避免污染用户家目录、避免跨仓库误回滚）。这里只做转发。
"""
from __future__ import annotations

from scripts.term_style import ok, warn

from . import SlashContext


def undo(ctx: SlashContext, arg: str) -> None:
    agent = getattr(ctx, 'agent', None)
    if agent is None or not callable(getattr(agent, 'undo_last_fix', None)):
        print(warn('当前会话没有可用的 Agent，无法 /undo。'))
        return
    reply = agent.undo_last_fix()
    prefix = ok('[UNDO]') if agent.last_ok else warn('[UNDO]')
    print(prefix)
    print(reply)


COMMANDS = {'/undo': undo}
