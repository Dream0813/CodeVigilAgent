"""斜杠命令扩展点：新命令放这个目录，不要往 ascend_cli 里塞。

背景：
    `handle_chat_slash()` 已经有 600 多行，每加一条命令就要在同一个函数里
    插一段 if —— 这就是评审说的「结构拥挤、加功能会互相影响」。

用法：
    在本目录新建一个 .py，写：

        from . import SlashContext

        def hello(ctx: SlashContext, arg: str) -> None:
            print('你好', arg)

        COMMANDS = {'/hello': hello}

    重启后 `/hello` 自动可用。不需要改 ascend_cli.py，也不需要登记。

约定：
    · 键必须以 / 开头（没写会自动补）
    · 函数签名统一是 (ctx, arg)
    · 内置命令优先：同名时本目录的命令不会生效
    · 某个模块导入失败只会跳过并记录，不影响其它命令
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from scripts.term_style import warn

Handler = Callable[['SlashContext', str], None]


@dataclass
class SlashContext:
    """命令执行时能拿到的上下文，避免各模块反向 import ascend_cli。"""

    agent: object
    repo_root: str
    usage: object = None
    extras: dict = field(default_factory=dict)


_cache: Tuple[Dict[str, Handler], List[str]] | None = None


def load_handlers() -> Tuple[Dict[str, Handler], List[str]]:
    """扫描本目录，返回 ({命令: 处理函数}, [警告])。结果缓存，进程内只扫一次。"""
    global _cache
    if _cache is not None:
        return _cache

    handlers: Dict[str, Handler] = {}
    warnings: List[str] = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith('_'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{info.name}')
        except Exception as exc:                        # noqa: BLE001
            warnings.append(f'{info.name}: 导入失败（{exc}）')
            continue
        table = getattr(module, 'COMMANDS', None)
        if not isinstance(table, dict):
            continue
        for name, handler in table.items():
            key = str(name if str(name).startswith('/') else f'/{name}').lower()
            if key in handlers:
                warnings.append(f'{info.name}: 命令 {key} 重复，已忽略')
                continue
            handlers[key] = handler
    _cache = (handlers, warnings)
    return _cache


def reset_cache() -> None:
    """测试用：强制下次重新扫描。"""
    global _cache
    _cache = None


def dispatch(text: str, ctx: SlashContext) -> bool:
    """命中扩展命令则执行并返回 True；否则返回 False（交给内置逻辑）。"""
    text = (text or '').strip()
    if not text.startswith('/'):
        return False
    head, _, arg = text.partition(' ')
    handler = load_handlers()[0].get(head.lower())
    if handler is None:
        return False
    try:
        handler(ctx, arg.strip())
    except Exception as exc:                            # noqa: BLE001
        print(warn(f'命令 {head} 执行失败：{exc}'))
    return True


__all__ = ['SlashContext', 'dispatch', 'load_handlers', 'reset_cache']
