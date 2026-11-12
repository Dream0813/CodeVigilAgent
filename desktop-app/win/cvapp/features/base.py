"""功能描述与分组定义。

一个「功能」= 侧边栏里的一个按钮（或底部输入框的一次提交）。
界面只认这个数据结构，不认识具体业务 —— 所以加功能不用改界面代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# 侧边栏分组顺序；没列在这里的组会排在最后。
GROUPS = ['审查', '输出', '系统']

# 输入框提交算一类特殊功能（placement='input'），不进侧边栏。
PLACEMENTS = ('sidebar', 'input')


@dataclass
class Feature:
    id: str                                  # 唯一标识，如 review.diff
    group: str                               # 侧边栏分组，见 GROUPS
    label: str                               # 按钮文字
    handler: Callable[..., None]             # 点击 / 提交时调用
    order: int = 100                         # 同组内排序，小的在上
    kind: str = 'normal'                     # normal | accent | danger
    placement: str = 'sidebar'               # sidebar | input
    requires_repo: bool = False              # 点击前必须选好仓库
    only_while_running: bool = False         # 只在任务运行时可用（如「取消」）
    shortcut: str = ''                       # tkinter 按键序列，如 '<F5>'
    hint: str = ''                           # 一句话说明，供文档/提示使用
    tags: list = field(default_factory=list)  # 预留：搜索、权限等扩展


def sort_key(feature: Feature) -> tuple:
    group = feature.group if feature.group in GROUPS else 'zzz'
    index = GROUPS.index(group) if group in GROUPS else len(GROUPS)
    return (index, feature.order, feature.label)
