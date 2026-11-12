"""把审查报告渲染成 Markdown，供 `review --report` 使用。

为什么单独一个模块：
    review() 现在已经负责取上下文、调审查器、写 JSON、算退出码；
    再把手写 Markdown 的细节塞进去，这个函数会变成第二个「什么都干」的巨块。
    渲染是纯函数（报告 dict → 字符串），可以单独测试，不碰终端也不碰网络。

跨平台：
    只用 pathlib + 显式 utf-8；不调用任何 shell 命令，
    所以 Windows / macOS / Linux 行为一致。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

SEVERITY_LABELS = {
    'critical': '严重',
    'high': '高',
    'medium': '中',
    'low': '低',
}
RECOMMENDATION_LABELS = {
    'approve': '通过',
    'request_changes': '要求修改',
    'comment': '仅评论',
}
COVERAGE_LABELS = {
    'full': '完整',
    'partial': '部分',
}


def _one_line(value) -> str:
    """标题里不能有换行，否则 Markdown 结构会断。"""
    return ' '.join(str(value or '').split())


def _text(value, fallback: str = '（未提供）') -> str:
    text = str(value or '').strip()
    return text or fallback


def _label(mapping: Dict[str, str], value) -> str:
    key = str(value or '').strip().lower()
    if not key:
        return '（未提供）'
    zh = mapping.get(key)
    return f'{zh}（{key}）' if zh else key


def _inline_code(value) -> str:
    """行内代码：把内容里的反引号换掉，避免把 Markdown 语法撑破。"""
    return '`' + str(value or '').replace('`', "'") + '`'


def _issue_section(issues: List[dict]) -> List[str]:
    lines: List[str] = []
    for index, issue in enumerate(issues, 1):
        severity = str(issue.get('severity') or 'unknown').lower()
        title = _one_line(issue.get('title') or issue.get('type') or '未命名问题')
        lines.append(f'### {index}. [{_label(SEVERITY_LABELS, severity)}] {title}')
        lines.append('')
        lines.append(f'- 严重程度：{_label(SEVERITY_LABELS, severity)}')
        if issue.get('type'):
            lines.append(f'- 类型：{_one_line(issue["type"])}')
        if issue.get('location'):
            lines.append(f'- 位置：{_inline_code(issue["location"])}')
        lines.append('')
        lines.append('**说明**')
        lines.append('')
        lines.append(_text(issue.get('description'), '（无说明）'))
        lines.append('')
        lines.append('**建议**')
        lines.append('')
        lines.append(_text(issue.get('suggestion'), '（无建议）'))
        lines.append('')
    return lines


def render_markdown(report: dict, context: Optional[dict] = None,
                    generated_at: Optional[datetime] = None) -> str:
    """生成 Markdown 文本。report 是 SmartReviewer 返回的 dict。"""
    context = context or {}
    result = (report or {}).get('review_result') if isinstance(report, dict) else None
    if not isinstance(result, dict):
        result = {}

    root = context.get('root') or ''
    repo_name = Path(root).name if root else '（未知仓库）'
    branch = context.get('branch') or '（未知分支）'
    moment = generated_at or datetime.now().astimezone()

    lines: List[str] = [
        '# CodeVigil Agent 审查报告',
        '',
        f'- 仓库：{_inline_code(repo_name)}',
        f'- 分支：{_inline_code(branch)}',
        f'- 审查时间：{moment.strftime("%Y-%m-%d %H:%M:%S %z")}',
        f'- 覆盖范围：{_label(COVERAGE_LABELS, result.get("coverage"))}',
        f'- 审查结论：{_label(RECOMMENDATION_LABELS, result.get("recommendation"))}',
        '',
        '## 总体结论',
        '',
    ]

    if result.get('error') or (isinstance(report, dict) and report.get('status') == 'error'):
        error = result.get('error') or (report or {}).get('error') or '未知错误'
        lines.extend([f'审查失败：{_one_line(error)}', ''])
        return '\n'.join(lines).rstrip() + '\n'

    assessment = _text(result.get('overall_assessment'), '（报告未提供总体结论）')
    lines.extend([assessment, ''])

    if result.get('coverage') == 'partial' and result.get('coverage_note'):
        lines.extend([f'> 范围提示：{_one_line(result["coverage_note"])}', ''])

    issues = result.get('issues')
    if not isinstance(issues, list):
        issues = []
    lines.extend([f'## 问题（{len(issues)}）', ''])
    if issues:
        lines.extend(_issue_section(issues))
    else:
        lines.extend(['未发现问题。', ''])

    retrieval = report.get('knowledge_retrieval') if isinstance(report, dict) else None
    warnings = retrieval.get('warnings') if isinstance(retrieval, dict) else None
    warnings = [str(item) for item in warnings] if isinstance(warnings, list) else []
    if warnings:
        lines.extend(['## 知识库提示', ''])
        lines.extend(f'- {_one_line(item)}' for item in warnings)
        lines.append('')

    references = retrieval.get('references') if isinstance(retrieval, dict) else None
    if isinstance(references, list) and references:
        lines.extend(['## 参考案例', ''])
        for ref in references:
            if not isinstance(ref, dict):
                continue
            title = _one_line(ref.get('title') or '未命名案例')
            url = str(ref.get('url') or '').strip()
            lines.append(f'- [{title}]({url})' if url else f'- {title}')
        lines.append('')

    changed = context.get('changed_files') or []
    if isinstance(changed, list) and changed:
        lines.extend(['## 改动文件', ''])
        for name in changed[:50]:
            lines.append(f'- {_inline_code(name)}')
        if len(changed) > 50:
            lines.append(f'- …（共 {len(changed)} 个，仅列前 50 个）')
        lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def write_markdown(path, text: str) -> Path:
    """写文件；失败时抛出 OSError，由调用方给出明确报错。"""
    destination = Path(path).expanduser()
    if destination.exists() and destination.is_dir():
        raise IsADirectoryError(f'目标是一个目录，不是文件：{destination}')
    parent = destination.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding='utf-8')
    return destination
