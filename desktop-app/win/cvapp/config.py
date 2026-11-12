"""配置读写：只碰文件，不碰界面。

两个文件：
    ~/.reviewagent/ai_config.json   模型配置（与终端版共用，所以桌面版
                                    改了设置，终端版也生效）
    <win 目录>/last_repo.txt        上次选的仓库，下次打开自动填上
"""
from __future__ import annotations

import json
import os

from . import HERE

CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.reviewagent', 'ai_config.json')
LAST_REPO_PATH = os.path.join(HERE, 'last_repo.txt')


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:                                   # noqa: BLE001
        return {}


def save_config(data: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_last_repo() -> str:
    try:
        with open(LAST_REPO_PATH, encoding='utf-8') as fh:
            return fh.read().strip()
    except Exception:                                   # noqa: BLE001
        return ''


def save_last_repo(path: str) -> None:
    try:
        with open(LAST_REPO_PATH, 'w', encoding='utf-8') as fh:
            fh.write(path)
    except Exception:                                   # noqa: BLE001
        pass
