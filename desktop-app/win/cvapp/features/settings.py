"""模型设置对话框：读写与终端版共用的 ai_config.json。

模型清单来自终端同一份 CATALOG（`scripts/model_catalog.py`），这里不另写列表：
    scripts.model_catalog.catalog_payload()  →  下拉框选项
    scripts.model_choices.build_choices()    →  该选哪一个、切厂商怎么联动

读不到清单（脚本目录缺失、CATALOG 为空）时降级成手填「模型 ID」，
provider 与其它键一律不动。
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from .. import ROOT, config, theme
from ..widgets import FlatButton
from .base import Feature

CUSTOM_FALLBACK_TITLE = '自定义模型…'


def _load_choices(provider: str, model: str):
    """返回 (choices, 错误信息)。任何异常都不抛给界面。"""
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from scripts.model_choices import build_choices
    except Exception as exc:                            # noqa: BLE001
        return _degraded(provider, model), f'找不到模型清单模块（{exc}）'

    try:
        from scripts.model_catalog import active_model, catalog_payload

        payload = catalog_payload(active_model(config.CONFIG_PATH))
        choices = build_choices(payload.get('catalog') or (), provider, model)
    except Exception as exc:                            # noqa: BLE001
        return build_choices([], provider, model), str(exc)
    if not choices.get('options'):
        return choices, '模型清单为空'
    return choices, ''


def _degraded(provider: str, model: str) -> dict:
    return {'options': [], 'index': -1, 'models': [], 'model_index': 0,
            'custom': model, 'custom_enabled': True, 'base_url': '',
            'provider': provider, 'model': model, 'degraded': True,
            'custom_title': CUSTOM_FALLBACK_TITLE}


def open_settings(app) -> None:
    cfg = config.load_config()
    provider0 = str(cfg.get('provider') or '')
    model0 = str(cfg.get('model') or '')

    win = tk.Toplevel(app.root)
    win.title('模型设置')
    win.configure(bg=theme.BG)
    win.transient(app.root)
    win.grab_set()
    win.resizable(False, False)

    body = tk.Frame(win, bg=theme.BG, padx=24, pady=20)
    body.pack(fill='both', expand=True)
    body.grid_columnconfigure(1, weight=1)

    choices, load_error = _load_choices(provider0, model0)
    state = {'choices': choices}
    custom_title = choices.get('custom_title') or CUSTOM_FALLBACK_TITLE

    style = ttk.Style(win)
    style.configure('Ra.TCombobox', fieldbackground=theme.PANEL,
                    background=theme.PANEL, foreground=theme.FG,
                    arrowcolor=theme.FG_DIM)
    style.map('Ra.TCombobox',
              fieldbackground=[('readonly', theme.PANEL)],
              foreground=[('readonly', theme.FG)])

    def row_label(row: int, text: str) -> None:
        tk.Label(body, text=text, bg=theme.BG, fg=theme.FG_DIM,
                 font=theme.ui_font(11), anchor='w').grid(
            row=row, column=0, sticky='w', pady=8)

    def make_entry(row: int, value: str, show: str = '') -> tk.Entry:
        widget = tk.Entry(
            body, bg=theme.PANEL, fg=theme.FG, insertbackground=theme.FG,
            relief='flat', font=theme.ui_font(11), highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_DIM,
            show=show,
        )
        widget.insert(0, value)
        widget.grid(row=row, column=1, sticky='ew', padx=(16, 0), ipady=6)
        return widget

    def make_combo(row: int) -> ttk.Combobox:
        widget = ttk.Combobox(body, state='readonly', style='Ra.TCombobox',
                              font=theme.ui_font(11), values=[])
        widget.grid(row=row, column=1, sticky='ew', padx=(16, 0), ipady=4)
        return widget

    hint = tk.Label(body, text='', bg=theme.BG, fg=theme.FG_FAINT,
                    font=theme.ui_font(10), anchor='w', justify='left',
                    wraplength=380)

    if choices.get('options'):
        row_label(0, '服务商')
        provider_cb = make_combo(0)
        provider_cb.configure(values=[opt['title'] for opt in choices['options']])
        provider_cb.current(choices['index'])

        row_label(1, '模型')
        model_cb = make_combo(1)

        # 自定义框始终可编辑：用户可以直接在这里打字，不需要先选「自定义模型…」。
        # 用 StringVar + trace 而不是按键事件 —— 粘贴、拖放、输入法都能覆盖到。
        custom_var = tk.StringVar(value=choices['custom'])
        row_label(2, '自定义模型')
        custom_entry = tk.Entry(
            body, textvariable=custom_var, bg=theme.PANEL, fg=theme.FG,
            insertbackground=theme.FG, relief='flat', font=theme.ui_font(11),
            highlightthickness=1, highlightbackground=theme.BORDER,
            highlightcolor=theme.ACCENT_DIM,
        )
        custom_entry.grid(row=2, column=1, sticky='ew', padx=(16, 0), ipady=6)

        row_label(3, 'API 地址')
        base_entry = make_entry(3, str(cfg.get('base_url') or ''))

        syncing = {'on': False}

        def set_custom_text(text: str) -> None:
            """程序写文本框：带守卫，避免触发 trace 把下拉也切走。"""
            syncing['on'] = True
            custom_var.set(text)
            syncing['on'] = False

        def refresh_models() -> None:
            current = state['choices']
            values = list(current['models'])
            model_cb.configure(values=values + [custom_title])
            model_cb.current(current['model_index'])
            set_custom_text(current['custom'])

        def on_provider(_event=None) -> None:
            from scripts.model_choices import select_provider

            state['choices'] = select_provider(state['choices'], provider_cb.current())
            refresh_models()
            # 切厂商自动带出该厂商 base_url，用户之后仍可改
            base_entry.delete(0, 'end')
            base_entry.insert(0, state['choices']['base_url'])

        def on_model(_event=None) -> None:
            from scripts.model_choices import select_model

            state['choices'] = select_model(state['choices'], model_cb.current())
            if model_cb.current() < len(state['choices']['models']):
                # 选回清单里的模型 → 清掉手填内容，避免残留值让人误会
                set_custom_text('')
            else:
                custom_entry.focus_set()

        def on_custom_changed(*_args) -> None:
            """在手填框里输入（含粘贴）→ 模型下拉自动跳到「自定义模型…」。"""
            if syncing['on']:
                return
            if not custom_var.get().strip():
                return
            from scripts.model_choices import select_model

            custom_index = len(state['choices']['models'])
            if model_cb.current() != custom_index:
                model_cb.current(custom_index)
                state['choices'] = select_model(state['choices'], custom_index)

        # 变量跟着窗口一起回收，不需要手动摘 trace
        custom_var.trace_add('write', on_custom_changed)

        provider_cb.bind('<<ComboboxSelected>>', on_provider)
        model_cb.bind('<<ComboboxSelected>>', on_model)
        refresh_models()
        hint.configure(text=f'模型清单来自终端（{len(choices["options"])} 个厂商）；'
                            f'清单里没有的模型直接写在「自定义模型」里。',
                       fg=theme.FG_FAINT)
        degrade = False
        last_row = 5
    else:
        # 读不到清单 → 手填模型 ID；provider 保持原值
        row_label(0, '模型 ID')
        custom_entry = make_entry(0, model0)
        provider_cb = model_cb = None
        row_label(1, 'API 地址')
        base_entry = make_entry(1, str(cfg.get('base_url') or ''))
        hint.configure(text=f'无法读取模型清单（{load_error}），已改为手动输入。',
                       fg=theme.DANGER)
        degrade = True
        last_row = 3

    row_label(last_row - 1, 'API Key')
    key_entry = make_entry(last_row - 1, str(cfg.get('api_key') or ''), show='*')
    hint.grid(row=last_row, column=0, columnspan=2, sticky='ew', pady=(10, 0))

    def save() -> None:
        if degrade:
            model = custom_entry.get().strip()
            picked = (provider0, model) if model else None
        else:
            from scripts.model_choices import resolve

            # prefer_custom：手填框有内容就以它为准（不必先选「自定义模型…」）
            picked = resolve(state['choices'], model_cb.current(), custom_entry.get(),
                             prefer_custom=True)
        if not picked or not picked[1]:
            hint.configure(text='模型不能为空：请在下拉里选一个，或选「自定义模型…」后填写名称。',
                           fg=theme.DANGER)
            custom_entry.focus_set()
            return
        provider, model = picked
        data = dict(cfg)                                 # 保留 api_key / label 等其它键
        if not degrade:
            data['provider'] = provider                  # 降级模式不动 provider
        data['model'] = model
        data['base_url'] = base_entry.get().strip()
        key = key_entry.get().strip()
        if key:
            data['api_key'] = key
        try:
            config.save_config(data)
        except Exception as exc:                         # noqa: BLE001
            hint.configure(text=f'保存失败：{exc}', fg=theme.DANGER)
            return
        app.append(f'\n配置已保存 → {config.CONFIG_PATH}\n', 'accent')
        win.destroy()

    buttons = tk.Frame(body, bg=theme.BG)
    buttons.grid(row=last_row + 1, column=0, columnspan=2, sticky='e', pady=(16, 0))
    FlatButton(buttons, '保存', save, accent=True,
               font=theme.ui_font(11)).pack(side='left')
    FlatButton(buttons, '取消', win.destroy,
               font=theme.ui_font(11)).pack(side='left', padx=(8, 0))

    tk.Label(body, text=config.CONFIG_PATH, bg=theme.BG, fg=theme.FG_FAINT,
             font=theme.ui_font(8), anchor='w').grid(
        row=last_row + 2, column=0, columnspan=2, sticky='w', pady=(12, 0))

    key_entry.focus_set()
    win.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_width()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_height()) // 3
    win.geometry(f'+{max(0, x)}+{max(0, y)}')


FEATURES = [
    Feature(
        id='settings.model', group='系统', label='模型设置',
        handler=open_settings, order=10, shortcut='<Control-comma>',
        hint='下拉选择服务商与模型 / 改 API Key（与终端版共用配置）',
    ),
]
