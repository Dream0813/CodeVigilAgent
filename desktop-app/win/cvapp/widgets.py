"""可复用控件：按钮、分组标题、输出面板。

这些控件不认识「审查」「设置」这些业务概念，只负责长得一致。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import ansi_term, theme


class FlatButton(tk.Button):
    """扁平按钮：无边框，悬停变色，支持 accent（强调）/ danger（危险）。"""

    def __init__(self, parent, text: str, command, accent: bool = False,
                 danger: bool = False, font: tuple | None = None, **kwargs):
        self._fg = theme.ACCENT if accent else (theme.DANGER if danger else theme.FG)
        super().__init__(
            parent, text=text, command=command, bg=theme.PANEL_HI, fg=self._fg,
            relief='flat', font=font or theme.ui_font(11), padx=12, pady=6,
            cursor='hand2', activebackground=theme.BG, activeforeground=self._fg,
            borderwidth=0, anchor='w' if kwargs.pop('left', False) else 'center',
            **kwargs,
        )
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)

    def _on_enter(self, _event=None) -> None:
        if str(self['state']) == 'normal':
            self.config(bg=theme.BG)

    def _on_leave(self, _event=None) -> None:
        self.config(bg=theme.PANEL_HI if str(self['state']) == 'normal' else theme.PANEL)


def section_label(parent, text: str) -> tk.Label:
    """侧边栏分组标题：小号、灰色、全大写观感。"""
    return tk.Label(
        parent, text=text, bg=theme.SIDEBAR, fg=theme.FG_FAINT,
        font=theme.ui_font(8), anchor='w', padx=10, pady=2,
    )


def divider(parent) -> tk.Frame:
    return tk.Frame(parent, bg=theme.BORDER, height=1)


class OutputPane(tk.Frame):
    """带滚动条的只读输出区，负责把 ANSI 颜色翻译成 tkinter tag。"""

    def __init__(self, parent, mono_font: tuple):
        super().__init__(parent, bg=theme.BORDER)
        inner = tk.Frame(self, bg=theme.PANEL)
        inner.pack(fill='both', expand=True, padx=1, pady=1)

        self.text = tk.Text(
            inner, bg=theme.PANEL, fg=theme.FG, insertbackground=theme.FG,
            relief='flat', font=mono_font, wrap='none', padx=12, pady=10,
            spacing1=1, spacing3=1, undo=False, state='normal',
        )
        vsb = ttk.Scrollbar(inner, orient='vertical', command=self.text.yview)
        hsb = ttk.Scrollbar(inner, orient='horizontal', command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.text.pack(side='left', fill='both', expand=True)

        self.text.tag_config('dim', foreground=theme.FG_DIM)
        self.text.tag_config('accent', foreground=theme.ACCENT)
        self.text.tag_config('err', foreground=theme.DANGER)
        self.text.tag_config('bold', font=(mono_font[0], mono_font[1], 'bold'))

    def append(self, text: str, tag: str | None = None) -> None:
        if not text:
            return
        for seg, color, bold in ansi_term.parse(text):
            tags = []
            if color:
                name = 'c_' + color.replace('#', '')
                self.text.tag_config(name, foreground=color)
                tags.append(name)
            if bold:
                tags.append('bold')
            if tag and not tags:
                tags.append(tag)
            self.text.insert('end', seg, tuple(tags) if tags else ())
        self.text.see('end')

    def clear(self) -> None:
        self.text.delete('1.0', 'end')
