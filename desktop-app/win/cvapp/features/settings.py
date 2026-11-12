"""模型设置对话框：读写与终端版共用的 ai_config.json。"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from .. import config, theme
from ..widgets import FlatButton
from .base import Feature

FIELDS = [
    ('provider', '服务商', 'deepseek'),
    ('model', '模型 ID', 'deepseek-flash'),
    ('base_url', 'base_url（可空）', ''),
    ('api_key', 'API Key', ''),
]


def open_settings(app) -> None:
    cfg = config.load_config()
    win = tk.Toplevel(app.root)
    win.title('模型设置')
    win.configure(bg=theme.BG)
    win.transient(app.root)
    win.grab_set()
    win.resizable(False, False)

    body = tk.Frame(win, bg=theme.BG, padx=24, pady=20)
    body.pack(fill='both', expand=True)
    body.grid_columnconfigure(1, weight=1)

    entries: dict[str, tk.Entry] = {}
    for row, (key, label, default) in enumerate(FIELDS):
        tk.Label(body, text=label, bg=theme.BG, fg=theme.FG_DIM,
                 font=theme.ui_font(11), anchor='w').grid(
            row=row, column=0, sticky='w', pady=8)
        entry = tk.Entry(
            body, bg=theme.PANEL, fg=theme.FG, insertbackground=theme.FG,
            relief='flat', font=theme.ui_font(11), highlightthickness=1,
            highlightbackground=theme.BORDER, highlightcolor=theme.ACCENT_DIM,
            show='*' if key == 'api_key' else '',
        )
        entry.insert(0, str(cfg.get(key, default) or ''))
        entry.grid(row=row, column=1, sticky='ew', padx=(16, 0), ipady=6)
        entries[key] = entry

    def save() -> None:
        data = {key: entries[key].get().strip() for key in entries}
        try:
            config.save_config(data)
        except Exception as exc:                       # noqa: BLE001
            messagebox.showerror('保存失败', str(exc), parent=win)
            return
        app.append(f'\n配置已保存 → {config.CONFIG_PATH}\n', 'accent')
        win.destroy()

    buttons = tk.Frame(body, bg=theme.BG)
    buttons.grid(row=len(FIELDS), column=0, columnspan=2, sticky='e', pady=(20, 0))
    FlatButton(buttons, '保存', save, accent=True,
               font=theme.ui_font(11)).pack(side='left')
    FlatButton(buttons, '取消', win.destroy,
               font=theme.ui_font(11)).pack(side='left', padx=(8, 0))

    tk.Label(body, text=config.CONFIG_PATH, bg=theme.BG, fg=theme.FG_FAINT,
             font=theme.ui_font(8), anchor='w').grid(
        row=len(FIELDS) + 1, column=0, columnspan=2, sticky='w', pady=(12, 0))

    entries['api_key'].focus_set()
    win.update_idletasks()
    # 居中到主窗口
    x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_width()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_height()) // 3
    win.geometry(f'+{max(0, x)}+{max(0, y)}')


FEATURES = [
    Feature(
        id='settings.model', group='系统', label='模型设置',
        handler=open_settings, order=10, shortcut='<Control-comma>',
        hint='修改服务商 / 模型 / API Key（与终端版共用配置）',
    ),
]
