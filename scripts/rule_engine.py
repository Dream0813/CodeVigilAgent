"""离线规则审查引擎（SmartReviewer 的规则部分独立成模块）。

2026-11-18 自审计后的结构拆分：smart_reviewer.py 超过结构守卫行数预算
（887 > 830），规则引擎与 AI 审查职责也不同源，独立成模块。

行为契约（与旧 SmartReviewer.review_with_rules 完全一致）：
- 每条规则报全部命中（上限 10 处/规则），逐处给 location
- 命中落在字符串字面量里的跳过（_in_string_literal 引号状态机）
- added 提供时只检查新增行
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

def _in_string_literal(line: str, pos: int) -> bool:
    """近似判断 pos 处的命中是否落在字符串字面量里（单行引号状态机）。

    规则引擎的 pattern（print(、except:、import *）命中代码本体才有意义；
    命中 `"print('started')"` 这种子进程命令字符串只会制造误报
    （2026-11-18 自审计实测：test_process_tree_lifecycle.py 的唯一离线
    命中就是这种假命中）。三引号跨行字面量不在此处展开，接受近似。
    """
    quote = None
    escaped = False
    for index, ch in enumerate(line):
        if index >= pos:
            return quote is not None
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if quote is None and ch in ('"', "'"):
            quote = ch
        elif quote == ch:
            quote = None
    return quote is not None


def review_with_rules(content: str, task_info: Dict, standards: Dict, added: Optional[List[tuple]] = None) -> Dict:
    """使用规则引擎审查（当没有 AI 时）

    added: 仓库 diff 的新增行 [(文件, 行号, 文本)]。提供时规则只检查这些行，
    避免把已删除的代码或未改动的上下文当成本次改动的问题；未提供时检查整段内容。

    每条规则报告全部命中（上限 10 处/规则，防止输出爆炸），逐处给 location；
    命中落在字符串字面量里的跳过（见 _in_string_literal）。
    """
    issues = []
    lines = added if added is not None else [(None, None, text) for text in content.splitlines()]

    def all_matches(pattern, limit=10):
        """全部命中 [(文件, 行号)]；旧版 first_match 只报首个，其余全部漏报。"""
        hits = []
        for path, line_no, text in lines:
            match = re.search(pattern, text) if isinstance(text, str) else None
            if match and not _in_string_literal(text, match.start()):
                hits.append((path, line_no))
                if len(hits) >= limit:
                    break
        return hits

    def location(hit):
        path, line_no = hit
        return f'{path}:{line_no}' if path and line_no else (path or '')

    # 规则 1: 检查常见错误模式
    error_patterns = [
        (r'except\s*:', 'bare except', 'medium', '使用 except Exception 代替 except:'),
        (r'print\(', 'debug print', 'low', '移除调试 print 语句'),
        (r'TODO', 'unfinished', 'low', '完成 TODO 项'),
        (r'import\s+\*', 'wildcard import', 'medium', '避免使用 from X import *'),
    ]

    for pattern, issue_type, severity, suggestion in error_patterns:
        for hit in all_matches(pattern):
            issues.append({
                'type': issue_type,
                'severity': severity,
                'description': f'发现 {issue_type}',
                'location': location(hit),
                'suggestion': suggestion
            })

    # 规则 2: NPU 特定检查
    if 'npu' in task_info['subtypes']:
        npu_patterns = [
            (r'\.cuda\(\)', 'cuda call', 'high', '应该使用 .npu() 而不是 .cuda()'),
            (r'torch\.cuda', 'cuda import', 'high', '应该使用 torch_npu'),
        ]

        for pattern, issue_type, severity, suggestion in npu_patterns:
            for hit in all_matches(pattern):
                issues.append({
                    'type': issue_type,
                    'severity': severity,
                    'description': f'NPU 代码问题: {issue_type}',
                    'location': location(hit),
                    'suggestion': suggestion
                })

    return {
        'issues': issues,
        'method': 'rule_based',
        'note': '使用规则引擎审查（配置 AI 可获得更智能的审查）',
        'overall_assessment': (
            f'规则引擎发现 {len(issues)} 个问题；建议逐项核实。' if issues else
            '规则引擎未命中已知问题规则；该结果不等同于完整语义审查。'
        ),
        'recommendation': 'comment',
    }
