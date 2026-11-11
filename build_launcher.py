"""
Build Script for Genshin Impact Launcher using PyInstaller.
Compiles a standalone Windows executable.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

def build():
    print("=" * 60)
    print("Bắt đầu build Genshin Impact Launcher (.exe)...")
    print("=" * 60)

    icon_path = BASE_DIR / "Themes" / "Default" / "window-icon.ico"
    if not icon_path.exists():
        icon_path = BASE_DIR / "Themes" / "Default" / "Shortcuts" / "GIMI.ico"
    main_script = BASE_DIR / "genshin_launcher.py"

    # PyInstaller arguments
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",                # Onedir is best for launchers with heavy assets and fast startup
        "--windowed",              # No black console window
        "--uac-admin",             # Request UAC elevation so 3DMigoto hook can inject into elevated GenshinImpact.exe
        f"--distpath={BASE_DIR / 'dist'}",
        "--collect-all=customtkinter",
        "--name=GenshinImpactLauncher",
    ]

    if icon_path.exists():
        cmd.append(f"--icon={icon_path}")

    # Add data directories
    for folder in ["Themes", "Locale", "Resources", "GIMI"]:
        src_path = BASE_DIR / folder
        if src_path.exists():
            cmd.append(f"--add-data={src_path};{folder}")

    # Add src/xxmi_launcher
    src_xxmi = BASE_DIR / "src"
    if src_xxmi.exists():
        cmd.append(f"--add-data={src_xxmi};src")

    # Add hidden imports
    hidden_imports = [
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "psutil",
        "customtkinter",
        "win32api",
        "win32com",
        "win32gui",
        "win32process",
        "win32security",
        "ctypes",
        "pefile",
        "tomllib",
        "pynput",
        "pynput.keyboard",
        "keyboard",
        "genshin_locales",
        "genshin_engine",
        "genshin_mod_manager",
        "genshin_macro",
        "genshin_plugins",
        "genshin_wishes",
        "genshin_network",
        "genshin_perf",
        "genshin_launcher_web",
        "genshin_launcher",
        "webview",
        "bottle",
        "clr",
        "clr_loader",
        "pythonnet",
        "proxy_tools",
        "webbrowser",
        "urllib.request",
        "urllib.parse",
        "pystray",
    ]
    for imp in hidden_imports:
        cmd.append(f"--hidden-import={imp}")

    # Add main entry script
    cmd.append(str(main_script))

    print(f"Chạy lệnh PyInstaller:\n{' '.join(cmd)}\n")
    ret = subprocess.run(cmd, cwd=str(BASE_DIR))

    if ret.returncode == 0:
        dist_folder = BASE_DIR / "dist" / "GenshinImpactLauncher"
        dist_exe = dist_folder / "GenshinImpactLauncher.exe"
        
        # Ensure Themes, Resources, GIMI are also copied directly into dist_folder for 100% path safety
        for extra in ["Themes", "Resources", "GIMI"]:
            src_extra = BASE_DIR / extra
            dst_extra = dist_folder / extra
            if src_extra.exists():
                shutil.copytree(src_extra, dst_extra, dirs_exist_ok=True)

        # Create Data_Mods folder in dist
        (dist_folder / "Data_Mods").mkdir(parents=True, exist_ok=True)

        # Ensure CustomTkinter assets (themes, fonts, icons) are present in _internal and root
        try:
            import customtkinter
            ctk_assets = Path(customtkinter.__file__).resolve().parent / "assets"
            if ctk_assets.exists():
                for sub in [dist_folder / "_internal" / "customtkinter" / "assets", dist_folder / "customtkinter" / "assets"]:
                    shutil.copytree(ctk_assets, sub, dirs_exist_ok=True)
                print("Đã bảo đảm CustomTkinter assets có mặt đầy đủ trong thư mục build!")
        except Exception as e:
            print(f"Lỗi sao chép CustomTkinter assets: {e}")
                
        print("=" * 60)
        print(" BUILD THÀNH CÔNG!")
        print(f"File thực thi: {dist_exe}")
        print("=" * 60)
    else:
        print("Build thất bại, vui lòng kiểm tra lỗi bên trên.")

if __name__ == "__main__":
    build()

