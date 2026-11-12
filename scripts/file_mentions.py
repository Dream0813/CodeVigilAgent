"""@文件引用：在对话里直接带上仓库文件内容。

参考 Cursor / Claude Code 的 @-mention、aider 的 /read：

    /review                     # 普通命令
    这个函数为什么会泄漏？@src/server.py
    对比一下 @src/old.py 和 @src/new.py
    @scripts/ 目录里有哪些入口？

规则（安全优先）：
    · 只允许仓库内的路径，绝对路径越界一律拒绝
    · 单文件最多 64 KB，一次最多 8 个引用，目录最多列 100 项
    · 二进制文件（含 NUL 字节）跳过，不当文本塞给模型
    · 找不到的引用不报错中断，只在提示里列出，原文保留
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

MENTION_RE = re.compile(
    # 中文标点常常紧跟路径且不带空格（"看下 @a.py，有问题"），
    # 所以把中文标点也当作分隔符；ASCII 标点留给结尾的 TRAILING 处理。
    r'(?<![\w@])@([^\s@，。；：、！？（）【】《》“”‘’"\'`]+)'
)
TRAILING = '，。；：、,.!?;:)）]】》"\''
MAX_FILES = 8
MAX_BYTES = 64 * 1024
MAX_DIR_ENTRIES = 100


def _within(base: Path, target: Path) -> bool:
    """target 是否在 base 目录内（跨盘符会抛 ValueError，视为不在）。"""
    try:
        return os.path.commonpath([str(base), str(target)]) == str(base)
    except ValueError:
        return False


def _human_size(size: int) -> str:
    if size < 1024:
        return f'{size} B'
    if size < 1024 * 1024:
        return f'{size / 1024:.1f} KB'
    return f'{size / 1024 / 1024:.1f} MB'


def _read_text(path: Path, limit: int) -> tuple[str, bool, bool]:
    """返回 (文本, 是否截断, 是否二进制)。"""
    with open(path, 'rb') as fh:
        head = fh.read(4096)
        if b'\x00' in head:
            return '', False, True
        fh.seek(0)
        raw = fh.read(limit + 1)
    truncated = len(raw) > limit
    return raw[:limit].decode('utf-8', 'replace'), truncated, False


def _dir_listing(path: Path, rel: str) -> str:
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return f'<dir path="{rel}">\n（无法读取：{exc}）\n</dir>'
    lines = []
    for entry in entries[:MAX_DIR_ENTRIES]:
        suffix = '/' if entry.is_dir() else ''
        lines.append(f'{entry.name}{suffix}')
    if len(entries) > MAX_DIR_ENTRIES:
        lines.append(f'…（另有 {len(entries) - MAX_DIR_ENTRIES} 项未列出）')
    return f'<dir path="{rel}">\n' + '\n'.join(lines) + '\n</dir>'


def expand(text: str, repo_root: str | None = None, *,
           max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES) -> Tuple[str, List[str], List[str]]:
    """把文本里的 @路径 展开成文件内容块。

    返回 (新文本, 已附带说明, 警告)。没有 @ 时原样返回。
    """
    if not text or '@' not in text:
        return text, [], []

    base = Path(repo_root or os.getcwd()).resolve()
    attachments: list[str] = []
    notes: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()

    for match in MENTION_RE.finditer(text):
        token = match.group(1).strip().rstrip(TRAILING)
        if not token:
            continue
        candidate = Path(token)
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            # Windows 上 @C:\x 会被 Path 当成相对路径，显式判一下
            if re.match(r'^[A-Za-z]:[\\/]', token):
                target = Path(token).resolve()
            else:
                target = (base / token).resolve()

        if not _within(base, target):
            warnings.append(f'@{token}：不在当前仓库内，已忽略')
            continue
        rel = os.path.relpath(str(target), str(base)).replace('\\', '/')
        if rel in seen:
            continue
        seen.add(rel)

        if not target.exists():
            warnings.append(f'@{token}：找不到这个文件或目录')
            continue
        if len(attachments) >= max_files:
            warnings.append(f'@{token}：一次最多引用 {max_files} 个，已忽略')
            continue

        if target.is_dir():
            attachments.append(_dir_listing(target, rel))
            notes.append(f'已附带目录 {rel}/')
            continue
        try:
            size = target.stat().st_size
        except OSError as exc:
            warnings.append(f'@{token}：读取失败（{exc}）')
            continue
        if size > max_bytes:
            warnings.append(f'@{token}：{_human_size(size)} 超过 {_human_size(max_bytes)}，已忽略')
            continue
        try:
            content, truncated, binary = _read_text(target, max_bytes)
        except OSError as exc:
            warnings.append(f'@{token}：读取失败（{exc}）')
            continue
        if binary:
            warnings.append(f'@{token}：看起来是二进制文件，已跳过')
            continue

        block = f'<file path="{rel}">\n{content}'
        if truncated:
            block += f'\n…（已截断，原文件 {_human_size(size)}）'
        block += '\n</file>'
        attachments.append(block)
        notes.append(f'已附带 {rel}（{_human_size(size)}）')

    if not attachments:
        return text, notes, warnings

    joined = '\n\n'.join(attachments)
    return f'{text}\n\n以下是我引用的文件内容：\n{joined}', notes, warnings
