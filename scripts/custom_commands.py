"""自定义斜杠命令：把常用提问存成 Markdown，用 /名字 调用。

参考 Claude Code / Cursor 的做法（`.claude/commands/*.md`、`@file`），
按本项目的目录习惯放在：

    项目级  <仓库>/.reviewagent/commands/**/*.md     —— 可随仓库共享
    用户级  ~/.reviewagent/commands/**/*.md          —— 所有项目通用

文件格式（frontmatter 可选）：

    ---
    description: 检查这个文件有没有并发问题
    argument-hint: <文件路径>
    ---
    请重点检查 @$ARGUMENTS 的并发安全：
    1. 共享状态是否加锁
    2. 是否存在 TOCTOU
    3. 异常路径下锁是否释放

用法：/并发 @src/server.py

设计约束：
    · 同名命令项目级覆盖用户级（项目规则优先）
    · 子目录会成为命名空间：commands/db/slow.md → /db:slow
    · 单文件上限 64 KB，整目录最多 200 个命令，防止误放大文件
    · 解析失败的文件跳过并记入 warnings，不影响其它命令
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

MAX_FILES = 200
MAX_BYTES = 64 * 1024
NAME_RE = re.compile(r'^[A-Za-z0-9_\-\u4e00-\u9fff:]+$')
ARG_RE = re.compile(r'\$\{?ARGUMENTS\}?')


@dataclass
class CustomCommand:
    name: str                 # 不含前导 /
    description: str = ''
    argument_hint: str = ''
    body: str = ''
    source: str = 'user'      # user | project
    path: str = ''
    warnings: List[str] = field(default_factory=list)

    def as_row(self) -> str:
        hint = f' {self.argument_hint}' if self.argument_hint else ''
        desc = f'  {self.description}' if self.description else ''
        return f'  /{self.name}{hint}{desc}  ({self.source})'


def _command_dirs(repo_root: Optional[str]) -> list[tuple[str, Path]]:
    """返回 [(source, dir)]，后面的覆盖前面的。"""
    dirs: list[tuple[str, Path]] = []
    home = Path(os.path.expanduser('~')) / '.reviewagent' / 'commands'
    dirs.append(('user', home))
    if repo_root:
        dirs.append(('project', Path(repo_root) / '.reviewagent' / 'commands'))
    return dirs


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """极简 frontmatter：只认 `key: value`，不引第三方 YAML。"""
    if not text.startswith('---'):
        return {}, text
    lines = text.splitlines()
    meta: dict[str, str] = {}
    end = None
    for index in range(1, min(len(lines), 40)):
        line = lines[index].strip()
        if line in ('---', '...'):
            end = index
            break
        if ':' in line:
            key, value = line.split(':', 1)
            meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    if end is None:
        return {}, text
    body = '\n'.join(lines[end + 1:]).lstrip('\n')
    return meta, body


def _fallback_description(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '```')):
            continue
        return line[:80]
    return ''


def _command_name(path: Path, base: Path) -> str:
    rel = path.relative_to(base).with_suffix('')
    return ':'.join(part for part in rel.parts if part)


def load_commands(repo_root: Optional[str] = None) -> tuple[Dict[str, CustomCommand], List[str]]:
    """扫描用户级与项目级命令，返回 (命令表, 警告列表)。"""
    commands: Dict[str, CustomCommand] = {}
    warnings: List[str] = []
    count = 0

    for source, base in _command_dirs(repo_root):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*.md')):
            if count >= MAX_FILES:
                warnings.append(f'命令数量超过 {MAX_FILES} 个，其余已忽略')
                break
            if any(part.startswith('.') for part in path.relative_to(base).parts):
                continue
            try:
                raw = path.read_bytes()
            except OSError as exc:
                warnings.append(f'{path.name}: 读取失败（{exc}）')
                continue
            if len(raw) > MAX_BYTES:
                warnings.append(f'{path.name}: 超过 {MAX_BYTES // 1024} KB，已跳过')
                continue
            text = raw.decode('utf-8', 'replace')
            name = _command_name(path, base)
            if not name or not NAME_RE.match(name):
                warnings.append(f'{path.name}: 文件名只能包含字母/数字/下划线/中文/冒号，已跳过')
                continue
            meta, body = _parse_frontmatter(text)
            if not body.strip():
                warnings.append(f'{path.name}: 正文为空，已跳过')
                continue
            commands[name] = CustomCommand(
                name=name,
                description=meta.get('description', '') or _fallback_description(body),
                argument_hint=meta.get('argument-hint', '') or meta.get('argument_hint', ''),
                body=body.strip(),
                source=source,
                path=str(path),
            )
            count += 1

    return commands, warnings


def expand_command(command: CustomCommand, arguments: str = '') -> str:
    """把 $ARGUMENTS 替换成实际参数；没有占位符时把参数附在末尾。"""
    args = (arguments or '').strip()
    body = command.body
    if ARG_RE.search(body):
        return ARG_RE.sub(lambda _m: args, body).strip()
    if args:
        return f'{body}\n\n补充参数：{args}'.strip()
    return body.strip()


def find_command(text: str, commands: Dict[str, CustomCommand]) -> tuple[Optional[CustomCommand], str]:
    """从 '/名字 参数' 里找出命令；不匹配返回 (None, '')。"""
    text = (text or '').strip()
    if not text.startswith('/'):
        return None, ''
    head, _, rest = text.partition(' ')
    name = head[1:].strip()
    return commands.get(name), rest.strip()


def format_commands(commands: Iterable[CustomCommand]) -> str:
    rows = sorted(commands, key=lambda c: c.name)
    if not rows:
        return ('还没有自定义命令。\n'
                '在 <仓库>/.reviewagent/commands/ 或 ~/.reviewagent/commands/ '
                '新建一个 .md 文件即可，例如：\n'
                '  .reviewagent/commands/并发.md\n')
    lines = ['自定义命令（/名字 参数）：']
    lines.extend(command.as_row() for command in rows)
    lines.append('')
    lines.append('新增：在 .reviewagent/commands/ 放一个 .md；正文里的 $ARGUMENTS 会被替换成参数。')
    return '\n'.join(lines)
