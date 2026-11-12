"""会话用量估算：/cost 与 aider 的 /tokens、Claude Code 的 /cost 对应。

项目用的是多家 OpenAI 兼容网关，各家返回的 usage 字段并不统一
（有的完全不返回），所以这里做**字符级估算**，并明确标注是估算值：

    ASCII   ≈ 4 字符 / token
    中文    ≈ 1 字 / token（含标点，粗略但足够判断「这次会话贵不贵」）

不显示金额：不同网关单价差异太大，报一个假的精确数字比不报更糟。
"""
from __future__ import annotations

from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """按字符类型粗估 token 数；空串返回 0。"""
    if not text:
        return 0
    cjk = 0
    for char in text:
        code = ord(char)
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            cjk += 1
    other = len(text) - cjk
    return max(1, int(round(cjk + other / 4)))


@dataclass
class UsageMeter:
    calls: int = 0
    prompt_chars: int = 0
    reply_chars: int = 0
    prompt_tokens: int = 0
    reply_tokens: int = 0

    def record(self, prompt: str, reply: str) -> None:
        self.calls += 1
        self.prompt_chars += len(prompt or '')
        self.reply_chars += len(reply or '')
        self.prompt_tokens += estimate_tokens(prompt or '')
        self.reply_tokens += estimate_tokens(reply or '')

    def reset(self) -> None:
        self.calls = self.prompt_chars = self.reply_chars = 0
        self.prompt_tokens = self.reply_tokens = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.reply_tokens

    def report(self, model: str | None = None) -> str:
        if not self.calls:
            return ('本次会话还没有调用模型。\n'
                    '（/cost 统计的是当前进程内的对话；一次性 --message 也会计入）')
        model_line = f'模型：{model}' if model else '模型：未知（未从配置读取到）'
        return '\n'.join([
            '本次会话用量（估算）',
            f'  {model_line}',
            f'  调用次数：{self.calls}',
            f'  输入：约 {self.prompt_tokens:,} tokens（{self.prompt_chars:,} 字符）',
            f'  输出：约 {self.reply_tokens:,} tokens（{self.reply_chars:,} 字符）',
            f'  合计：约 {self.total_tokens:,} tokens',
            '',
            '说明：中文按 1 字 ≈ 1 token、其它按 4 字符 ≈ 1 token 估算；',
            '实际计费以服务商返回的 usage 为准（部分网关不返回 usage）。',
        ])
