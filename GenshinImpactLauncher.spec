# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/Themes', 'Themes'), ('C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/Locale', 'Locale'), ('C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/Resources', 'Resources'), ('C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/GIMI', 'GIMI'), ('C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/src', 'src')]
binaries = []
hiddenimports = ['PIL', 'PIL.Image', 'PIL.ImageTk', 'psutil', 'customtkinter', 'win32api', 'win32com', 'win32gui', 'win32process', 'win32security', 'ctypes', 'pefile', 'tomllib', 'pynput', 'pynput.keyboard', 'keyboard', 'genshin_locales', 'genshin_engine', 'genshin_mod_manager', 'genshin_macro', 'genshin_plugins', 'genshin_wishes', 'genshin_network', 'genshin_perf', 'genshin_launcher_web', 'genshin_launcher', 'webview', 'bottle', 'clr', 'clr_loader', 'pythonnet', 'proxy_tools', 'webbrowser', 'urllib.request', 'urllib.parse', 'pystray']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/genshin_launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GenshinImpactLauncher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['C:/Users/Admin/OneDrive/Máy tính/SakuraBot/GenshinLauncher/Themes/Default/window-icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='GenshinImpactLauncher',
)
