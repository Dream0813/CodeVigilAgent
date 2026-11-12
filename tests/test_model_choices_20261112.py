"""模型下拉的纯逻辑（scripts/model_choices.py）。

桌面端（Windows tkinter / macOS Swift）都按这套规则摆下拉框，这里锁住行为：
current 优先、未知厂商保持原值、未知模型走自定义、切厂商联动。
"""
import unittest

from scripts.model_catalog import CATALOG, catalog_payload
from scripts.model_choices import build_choices, resolve, select_model, select_provider


def catalog(provider='', model=''):
    return catalog_payload({'provider': provider, 'model': model, 'base_url': ''})['catalog']


def cached():
    """模块级缓存，避免每个用例重算 12 个厂商。"""
    return catalog()


class BuildChoicesTests(unittest.TestCase):
    def test_selects_configured_vendor_and_model(self):
        choices = build_choices(cached(), 'glm', 'glm-4-flash')
        options = choices['options']
        self.assertEqual(len(options), len(CATALOG))
        self.assertEqual(options[choices['index']]['label'], 'glm')
        self.assertEqual(choices['models'][choices['model_index']], 'glm-4-flash')
        self.assertFalse(choices['custom_enabled'])
        self.assertEqual(choices['custom'], '')

    def test_current_wins_over_bare_provider_match(self):
        # kimi 的 file_provider 也是 openai，必须靠 base_url 认出来
        for label in ('kimi', 'gemini', 'xai', 'qwen', 'doubao', 'hunyuan', 'siliconflow', 'minimax'):
            entry = next(item for item in CATALOG if item['label'] == label)
            payload = catalog_payload({'provider': entry['file_provider'],
                                       'model': entry['default_model'],
                                       'base_url': entry['base_url']})['catalog']
            choices = build_choices(payload, entry['file_provider'], entry['default_model'])
            self.assertEqual(choices['options'][choices['index']]['label'], label)
            self.assertEqual(choices['models'][choices['model_index']], entry['default_model'])

    def test_unknown_model_goes_to_custom_without_losing_name(self):
        choices = build_choices(cached(), 'glm', 'my-private-glm')
        self.assertEqual(choices['model_index'], len(choices['models']))
        self.assertEqual(choices['custom'], 'my-private-glm')
        self.assertTrue(choices['custom_enabled'])
        self.assertEqual(resolve(choices, choices['model_index'], choices['custom']),
                         ('glm', 'my-private-glm'))

    def test_unknown_vendor_gets_keep_option_first(self):
        choices = build_choices(cached(), 'myproxy', 'x-1')
        first = choices['options'][0]
        self.assertTrue(first['keep'])
        self.assertEqual(choices['index'], 0)
        self.assertIn('myproxy', first['title'])
        self.assertEqual(resolve(choices, 0, 'x-1'), ('myproxy', 'x-1'))

    def test_empty_catalog_degrades_to_manual(self):
        choices = build_choices([], 'glm', 'glm-4')
        self.assertTrue(choices['degraded'])
        self.assertEqual(choices['options'], [])
        self.assertTrue(choices['custom_enabled'])
        self.assertEqual(resolve(choices, None, 'glm-4'), ('glm', 'glm-4'))
        self.assertIsNone(resolve(choices, None, '   '))

    def test_titles_carry_alias(self):
        titles = {opt['label']: opt['title'] for opt in build_choices(cached())['options']}
        self.assertIn('智谱', titles['glm'])
        self.assertEqual(titles['deepseek'], 'deepseek')


class InteractionTests(unittest.TestCase):
    def test_switch_vendor_updates_models_and_base_url(self):
        choices = build_choices(cached(), 'glm', 'glm-4-flash')
        index = next(i for i, opt in enumerate(choices['options']) if opt['label'] == 'kimi')
        choices = select_provider(choices, index)
        self.assertEqual(choices['base_url'], 'https://api.moonshot.cn/v1')
        self.assertEqual(choices['models'][choices['model_index']], 'kimi-latest')
        self.assertFalse(choices['custom_enabled'])

    def test_select_custom_enables_entry(self):
        choices = build_choices(cached(), 'glm', 'glm-4-flash')
        choices = select_model(choices, len(choices['models']))
        self.assertTrue(choices['custom_enabled'])
        choices = select_model(choices, 0)
        self.assertFalse(choices['custom_enabled'])

    def test_empty_model_is_rejected(self):
        choices = build_choices(cached(), 'glm', 'glm-4-flash')
        choices = select_model(choices, len(choices['models']))
        self.assertIsNone(resolve(choices, choices['model_index'], '  '))

    def test_typed_text_wins_when_prefer_custom(self):
        """直接在手填框打字、没去下拉里选「自定义模型…」也要生效。"""
        choices = build_choices(cached(), 'glm', 'glm-4-flash')
        self.assertEqual(resolve(choices, 0, 'typed-model', prefer_custom=True),
                         ('glm', 'typed-model'))
        # 没打字就仍然用下拉选中的模型
        self.assertEqual(resolve(choices, 0, '', prefer_custom=True), ('glm', 'glm-4'))
        # 关掉 prefer_custom 时保持旧行为（下拉优先）
        self.assertEqual(resolve(choices, 0, 'typed-model'), ('glm', 'glm-4'))

    def test_keep_option_preserves_original_provider(self):
        choices = build_choices(cached(), 'myproxy', '')
        self.assertTrue(choices['options'][0]['keep'])
        self.assertEqual(resolve(choices, 0, 'whatever'), ('myproxy', 'whatever'))


if __name__ == '__main__':
    unittest.main()
