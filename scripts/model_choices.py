"""模型下拉选项的纯逻辑：没有界面、没有 IO、没有平台依赖。

Windows（tkinter）和 macOS（Swift）两套桌面端的「模型设置」都按同一套规则摆下拉框：

1. 厂商优先选 CLI 标了 ``current`` 的那一条 —— kimi / gemini / qwen 等的
   ``file_provider`` 都是 ``openai``，只按 provider 匹配会把它们认错，得靠 base_url。
2. 配置里的厂商不在清单中 → 第一项是「保持原值（xxx）」，不擅自改掉。
3. 模型默认选 ``default_model``；配置里的模型不在清单里 → 落到「自定义模型…」
   并把原名回填（不强行改成默认值）。
4. 自定义模型名留空 = 无效，由调用方提示，不写配置。

放在 scripts/ 是为了能在没有窗口的测试里直接对拍（见
tests/test_model_choices_20261112.py）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

CUSTOM_TITLE = '自定义模型…'
KEEP_TITLE = '保持原值（{provider}）'


def _norm(text: str) -> str:
    return (text or '').strip().lower()


def entry_matches(entry: Dict, provider: str) -> bool:
    """配置里的 provider 可能是 label / file_provider / alias。"""
    name = _norm(provider)
    if not name:
        return False
    names = {_norm(entry.get('label')), _norm(entry.get('file_provider'))}
    names.update(_norm(alias) for alias in (entry.get('aliases') or ()))
    return name in names


def entry_title(entry: Dict) -> str:
    """下拉框标题：厂商名 + 一个别名（别名同样来自 catalog）。

    优先挑中文别名（glm → 智谱、qwen → 通义），对中文用户更好认；
    没有中文别名就取第一个不同的。
    """
    label = entry.get('label') or ''
    aliases = [alias for alias in (entry.get('aliases') or ()) if _norm(alias) != _norm(label)]
    if not aliases:
        return label
    alias = next((item for item in aliases if any(ord(ch) > 127 for ch in item)), aliases[0])
    return f'{label}（{alias}）'


def _option(entry: Dict) -> Dict:
    return {
        'title': entry_title(entry),
        'label': entry.get('label') or '',
        'file_provider': entry.get('file_provider') or '',
        'base_url': entry.get('base_url') or '',
        'models': list(entry.get('models') or ()),
        'default_model': entry.get('default_model') or '',
        'keep': False,
    }


def _with_models(option: Dict, preferred: str) -> Dict:
    """给定厂商选项，算出模型下拉该显示什么。"""
    models = list(option['models'])
    if option['keep'] or not models:
        return {'models': [], 'model_index': 0, 'custom': preferred, 'custom_enabled': True}
    if preferred:
        if preferred in models:
            return {'models': models, 'model_index': models.index(preferred),
                    'custom': '', 'custom_enabled': False}
        return {'models': models, 'model_index': len(models),
                'custom': preferred, 'custom_enabled': True}
    default = option['default_model']
    if default in models:
        return {'models': models, 'model_index': models.index(default),
                'custom': '', 'custom_enabled': False}
    return {'models': models, 'model_index': 0, 'custom': '', 'custom_enabled': False}


def build_choices(catalog: Sequence[Dict], provider: str = '', model: str = '') -> Dict:
    """打开对话框时调用：算出厂商列表、默认选中项、模型列表。

    catalog 直接来自 ``scripts.model_catalog.catalog_payload()['catalog']``。
    清单为空时返回降级结构（调用方改成手填模型 ID）。
    """
    entries = list(catalog or ())
    provider = (provider or '').strip()
    model = (model or '').strip()

    if not entries:
        return {'options': [], 'index': -1, 'models': [], 'model_index': 0,
                'custom': model, 'custom_enabled': True, 'base_url': '',
                'provider': provider, 'model': model, 'degraded': True,
                'custom_title': CUSTOM_TITLE}

    preferred = (next((e for e in entries if e.get('current')), None)
                 or next((e for e in entries if entry_matches(e, provider)), None)
                 or entries[0])
    options: List[Dict] = [_option(entry) for entry in entries]
    index = next((i for i, entry in enumerate(entries)
                  if entry.get('label') == preferred.get('label')), 0)

    known = any(entry.get('current') or entry_matches(entry, provider) for entry in entries)
    if provider and not known:
        options.insert(0, {
            'title': KEEP_TITLE.format(provider=provider),
            'label': provider,
            'file_provider': provider,
            'base_url': '',
            'models': [],
            'default_model': '',
            'keep': True,
        })
        index = 0

    state = _with_models(options[index], model)
    return {
        'options': options,
        'index': index,
        'models': state['models'],
        'model_index': state['model_index'],
        'custom': state['custom'],
        'custom_enabled': state['custom_enabled'],
        'base_url': '',          # 由调用方用配置里的值初始化，不要覆盖用户手填
        'provider': provider,
        'model': model,
        'degraded': False,
        'custom_title': CUSTOM_TITLE,
    }


def select_provider(choices: Dict, index: int) -> Dict:
    """切换厂商：模型列表跟着换、默认选 default_model、带出该厂商 base_url。"""
    options = choices.get('options') or []
    if not options:
        return dict(choices)
    index = max(0, min(index, len(options) - 1))
    option = options[index]
    fallback = choices.get('model') or ''
    state = _with_models(option, fallback if option['keep'] else '')
    out = dict(choices)
    out.update({
        'index': index,
        'models': state['models'],
        'model_index': state['model_index'],
        'custom': state['custom'],
        'custom_enabled': state['custom_enabled'],
        'base_url': option['base_url'],
    })
    return out


def select_model(choices: Dict, model_index: int) -> Dict:
    """切换模型：选中「自定义」时把手输框放出来。"""
    out = dict(choices)
    out['model_index'] = model_index
    out['custom_enabled'] = model_index >= len(out.get('models') or ())
    return out


def resolve(choices: Dict, model_index: Optional[int] = None,
            custom_text: str = '', prefer_custom: bool = False) -> Optional[Tuple[str, str]]:
    """读回用户的选择 → (provider, model)；模型为空返回 None。

    prefer_custom=True 时（桌面端用）：手填框里有内容就以它为准 —— 用户直接在
    「自定义模型」里打字时，不需要先去下拉里选一次「自定义模型…」。
    """
    models = choices.get('models') or []
    if model_index is None:
        model_index = choices.get('model_index', 0)
    text = (custom_text or '').strip()
    if prefer_custom and text:
        model = text
    elif 0 <= model_index < len(models):
        model = models[model_index]
    else:
        model = text
    if not model:
        return None
    options = choices.get('options') or []
    index = choices.get('index', -1)
    if 0 <= index < len(options):
        provider = options[index].get('file_provider') or ''
    else:
        provider = ''
    return (provider or choices.get('provider') or '', model)


def base_url_for(choices: Dict, index: Optional[int] = None) -> str:
    """某个厂商的 base_url（切换厂商时给输入框用）。"""
    options = choices.get('options') or []
    if index is None:
        index = choices.get('index', -1)
    if 0 <= index < len(options):
        return options[index].get('base_url') or ''
    return ''
