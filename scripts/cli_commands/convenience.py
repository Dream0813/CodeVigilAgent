"""便利类斜杠命令：复制、打开目录、用量、自定义命令列表。

这些命令和审查逻辑无关，放在独立文件里，
`handle_chat_slash()` 只负责把请求转进来，不再继续变胖。
"""
from __future__ import annotations

from pathlib import Path

from scripts.agent_home import config_path, home_dir
from scripts.clipboard import copy_text
from scripts.config_backup import backup_dir
from scripts.custom_commands import format_commands, load_commands
from scripts.system_open import open_path
from scripts.term_style import ok, warn

from . import SlashContext


def copy_last_reply(ctx: SlashContext, arg: str) -> None:
    """把上一条回答放进系统剪贴板。"""
    reply = getattr(ctx.agent, 'last_reply', None)
    if not reply:
        print(warn('没有可复制的回答（先问一次再 /copy）。'))
        return
    copied, detail = copy_text(reply)
    print(ok(detail) if copied else warn(detail))


def open_directory(ctx: SlashContext, arg: str) -> None:
    """打开仓库 / 配置 / 会话 / 备份目录。"""
    target = (arg or 'repo').strip().lower()
    targets = {
        'repo': Path(ctx.repo_root),
        'config': Path(config_path()).parent,
        'home': home_dir(),
        'sessions': home_dir() / 'sessions',
        'backups': backup_dir(),
    }
    path = targets.get(target)
    if path is None:
        print(warn('用法: /dir repo|config|sessions|backups'))
        return
    opened, detail = open_path(path)
    print(ok(detail) if opened else warn(detail))


def show_usage(ctx: SlashContext, arg: str) -> None:
    """本次会话的 token 估算。"""
    if ctx.usage is None:
        print(warn('还没有用量数据。'))
        return
    config = getattr(ctx.agent, 'model_config', None)
    model = config.get('model') if isinstance(config, dict) else None
    print(ctx.usage.report(model))


def list_custom_commands(ctx: SlashContext, arg: str) -> None:
    """列出项目级 / 用户级自定义命令。"""
    commands, warnings = load_commands(ctx.repo_root)
    print(format_commands(commands.values()))
    for message in warnings[:5]:
        print(warn(f'  · {message}'))


COMMANDS = {
    '/copy': copy_last_reply,
    '/yank': copy_last_reply,
    # 注意：不能叫 /open —— 那是内置的「打开历史会话」别名，会被内置逻辑优先接走
    '/dir': open_directory,
    '/reveal': open_directory,
    '/cost': show_usage,
    '/tokens': show_usage,
    '/usage': show_usage,
    '/commands': list_custom_commands,
    '/cmds': list_custom_commands,
}
