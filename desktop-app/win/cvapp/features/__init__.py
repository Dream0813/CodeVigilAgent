"""功能注册表：自动发现本目录下的所有功能模块。

加一个功能 = 在 features/ 下新建一个 .py，里面写：
    FEATURES = [Feature(...)]
不需要改 shell、不需要改这个文件、不需要改 app.py。

加载失败的模块会被跳过并记下来（显示在状态栏），
一个坏功能不会拖垮整个程序。
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import GROUPS, Feature, sort_key

__all__ = ['GROUPS', 'Feature', 'load']


def load() -> tuple[list[Feature], list[str]]:
    """返回 (功能列表, 错误列表)。"""
    features: list[Feature] = []
    errors: list[str] = []
    seen: set[str] = set()

    for info in pkgutil.iter_modules(__path__):
        if info.name == 'base' or info.name.startswith('_'):
            continue
        try:
            module = importlib.import_module(f'{__name__}.{info.name}')
        except Exception as exc:                        # noqa: BLE001
            errors.append(f'{info.name}: {exc}')
            continue
        for feature in getattr(module, 'FEATURES', []):
            if not isinstance(feature, Feature):
                errors.append(f'{info.name}: FEATURES 里有非 Feature 对象')
                continue
            if feature.id in seen:
                errors.append(f'{info.name}: 功能 id 重复 {feature.id}')
                continue
            seen.add(feature.id)
            features.append(feature)

    features.sort(key=sort_key)
    return features, errors
