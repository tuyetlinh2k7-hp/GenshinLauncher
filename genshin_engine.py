"""
Genshin Impact Launcher - Core Engine
Handles game autodetection, GIMI (3DMigoto) hook injection, FPS unlocker, and process lifecycle.
Based on XXMI Launcher GIMI architecture.
"""

import os
import sys
import json
import time
import winreg
import shutil
import logging
import psutil
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# Setup logging
logging.basicConfig(
    filename='genshin_launcher.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    encoding='utf-8'
)
log = logging.getLogger("GenshinEngine")

def get_base_dir() -> Path:
    """Resolves root GenshinLauncher directory properly in both dev and PyInstaller frozen modes."""
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "GIMI").exists():
            return exe_dir
        if (exe_dir / "_internal" / "GIMI").exists():
            return exe_dir
        if hasattr(sys, '_MEIPASS') and (Path(sys._MEIPASS) / "GIMI").exists():
            return Path(sys._MEIPASS)
        if (exe_dir.parent / "GIMI").exists():
            return exe_dir.parent
        if (exe_dir.parent.parent / "GIMI").exists():
            return exe_dir.parent.parent
        return exe_dir
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()

if (BASE_DIR / "GIMI").exists():
    GIMI_DIR = BASE_DIR / "GIMI"
elif (BASE_DIR / "_internal" / "GIMI").exists():
    GIMI_DIR = BASE_DIR / "_internal" / "GIMI"
else:
    GIMI_DIR = BASE_DIR / "GIMI"

if (BASE_DIR / "Resources").exists():
    RESOURCES_DIR = BASE_DIR / "Resources"
elif (BASE_DIR / "_internal" / "Resources").exists():
    RESOURCES_DIR = BASE_DIR / "_internal" / "Resources"
else:
    RESOURCES_DIR = BASE_DIR / "Resources"

PACKAGES_DIR = RESOURCES_DIR / "Packages"
XXMI_PKG_DIR = PACKAGES_DIR / "XXMI"
FPS_PKG_DIR = PACKAGES_DIR / "GI-FPS-Unlocker"
CONFIG_FILE = BASE_DIR / "genshin_config.json"


def is_admin() -> bool:
    """Checks if current process has Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def enable_debug_privilege():
    """
    Enables SeDebugPrivilege for full process inspection and injection access.
    Prevents 'Invalid Handle: 5' (ERROR_ACCESS_DENIED) during 3DMigoto verification.
    """
    try:
        import win32security
        import win32api

        hToken = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY
        )
        luid = win32security.LookupPrivilegeValue(None, win32security.SE_DEBUG_NAME)
        newPrivileges = [(luid, win32security.SE_PRIVILEGE_ENABLED)]
        win32security.AdjustTokenPrivileges(hToken, 0, newPrivileges)
        log.info("Successfully enabled SeDebugPrivilege.")
    except Exception as e:
        log.warning(f"Could not enable SeDebugPrivilege: {e}")


# Automatically try to enable debug privilege on import
enable_debug_privilege()

DEFAULT_CONFIG: Dict[str, Any] = {
    "game_path": "",
    "unlock_fps": False,
    "fps_target": 120,
    "window_mode": "BORDERLESS",  # "BORDERLESS", "EXCLUSIVE", "WINDOWED"
    "process_priority": "NORMAL",  # "NORMAL", "HIGH", "ABOVE_NORMAL"
    "disable_dcr": True,
    "enforce_rendering": True,
    "enable_hdr": False,
    "launch_options": "",
    "auto_close_launcher": False,
    "language": "vi",
}


def load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception as e:
            log.error(f"Failed to read {CONFIG_FILE}: {e}")
    else:
        # Try to import from existing user XXMI config if available
        user_xxmi_cfg = Path(os.path.expandvars(r"%APPDATA%\XXMI Launcher\XXMI Launcher Config.json"))
        if user_xxmi_cfg.exists():
            try:
                with open(user_xxmi_cfg, "r", encoding="utf-8") as f:
                    xxmi_data = json.load(f)
                    gimi_imp = xxmi_data.get("Importers", {}).get("GIMI", {}).get("Importer", {})
                    if gimi_imp.get("game_folder"):
                        folder = Path(gimi_imp["game_folder"])
                        for exe in ["GenshinImpact.exe", "YuanShen.exe"]:
                            candidate = folder / exe
                            if candidate.exists():
                                cfg["game_path"] = str(candidate)
                                break
                    if "unlock_fps" in gimi_imp:
                        cfg["unlock_fps"] = bool(gimi_imp["unlock_fps"])
                    if "unlock_fps_value" in gimi_imp:
                        cfg["fps_target"] = int(gimi_imp["unlock_fps_value"])
                    if "window_mode" in gimi_imp:
                        cfg["window_mode"] = str(gimi_imp["window_mode"])
                    log.info("Imported initial settings from user XXMI config!")
            except Exception as e:
                log.warning(f"Failed to read existing XXMI config: {e}")

    # If game_path is still empty, autodectect
    if not cfg.get("game_path") or not Path(cfg["game_path"]).exists():
        detected = autodetect_game_executable()
        if detected:
            cfg["game_path"] = detected

    save_config(cfg)
    return cfg


def save_config(cfg: Dict[str, Any]):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        log.error(f"Failed to save {CONFIG_FILE}: {e}")


def autodetect_game_executable() -> Optional[str]:
    """
    Autodetects GenshinImpact.exe or YuanShen.exe via:
    1. HoyoPlay standard installation paths
    2. Registry keys (miHoYo, HoyoPlay, Cognosphere, Uninstall)
    3. Common local disk folders
    """
    candidates = []

    # 1. HoyoPlay standard paths across all active Windows drives
    import string
    active_drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    for dr_str in active_drives:
        dr = Path(dr_str)
        candidates = [
            dr / "Program Files" / "HoYoPlay" / "games" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Program Files" / "HoYoPlay" / "games" / "Genshin Impact game" / "YuanShen.exe",
            dr / "HoYoPlay" / "games" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "HoYoPlay" / "games" / "Genshin Impact game" / "YuanShen.exe",
            dr / "Program Files" / "Genshin Impact" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Genshin Impact" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Games" / "Genshin Impact" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Games" / "HoYoPlay" / "games" / "Genshin Impact game" / "GenshinImpact.exe",
            dr / "Genshin Impact" / "GenshinImpact.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)

    # 2. Check Windows Registry
    registry_locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Genshin Impact"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\原神"),
        (winreg.HKEY_CURRENT_USER, r"Software\miHoYo\Genshin Impact"),
        (winreg.HKEY_CURRENT_USER, r"Software\Cognosphere\Genshin Impact"),
        (winreg.HKEY_CURRENT_USER, r"Software\miHoYo\HYP\1_0"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\miHoYo\HYP\1_0"),
    ]
    for hkey, subkey in registry_locations:
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                for val_name in ["InstallPath", "Path", "InstallLocation"]:
                    try:
                        val, _ = winreg.QueryValueEx(key, val_name)
                        if val:
                            folder = Path(val)
                            for exe in ["GenshinImpact.exe", "YuanShen.exe"]:
                                f1 = folder / exe
                                if f1.exists():
                                    return str(f1)
                                f2 = folder / "Genshin Impact game" / exe
                                if f2.exists():
                                    return str(f2)
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            pass

    # 3. Check AppData output_log.txt for installation directory
    locallow_log = Path(os.path.expandvars(r"%APPDATA%\..\LocalLow\miHoYo\Genshin Impact\output_log.txt"))
    if locallow_log.exists():
        try:
            with open(locallow_log, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(8192)
                import re
                m = re.search(r"([a-zA-Z]:[\\/][^:\r\n]*Genshin Impact game)", content, re.IGNORECASE)
                if m:
                    folder = Path(m.group(1))
                    for exe in ["GenshinImpact.exe", "YuanShen.exe"]:
                        f = folder / exe
                        if f.exists():
                            return str(f)
        except Exception:
            pass

    return None


def find_hoyoplay_launcher() -> Optional[Path]:
    """Finds the official HoYoPlay launcher executable across all drives and paths."""
    import string
    active_drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    sub_paths = [
        Path("Program Files") / "HoYoPlay" / "launcher.exe",
        Path("Program Files (x86)") / "HoYoPlay" / "launcher.exe",
        Path("HoYoPlay") / "launcher.exe",
        Path("Games") / "HoYoPlay" / "launcher.exe",
    ]
    for dr_str in active_drives:
        dr = Path(dr_str)
        for sp in sub_paths:
            p = dr / sp
            if p.exists():
                return p
    return None


def launch_hoyoplay() -> bool:
    """Launches the official HoYoPlay launcher for game updates and file repair."""
    hyp_exe = find_hoyoplay_launcher()
    if not hyp_exe:
        return False
    try:
        subprocess.Popen([str(hyp_exe)], cwd=str(hyp_exe.parent))
        return True
    except Exception as e:
        log.error(f"Failed to launch HoYoPlay: {e}")
        return False


def get_installed_game_version(game_exe_str: Optional[str] = None) -> str:
    """Reads game_version from game's config.ini."""
    target_exe = game_exe_str or autodetect_game_executable()
    if not target_exe:
        return "7.1.0"
    cfg_file = Path(target_exe).parent / "config.ini"
    if cfg_file.exists():
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(cfg_file, encoding="utf-8")
            return cp.get("general", "game_version", fallback="7.1.0")
        except Exception:
            pass
    return "7.1.0"


def get_game_process() -> Optional[psutil.Process]:
    """Returns the running Genshin Impact process if active."""
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time', 'memory_info']):
        try:
            name = proc.info['name']
            if name and name.lower() in ['genshinimpact.exe', 'yuanshen.exe']:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return None


def get_game_status() -> Dict[str, Any]:
    """Returns real-time status of Genshin Impact process."""
    proc = get_game_process()
    if proc:
        try:
            mem = proc.memory_info().rss / (1024 * 1024)
            uptime = int(time.time() - proc.create_time())
            mins, secs = divmod(uptime, 60)
            hours, mins = divmod(mins, 60)
            time_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
            return {
                "running": True,
                "pid": proc.pid,
                "name": proc.name(),
                "memory_mb": round(mem, 1),
                "uptime": time_str,
            }
        except Exception:
            pass
    return {
        "running": False,
        "pid": 0,
        "name": "",
        "memory_mb": 0,
        "uptime": "",
    }


def get_game_detailed_info(game_exe_str: Optional[str] = None) -> Dict[str, Any]:
    """Trả về gói thông tin cơ bản và trạng thái hệ thống của Genshin Impact."""
    target_exe = game_exe_str or autodetect_game_executable()
    ver = get_installed_game_version(target_exe)
    status = get_game_status()

    server_name = "Châu Á / Quốc Tế (os_asia - hk4e_global)"
    cps_info = "mihoyo / HoYoverse"
    dir_path = ""
    size_str = "~159 GB"

    if target_exe and Path(target_exe).exists():
        p = Path(target_exe)
        dir_path = str(p.parent)
        cfg_file = p.parent / "config.ini"
        if cfg_file.exists():
            try:
                import configparser
                cp = configparser.ConfigParser()
                cp.read(cfg_file, encoding="utf-8")
                cps_info = cp.get("general", "cps", fallback="mihoyo")
                uapc = cp.get("general", "uapc", fallback="")
                if "hk4e_cn" in uapc:
                    server_name = "Trung Quốc (Celestia / Irminsul - gf_01)"
                elif "hk4e_global" in uapc:
                    server_name = "Quốc Tế / Châu Á (os_asia - hk4e_global)"
            except Exception:
                pass

    return {
        "name": "Genshin Impact (原神)",
        "version": ver,
        "exe_path": target_exe or "Chưa cài đặt / Không tìm thấy",
        "game_dir": dir_path or "Chưa xác định",
        "publisher": cps_info,
        "server": server_name,
        "graphics_api": "DirectX 11 (Direct3D 11)",
        "mod_system": "Ảo hóa liên kết Windows Junction (An toàn 100%)",
        "is_running": status["running"],
        "pid": status["pid"],
        "memory_mb": status["memory_mb"],
        "uptime": status["uptime"],
        "approx_size": size_str
    }


def kill_background_hoyoplay() -> int:
    """
    Terminates HoYoPlay background processes (hyp.exe, launcher.exe, hoyoplay.exe, hyphelper.exe)
    so that HoYoPlay launcher does not stay running in the system tray and pop up when the game exits.
    """
    targets = {'hyp.exe', 'launcher.exe', 'hoyoplay.exe', 'hyphelper.exe', 'hypworker.exe', 'hypreporter.exe'}
    killed_count = 0
    for proc in psutil.process_iter(['pid', 'name', 'exe']):
        try:
            name = proc.info['name']
            if name and name.lower() in targets:
                exe_path = (proc.info.get('exe') or '').lower()
                # Verify that it is indeed HoYoPlay or HYP
                if 'hoyoplay' in exe_path or name.lower().startswith('hyp') or 'hoyoplay' in name.lower():
                    proc.kill()
                    killed_count += 1
                    log.info(f"Terminated background HoYoPlay process {name} (PID: {proc.pid})")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed_count


def has_visible_window(pid: int) -> bool:
    """
    Checks if the process with the given PID has at least one visible top-level window.
    Used to ensure GenshinImpact.exe has fully initialized before unhooking 3DMigoto.
    """
    try:
        import win32gui
        import win32process
    except ImportError:
        return False

    found_hwnds = []

    def enum_windows_callback(hwnd, extra):
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == pid:
                if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
                    rect = win32gui.GetWindowRect(hwnd)
                    width = rect[2] - rect[0]
                    height = rect[3] - rect[1]
                    # Window must have non-trivial size (skip hidden 0x0 or 1x1 helper windows)
                    if width > 200 and height > 200:
                        found_hwnds.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(enum_windows_callback, None)
    except Exception:
        pass

    return len(found_hwnds) > 0


def kill_game_process() -> bool:
    """Terminates any active Genshin Impact processes."""
    killed = False
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() in ['genshinimpact.exe', 'yuanshen.exe', 'unlockfps_nc.exe']:
                proc.terminate()
                killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    kill_background_hoyoplay()
    return killed


def update_d3dx_ini(game_exe_name: str, enforce_rendering: bool = True):
    """
    Updates d3dx.ini in GIMI folder to ensure proper loader and rendering hooks.
    Crucial: 3DMigoto's d3d11.dll checks [Loader] loader = ... and target = ...
    If loader does not match current process, d3d11.dll initialization fails with error 1114.
    """
    d3dx_path = GIMI_DIR / "d3dx.ini"
    if not d3dx_path.exists():
        log.warning(f"{d3dx_path} does not exist.")
        return

    try:
        with open(d3dx_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        import re
        current_exe = Path(sys.executable).name

        # 1. Ensure target process in d3dx.ini matches the game executable
        if re.search(r"^[;\s]*target\s*=.*$", content, re.MULTILINE):
            content = re.sub(r"^[;\s]*target\s*=.*$", f"target = {game_exe_name}", content, flags=re.MULTILINE)
        else:
            content = re.sub(r"(\[Loader\])", f"\\1\ntarget = {game_exe_name}", content, flags=re.IGNORECASE)

        # 2. Ensure loader in d3dx.ini matches current process (python.exe, GenshinImpactLauncher.exe, etc.)
        if re.search(r"^[;\s]*loader\s*=.*$", content, re.MULTILINE):
            content = re.sub(r"^[;\s]*loader\s*=.*$", f"loader = {current_exe}", content, flags=re.MULTILINE)
        else:
            content = re.sub(r"(\[Loader\])", f"\\1\nloader = {current_exe}", content, flags=re.IGNORECASE)

        # 3. Ensure allow_buffer_resize if enforce_rendering is enabled
        if enforce_rendering:
            if re.search(r"^[;\s]*allow_buffer_resize\s*=.*$", content, re.MULTILINE):
                content = re.sub(r"^[;\s]*allow_buffer_resize\s*=.*$", "allow_buffer_resize = 1", content, flags=re.MULTILINE)

        with open(d3dx_path, "w", encoding="utf-8") as f:
            f.write(content)
        log.info(f"Updated d3dx.ini successfully (target={game_exe_name}, loader={current_exe}).")
    except Exception as e:
        log.error(f"Failed to update d3dx.ini: {e}")


def spawn_process_elevated(exe_path: Path, args: str, work_dir: Path) -> bool:
    """
    Launches an executable using ShellExecuteW to properly handle Windows UAC elevation.
    GenshinImpact.exe requires Administrator privileges; subprocess.Popen fails with WinError 740.
    """
    res = ctypes.windll.shell32.ShellExecuteW(
        None,
        "open",
        str(exe_path),
        args,
        str(work_dir),
        1  # SW_SHOWNORMAL
    )
    if res <= 32:
        # Fallback to explicit runas
        res = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe_path),
            args,
            str(work_dir),
            1
        )
    return res > 32


def configure_fps_unlocker(game_exe_path: str, fps_target: int = 120, window_mode: str = "BORDERLESS", priority: int = 3, dll_list: List[str] = None):
    """
    Configures GI-FPS-Unlocker's fps_config.json.
    """
    template_path = FPS_PKG_DIR / "fps_config_template.json"
    target_path = FPS_PKG_DIR / "fps_config.json"

    fps_config = {}
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                fps_config = json.load(f)
        except Exception:
            pass

    if not fps_config and template_path.exists():
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                fps_config = json.load(f)
        except Exception:
            pass

    fps_config["GamePath"] = str(game_exe_path)
    fps_config["FPSTarget"] = fps_target
    fps_config["Priority"] = priority
    fps_config["AutoStart"] = True
    fps_config["AutoClose"] = True

    if window_mode == "BORDERLESS":
        fps_config["PopupWindow"] = True
        fps_config["Fullscreen"] = False
        fps_config["IsExclusiveFullscreen"] = False
    elif window_mode == "EXCLUSIVE":
        fps_config["PopupWindow"] = False
        fps_config["Fullscreen"] = True
        fps_config["IsExclusiveFullscreen"] = True
    elif window_mode == "WINDOWED":
        fps_config["PopupWindow"] = False
        fps_config["Fullscreen"] = False
        fps_config["IsExclusiveFullscreen"] = False

    if dll_list:
        fps_config["DllList"] = [str(p) for p in dll_list if os.path.exists(p)]

    try:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(fps_config, f, indent=4)
        log.info(f"Configured FPS unlocker for target {fps_target} FPS.")
    except Exception as e:
        log.error(f"Failed to write fps_config.json: {e}")


class DllInjector:
    """
    Self-contained 3DMigoto DLL hook injector based on 3dmloader.dll.
    Direct ctypes implementation without external dependencies (no tomllib/locale_manager).
    """
    def __init__(self, injector_lib_path: Path, load_hook: bool = True, load_inject: bool = False):
        self.lib = None
        self.dll_path = None
        self.target_process = None
        self.hook = None
        self.mutex = None
        self.load(Path(injector_lib_path).resolve(), load_hook, load_inject)

    def load(self, injector_lib_path: Path, load_hook: bool = True, load_inject: bool = False):
        if not injector_lib_path.exists():
            raise ValueError(f"Không tìm thấy file injector: {injector_lib_path}")

        try:
            self.lib = ctypes.cdll.LoadLibrary(str(injector_lib_path))
        except Exception as e:
            raise ValueError(f"Không thể nạp thư viện injector: {e}") from e

        try:
            import ctypes.wintypes as wt
            if load_hook:
                self.lib.HookLibrary.argtypes = (wt.LPCWSTR, ctypes.POINTER(wt.HHOOK), ctypes.POINTER(wt.HANDLE))
                self.lib.HookLibrary.restype = ctypes.c_int

                self.lib.WaitForInjection.argtypes = (wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int)
                self.lib.WaitForInjection.restype = ctypes.c_int

                self.lib.UnhookLibrary.argtypes = (ctypes.POINTER(wt.HHOOK), ctypes.POINTER(wt.HANDLE))
                self.lib.UnhookLibrary.restype = ctypes.c_int

            if load_inject:
                self.lib.Inject.argtypes = (wt.DWORD, wt.LPCWSTR, ctypes.c_int)
                self.lib.Inject.restype = ctypes.c_int
        except Exception as e:
            try:
                self.unload()
            except Exception:
                pass
            raise ValueError(f"Không thể cấu hình hàm injector: {e}") from e

    def unload(self):
        if self.lib and hasattr(self.lib, '_handle') and self.lib._handle:
            import ctypes.wintypes as wt
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.FreeLibrary.argtypes = [wt.HMODULE]
            kernel32.FreeLibrary(self.lib._handle)
            self.lib = None

    def hook_library(self, dll_path: Path, target_process: str):
        import ctypes.wintypes as wt
        if self.hook is not None:
            self.unhook_library()

        self.dll_path = wt.LPCWSTR(str(dll_path.resolve()))
        self.target_process = wt.LPCWSTR(target_process)
        self.hook = wt.HHOOK()
        self.mutex = wt.HANDLE()

        result = self.lib.HookLibrary(self.dll_path, ctypes.byref(self.hook), ctypes.byref(self.mutex))

        if result == 100:
            raise ValueError("Một phiên bản 3DMigotoLoader khác hiện đang chạy!")
        elif result == 200:
            raise ValueError(f"Không thể tải {dll_path.name} (Code 200)!")
        elif result == 300:
            raise ValueError(f"File {dll_path.name} thiếu điểm nhập (entry point)!")
        elif result == 400:
            raise ValueError(f"Không thể thiết lập Windows CBT hook cho {dll_path.name}!")
        elif result != 0:
            raise ValueError(f"Lỗi không xác định khi hook {dll_path.name} (Code {result})!")
        if not bool(self.hook):
            raise ValueError(f"Hook bị NULL cho {dll_path.name}!")

    def wait_for_injection(self, timeout: int = 15) -> bool:
        if self.dll_path is None or self.target_process is None or self.hook is None:
            return False
        result = self.lib.WaitForInjection(self.dll_path, self.target_process, ctypes.c_int(timeout))
        return result == 0

    def unhook_library(self) -> bool:
        if self.hook is None and self.mutex is None:
            return True
        result = self.lib.UnhookLibrary(ctypes.byref(self.hook), ctypes.byref(self.mutex))
        self.dll_path = None
        self.target_process = None
        self.hook = None
        self.mutex = None
        return result == 0


def build_command_line_args(window_mode: str, extra_args: str) -> str:
    """Builds Genshin Impact Unity command line arguments."""
    args = []
    if window_mode == "BORDERLESS":
        args.append("-popupwindow")
    elif window_mode == "EXCLUSIVE":
        args.append("-window-mode exclusive")
    
    if extra_args.strip():
        args.append(extra_args.strip())

    return " ".join(args)


def launch_game(
    with_mods: bool = True,
    unlock_fps: bool = False,
    custom_cfg: Optional[Dict[str, Any]] = None,
    status_callback: Optional[Any] = None
) -> Tuple[bool, str]:
    """
    Main Launch Routine:
    - with_mods: Injects GIMI 3DMigoto (d3d11.dll) via 3dmloader.dll
    - unlock_fps: Runs with GI-FPS-Unlocker
    - custom_cfg: Override config
    - status_callback: Optional callable for real-time status updates
    """
    def log_status(msg: str):
        log.info(msg)
        if status_callback:
            try:
                status_callback(msg)
            except Exception:
                pass

    cfg = load_config()
    if custom_cfg:
        cfg.update(custom_cfg)

    game_path_str = cfg.get("game_path", "")
    if not game_path_str or not os.path.exists(game_path_str):
        return False, "Không tìm thấy file GenshinImpact.exe! Vui lòng chọn đường dẫn game trong cài đặt."

    game_exe_path = Path(game_path_str).resolve()
    game_folder = game_exe_path.parent
    game_exe_name = game_exe_path.name

    # Check if game is already running
    if get_game_process():
        return False, f"Trò chơi {game_exe_name} hiện đang chạy rồi!"

    # Ensure background HoYoPlay tray service is closed so it doesn't pop up upon game exit
    hoyoplay_killed = kill_background_hoyoplay()
    if hoyoplay_killed > 0:
        log.info(f"Closed {hoyoplay_killed} background HoYoPlay processes before launch.")

    window_mode = cfg.get("window_mode", "BORDERLESS")
    fps_target = int(cfg.get("fps_target", 120))
    launch_args_str = build_command_line_args(window_mode, cfg.get("launch_options", ""))

    # 1. Launch with FPS Unlocker if enabled
    if unlock_fps:
        fps_exe = FPS_PKG_DIR / "unlockfps_nc.exe"
        if fps_exe.exists():
            dll_list = []
            if with_mods:
                gimi_d3d11 = GIMI_DIR / "d3d11.dll"
                if gimi_d3d11.exists():
                    dll_list.append(str(gimi_d3d11))
                update_d3dx_ini(game_exe_name, cfg.get("enforce_rendering", True))

            configure_fps_unlocker(
                game_exe_path=str(game_exe_path),
                fps_target=fps_target,
                window_mode=window_mode,
                priority=3 if cfg.get("process_priority") == "NORMAL" else 1,
                dll_list=dll_list
            )

            try:
                log_status(f"Đang khởi động qua FPS Unlocker ({fps_target} FPS)...")
                subprocess.Popen(
                    [str(fps_exe)],
                    cwd=str(FPS_PKG_DIR),
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )
                
                # Wait for game window
                deadline = time.monotonic() + 45.0
                while time.monotonic() < deadline:
                    proc = get_game_process()
                    if proc and has_visible_window(proc.pid):
                        break
                    time.sleep(0.5)

                kill_background_hoyoplay()
                return True, f"Đã khởi động Genshin Impact thành công cùng Mở Khóa FPS ({fps_target} FPS)!"
            except Exception as e:
                log.error(f"Failed to start FPS unlocker: {e}")
                return False, f"Lỗi khởi động FPS Unlocker: {e}"

    # 2. Launch with GIMI (3DMigoto) Hook
    if with_mods:
        loader_path = XXMI_PKG_DIR / "3dmloader.dll"
        d3d11_path = GIMI_DIR / "d3d11.dll"

        if not loader_path.exists() or not d3d11_path.exists():
            return False, f"Thiếu file GIMI 3DMigoto ({loader_path.name} hoặc {d3d11_path.name})!"

        update_d3dx_ini(game_exe_name, cfg.get("enforce_rendering", True))

        try:
            log_status("Đang thiết lập GIMI 3DMigoto Hook...")
            injector = DllInjector(loader_path, load_hook=True, load_inject=False)
            try:
                injector.hook_library(d3d11_path, game_exe_name)
                log.info(f"Hook installed for {d3d11_path.name} -> {game_exe_name}")
            except Exception as hook_err:
                log.error(f"Failed to install hook: {hook_err}")
                try:
                    injector.unload()
                except Exception:
                    pass
                return False, f"Không thể thiết lập Hook 3DMigoto: {hook_err}"

            # Spawn game process elevated via ShellExecuteW (handles UAC automatically)
            log_status(f"Đang khởi động game {game_exe_name}...")
            spawned = spawn_process_elevated(game_exe_path, launch_args_str, game_folder)
            if not spawned:
                try:
                    injector.unhook_library()
                    injector.unload()
                except Exception:
                    pass
                return False, "Không thể khởi động GenshinImpact.exe (Quyền Administrator bị từ chối)!"

            # Wait for game process and visible window before unhooking CBT hook!
            # Genshin Impact takes 15-30s to initialize anti-cheat and display window
            log_status("Đang chờ game nạp và hiển thị cửa sổ (giữ hook an toàn)...")
            deadline = time.monotonic() + 60.0
            window_found = False

            try:
                while time.monotonic() < deadline:
                    proc = get_game_process()
                    if proc:
                        if has_visible_window(proc.pid):
                            window_found = True
                            log_status(f"Đã phát hiện cửa sổ game (PID {proc.pid})! Đang hoàn tất nạp Mod...")
                            break
                    time.sleep(0.5)

                if window_found:
                    # Give DirectX 11 and Unity swapchain 3.5 seconds to settle
                    time.sleep(3.5)
                    try:
                        injected = injector.wait_for_injection(5)
                        log.info(f"Injection status verification: {injected}")
                    except Exception as e:
                        log.warning(f"wait_for_injection notice: {e}")
                else:
                    log.warning("Cửa sổ game chưa xuất hiện sau 60s, tiến hành gỡ hook.")

            finally:
                # Safely unhook and unload injector now that game is up
                try:
                    injector.unhook_library()
                    injector.unload()
                    log.info("Đã gỡ hook 3DMigoto an toàn.")
                except Exception as e:
                    log.warning(f"Lỗi khi gỡ hook: {e}")

            # Ensure HoYoPlay did not sneak into background
            kill_background_hoyoplay()

            return True, "Đã khởi động Genshin Impact với GIMI Mod thành công! (Nhấn F10 trong game để reload Mod)"

        except Exception as e:
            log.exception(f"Error during GIMI hook injection: {e}")
            spawn_process_elevated(game_exe_path, launch_args_str, game_folder)
            return True, f"Đã khởi động game trực tiếp (Sự cố Hook: {e})"

    # 3. Vanilla Launch (Direct)
    try:
        log_status(f"Đang khởi động Vanilla: {game_exe_name}...")
        spawned = spawn_process_elevated(game_exe_path, launch_args_str, game_folder)
        if not spawned:
            return False, "Không thể khởi động GenshinImpact.exe (Quyền Administrator bị từ chối)!"
        time.sleep(3.0)
        kill_background_hoyoplay()
        return True, "Đã khởi động Genshin Impact trực tiếp (Chế độ gốc không Mod) thành công!"
    except Exception as e:
        log.error(f"Failed to launch game: {e}")
        return False, f"Không thể khởi động game: {e}"


def open_folder(folder_path: Path):
    """Opens directory in Windows File Explorer."""
    folder_path = folder_path.resolve()
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder_path))


def create_desktop_shortcut() -> bool:
    """Creates a Desktop shortcut for Genshin Launcher."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        desktop_dir = shell.SpecialFolders("Desktop")
        shortcut_path = os.path.join(desktop_dir, "Genshin Impact (GIMI Launcher).lnk")

        shortcut = shell.CreateShortcut(shortcut_path)
        
        # Check if built exe exists
        built_exe = BASE_DIR / "dist" / "GenshinImpactLauncher" / "GenshinImpactLauncher.exe"
        single_exe = BASE_DIR / "GenshinImpactLauncher.exe"
        bat_launcher = BASE_DIR / "Run_Genshin_Launcher.bat"

        if single_exe.exists():
            shortcut.TargetPath = str(single_exe)
            shortcut.WorkingDirectory = str(BASE_DIR)
        elif built_exe.exists():
            shortcut.TargetPath = str(built_exe)
            shortcut.WorkingDirectory = str(built_exe.parent)
        elif bat_launcher.exists():
            shortcut.TargetPath = str(bat_launcher)
            shortcut.WorkingDirectory = str(BASE_DIR)
        else:
            shortcut.TargetPath = sys.executable
            shortcut.Arguments = f'"{BASE_DIR / "genshin_launcher.py"}"'
            shortcut.WorkingDirectory = str(BASE_DIR)

        icon_path = BASE_DIR / "Themes" / "Default" / "Shortcuts" / "GIMI.ico"
        if icon_path.exists():
            shortcut.IconLocation = f"{icon_path},0"

        shortcut.Description = "Genshin Impact GIMI Mod Launcher"
        shortcut.save()
        log.info(f"Desktop shortcut created: {shortcut_path}")
        return True
    except Exception as e:
        log.error(f"Failed to create desktop shortcut: {e}")
        return False

