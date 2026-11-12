"""配置读写：只碰文件，不碰界面。

两个文件：
    ai_config.json                  模型配置（与终端版共用，所以桌面版
                                    改了设置，终端版也生效）。解析顺序与
                                    CLI 一致：REVIEWAGENT_CONFIG →
                                    REVIEWAGENT_HOME/ai_config.json →
                                    ~/.reviewagent/ai_config.json
    <win 目录>/last_repo.txt        上次选的仓库，下次打开自动填上
"""
from __future__ import annotations

import json
import os

from . import HERE


def _config_path() -> str:
    """与 scripts/agent_home.resolve_config_file 保持同一套优先级。

    两边不一致的话，桌面版改完设置、终端版却读另一份文件，会出现
    「明明保存了却没生效」。
    """
    explicit = os.environ.get('REVIEWAGENT_CONFIG', '').strip()
    if explicit:
        return os.path.expanduser(explicit)
    home = os.environ.get('REVIEWAGENT_HOME', '').strip()
    root = os.path.expanduser(home) if home else os.path.join(
        os.path.expanduser('~'), '.reviewagent')
    return os.path.join(root, 'ai_config.json')


CONFIG_PATH = _config_path()
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
