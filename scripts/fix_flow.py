"""补丁生成/应用/回滚流程（ConversationAgent 的 mixin）。

2026-11-18 自审计后的结构拆分：conversation_agent.py 超过结构守卫
行数预算（994 > 920），且 /fix /apply /discard /undo 是一条完整的
「审查→修复」链路，独立成模块更好测更好读。

宿主（ConversationAgent）需提供这些属性/方法：
    self.client / self.work_root / self.pending_fix / self.undo_bundle /
    self.contexts / self.history / self.last_review_report /
    self.last_ok / self.progress() / self._fail()
"""
from __future__ import annotations

import json
from typing import Optional

from scripts.patch_fix import (
    FIX_SYSTEM,
    apply_fix,
    apply_undo_bundle,
    capture_undo_bundle,
    detect_domain_from_contexts,
    detect_domain_from_diff,
    finalize_undo_bundle,
    format_apply_result,
    parse_fix_json,
    preview_fix,
)
from scripts.patch_fix import ProposedFix  # 类型标注用


class FixFlowMixin:
    """/fix → 预览 → /apply → /undo 的完整流程。不落盘状态全在宿主实例上。"""

    def discard_fix(self) -> str:
        if not self.pending_fix:
            return '当前没有待确认的补丁。'
        self.pending_fix = None
        return '已丢弃待确认补丁。'

    def _review_fix_source(self) -> Optional[tuple]:
        """从最近一次 /review 报告提取 (diff, changed_paths, issues)。

        只取有内容的问题：审查失败（review_result.error）或零问题时返回 None，
        不让空证据进补丁生成。
        """
        report = self.last_review_report
        if not isinstance(report, dict):
            return None
        result = report.get('review_result') or {}
        raw_issues = result.get('issues') or []
        repository = (report.get('metadata') or {}).get('repository') or {}
        if not isinstance(raw_issues, list) or not raw_issues:
            return None
        issues = []
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue
            trimmed = {key: issue.get(key) for key in
                       ('severity', 'type', 'title', 'description', 'location', 'suggestion')}
            if any(str(value or '').strip() for value in trimmed.values()):
                issues.append(trimmed)
        if not issues:
            return None
        return (repository.get('diff') or ''), list(repository.get('changed_files') or []), issues

    def propose_fix(self, explicit_scenario: Optional[str] = None,
                    from_review: bool = False) -> str:
        """Generate a patch preview from active PR/Issue context, or the last
        local /review report (from_review=True). Does not write files."""
        self.last_ok = True
        self.pending_fix = None
        if from_review:
            source = self._review_fix_source()
            if source is None:
                return self._fail(
                    '没有可用的本地审查结果。请先 /review（可加 staged），'
                    '确认有问题清单后再 /fix from-review。')
            diff, changed_paths, review_issues = source
            try:
                scenario, reason, specialist_text = detect_domain_from_diff(
                    diff, changed_paths, explicit=explicit_scenario)
            except (ValueError, OSError) as exc:
                return self._fail(f'专业上下文未就绪：{exc}')
            self.progress(f'识别领域: {scenario}（{reason or "n/a"}）')
            payload = {
                'instruction': '请基于最近一次本地代码审查的发现，生成可本地应用的最小补丁 JSON。'
                               '只修有 location/suggestion 支撑的问题；一条补丁只改一处；'
                               '证据不足以安全修改时返回空 files，不要猜。',
                'scenario': scenario,
                'specialist_reason': reason,
                'specialist_rules': specialist_text or '',
                'review_issues': review_issues,
                'changed_files': changed_paths,
                'recent_dialogue': self.history[-4:],
                'work_root': str(self.work_root),
            }
        else:
            if not self.contexts:
                return self._fail('没有活跃的 PR/Issue 上下文。请先粘贴 GitHub 链接完成分析，再输入 /fix。'
                                  '本地改动也可用 /review 后 /fix from-review。')
            try:
                scenario, reason, specialist_text = detect_domain_from_contexts(
                    self.contexts, explicit=explicit_scenario)
            except (ValueError, OSError) as exc:
                return self._fail(f'专业上下文未就绪：{exc}')
            self.progress(f'识别领域: {scenario}（{reason or "n/a"}）')
            payload = {
                'instruction': '请基于证据生成可本地应用的最小补丁 JSON。',
                'scenario': scenario,
                'specialist_reason': reason,
                'specialist_rules': specialist_text or '',
                'active_pr_issues': self.contexts,
                'recent_dialogue': self.history[-4:],
                'work_root': str(self.work_root),
            }
        if scenario in ('operator', 'inference', 'opengauss') and not specialist_text:
            self.progress('专业规范未加载到正文，将用通用规则生成补丁预览')
        self.progress('生成补丁预览（不会写入磁盘）…')
        try:
            raw = self.client.chat(
                json.dumps(payload, ensure_ascii=False),
                system_prompt=FIX_SYSTEM,
                temperature=0.2,
                max_tokens=4000,
            )
        except Exception:
            return self._fail('生成补丁时 AI 请求异常。')
        if not isinstance(raw, str) or not raw.strip() or raw.lstrip().startswith('Error:'):
            return self._fail('生成补丁失败：' + (raw if isinstance(raw, str) else '未知错误'))

        try:
            fix = parse_fix_json(raw)
        except ValueError as exc:
            return self._fail(f'补丁格式错误：{exc}。请重新 /fix。')
        fix.specialist_reason = reason
        if not fix.scenario or fix.scenario == 'general':
            fix.scenario = scenario
        self.pending_fix = fix
        return preview_fix(fix, root=self.work_root)

    def apply_pending_fix(self, confirm: bool = False, dry_run: bool = False) -> str:
        """Apply pending fix only when confirm=True (or dry_run preview of apply)."""
        self.last_ok = True
        if not self.pending_fix:
            return self._fail('没有待应用的补丁。请先 /fix 生成预览。')
        if not confirm and not dry_run:
            return self._fail('安全起见：请使用 /apply 明确确认后再写入。可用 /fix 重新预览。')
        if not self.pending_fix.files:
            self.pending_fix = None
            return '补丁为空，未写入任何文件。'
        self.progress('写入本地改动…' if not dry_run else 'dry-run 检查…')
        # 写入前抓回滚快照；写入成功后补上 after 内容，供 /undo 一键还原
        bundle = None if dry_run else capture_undo_bundle(self.pending_fix, self.work_root)
        result = apply_fix(self.pending_fix, root=self.work_root, dry_run=dry_run)
        self.last_ok = bool(result.get('ok'))
        text = format_apply_result(result)
        if not dry_run and self.last_ok:
            self.undo_bundle = finalize_undo_bundle(bundle, self.pending_fix, self.work_root)
            self.pending_fix = None
            text += '\n\n待确认补丁已清除。可用 git diff 检查改动'
            if self.undo_bundle:
                text += '；后悔可 /undo 回滚（本会话内有效）'
            text += '。'
        return text

    def undo_last_fix(self) -> str:
        """回滚最近一次成功 /apply 写入的文件（会话内有效，不落盘）。"""
        self.last_ok = True
        if not self.undo_bundle:
            return self._fail('没有可回滚的快照（undo 只覆盖本会话最近一次成功 '
                              '/apply，且要求补丁后文件未被再次修改）。')
        result = apply_undo_bundle(self.undo_bundle, root=self.work_root)
        self.last_ok = bool(result.get('ok'))
        text = format_apply_result(result)
        if self.last_ok:
            self.undo_bundle = None
            text += '\n已回滚到 /apply 之前的内容。可用 git diff 复核。'
        return text
