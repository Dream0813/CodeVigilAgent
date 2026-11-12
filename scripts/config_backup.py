"""配置文件备份与回滚。

场景：改 provider / model / api_key 写错一个字符，终端版和桌面版就都用不了。
这里在每次 `config --set` 之前自动留一份，随时能 `config --restore` 回去。

存放位置：~/.reviewagent/backups/（可用 REVIEWAGENT_BACKUP_DIR 覆盖，便于测试）
保留策略：默认只留最近 20 份，避免无限增长。
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_KEEP = 20


def backup_dir() -> Path:
    override = (os.environ.get('REVIEWAGENT_BACKUP_DIR') or '').strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / '.reviewagent' / 'backups'


def _unique_path(directory: Path, tag: str) -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    safe_tag = ''.join(ch for ch in tag if ch.isalnum() or ch in '-_') or 'manual'
    candidate = directory / f'ai_config.{stamp}.{safe_tag}.json'
    index = 1
    while candidate.exists():
        candidate = directory / f'ai_config.{stamp}-{index}.{safe_tag}.json'
        index += 1
    return candidate


def create_backup(config_path, tag: str = 'manual',
                  directory: Optional[Path] = None,
                  keep: int = DEFAULT_KEEP) -> Optional[Path]:
    """备份配置文件；文件不存在时返回 None（第一次使用不算错误）。"""
    source = Path(config_path).expanduser()
    if not source.is_file():
        return None
    target_dir = Path(directory) if directory else backup_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_path(target_dir, tag)
    shutil.copy2(source, target)
    _prune(target_dir, keep)
    return target


def list_backups(directory: Optional[Path] = None) -> List[Path]:
    """按时间倒序返回备份文件（最新的在前）。"""
    target_dir = Path(directory) if directory else backup_dir()
    if not target_dir.is_dir():
        return []
    files = [p for p in target_dir.glob('ai_config.*.json') if p.is_file()]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def _prune(directory: Path, keep: int) -> None:
    if keep <= 0:
        return
    for old in list_backups(directory)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _pick(name: Optional[str], backups: List[Path]) -> Path:
    if not backups:
        raise FileNotFoundError('还没有任何备份')
    if not name or name.strip().lower() in ('latest', 'last'):
        return backups[0]
    wanted = name.strip()
    exact = [p for p in backups if p.name == wanted]
    if exact:
        return exact[0]
    matched = [p for p in backups if wanted in p.name]
    if len(matched) == 1:
        return matched[0]
    if not matched:
        raise FileNotFoundError(f'没有找到匹配「{name}」的备份')
    raise ValueError(f'「{name}」匹配到 {len(matched)} 个备份，请写得更具体')


def restore_backup(config_path, name: Optional[str] = None,
                   directory: Optional[Path] = None) -> Tuple[Path, Optional[Path]]:
    """恢复备份；返回 (被恢复的备份, 恢复前的安全备份或 None)。"""
    target_dir = Path(directory) if directory else backup_dir()
    source = _pick(name, list_backups(target_dir))
    config = Path(config_path).expanduser()
    safety = create_backup(config, tag='before-restore', directory=target_dir)
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, config)
    return source, safety
