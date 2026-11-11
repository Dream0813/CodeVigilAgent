"""在桌面创建 CodeVigil Agent 的快捷方式（.lnk）。

为什么不用 PowerShell：
    本机安全策略禁止 `New-Object -ComObject`（会报「COM object
    instantiation can run arbitrary code」）。改用 Python 的 ctypes
    直接调 IShellLink 接口，属于进程内 API 调用，不走那条限制。

用法：
    python desktop-app/win/make_shortcut.py
    python desktop-app/win/make_shortcut.py --name "我的名字" --remove
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
from ctypes import POINTER, byref, c_ulong, c_ushort, c_void_p, wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

CLSID_SHELLLINK = '{00021401-0000-0000-C000-000000000046}'
IID_ISHELLLINK = '{000214F9-0000-0000-C000-000000000046}'
IID_IPERSISTFILE = '{0000010B-0000-0000-C000-000000000046}'

CLSCTX_INPROC_SERVER = 1


class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', c_ulong),
        ('Data2', c_ushort),
        ('Data3', c_ushort),
        ('Data4', ctypes.c_ubyte * 8),
    ]


ole32 = ctypes.windll.ole32
ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, POINTER(GUID)]
ole32.CLSIDFromString.restype = ctypes.c_long
ole32.CoInitialize.argtypes = [c_void_p]
ole32.CoCreateInstance.argtypes = [
    POINTER(GUID), c_void_p, wintypes.DWORD, POINTER(GUID), POINTER(c_void_p),
]
ole32.CoCreateInstance.restype = ctypes.c_long


def guid(text: str) -> GUID:
    g = GUID()
    hr = ole32.CLSIDFromString(text, byref(g))
    if hr != 0:
        raise OSError(f'CLSIDFromString 失败: {text} hr={hr:#x}')
    return g


def vtable_call(ptr: c_void_p, index: int, *argtypes, restype=ctypes.c_long):
    """取 COM 对象 vtable 里的第 index 个方法并调用。"""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(vtable[index])


def desktop_dir() -> str:
    """取真实桌面路径（可能被 OneDrive 重定向，不能硬拼 ~/Desktop）。"""
    buf = ctypes.create_unicode_buffer(260)
    # CSIDL_DESKTOPDIRECTORY = 0x0010
    hr = ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)
    if hr == 0 and buf.value:
        return buf.value
    return os.path.join(os.path.expanduser('~'), 'Desktop')


def make_shortcut(target: str, arguments: str, workdir: str,
                   name: str, description: str = '',
                   icon: str = '', icon_index: int = 0) -> str:
    ole32.CoInitialize(None)

    p_link = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(guid(CLSID_SHELLLINK)), None, CLSCTX_INPROC_SERVER,
        byref(guid(IID_ISHELLLINK)), byref(p_link),
    )
    if hr != 0 or not p_link:
        raise OSError(f'CoCreateInstance 失败 hr={hr:#x}')

    # IShellLinkW 的方法顺序（vtable 索引）
    vtable_call(p_link, 20, wintypes.LPCWSTR, wintypes.DWORD)(p_link, target, 0)
    vtable_call(p_link, 9, wintypes.LPCWSTR)(p_link, workdir)
    if arguments:
        vtable_call(p_link, 11, wintypes.LPCWSTR)(p_link, arguments)
    if description:
        vtable_call(p_link, 7, wintypes.LPCWSTR)(p_link, description)
    if icon:
        vtable_call(p_link, 17, wintypes.LPCWSTR, ctypes.c_int)(p_link, icon, icon_index)

    # 转 IPersistFile 保存
    p_file = c_void_p()
    hr = vtable_call(p_link, 0, POINTER(GUID), POINTER(c_void_p))(
        p_link, byref(guid(IID_IPERSISTFILE)), byref(p_file))
    if hr != 0 or not p_file:
        raise OSError(f'QueryInterface(IPersistFile) 失败 hr={hr:#x}')

    if not name.lower().endswith('.lnk'):
        name += '.lnk'
    path = os.path.join(desktop_dir(), name)
    hr = vtable_call(p_file, 6, wintypes.LPCWSTR, wintypes.BOOL)(p_file, path, True)
    if hr != 0:
        raise OSError(f'Save 失败 hr={hr:#x}')

    vtable_call(p_link, 2)(p_link)      # Release
    vtable_call(p_file, 2)(p_file)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description='在桌面创建启动快捷方式')
    ap.add_argument('--name', default='CodeVigil Agent')
    ap.add_argument('--remove', action='store_true', help='删除已有快捷方式')
    args = ap.parse_args()

    name = args.name if args.name.lower().endswith('.lnk') else args.name + '.lnk'
    path = os.path.join(desktop_dir(), name)

    if args.remove:
        if os.path.exists(path):
            os.remove(path)
            print(f'已删除：{path}')
        else:
            print(f'不存在：{path}')
        return 0

    # 优先用 pythonw.exe：启动时不会带一个黑色控制台窗口
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    launcher = pyw if os.path.exists(pyw) else exe
    app = os.path.join(HERE, 'app.py')

    out = make_shortcut(
        target=launcher,
        arguments=f'"{app}"',
        workdir=ROOT,
        name=name,
        description='昇腾 AI Infra 代码审查助手',
        icon=launcher,
    )
    print(f'已创建：{out}')
    print(f'  目标：{launcher}')
    print(f'  参数："{app}"')
    print(f'  工作目录：{ROOT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
