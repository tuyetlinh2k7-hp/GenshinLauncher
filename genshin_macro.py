"""
Genshin Impact Launcher - Macro Automation Engine
Features:
1. Basic Safe Macros (100% An toàn - Giả lập thao tác phím người dùng chuẩn Windows SendInput)
   - Auto Cốt Truyện / Tự động qua đối thoại (Auto Dialogue with Space + Left Click)
   - Auto Nhặt Đồ (Auto Loot - Spam phím F tốc độ cao)
   - Auto Phím Z (Auto Gadget - Kích hoạt bảo bối định kỳ)
2. Macro Pro (Combo phím chuỗi theo thời gian cho đội hình)
   - Ghi lại thao tác trực tiếp (Macro Recording từ bàn phím + chuột chuẩn xác, hỗ trợ giữ phím/nhấn chuột gồng đòn đánh)
   - Lọc bỏ thao tác ngoài game / click chuột trong launcher
   - Phím tắt kết thúc ghi macro an toàn (mặc định F9 hoặc dừng từ Launcher, không bị ngắt đột ngột bởi phím ESC)
   - Nạp thao tác từ người khác (Import / Upload file JSON)
   - Xuất thao tác chia sẻ (Export JSON)
3. Window Foreground Safety: Chỉ bấm khi cửa sổ GenshinImpact.exe / game đang hoạt động trên màn hình
"""

import os
import sys
import time
import json
import logging
import threading
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Optional, Dict, Any, List

log = logging.getLogger("MacroEngine")

# Hardware Scan Codes for DirectInput / Windows SendInput
SCAN_CODES = {
    # Letters
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15, "z": 0x2C,

    # Numbers
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,

    # Controls & Specials
    "space": 0x39, "tab": 0x0F, "shift": 0x2A, "ctrl": 0x1D, "alt": 0x38,
    "enter": 0x1C, "esc": 0x01, "backspace": 0x0E,

    # Function Keys
    "f1": 0x3B, "f2": 0x3C, "f3": 0x3D, "f4": 0x3E, "f5": 0x3F,
    "f6": 0x40, "f7": 0x41, "f8": 0x42, "f9": 0x43, "f10": 0x44,
    "f11": 0x57, "f12": 0x58,

    # Arrows
    "up": 0x48, "left": 0x4B, "right": 0x4D, "down": 0x50,

    # Mouse
    "lclick": 0x00, "rclick": 0x01, "mclick": 0x02,
}

# Alias mapping from pynput key names to scan codes
KEY_ALIASES = {
    "shift_l": "shift", "shift_r": "shift",
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "space": "space", "enter": "enter", "return": "enter",
    "esc": "esc", "escape": "esc",
    "backspace": "backspace", "tab": "tab",
    "up": "up", "down": "down", "left": "left", "right": "right",
}

PUL = ctypes.POINTER(ctypes.c_ulong)

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", PUL)
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput)
    ]

class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I)
    ]

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040


def send_key_scancode(scancode: int, press: bool = True):
    """Gửi tín hiệu Scan Code phần cứng trực tiếp tới Windows."""
    flags = KEYEVENTF_SCANCODE
    if not press:
        flags |= KEYEVENTF_KEYUP
    extra = ctypes.c_ulong(0)
    ii = Input_I()
    ii.ki = KeyBdInput(0, scancode, flags, 0, ctypes.pointer(extra))
    x = Input(ctypes.c_ulong(INPUT_KEYBOARD), ii)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))


def send_key_press_and_release(scancode: int, duration_ms: int = 30):
    """Nhấn giữ phím trong duration_ms rồi thả ra (hỗ trợ đè phím, skill gồng, lướt)."""
    send_key_scancode(scancode, press=True)
    sleep_s = max(0.015, duration_ms / 1000.0)
    time.sleep(sleep_s)
    send_key_scancode(scancode, press=False)


def send_mouse_click(button: str = "lclick", duration_ms: int = 25):
    """Nhấn giữ chuột trong duration_ms rồi thả ra (hỗ trợ trọng kích, gồng cung)."""
    extra = ctypes.c_ulong(0)
    if button == "lclick":
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == "rclick":
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    else:
        down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

    ii_down = Input_I()
    ii_down.mi = MouseInput(0, 0, 0, down_flag, 0, ctypes.pointer(extra))
    x_down = Input(ctypes.c_ulong(INPUT_MOUSE), ii_down)

    ii_up = Input_I()
    ii_up.mi = MouseInput(0, 0, 0, up_flag, 0, ctypes.pointer(extra))
    x_up = Input(ctypes.c_ulong(INPUT_MOUSE), ii_up)

    ctypes.windll.user32.SendInput(1, ctypes.pointer(x_down), ctypes.sizeof(x_down))
    sleep_s = max(0.015, duration_ms / 1000.0)
    time.sleep(sleep_s)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x_up), ctypes.sizeof(x_up))


def trigger_in_game_reload_f10():
    """Triggers F10 scancode to reload all mods in-game."""
    send_key_scancode(SCAN_CODES["f10"], press=True)
    time.sleep(0.03)
    send_key_scancode(SCAN_CODES["f10"], press=False)


def is_genshin_foreground() -> bool:
    """Checks if active foreground window belongs to GenshinImpact.exe or YuanShen.exe."""
    try:
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return False
        proc = psutil.Process(pid)
        return proc.name().lower() in ["genshinimpact.exe", "yuanshen.exe", "starrail.exe", "zenlesszonezero.exe", "client-win64-shipping.exe"]
    except Exception:
        return False


# =========================================================================
# MACRO RECORDER (BỘ GHI LẠI THAO TÁC NÂNG CẤP - THÔNG MINH & CHUẨN XÁC)
# =========================================================================
class MacroRecorder:
    def __init__(self):
        self.is_recording = False
        self.events: List[Dict[str, Any]] = []
        self.last_event_time = 0.0
        self._keyboard_listener = None
        self._mouse_listener = None
        self._stop_callback = None
        self.stop_hotkey = "f9"
        self.only_in_game = True

        # Track currently held keys to avoid OS repeat spam & compute hold duration
        self._active_keys: Dict[str, float] = {}
        self._active_mouse: Dict[str, float] = {}
        self._has_first_input = False

    def _normalize_key(self, key) -> Optional[str]:
        """Chuyển đổi key từ pynput sang tên key chuẩn trong SCAN_CODES."""
        key_str = ""
        if isinstance(key, str):
            key_str = key.lower()
        elif hasattr(key, 'char') and key.char:
            key_str = key.char.lower()
        elif hasattr(key, 'name') and key.name:
            key_str = key.name.lower()

        key_str = KEY_ALIASES.get(key_str, key_str)
        if key_str in SCAN_CODES:
            return key_str
        return None

    def start_recording(self, on_stop=None, stop_hotkey: str = "f9", only_in_game: bool = True):
        """
        Bắt đầu ghi lại thao tác bàn phím và chuột.
        - stop_hotkey: Phím dừng ghi (mặc định F9 để không xung đột ESC mở menu Paimon trong game).
        - only_in_game: Chỉ ghi khi cửa sổ game đang ở tiêu điểm (bỏ qua click trong launcher hoặc khi Alt-Tab).
        """
        try:
            from pynput import keyboard, mouse
        except ImportError:
            log.error("pynput not available for recording")
            return False

        self.events = []
        self.last_event_time = time.time()
        self.is_recording = True
        self._stop_callback = on_stop
        self.stop_hotkey = stop_hotkey.lower()
        self.only_in_game = only_in_game
        self._active_keys.clear()
        self._active_mouse.clear()
        self._has_first_input = False

        def on_press(key):
            if not self.is_recording:
                return False

            key_norm = self._normalize_key(key)

            # Check stop hotkey (F9 by default, not ESC)
            if key_norm and key_norm == self.stop_hotkey:
                threading.Thread(target=self.stop_recording, daemon=True).start()
                return False

            # Ignore window-switching keys
            if key_norm in ["alt", "tab", "cmd", "win"]:
                return

            # If only_in_game is enabled, ignore events while game is not active
            if self.only_in_game and not is_genshin_foreground():
                return

            # Ignore OS auto-repeat while key is held down
            if key_norm and key_norm in self._active_keys:
                return

            now = time.time()
            if key_norm:
                self._active_keys[key_norm] = now

        def on_release(key):
            if not self.is_recording:
                return False

            key_norm = self._normalize_key(key)
            if not key_norm or key_norm not in self._active_keys:
                return

            press_time = self._active_keys.pop(key_norm, None)
            if press_time is None:
                return

            now = time.time()
            duration_ms = max(25, int((now - press_time) * 1000))

            if not self._has_first_input:
                delay_ms = 50  # Start first move promptly
                self._has_first_input = True
            else:
                delay_ms = max(25, min(4000, int((press_time - self.last_event_time) * 1000)))

            self.last_event_time = now

            self.events.append({
                "type": "key",
                "key": key_norm,
                "delay_ms": delay_ms,
                "duration_ms": duration_ms
            })

        def on_click(x, y, button, pressed):
            if not self.is_recording:
                return False

            # If only_in_game is enabled, ignore clicks outside game
            if self.only_in_game and not is_genshin_foreground():
                return

            b_name = "lclick" if button == mouse.Button.left else ("rclick" if button == mouse.Button.right else "mclick")
            now = time.time()

            if pressed:
                self._active_mouse[b_name] = now
            else:
                press_time = self._active_mouse.pop(b_name, None)
                if press_time is None:
                    press_time = now - 0.025

                duration_ms = max(25, int((now - press_time) * 1000))

                if not self._has_first_input:
                    delay_ms = 50
                    self._has_first_input = True
                else:
                    delay_ms = max(25, min(4000, int((press_time - self.last_event_time) * 1000)))

                self.last_event_time = now

                self.events.append({
                    "type": "mouse",
                    "button": b_name,
                    "delay_ms": delay_ms,
                    "duration_ms": duration_ms
                })

        self._keyboard_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse_listener = mouse.Listener(on_click=on_click)
        self._keyboard_listener.start()
        self._mouse_listener.start()
        log.info(f"Macro recording started (Stop key: {self.stop_hotkey.upper()}).")
        return True

    def stop_recording(self) -> List[Dict[str, Any]]:
        if not self.is_recording:
            return self.events
        self.is_recording = False

        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        log.info(f"Macro recording finished with {len(self.events)} events.")
        if self._stop_callback:
            try:
                self._stop_callback(self.events)
            except Exception as e:
                log.warning(f"Error in recording stop callback: {e}")
        return self.events


DEFAULT_MACRO_CONFIG: Dict[str, Any] = {
    "auto_story": {
        "enabled": False,
        "hotkey": "f8",
        "interval_ms": 100,
    },
    "auto_loot": {
        "enabled": False,
        "hotkey": "f7",
        "interval_ms": 40,
    },
    "auto_gadget": {
        "enabled": False,
        "hotkey": "f9",
        "interval_ms": 2500,
    },
    "combos": [
        {
            "id": "combo_default_1",
            "name": "Combo Nộ & Kỹ năng Đội hình",
            "hotkey": "f11",
            "enabled": False,
            "steps": [
                {"type": "key", "key": "1", "delay_ms": 150, "duration_ms": 30},
                {"type": "key", "key": "e", "delay_ms": 300, "duration_ms": 40},
                {"type": "key", "key": "q", "delay_ms": 350, "duration_ms": 40},
                {"type": "key", "key": "2", "delay_ms": 150, "duration_ms": 30},
                {"type": "key", "key": "e", "delay_ms": 300, "duration_ms": 40}
            ]
        }
    ]
}


class MacroEngine:
    def __init__(self, config_path: Path):
        self.config_path = Path(config_path)
        self.cfg = self.load_config()
        self.running = True
        self.worker_thread = None
        self.recorder = MacroRecorder()
        self._current_combo_thread = None

        self.start_worker()
        self.setup_hotkeys()

    def load_config(self) -> Dict[str, Any]:
        cfg = DEFAULT_MACRO_CONFIG.copy()
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cfg.update(data)
            except Exception as e:
                log.error(f"Failed to load macro config: {e}")
        self.save_config(cfg)
        return cfg

    def save_config(self, cfg: Optional[Dict[str, Any]] = None):
        if cfg:
            self.cfg = cfg
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            log.error(f"Failed to save macro config: {e}")

    def toggle_feature(self, feature_name: str) -> bool:
        if feature_name in self.cfg:
            new_val = not self.cfg[feature_name].get("enabled", False)
            self.cfg[feature_name]["enabled"] = new_val
            self.save_config()
            log.info(f"Macro {feature_name} toggled: {new_val}")
            return new_val
        return False

    def is_feature_enabled(self, feature_name: str) -> bool:
        return self.cfg.get(feature_name, {}).get("enabled", False)

    def add_combo(self, name: str, hotkey: str, steps: List[Dict[str, Any]], combo_id: Optional[str] = None) -> Dict[str, Any]:
        """Thêm combo macro mới (Chấp nhận cả combo_id tùy chọn để tương thích tối đa)."""
        cid = combo_id or f"combo_{int(time.time())}"
        combo_item = {
            "id": cid,
            "name": name or "Macro Combo Tự Đặt",
            "hotkey": (hotkey or "f11").strip().lower(),
            "enabled": True,
            "steps": steps
        }
        if "combos" not in self.cfg:
            self.cfg["combos"] = []
        self.cfg["combos"].append(combo_item)
        self.save_config()
        self.setup_hotkeys()
        return combo_item

    def delete_combo(self, combo_id: str) -> bool:
        if "combos" in self.cfg:
            before_len = len(self.cfg["combos"])
            self.cfg["combos"] = [c for c in self.cfg["combos"] if c.get("id") != combo_id]
            if len(self.cfg["combos"]) < before_len:
                self.save_config()
                self.setup_hotkeys()
                return True
        return False

    def export_combo(self, combo_id: str, out_path: Path) -> bool:
        combos = self.cfg.get("combos", [])
        combo = next((c for c in combos if c.get("id") == combo_id), None)
        if not combo:
            return False
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(combo, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            log.error(f"Export combo error: {e}")
            return False

    def import_combo(self, in_path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(in_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "steps" not in data:
                return None
            data["id"] = f"combo_{int(time.time())}"
            if "combos" not in self.cfg:
                self.cfg["combos"] = []
            self.cfg["combos"].append(data)
            self.save_config()
            self.setup_hotkeys()
            return data
        except Exception as e:
            log.error(f"Import combo error: {e}")
            return None

    def start_worker(self):
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        last_gadget_time = 0.0

        while self.running:
            try:
                # Only execute if Genshin Impact window is actively in foreground!
                if is_genshin_foreground():
                    # 1. Auto Story (Spam Space & Click)
                    if self.cfg.get("auto_story", {}).get("enabled", False):
                        send_key_scancode(SCAN_CODES["space"], press=True)
                        time.sleep(0.015)
                        send_key_scancode(SCAN_CODES["space"], press=False)
                        send_mouse_click("lclick", duration_ms=20)
                        time.sleep(self.cfg["auto_story"].get("interval_ms", 100) / 1000.0)

                    # 2. Auto Loot (Spam F)
                    if self.cfg.get("auto_loot", {}).get("enabled", False):
                        send_key_scancode(SCAN_CODES["f"], press=True)
                        time.sleep(0.015)
                        send_key_scancode(SCAN_CODES["f"], press=False)
                        time.sleep(self.cfg["auto_loot"].get("interval_ms", 40) / 1000.0)

                    # 3. Auto Gadget (Press Z periodically)
                    if self.cfg.get("auto_gadget", {}).get("enabled", False):
                        now = time.time()
                        interval = self.cfg["auto_gadget"].get("interval_ms", 2500) / 1000.0
                        if now - last_gadget_time >= interval:
                            send_key_scancode(SCAN_CODES["z"], press=True)
                            time.sleep(0.02)
                            send_key_scancode(SCAN_CODES["z"], press=False)
                            last_gadget_time = now

                time.sleep(0.02)
            except Exception:
                time.sleep(0.5)

    def setup_hotkeys(self, overlay_callback=None, network_cut_callback=None, hud_callback=None):
        """Registers global hotkeys to toggle macros directly while in-game using pynput."""
        try:
            from pynput import keyboard as pynput_keyboard

            if hasattr(self, "_pynput_listener") and self._pynput_listener:
                try:
                    self._pynput_listener.stop()
                except Exception:
                    pass

            hotkey_mapping = {}

            def make_toggle_handler(feature):
                return lambda: self.toggle_feature(feature)

            story_hk = self.cfg.get("auto_story", {}).get("hotkey", "f8").lower()
            if story_hk:
                hotkey_mapping[f"<{story_hk}>"] = make_toggle_handler("auto_story")

            loot_hk = self.cfg.get("auto_loot", {}).get("hotkey", "f7").lower()
            if loot_hk:
                hotkey_mapping[f"<{loot_hk}>"] = make_toggle_handler("auto_loot")

            gadget_hk = self.cfg.get("auto_gadget", {}).get("hotkey", "f9").lower()
            if gadget_hk:
                hotkey_mapping[f"<{gadget_hk}>"] = make_toggle_handler("auto_gadget")

            # Combo hotkeys
            for c in self.cfg.get("combos", []):
                chk = c.get("hotkey", "").lower()
                cid = c.get("id")
                if chk and cid and c.get("enabled", True):
                    def make_combo_handler(combo_id=cid):
                        return lambda: self.execute_combo(combo_id)
                    hotkey_mapping[f"<{chk}>"] = make_combo_handler()

            if overlay_callback:
                hotkey_mapping["<f12>"] = overlay_callback

            if network_cut_callback:
                # Ctrl+F11 to toggle network cut
                hotkey_mapping["<ctrl>+<f11>"] = network_cut_callback

            if hud_callback:
                # F11 to toggle mini HUD
                hotkey_mapping["<f11>"] = hud_callback

            if hotkey_mapping:
                self._pynput_listener = pynput_keyboard.GlobalHotKeys(hotkey_mapping)
                self._pynput_listener.start()
                log.info(f"Registered global hotkeys: {list(hotkey_mapping.keys())}")
        except Exception as e:
            log.warning(f"Could not hook global hotkeys: {e}")

    def execute_combo(self, combo_id: str):
        """Executes a custom combo sequence."""
        if not is_genshin_foreground():
            return

        combos = self.cfg.get("combos", [])
        combo = next((c for c in combos if c.get("id") == combo_id), None)
        if not combo:
            return

        def run_combo():
            for step in combo.get("steps", []):
                if not is_genshin_foreground():
                    break
                delay_ms = step.get("delay_ms", 150)
                if delay_ms > 0:
                    time.sleep(min(delay_ms, 5000) / 1000.0)

                step_type = step.get("type", "key")
                duration_ms = step.get("duration_ms", 30)

                if step_type == "mouse" or "button" in step:
                    send_mouse_click(step.get("button", "lclick"), duration_ms=duration_ms)
                else:
                    key_name = step.get("key", "").lower()
                    key_name = KEY_ALIASES.get(key_name, key_name)
                    sc = SCAN_CODES.get(key_name)
                    if sc is not None:
                        send_key_press_and_release(sc, duration_ms=duration_ms)

        self._current_combo_thread = threading.Thread(target=run_combo, daemon=True)
        self._current_combo_thread.start()

    def destroy(self):
        self.running = False
        if hasattr(self, "_pynput_listener") and self._pynput_listener:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
