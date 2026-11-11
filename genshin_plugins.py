"""
Genshin Impact Plugins Management System
Quản lý các plugin phụ trợ:
1. Chạy chương trình kèm sau khi vào game (Discord, OBS, Macro, RPC...)
2. Gộp mod đang bật thành 1 thư mục mod mới
3. Tích hợp ReShade Add-On (junction reshade-shaders + ReShade.ini)
4. Thêm mod nhanh bằng kéo-thả file nén (.zip, .rar, .7z) hoặc thư mục
5. Phân tích lịch sử cầu nguyện (Wish Tracker)
"""

import os
import sys
import json
import time
import shutil
import zipfile
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import _winapi
except ImportError:
    _winapi = None

def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
PLUGINS_CONFIG_FILE = BASE_DIR / "genshin_plugins.json"


class PluginManager:
    def __init__(self, config_file: Path = PLUGINS_CONFIG_FILE):
        self.config_file = config_file
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        default_config = {
            "plugins": {
                "auto_launch": {
                    "enabled": True,
                    "title": "Chạy chương trình sau khi vào game",
                    "version": "1.0.0",
                    "author": "Yuuki",
                    "desc": "Cho phép gán 1 hay nhiều chương trình (Discord, tool overlay, macro, RPC hiện game...) để launcher tự động chạy kèm ngay sau khi phát hiện game đã khởi chạy thành công — mỗi chương trình có thể đặt độ trễ riêng và bật/tắt độc lập.",
                    "apps": [
                        {
                            "id": "app_discord",
                            "name": "Discord",
                            "path": r"C:\Users\%USERNAME%\AppData\Local\Discord\Update.exe --processStart Discord.exe",
                            "delay": 3,
                            "enabled": False
                        }
                    ]
                },
                "merge_mods": {
                    "enabled": True,
                    "title": "Gộp mod đang bật thành thư mục",
                    "version": "1.0.0",
                    "author": "Yuuki",
                    "desc": "Thêm 1 tab cho phép chọn 1 hay nhiều hạng mục (Nhân vật/Vũ khí/Hiệu ứng) để gộp toàn bộ các mod đang bật trong các hạng mục đó thành 1 thư mục mod duy nhất trong tab 'Thư mục mod', chỉ với 1 lần bấm."
                },
                "wish_history": {
                    "enabled": True,
                    "title": "Lịch sử cầu nguyện",
                    "version": "2.2.1",
                    "author": "HoYo Launcher Mods",
                    "desc": "Tự lấy lịch sử cầu nguyện từ cache cục bộ của game, phân tích và thống kê tỉ lệ nổ 5★, 4★, chuỗi bảo hiểm, pity hiện tại và lịch sử từng lượt quay."
                },
                "reshade": {
                    "enabled": False,
                    "title": "Tích hợp ReShade (bộ lọc màu/post-processing)",
                    "version": "XXMI Add-On",
                    "author": "HoYo Launcher Mods",
                    "desc": "BẬT plugin trong tab Plugin là junction reshade-shaders + ReShade.ini được tạo ngay vào thư mục game, TẮT plugin là junction gỡ khỏi thư mục game; mỗi lần bấm Bắt đầu Game, injector canh sẵn tiêm ReShade vào game ngay khoảnh khắc game xuất hiện. Bấm phím F8 trong game để mở bảng chỉnh màu của ReShade."
                },
                "fast_mod_import": {
                    "enabled": True,
                    "title": "Thêm mod nhanh (kéo-thả file nén)",
                    "version": "1.1.0",
                    "author": "Yuuki",
                    "desc": "Thêm 1 tab dạng cửa sổ thả mod: kéo-thả file nén (.zip, .rar, .7z, .tar, .gz...) hoặc thư mục mod đã giải nén vào BẤT KỲ VỊ TRÍ NÀO trong khung, chọn vị trí thêm (nhân vật/vũ khí/hiệu ứng), chọn icon nếu mod có nhiều ảnh, đặt tên rồi thêm — cửa sổ vẫn mở để thêm liên tục nhiều mod."
                }
            }
        }

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge keys
                    for k, v in default_config["plugins"].items():
                        if k not in data.get("plugins", {}):
                            data.setdefault("plugins", {})[k] = v
                    return data
            except Exception:
                pass

        return default_config

    def save_config(self):
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PluginManager] Lỗi lưu cấu hình: {e}")

    def is_enabled(self, plugin_id: str) -> bool:
        return self.config.get("plugins", {}).get(plugin_id, {}).get("enabled", False)

    def set_enabled(self, plugin_id: str, enabled: bool):
        if plugin_id in self.config.get("plugins", {}):
            self.config["plugins"][plugin_id]["enabled"] = enabled
            self.save_config()

    def get_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        return self.config.get("plugins", {}).get(plugin_id)

    def get_all_plugins(self) -> Dict[str, Any]:
        return self.config.get("plugins", {})

    def get_active_count(self) -> Tuple[int, int]:
        plugins = self.config.get("plugins", {})
        active = sum(1 for p in plugins.values() if p.get("enabled", False))
        return active, len(plugins)

    # =========================================================================
    # 1. AUTO LAUNCH COMPANION APPS POST-GAME LAUNCH
    # =========================================================================
    def get_auto_launch_apps(self) -> List[Dict[str, Any]]:
        return self.config.get("plugins", {}).get("auto_launch", {}).get("apps", [])

    def add_auto_launch_app(self, name: str, path: str, delay: int = 3, enabled: bool = True):
        app_id = f"app_{int(time.time() * 1000)}"
        apps = self.config.setdefault("plugins", {}).setdefault("auto_launch", {}).setdefault("apps", [])
        apps.append({
            "id": app_id,
            "name": name,
            "path": path,
            "delay": delay,
            "enabled": enabled
        })
        self.save_config()

    def remove_auto_launch_app(self, app_id: str):
        apps = self.config.get("plugins", {}).get("auto_launch", {}).get("apps", [])
        self.config["plugins"]["auto_launch"]["apps"] = [a for a in apps if a.get("id") != app_id]
        self.save_config()

    def toggle_auto_launch_app(self, app_id: str, enabled: bool):
        apps = self.config.get("plugins", {}).get("auto_launch", {}).get("apps", [])
        for a in apps:
            if a.get("id") == app_id:
                a["enabled"] = enabled
        self.save_config()

    def run_post_launch_apps(self):
        """
        Khởi chạy các ứng dụng đồng hành được cấu hình sau khi game chạy
        """
        if not self.is_enabled("auto_launch"):
            return

        apps = self.get_auto_launch_apps()

        def _worker(app_info):
            delay = app_info.get("delay", 3)
            time.sleep(delay)
            app_path = os.path.expandvars(app_info.get("path", ""))
            if not app_path:
                return

            try:
                # Nếu path có arguments
                subprocess.Popen(app_path, shell=True)
                print(f"[AutoLaunch] Đã khởi chạy: {app_info.get('name')}")
            except Exception as e:
                print(f"[AutoLaunch] Lỗi khởi chạy {app_info.get('name')}: {e}")

        for app in apps:
            if app.get("enabled", True):
                t = threading.Thread(target=_worker, args=(app,), daemon=True)
                t.start()

    # =========================================================================
    # 2. GỘP MOD ĐANG BẬT THÀNH THƯ MỤC MOD MỚI (MERGE MODS)
    # =========================================================================
    def merge_active_mods(self, mods_dir: Path, data_mods_dir: Path, target_name: str) -> Tuple[bool, str]:
        """
        Quét toàn bộ mod đang bật (junction hoặc folder trong GIMI/Mods),
        sao chép toàn bộ file vào thư mục mới trong Data_Mods/<target_name>
        """
        if not mods_dir.exists():
            return False, f"Thư mục Mods không tồn tại: {mods_dir}"

        target_dir = data_mods_dir / "Gộp_Mod" / target_name
        if target_dir.exists():
            return False, f"Thư mục mod gộp đã tồn tại: {target_dir.name}"

        target_dir.mkdir(parents=True, exist_ok=True)

        copied_count = 0
        try:
            for item in mods_dir.iterdir():
                if item.name.startswith((".", "DISABLED_", "DISABLED")):
                    continue

                dest_item = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest_item, dirs_exist_ok=True)
                    copied_count += 1
                elif item.is_file():
                    shutil.copy2(item, dest_item)
                    copied_count += 1

            if copied_count == 0:
                shutil.rmtree(target_dir, ignore_errors=True)
                return False, "Không có mod nào đang bật để gộp!"

            return True, f"Đã gộp thành công {copied_count} mod vào thư mục: {target_name}"

        except Exception as e:
            return False, f"Lỗi khi gộp mod: {e}"

    # =========================================================================
    # 3. TÍCH HỢP RESHADE ADD-ON (JUNCTION & INJECTION)
    # =========================================================================
    def toggle_reshade(self, game_folder: Path, enable: bool) -> Tuple[bool, str]:
        """
        Tạo hoặc gỡ liên kết Junction cho ReShade shaders và ReShade.ini vào game
        """
        reshade_dir = BASE_DIR / "Resources" / "ReShade"
        shaders_source = reshade_dir / "reshade-shaders"
        ini_source = reshade_dir / "ReShade.ini"

        if not game_folder.exists():
            return False, "Thư mục game không tồn tại!"

        game_shaders = game_folder / "reshade-shaders"
        game_ini = game_folder / "ReShade.ini"

        if enable:
            if not reshade_dir.exists():
                reshade_dir.mkdir(parents=True, exist_ok=True)
            if not shaders_source.exists():
                shaders_source.mkdir(parents=True, exist_ok=True)
                (shaders_source / "Shaders").mkdir(parents=True, exist_ok=True)
                (shaders_source / "Textures").mkdir(parents=True, exist_ok=True)

            if not ini_source.exists():
                with open(ini_source, "w", encoding="utf-8") as f:
                    f.write("[GENERAL]\nEffectSearchPaths=.\\reshade-shaders\\Shaders\nTextureSearchPaths=.\\reshade-shaders\\Textures\nKeyOverlay=119\n")

            try:
                # Xóa junction cũ nếu có
                if game_shaders.is_symlink() or (game_shaders.exists() and not game_shaders.is_file()):
                    try:
                        os.rmdir(game_shaders)
                    except Exception:
                        pass

                if _winapi:
                    _winapi.CreateJunction(str(shaders_source), str(game_shaders))
                else:
                    os.symlink(shaders_source, game_shaders, target_is_directory=True)

                if ini_source.exists() and not game_ini.exists():
                    shutil.copy2(ini_source, game_ini)

                self.set_enabled("reshade", True)
                return True, "Đã bật ReShade Add-On! Junction reshade-shaders đã gắn vào game."
            except Exception as e:
                return False, f"Lỗi tạo Junction ReShade: {e}"
        else:
            try:
                if game_shaders.exists():
                    try:
                        os.rmdir(game_shaders)
                    except Exception:
                        pass
                if game_ini.exists():
                    try:
                        game_ini.unlink(missing_ok=True)
                    except Exception:
                        pass
                self.set_enabled("reshade", False)
                return True, "Đã tắt ReShade Add-On. Junction đã được gỡ an toàn khỏi game."
            except Exception as e:
                return False, f"Lỗi gỡ ReShade: {e}"

    # =========================================================================
    # 4. THÊM MOD NHANH (FAST ARCHIVE IMPORTER)
    # =========================================================================
    def import_mod_archive(self, archive_path: Path, category: str, mod_name: str, data_mods_dir: Path) -> Tuple[bool, str]:
        """
        Giải nén file nén (.zip) hoặc copy thư mục vào Data_Mods/<Category>/<ModName>
        """
        if not archive_path.exists():
            return False, f"File mod không tồn tại: {archive_path}"

        target_dir = data_mods_dir / category / mod_name
        if target_dir.exists():
            return False, f"Mod '{mod_name}' đã tồn tại trong mục '{category}'!"

        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            if archive_path.is_file():
                suffix = archive_path.suffix.lower()
                if suffix == ".zip":
                    with zipfile.ZipFile(archive_path, "r") as z:
                        z.extractall(target_dir)
                else:
                    # Các định dạng khác (.rar, .7z) - kiểm tra có 7z hoặc WinRAR trong PATH không
                    extracted = False
                    for tool in ["7z", "winrar"]:
                        try:
                            if tool == "7z":
                                subprocess.run(["7z", "x", str(archive_path), f"-o{target_dir}", "-y"], check=True)
                                extracted = True
                                break
                        except Exception:
                            continue

                    if not extracted:
                        # Copy trực tiếp file
                        shutil.copy2(archive_path, target_dir)

            elif archive_path.is_dir():
                shutil.copytree(archive_path, target_dir, dirs_exist_ok=True)

            return True, f"Đã thêm thành công mod '{mod_name}' vào '{category}'!"

        except Exception as e:
            shutil.rmtree(target_dir, ignore_errors=True)
            return False, f"Lỗi giải nén mod: {e}"


plugin_manager = PluginManager()

