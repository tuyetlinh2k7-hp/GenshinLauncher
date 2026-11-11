"""
Genshin Impact Launcher - Modern Web UI Edition (Powered by Microsoft Edge WebView2)
Features:
1. Glassmorphism AAA Web Aesthetic with custom frameless window
2. Instant responsive UI with Tailwind & modern CSS
3. Real-time bidirectional Python <-> Web bridge
4. Full integration with GIMI Virtualizer, Macro, ORFix, HoYoPlay, Wishes & Plugins
"""

import os
import sys
import json
import time
import socket
import logging
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

from bottle import Bottle, static_file, request, response
import webview

# Setup Base Paths
def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))

# Resolve resource locations (supporting PyInstaller _internal & dev mode)
def resolve_res_path(sub_path: str) -> Path:
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(Path(sys._MEIPASS) / sub_path)
    candidates.append(BASE_DIR / sub_path)
    candidates.append(BASE_DIR / "_internal" / sub_path)
    candidates.append(Path(__file__).resolve().parent / sub_path)
    
    for c in candidates:
        if c.exists():
            return c
    return BASE_DIR / sub_path

WEB_DIR = resolve_res_path("web")

import genshin_engine as engine
from genshin_mod_manager import ModManager
from genshin_macro import MacroEngine
from genshin_wishes import wish_tracker
from genshin_plugins import plugin_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("WebLauncher")

# Find an available port
def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

PORT = get_free_port()
app = Bottle()

# Global Instances
mod_manager = ModManager(BASE_DIR)
macro_engine = MacroEngine(BASE_DIR / "genshin_macro_config.json")
window_ref: Optional[webview.Window] = None

# =========================================================================
# STATIC FILE ROUTES
# =========================================================================
@app.route("/")
def index():
    w = resolve_res_path("web")
    return static_file("index.html", root=str(w))

@app.route("/style.css")
def style():
    w = resolve_res_path("web")
    return static_file("style.css", root=str(w), mimetype="text/css")

@app.route("/app.js")
def app_js():
    w = resolve_res_path("web")
    return static_file("app.js", root=str(w), mimetype="application/javascript")

@app.route("/web/<filepath:path>")
def static_web(filepath):
    w = resolve_res_path("web")
    return static_file(filepath, root=str(w))

@app.route("/bg-image")
def bg_image():
    bg_p = resolve_res_path("Themes/Default/MainWindow/LauncherFrame/background-image-gimi.webp")
    if bg_p.exists():
        return static_file(bg_p.name, root=str(bg_p.parent), mimetype="image/webp")
    return ""

@app.route("/game-icon")
def game_icon():
    ico_p = resolve_res_path("Themes/Default/Shortcuts/GIMI.ico")
    if ico_p.exists():
        return static_file(ico_p.name, root=str(ico_p.parent), mimetype="image/x-icon")
    return ""

@app.route("/thumbnail")
def thumbnail():
    p_str = request.query.get("path")
    if p_str:
        p = Path(p_str)
        if p.exists() and p.is_file():
            mime = "image/png"
            if p.suffix.lower() in [".jpg", ".jpeg"]:
                mime = "image/jpeg"
            elif p.suffix.lower() == ".webp":
                mime = "image/webp"
            return static_file(p.name, root=str(p.parent), mimetype=mime)
    return game_icon()

# =========================================================================
# API REST ROUTES
# =========================================================================
@app.route("/api/init", method="GET")
def api_init():
    is_admin = engine.is_admin()
    ver = engine.get_installed_game_version()
    mods = mod_manager.get_all_mods()
    return {
        "success": True,
        "is_admin": is_admin,
        "game_version": ver,
        "total_mods": len(mods),
        "enabled_mods": sum(1 for m in mods if m.is_enabled)
    }

@app.route("/api/status", method="GET")
def api_status():
    return engine.get_game_status()

@app.route("/api/game/launch", method="POST")
def api_game_launch():
    data = request.json or {}
    with_mods = data.get("with_mods", True)
    unlock_fps = data.get("unlock_fps", False)
    
    res = engine.launch_game(with_mods=with_mods, unlock_fps=unlock_fps)
    return res

@app.route("/api/hoyoplay/open", method="POST")
def api_hoyoplay_open():
    ok = engine.launch_hoyoplay()
    return {"success": ok}

@app.route("/api/folder/open", method="POST")
def api_folder_open():
    f = (request.json or {}).get("folder")
    if f == "mods":
        engine.open_folder(mod_manager.data_mods_dir)
    elif f == "shaders":
        engine.open_folder(engine.GIMI_DIR / "ShaderFixes")
    elif f == "game":
        exe = engine.autodetect_game_executable()
        if exe: engine.open_folder(Path(exe).parent)
    elif f == "d3dx":
        d3dx = engine.GIMI_DIR / "d3dx.ini"
        if d3dx.exists():
            os.system(f'notepad.exe "{d3dx}"')
    return {"success": True}

@app.route("/api/shortcut/create", method="POST")
def api_shortcut_create():
    desktop = Path(os.path.expanduser("~/Desktop"))
    lnk = desktop / "Genshin Impact (GIMI Launcher).lnk"
    exe = BASE_DIR / "dist" / "GenshinImpactLauncher" / "GenshinImpactLauncher.exe"
    if not exe.exists():
        exe = BASE_DIR / "Run_Genshin_Launcher.bat"
    ico = BASE_DIR / "Themes" / "Default" / "Shortcuts" / "GIMI.ico"
    ok = engine.create_windows_shortcut(lnk, exe, icon_path=ico)
    return {"success": ok}

@app.route("/api/admin/restart", method="POST")
def api_admin_restart():
    import ctypes
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        args = " ".join([f'"{a}"' for a in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, args, None, 1)
    else:
        script_path = str(Path(__file__).resolve())
        args = f'"{script_path}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, str(BASE_DIR), 1)
    if window_ref:
        window_ref.destroy()
    sys.exit(0)

# Window Controls
@app.route("/api/window/minimize", method="GET")
def win_min():
    if window_ref: window_ref.minimize()
    return {"success": True}

@app.route("/api/window/maximize", method="GET")
def win_max():
    if window_ref:
        if window_ref.state == "maximized":
            window_ref.restore()
        else:
            window_ref.maximize()
    return {"success": True}

@app.route("/api/window/close", method="GET")
def win_close():
    if window_ref: window_ref.destroy()
    return {"success": True}

# Mods Endpoints
@app.route("/api/mods/list", method="POST")
def api_mods_list():
    data = request.json or {}
    cat_filter = data.get("category", "Tất Cả")
    search = data.get("search", "").lower()
    sort_mode = data.get("sort", "name_asc")

    all_mods = mod_manager.get_all_mods()
    categories = {"Tất Cả": len(all_mods)}
    for m in all_mods:
        categories[m.category] = categories.get(m.category, 0) + 1

    filtered = []
    for m in all_mods:
        if cat_filter != "Tất Cả" and m.category != cat_filter:
            continue
        if search and search not in m.name.lower():
            continue
        filtered.append({
            "name": m.name,
            "category": m.category,
            "is_enabled": m.is_enabled,
            "size_mb": m.size_mb,
            "thumbnail": str(m.thumbnail) if m.thumbnail else None
        })

    if sort_mode == "name_desc":
        filtered.sort(key=lambda x: x["name"].lower(), reverse=True)
    elif sort_mode == "size_desc":
        filtered.sort(key=lambda x: x["size_mb"], reverse=True)
    else:
        filtered.sort(key=lambda x: x["name"].lower())

    return {
        "success": True,
        "categories": categories,
        "mods": filtered
    }

@app.route("/api/mod/toggle", method="POST")
def api_mod_toggle():
    data = request.json or {}
    name = data.get("name")
    enabled = data.get("enabled", True)
    ok = mod_manager.set_mod_enabled(name, enabled)
    return {"success": ok}

@app.route("/api/mod/toggle_all", method="POST")
def api_mod_toggle_all():
    enabled = (request.json or {}).get("enabled", True)
    mod_manager.set_all_mods_enabled(enabled)
    return {"success": True}

@app.route("/api/mod/trash", method="POST")
def api_mod_trash():
    name = (request.json or {}).get("name")
    ok = mod_manager.trash_mod(name)
    return {"success": ok}

@app.route("/api/mod/add_dialog", method="POST")
def api_mod_add():
    if window_ref:
        result = window_ref.create_file_dialog(webview.FOLDER_DIALOG)
        if result and len(result) > 0:
            folder = Path(result[0])
            mod_manager.import_mod_folder(folder)
            return {"success": True}
    return {"success": False}

# Groups Endpoints
@app.route("/api/groups/list", method="GET")
def api_groups_list():
    return {"success": True, "groups": mod_manager.get_groups()}

@app.route("/api/groups/create", method="POST")
def api_groups_create():
    name = (request.json or {}).get("name")
    if name:
        g = mod_manager.create_group(name)
        return {"success": True, "group": g}
    return {"success": False}

@app.route("/api/groups/toggle", method="POST")
def api_groups_toggle():
    data = request.json or {}
    gid = data.get("id")
    enabled = data.get("enabled", True)
    count = mod_manager.set_group_enabled(gid, enabled)
    return {"success": True, "count": count}

@app.route("/api/groups/delete", method="POST")
def api_groups_delete():
    gid = (request.json or {}).get("id")
    ok = mod_manager.delete_group(gid)
    return {"success": ok}

# Macro Endpoints
@app.route("/api/macro/config", method="GET")
def api_macro_config():
    return macro_engine.cfg

@app.route("/api/macro/toggle", method="POST")
def api_macro_toggle():
    data = request.json or {}
    feature = data.get("feature")
    enabled = data.get("enabled")
    macro_engine.cfg.setdefault(feature, {})["enabled"] = enabled
    macro_engine.save_config()
    return {"success": True}

@app.route("/api/macro/combo", method="POST")
def api_macro_combo():
    cid = (request.json or {}).get("id", "combo_default_1")
    macro_engine.execute_combo(cid)
    return {"success": True}

# ORFix Endpoints
@app.route("/api/fix/scan", method="POST")
def api_fix_scan():
    dry_run = (request.json or {}).get("dry_run", False)
    res = mod_manager.scan_and_fix_mods(dry_run=dry_run)
    return res

@app.route("/api/fix/undo", method="POST")
def api_fix_undo():
    count = mod_manager.restore_all_fix_backups()
    return {"success": True, "count": count}

# Wishes Endpoints
@app.route("/api/wish/stats", method="GET")
def api_wish_stats():
    return wish_tracker.compute_stats("301")

@app.route("/api/wish/import_cache", method="POST")
def api_wish_import():
    ok = wish_tracker.import_from_game_cache()
    return {"success": ok}

# Plugins Endpoints
@app.route("/api/plugins/list", method="GET")
def api_plugins_list():
    active, _ = plugin_manager.get_active_count()
    return {
        "success": True,
        "active_count": active,
        "plugins": plugin_manager.get_all_plugins()
    }

@app.route("/api/plugins/toggle", method="POST")
def api_plugins_toggle():
    data = request.json or {}
    p_id = data.get("id")
    enabled = data.get("enabled", True)
    ok = plugin_manager.set_plugin_enabled(p_id, enabled)
    return {"success": ok}

# Trash Endpoints
@app.route("/api/trash/list", method="GET")
def api_trash_list():
    return {"success": True, "items": mod_manager.get_trash_items()}

@app.route("/api/trash/restore", method="POST")
def api_trash_restore():
    folder = (request.json or {}).get("folder")
    ok = mod_manager.restore_from_trash(folder)
    return {"success": ok}

@app.route("/api/trash/empty", method="POST")
def api_trash_empty():
    count = mod_manager.empty_trash()
    return {"success": True, "count": count}

# =========================================================================
# LAUNCHER MAIN ENTRY
# =========================================================================
def run_local_server():
    app.run(host="127.0.0.1", port=PORT, quiet=True)

def main():
    global window_ref

    # 1. Start Macro background engine
    macro_engine.start_worker()

    # 2. Start local HTTP server
    srv_thread = threading.Thread(target=run_local_server, daemon=True)
    srv_thread.start()
    time.sleep(0.4)

    # 3. Create pywebview window
    url = f"http://127.0.0.1:{PORT}/"
    log.info(f"Starting Web Launcher at {url}...")

    window_ref = webview.create_window(
        title="Genshin Impact Launcher - HoYoPlay Edition",
        url=url,
        width=1260,
        height=780,
        min_size=(1050, 680),
        frameless=True,
        easy_drag=False,
        background_color="#0a0d18"
    )

    webview.start(debug=False)

if __name__ == "__main__":
    main()
