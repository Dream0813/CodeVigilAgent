"""Known providers / models for /model switching (mirrors bin/onboard.js catalogs)."""

from __future__ import annotations

import json
import sys
from typing import Dict, List, Optional, Tuple


# file_provider: value stored in ai_config.json (native adapter or openai+base_url)
# label: logical vendor name shown to user
CATALOG: List[Dict] = [
    {
        'label': 'deepseek',
        'file_provider': 'deepseek',
        'base_url': '',
        # 2026-11 校准：官方只接受 deepseek-flash / deepseek-v4-pro，
        # 旧的 deepseek-chat / deepseek-reasoner / deepseek-v3.x 会 400。
        'models': [
            'deepseek-flash', 'deepseek-v4-pro',
        ],
        'default_model': 'deepseek-flash',
        'aliases': ('deepseek',),
    },
    {
        'label': 'openai',
        'file_provider': 'openai',
        'base_url': 'https://api.openai.com/v1',
        'models': [
            'gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4.1-mini',
            'o1', 'o3-mini', 'o4-mini', 'gpt-3.5-turbo',
        ],
        'default_model': 'gpt-4o',
        'aliases': ('openai', 'gpt'),
    },
    {
        'label': 'claude',
        'file_provider': 'claude',
        'base_url': '',
        'models': [
            'claude-opus-4-20250514', 'claude-sonnet-4-20250514',
            'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022',
        ],
        'default_model': 'claude-3-5-sonnet-20241022',
        'aliases': ('claude', 'anthropic'),
    },
    {
        'label': 'glm',
        'file_provider': 'glm',
        'base_url': '',
        'models': [
            'glm-4', 'glm-4-plus', 'glm-4-air', 'glm-4-flash', 'glm-4-long',
            'glm-4v', 'glm-z1-air', 'glm-3-turbo',
        ],
        'default_model': 'glm-4-flash',
        'aliases': ('glm', 'zhipu', '智谱'),
    },
    {
        'label': 'minimax',
        'file_provider': 'openai',
        'base_url': 'https://api.minimax.chat/v1',
        'models': [
            'MiniMax-M1', 'MiniMax-Text-01',
            'abab6.5s-chat', 'abab6.5-chat', 'abab5.5-chat',
        ],
        'default_model': 'MiniMax-Text-01',
        'aliases': ('minimax',),
    },
    {
        'label': 'gemini',
        'file_provider': 'openai',
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'models': [
            'gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-pro',
        ],
        'default_model': 'gemini-2.5-flash',
        'aliases': ('gemini', 'google'),
    },
    {
        'label': 'xai',
        'file_provider': 'openai',
        'base_url': 'https://api.x.ai/v1',
        'models': ['grok-4', 'grok-4-latest', 'grok-3', 'grok-3-mini', 'grok-2'],
        'default_model': 'grok-3',
        'aliases': ('xai', 'grok'),
    },
    {
        'label': 'qwen',
        'file_provider': 'openai',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'models': [
            'qwen-max', 'qwen-plus', 'qwen-turbo', 'qwen-long',
            'qwen2.5-72b-instruct', 'qwq-32b', 'qwen3-32b',
        ],
        'default_model': 'qwen-plus',
        'aliases': ('qwen', '通义', 'dashscope'),
    },
    {
        'label': 'doubao',
        'file_provider': 'openai',
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'models': [
            'doubao-seed-1.6', 'doubao-1.5-pro-32k', 'doubao-pro-32k', 'doubao-lite-32k',
        ],
        'default_model': 'doubao-1.5-pro-32k',
        'aliases': ('doubao', '豆包', 'volc'),
    },
    {
        'label': 'hunyuan',
        'file_provider': 'openai',
        'base_url': 'https://api.hunyuan.cloud.tencent.com/v1',
        'models': [
            'hunyuan-lite', 'hunyuan-standard', 'hunyuan-pro', 'hunyuan-turbo',
        ],
        'default_model': 'hunyuan-turbo',
        'aliases': ('hunyuan', '混元'),
    },
    {
        'label': 'kimi',
        'file_provider': 'openai',
        'base_url': 'https://api.moonshot.cn/v1',
        'models': [
            'moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k',
            'kimi-latest', 'kimi-k2-0711-preview',
        ],
        'default_model': 'kimi-latest',
        'aliases': ('kimi', 'moonshot'),
    },
    {
        'label': 'siliconflow',
        'file_provider': 'openai',
        'base_url': 'https://api.siliconflow.cn/v1',
        'models': [
            'deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1',
            'Qwen/Qwen2.5-72B-Instruct', 'THUDM/GLM-4-9B-0414',
        ],
        'default_model': 'deepseek-ai/DeepSeek-V3',
        'aliases': ('siliconflow', '硅基'),
    },
]


def _norm(s: str) -> str:
    return (s or '').strip().lower()


def _base_key(provider: str, base_url: str) -> Tuple[str, str]:
    return (_norm(provider), _norm(base_url).rstrip('/'))


def find_entry_by_alias(token: str) -> Optional[Dict]:
    t = _norm(token)
    for entry in CATALOG:
        if t == _norm(entry['label']) or t in {_norm(a) for a in entry.get('aliases', ())}:
            return entry
        for m in entry['models']:
            if t == _norm(m):
                return entry
    # prefix / contains for glm-4-xxx etc.
    for entry in CATALOG:
        for m in entry['models']:
            if _norm(m).startswith(t) or t.startswith(_norm(entry['label'])):
                if t.startswith(_norm(entry['label'])) or any(
                        _norm(m2).startswith(t) for m2 in entry['models']):
                    return entry
    return None


def resolve_model_request(raw: str) -> Dict:
    """Parse user input like 'glm' / 'glm-4-flash' / 'MiniMax-M1'.

    Returns dict:
      ok, label, file_provider, model, base_url, matched_exact, message
    """
    text = (raw or '').strip()
    if not text:
        return {'ok': False, 'message': '用法: /model <厂商或模型ID>  例: /model glm  或  /model glm-4-flash'}

    parts = text.split()
    token = parts[0]
    explicit_model = parts[1] if len(parts) > 1 else ''

    # Exact model id match first
    for entry in CATALOG:
        for m in entry['models']:
            if _norm(token) == _norm(m):
                return {
                    'ok': True,
                    'label': entry['label'],
                    'file_provider': entry['file_provider'],
                    'model': m,
                    'base_url': entry.get('base_url') or '',
                    'matched_exact': True,
                    'message': f"识别为 {entry['label']} / {m}",
                }

    entry = find_entry_by_alias(token)
    if not entry:
        # Unknown: keep as bare model id on current gateway — caller decides
        return {
            'ok': True,
            'label': 'custom',
            'file_provider': None,
            'model': text,
            'base_url': None,
            'matched_exact': False,
            'message': f'未识别厂商，将只改 model={text}（仍用当前 API/base_url）',
        }

    model = explicit_model or entry['default_model']
    if explicit_model:
        # allow custom id under known vendor
        model = explicit_model
    else:
        # if token looks like a model under this vendor
        for m in entry['models']:
            if _norm(token) == _norm(m) or _norm(m).startswith(_norm(token)):
                if _norm(token) != _norm(entry['label']) and token.lower() not in {
                        a.lower() for a in entry.get('aliases', ())}:
                    model = m
                    break

    # Vendor-only token (glm / minimax) → default model
    if _norm(token) in {_norm(entry['label']), *{_norm(a) for a in entry.get('aliases', ())}}:
        model = explicit_model or entry['default_model']

    return {
        'ok': True,
        'label': entry['label'],
        'file_provider': entry['file_provider'],
        'model': model,
        'base_url': entry.get('base_url') or '',
        'matched_exact': True,
        'message': f"识别为 {entry['label']} / {model}",
    }


def gateway_changed(current: Dict, target: Dict) -> bool:
    """True if provider/base_url family changes (needs a new API key)."""
    if not target.get('file_provider'):
        return False
    cur_p = _norm(current.get('provider') or '')
    cur_b = _norm(current.get('base_url') or '').rstrip('/')
    # Treat openai+minimax base as minimax lane
    tgt_p = _norm(target['file_provider'])
    tgt_b = _norm(target.get('base_url') or '').rstrip('/')
    return _base_key(cur_p, cur_b) != _base_key(tgt_p, tgt_b)


def apply_target_to_config(data: Dict, target: Dict, api_key: Optional[str] = None) -> Dict:
    """Return updated config dict."""
    out = dict(data or {})
    out['model'] = target['model']
    if target.get('file_provider'):
        out['provider'] = target['file_provider']
        base = target.get('base_url') or ''
        if base:
            out['base_url'] = base
        else:
            # native adapters should not keep a foreign base_url
            out['base_url'] = ''
        out['label'] = target.get('label') or out.get('label')
    if api_key is not None:
        out['api_key'] = api_key
    return out


def format_catalog_help() -> str:
    lines = ['可用厂商（/model <名> 会切厂商并要求对应 API Key）:']
    for entry in CATALOG:
        sample = entry['default_model']
        lines.append(f"  {entry['label']:12} 例: /model {entry['label']}  → {sample}")
    lines.append('也可直接: /model glm-4-flash  /model MiniMax-M1')
    return '\n'.join(lines)


def _norm_base(value: str) -> str:
    return _norm(value).rstrip('/')


def _text(value) -> str:
    """配置里的值可能不是字符串（手改坏了），统一成字符串，别让 --list 崩。"""
    if value is None:
        return ''
    return value if isinstance(value, str) else str(value)


def active_model(path: Optional[str] = None) -> Dict:
    """只读三项：provider / model / base_url。

    文件不存在、JSON 坏了、顶层不是对象、字段类型怪 —— 一律降级为空串，
    绝不让 `model --list` 因为配置文件有问题而抛异常。
    api_key 在这里完全不读取，避免任何形式的回显。
    """
    from scripts.agent_home import read_config, resolve_existing_config

    data: Dict = {}
    try:
        loaded = read_config(path or resolve_existing_config()) or {}
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    return {key: _text(data.get(key)) for key in ('provider', 'model', 'base_url')}


def catalog_payload(active: Optional[Dict] = None) -> Dict:
    """CATALOG 的机器可读版本，给 `model --list --json` 与桌面端下拉框用。

    唯一数据源就是本文件的 CATALOG，不额外维护第二份清单。
    active 只取 provider / model / base_url 三个键：api_key 一律不读取、不输出。
    """
    raw = active if isinstance(active, dict) else {}
    active = {key: _text(raw.get(key)) for key in ('provider', 'model', 'base_url')}
    a_provider = _norm(active['provider'])
    a_base = _norm_base(active['base_url'])

    provider_hits: List[bool] = []
    current_hits: List[bool] = []
    for entry in CATALOG:
        names = {_norm(entry['label']), _norm(entry['file_provider'])}
        names.update(_norm(a) for a in entry.get('aliases', ()))
        hit = bool(a_provider) and a_provider in names
        provider_hits.append(hit)
        if a_base:
            current_hits.append(hit and _norm_base(entry.get('base_url') or '') == a_base)
        else:
            # 配置里没写 base_url 时，只有「原生适配器」条目（base_url 为空）算当前
            current_hits.append(hit and not _norm_base(entry.get('base_url') or ''))

    if not any(current_hits):
        # 兜底：base_url 对不上时，至少把 provider 命中的第一个条目标成当前
        for index, hit in enumerate(provider_hits):
            if hit:
                current_hits[index] = True
                break

    catalog = []
    for entry, is_current in zip(CATALOG, current_hits):
        catalog.append({
            'label': entry['label'],
            'file_provider': entry['file_provider'],
            'base_url': entry.get('base_url') or '',
            'models': list(entry['models']),
            'default_model': entry['default_model'],
            'aliases': list(entry.get('aliases', ())),
            'current': bool(is_current),
        })
    return {
        'catalog': catalog,
        'active': {
            'provider': active['provider'],
            'model': active['model'],
            'base_url': active['base_url'],
        },
    }


def format_catalog_json(active: Optional[Dict] = None) -> str:
    """纯 ASCII 的 JSON：Windows / macOS / Linux 内容完全一致。"""
    return json.dumps(catalog_payload(active), ensure_ascii=True, indent=2)


def print_catalog_json(active: Optional[Dict] = None) -> None:
    """直接写字节流输出 JSON。

    print() 走文本层，Windows 会把 '\\n' 翻译成 '\\r\\n'，重定向到文件后
    和 macOS / Linux 的字节就不一样了。这里绕开文本层，三个平台都是 LF。
    内容全是 ASCII，不需要经过控制台编码。
    """
    text = format_catalog_json(active)
    buffer = getattr(sys.stdout, 'buffer', None)
    if buffer is None:  # 被重定向到 StringIO（测试）时退回普通 print
        print(text)
        return
    buffer.write((text + '\n').encode('ascii'))
    buffer.flush()


def format_catalog_list(payload: Dict) -> str:
    """人读版清单（`model --list` 不带 --json 时用）。"""
    lines = ['可用厂商与模型（来源: scripts/model_catalog.py CATALOG）:']
    for entry in payload['catalog']:
        mark = '  [当前]' if entry['current'] else ''
        lines.append(f"  {entry['label']}（{entry['file_provider']}）{mark}")
        for model in entry['models']:
            suffix = '  (默认)' if model == entry['default_model'] else ''
            lines.append(f"      {model}{suffix}")
        if entry['base_url']:
            lines.append(f"      base_url: {entry['base_url']}")
    active = payload['active']
    lines.append(
        f"当前配置: provider={active['provider'] or '(未设置)'} "
        f"model={active['model'] or '(未设置)'} "
        f"base_url={active['base_url'] or '(默认)'}"
    )
    return '\n'.join(lines)
