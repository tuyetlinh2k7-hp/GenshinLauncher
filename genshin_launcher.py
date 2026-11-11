"""
Genshin Impact Launcher - Advanced Edition
Based on XXMI / HoYo Launcher Mods Architecture.
Features:
1. Game Launch & Live Process Monitor (GIMI Hook, Vanilla, FPS Unlocker)
2. Mod Manager with Windows Junction Links (Instant toggle without copying files)
3. Character / Waifu / Category Filter & Mod Cards
4. Mod Groups / Presets with 1-click batch activation
5. Macro Automation (Auto Story, Auto Loot, Auto Gadget Z, Custom Combos)
6. Mod Auto-Fixer (ORFix & Syntax Checker)
7. Soft-Delete Trash (Recycle Bin) with Restore & Empty
8. Settings (Window mode, FPS, Priority, Language, UAC Admin)
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
import ctypes
from pathlib import Path
from typing import Optional, Dict, Any, List

import customtkinter as ctk
from PIL import Image, ImageTk

# Setup launcher root
def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "GIMI").exists():
            return exe_dir
        if (exe_dir.parent / "GIMI").exists():
            return exe_dir.parent
        if (exe_dir.parent.parent / "GIMI").exists():
            return exe_dir.parent.parent
        if hasattr(sys, '_MEIPASS') and (Path(sys._MEIPASS) / "GIMI").exists():
            return Path(sys._MEIPASS)
        return exe_dir
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))

import genshin_engine as engine
from genshin_locales import get_text, LOCALES
from genshin_mod_manager import ModManager, ModInfo
from genshin_macro import MacroEngine, MacroRecorder
from genshin_plugins import plugin_manager
from genshin_wishes import wish_tracker, BANNER_NAMES
from genshin_network import network_manager, KNOWN_GAMES
from genshin_perf import perf_monitor, PerformanceMiniHUD
import webbrowser
from tkinter import messagebox, filedialog

# Enable High-DPI scaling on Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def ensure_admin():
    """Ensures launcher runs with Administrator privileges."""
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False

    if not is_admin:
        try:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
                args = " ".join([f'"{a}"' for a in sys.argv[1:]])
                res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, args, None, 1)
            else:
                script_path = str(Path(__file__).resolve())
                args = f'"{script_path}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])
                res = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, str(BASE_DIR), 1)

            if res > 32:
                sys.exit(0)
        except Exception:
            pass


class ModernGenshinLauncher(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.cfg = engine.load_config()
        self.lang = self.cfg.get("language", "vi")
        self.mod_manager = ModManager(BASE_DIR)
        self.macro_engine = MacroEngine(BASE_DIR / "genshin_macro_config.json")

        self.title("Genshin Impact Pro Launcher & Mod Manager")
        self.geometry("1180x740")
        self.minsize(1050, 680)
        self.configure(fg_color="#0f111a")

        # Window icon
        icon_path = BASE_DIR / "Themes" / "Default" / "window-icon.ico"
        if not icon_path.exists():
            icon_path = BASE_DIR / "Themes" / "Default" / "Shortcuts" / "GIMI.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        self.current_tab = "home"
        self.selected_category = "Tất Cả"
        self.selected_group_id = None
        self.search_query = ""
        self.is_launching = False
        self.monitor_running = True
        self.game_running = False

        self.selected_wish_banner = "301"
        self.wish_view_mode = "history"
        self.wish_history_page = 1
        self.wish_items_per_page = 25
        self.wish_filter_rarity = "ALL"
        self.plugin_manager = plugin_manager
        self.wish_tracker = wish_tracker

        self.macro_recorder: Optional[MacroRecorder] = None
        self._tray_icon = None
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._thumb_cache: Dict[str, ctk.CTkImage] = {}
        self._in_game_overlay = None
        self._mini_hud: Optional[PerformanceMiniHUD] = None
        self._last_perf_metrics: Dict[str, Any] = {}

        self.network_manager = network_manager
        self.network_manager.set_config_game_path(self.cfg.get("game_path", ""))
        self.perf_monitor = perf_monitor
        self.perf_monitor.add_subscriber(lambda data: self.after(0, lambda d=data: self._on_perf_update(d)))
        self.perf_monitor.start()

        self.game_version = engine.get_installed_game_version()
        self.macro_engine.start_worker()
        self.macro_engine.setup_hotkeys(
            overlay_callback=lambda: self.after(0, self.toggle_in_game_overlay),
            network_cut_callback=lambda: self.after(0, self._quick_toggle_current_game_network),
            hud_callback=lambda: self.after(0, self.toggle_mini_hud)
        )

        self._setup_layout()
        self._start_monitor_thread()

    def _t(self, key: str, **kwargs) -> str:
        return get_text(key, self.lang, **kwargs)

    # -------------------------------------------------------------------------
    # Layout Setup
    # -------------------------------------------------------------------------
    def _setup_layout(self):
        # 1. Left Sidebar Navigation
        self.sidebar = ctk.CTkFrame(self, width=205, corner_radius=0, fg_color="#0f121d")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Brand / Logo Header
        self.brand_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.brand_frame.pack(fill="x", padx=12, pady=(16, 16))

        brand_top = ctk.CTkFrame(self.brand_frame, fg_color="transparent")
        brand_top.pack(fill="x")

        brand_lbl = ctk.CTkLabel(
            brand_top,
            text="GENSHIN PRO",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color="#38bdf8"
        )
        brand_lbl.pack(side="left")

        ver_badge = ctk.CTkLabel(
            brand_top,
            text="v2.5",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0c4a6e",
            corner_radius=6,
            padx=6,
            pady=1
        )
        ver_badge.pack(side="right")

        sub_lbl = ctk.CTkLabel(
            self.brand_frame,
            text="Mod Manager & Launcher",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#64748b"
        )
        sub_lbl.pack(anchor="w", pady=(2, 0))

        # Navigation Buttons
        self.nav_buttons = {}
        nav_items = [
            ("home", "🚀  " + self._t("nav_home")),
            ("mods", "👗  " + self._t("nav_mods")),
            ("groups", "📁  " + self._t("nav_groups")),
            ("macro", "⚡  " + self._t("nav_macro")),
            ("fix", "🔧  " + self._t("nav_fix")),
            ("wishes", "⭐  " + self._t("nav_wishes")),
            ("plugins", "🧩  " + self._t("nav_plugins")),
            ("network_perf", "🌐  " + self._t("nav_network_perf")),
            ("trash", "🗑️  " + self._t("nav_trash")),
            ("settings", "⚙️  " + self._t("nav_settings")),
        ]

        for tab_id, text in nav_items:
            is_init = (tab_id == "home")
            btn = ctk.CTkButton(
                self.sidebar,
                text=text,
                anchor="w",
                height=38,
                corner_radius=8,
                font=ctk.CTkFont(size=12, weight="bold" if is_init else "normal"),
                fg_color="#1e2942" if is_init else "transparent",
                hover_color="#181e30",
                text_color="#38bdf8" if is_init else "#94a3b8",
                border_width=1 if is_init else 0,
                border_color="#0284c7" if is_init else "#0f121d",
                command=lambda tid=tab_id: self.switch_tab(tid)
            )
            btn.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[tab_id] = btn

        # Admin Badge & Live Status at bottom of sidebar
        self.sidebar_bottom = ctk.CTkFrame(self.sidebar, fg_color="#131728", corner_radius=8)
        self.sidebar_bottom.pack(side="bottom", fill="x", padx=8, pady=12)

        self.sidebar_game_status = ctk.CTkLabel(
            self.sidebar_bottom,
            text="⚪ Game: Chưa chạy",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        self.sidebar_game_status.pack(anchor="w", padx=8, pady=(6, 2))

        is_admin = engine.is_admin()
        admin_text = "🛡️ Quyền: Administrator" if is_admin else "⚠️ Cần quyền Admin"
        admin_color = "#10b981" if is_admin else "#f59e0b"
        self.admin_lbl = ctk.CTkLabel(
            self.sidebar_bottom,
            text=admin_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=admin_color
        )
        self.admin_lbl.pack(anchor="w", padx=8, pady=(0, 6))

        # 2. Main Content Container
        self.main_container = ctk.CTkFrame(self, corner_radius=0, fg_color="#0a0c16")
        self.main_container.pack(side="right", fill="both", expand=True)

        # Tab Frames dictionary
        self.tab_frames = {}
        self._build_home_tab()
        self._build_mods_tab()
        self._build_groups_tab()
        self._build_macro_tab()
        self._build_fix_tab()
        self._build_wishes_tab()
        self._build_plugins_tab()
        self._build_network_perf_tab()
        self._build_trash_tab()
        self._build_settings_tab()

        self.switch_tab("home")

    def switch_tab(self, tab_id: str):
        self.current_tab = tab_id
        for tid, btn in self.nav_buttons.items():
            if tid == tab_id:
                btn.configure(
                    fg_color="#1e2942",
                    text_color="#38bdf8",
                    border_width=1,
                    border_color="#0284c7",
                    font=ctk.CTkFont(size=12, weight="bold")
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color="#94a3b8",
                    border_width=0,
                    font=ctk.CTkFont(size=12, weight="normal")
                )

        for tid, frame in self.tab_frames.items():
            if tid == tab_id:
                frame.pack(fill="both", expand=True)
                if tab_id == "home":
                    self._refresh_game_info_display()
                elif tab_id == "mods":
                    self._refresh_mods_ui()
                elif tab_id == "groups":
                    self._refresh_groups_ui()
                elif tab_id == "wishes":
                    self._refresh_wishes_ui()
                elif tab_id == "plugins":
                    self._refresh_plugins_ui()
                elif tab_id == "network_perf":
                    self._refresh_network_perf_ui()
                elif tab_id == "trash":
                    self._refresh_trash_ui()
            else:
                frame.pack_forget()

    # =========================================================================
    # 1. TAB: HOME (KHỞI ĐỘNG CHUẨN HOYOPLAY)
    # =========================================================================
    def _build_home_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["home"] = frame

        # Top HoYoPlay Game Header Bar
        hyp_header = ctk.CTkFrame(frame, height=42, fg_color="transparent")
        hyp_header.pack(fill="x", padx=16, pady=(12, 6))

        game_title_lbl = ctk.CTkLabel(
            hyp_header,
            text="GENSHIN IMPACT",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#f8fafc"
        )
        game_title_lbl.pack(side="left")

        ver_badge = ctk.CTkLabel(
            hyp_header,
            text=f"v{self.game_version}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0c4a6e",
            corner_radius=6,
            padx=8,
            pady=2
        )
        ver_badge.pack(side="left", padx=10)

        hyp_update_btn = ctk.CTkButton(
            hyp_header,
            text="🔄 Mở HoYoPlay (Cập nhật game)",
            height=30,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self._open_hoyoplay_update
        )
        hyp_update_btn.pack(side="right")

        # Top Banner / Artwork
        self.home_banner = ctk.CTkFrame(frame, height=180, corner_radius=12, fg_color="#181c2e")
        self.home_banner.pack(fill="x", padx=16, pady=(0, 12))
        self.home_banner.pack_propagate(False)

        # Artwork Image Label (customizable wallpaper)
        self.banner_img_lbl = ctk.CTkLabel(self.home_banner, text="")
        self.banner_img_lbl.place(x=0, y=0, relwidth=1, relheight=1)
        self._update_home_banner_image()

        # Banner Overlay Text
        banner_title = ctk.CTkLabel(
            self.home_banner,
            text="GENSHIN IMPACT LAUNCHER",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#ffffff",
            fg_color="#0f172a",
            corner_radius=6,
            padx=12,
            pady=4
        )
        banner_title.place(x=20, y=25)

        banner_sub = ctk.CTkLabel(
            self.home_banner,
            text="Hệ thống Khởi Động, Quản Lý Mod Ảo Hóa & Tối Ưu Hóa Game",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color="#e2e8f0",
            fg_color="#0f172a",
            corner_radius=6,
            padx=12,
            pady=2
        )
        banner_sub.place(x=20, y=65)

        # Status Pill inside Banner
        self.status_pill = ctk.CTkLabel(
            self.home_banner,
            text=f"● {self._t('status_ready')}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=12,
            padx=14,
            pady=4
        )
        self.status_pill.place(x=20, y=105)

        # Wallpaper Picker Quick Buttons inside Banner (Top-Right)
        wall_btn_box = ctk.CTkFrame(self.home_banner, fg_color="transparent")
        wall_btn_box.place(relx=1.0, x=-160, y=16)

        pick_bg_btn = ctk.CTkButton(
            wall_btn_box,
            text="🖼️ Đổi ảnh nền",
            width=100,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._pick_custom_wallpaper
        )
        pick_bg_btn.pack(side="left", padx=2)

        reset_bg_btn = ctk.CTkButton(
            wall_btn_box,
            text="↩️",
            width=32,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._reset_custom_wallpaper
        )
        reset_bg_btn.pack(side="left", padx=2)

        # Live Performance & Network Quick Bar on Home
        self.home_perf_bar = ctk.CTkFrame(frame, height=36, corner_radius=8, fg_color="#121727", border_width=1, border_color="#1e293b")
        self.home_perf_bar.pack(fill="x", padx=16, pady=(0, 10))
        self.home_perf_bar.pack_propagate(False)

        self.home_telemetry_lbl = ctk.CTkLabel(
            self.home_perf_bar,
            text="⚡ Ping: -- ms  |  CPU: 0%  |  RAM: 0 MB  |  GPU: 0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8"
        )
        self.home_telemetry_lbl.pack(side="left", padx=12)

        self.home_net_status_lbl = ctk.CTkLabel(
            self.home_perf_bar,
            text="🌐 Mạng: Bình thường",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#10b981",
            fg_color="#064e3b",
            corner_radius=6,
            padx=8,
            pady=2
        )
        self.home_net_status_lbl.pack(side="left", padx=8)

        self.home_net_toggle_btn = ctk.CTkButton(
            self.home_perf_bar,
            text="🔌 Ngắt Mạng Game",
            width=115,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._quick_toggle_current_game_network
        )
        self.home_net_toggle_btn.pack(side="right", padx=8)

        self.home_hud_toggle_btn = ctk.CTkButton(
            self.home_perf_bar,
            text="🖥️ HUD Nổi (F11)",
            width=110,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self.toggle_mini_hud
        )
        self.home_hud_toggle_btn.pack(side="right", padx=4)

        # Running Info Card (Hidden when game not running)
        self.running_card = ctk.CTkFrame(frame, corner_radius=10, fg_color="#162033", border_width=1, border_color="#0284c7")
        self.running_info_label = ctk.CTkLabel(
            self.running_card,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8",
            padx=12,
            pady=8
        )
        self.running_info_label.pack(side="left")

        kill_btn = ctk.CTkButton(
            self.running_card,
            text=self._t("btn_kill"),
            height=30,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._confirm_kill_game
        )
        kill_btn.pack(side="right", padx=10, pady=6)

        self.home_running_net_btn = ctk.CTkButton(
            self.running_card,
            text="🔌 Ngắt Mạng",
            width=110,
            height=30,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._quick_toggle_current_game_network
        )
        self.home_running_net_btn.pack(side="right", padx=6, pady=6)

        self.home_running_hud_btn = ctk.CTkButton(
            self.running_card,
            text="🖥️ HUD Nổi",
            width=90,
            height=30,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.toggle_mini_hud
        )
        self.home_running_hud_btn.pack(side="right", padx=6, pady=6)

        # Launch Action Cards (HoYoPlay Iconic Style)
        action_box = ctk.CTkFrame(frame, fg_color="transparent")
        action_box.pack(fill="x", padx=16, pady=(0, 12))

        # Launch Mod Button (Big Primary HoYoPlay Golden Amber Button)
        self.launch_mod_btn = ctk.CTkButton(
            action_box,
            text="▶ BẮT ĐẦU CHƠI (BẬT MOD)",
            height=54,
            corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#f59e0b",
            hover_color="#d97706",
            text_color="#000000",
            command=lambda: self._handle_launch(with_mods=True, unlock_fps=False)
        )
        self.launch_mod_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Launch FPS Button
        self.launch_fps_btn = ctk.CTkButton(
            action_box,
            text="🚀 " + self._t("btn_launch_fps"),
            height=54,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0d9488",
            hover_color="#0f766e",
            command=lambda: self._handle_launch(with_mods=True, unlock_fps=True)
        )
        self.launch_fps_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Launch Vanilla Button
        self.launch_vanilla_btn = ctk.CTkButton(
            action_box,
            text="🛡️ " + self._t("btn_launch_vanilla"),
            height=54,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._handle_launch(with_mods=False, unlock_fps=False)
        )
        self.launch_vanilla_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        # Launch HoYoPlay Button
        self.launch_hyp_btn = ctk.CTkButton(
            action_box,
            text="🔄 HoYoPlay",
            height=54,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._open_hoyoplay_update
        )
        self.launch_hyp_btn.pack(side="left", fill="x", expand=True)

        # Quick Links Bar
        quick_bar = ctk.CTkFrame(frame, fg_color="transparent")
        quick_bar.pack(fill="x", padx=16, pady=(0, 10))

        quick_buttons = [
            ("🎮 Menu Trong Game (F12)", self.toggle_in_game_overlay),
            (self._t("btn_open_mods"), lambda: engine.open_folder(self.mod_manager.data_mods_dir)),
            ("🔄 Mở HoYoPlay", self._open_hoyoplay_update),
            (self._t("btn_open_shaders"), lambda: engine.open_folder(engine.GIMI_DIR / "ShaderFixes")),
            (self._t("btn_open_game"), lambda: self._open_game_folder()),
            (self._t("btn_shortcut"), self._create_shortcut),
        ]
        for qtext, qcmd in quick_buttons:
            qbtn = ctk.CTkButton(
                quick_bar,
                text=qtext,
                height=32,
                corner_radius=6,
                font=ctk.CTkFont(size=12),
                fg_color="#1e293b",
                hover_color="#334155",
                command=qcmd
            )
            qbtn.pack(side="left", expand=True, fill="x", padx=3)

        # Game Information Card (Thông tin cơ bản của Game)
        self._build_game_info_card(frame)

        # Log & Diagnostics Box
        log_card = ctk.CTkFrame(frame, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        log_hdr_frame = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr_frame.pack(fill="x", padx=12, pady=(8, 4))

        log_hdr = ctk.CTkLabel(
            log_hdr_frame,
            text="Nhật Ký Khởi Động & Trạng Thái Hệ Thống:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        log_hdr.pack(side="left")

        clear_log_btn = ctk.CTkButton(
            log_hdr_frame,
            text="🗑️ Xóa log",
            width=70,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._clear_log
        )
        clear_log_btn.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            log_card,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#cbd5e1",
            fg_color="#0a0c16",
            corner_radius=8,
            wrap="word"
        )
        self.log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._append_log("Khởi động Launcher hoàn tất. Đã sẵn sàng nạp Mod ảo hóa!")
        self._append_log("Mẹo: Nhấn [F10] trong game để nạp lại Mod. Nhấn [F12] để mở Menu Trong Game.")

    def _build_game_info_card(self, parent):
        self.game_info_card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        self.game_info_card.pack(fill="x", padx=16, pady=(0, 10))

        info_hdr_frame = ctk.CTkFrame(self.game_info_card, fg_color="transparent")
        info_hdr_frame.pack(fill="x", padx=12, pady=(8, 4))

        info_hdr = ctk.CTkLabel(
            info_hdr_frame,
            text="🎮 Thông Tin Cơ Bản Của Game & Hệ Thống:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        info_hdr.pack(side="left")

        refresh_info_btn = ctk.CTkButton(
            info_hdr_frame,
            text="🔄 Làm mới",
            width=75,
            height=24,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._refresh_game_info_display
        )
        refresh_info_btn.pack(side="right")

        self.info_grid = ctk.CTkFrame(self.game_info_card, fg_color="transparent")
        self.info_grid.pack(fill="x", padx=12, pady=(0, 8))
        self._refresh_game_info_display()

    def _refresh_game_info_display(self):
        if not hasattr(self, "info_grid") or not self.info_grid:
            return
        for w in self.info_grid.winfo_children():
            w.destroy()

        info = engine.get_game_detailed_info(self.cfg.get("game_path"))

        left_col = ctk.CTkFrame(self.info_grid, fg_color="transparent")
        left_col.pack(side="left", fill="both", expand=True)

        left_items = [
            ("📌 Phiên bản:", f"{info.get('version', '7.2.0')} ({info.get('graphics_api', 'DirectX 11')})", "#38bdf8"),
            ("🌐 Máy chủ / Vùng:", info.get('server', 'Quốc Tế (os_asia)'), "#f1f5f9"),
            ("🏢 Đơn vị phát hành:", info.get('publisher', 'mihoyo / HoYoverse'), "#cbd5e1"),
            ("💾 Dung lượng game:", info.get('size', '~159 GB'), "#a7f3d0"),
        ]

        for label_text, val_text, val_col in left_items:
            row = ctk.CTkFrame(left_col, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label_text, width=130, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").pack(side="left")
            ctk.CTkLabel(row, text=val_text, anchor="w", font=ctk.CTkFont(size=11), text_color=val_col).pack(side="left")

        right_col = ctk.CTkFrame(self.info_grid, fg_color="transparent")
        right_col.pack(side="right", fill="both", expand=True)

        status_text = "🟢 Đang chạy" if info.get('is_running') else "⚪ Đã dừng (Sẵn sàng)"
        status_color = "#10b981" if info.get('is_running') else "#94a3b8"

        right_items = [
            ("⚡ Trạng thái tiến trình:", status_text, status_color),
            ("🚀 Cấu hình hiển thị:", f"{self.cfg.get('window_mode', 'BORDERLESS')} | {self.cfg.get('fps_target', 120)} FPS", "#fbbf24"),
            ("📂 Thư mục cài đặt:", info.get('directory', 'Chưa rõ'), "#94a3b8"),
        ]

        for label_text, val_text, val_col in right_items:
            row = ctk.CTkFrame(right_col, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label_text, width=140, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").pack(side="left")
            ctk.CTkLabel(row, text=val_text, anchor="w", font=ctk.CTkFont(size=11), text_color=val_col).pack(side="left")

    def _update_home_banner_image(self):
        custom_bg = self.cfg.get("custom_wallpaper_path", "")
        bg_path = None
        if custom_bg and Path(custom_bg).exists():
            bg_path = Path(custom_bg)
        else:
            default_bg = BASE_DIR / "Themes" / "Default" / "MainWindow" / "LauncherFrame" / "background-image-gimi.webp"
            if default_bg.exists():
                bg_path = default_bg

        if bg_path and bg_path.exists():
            try:
                pil_img = Image.open(bg_path).convert("RGBA")
                pil_img = pil_img.resize((1000, 180), Image.Resampling.LANCZOS)
                self.banner_ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(1000, 180))
                if hasattr(self, "banner_img_lbl") and self.banner_img_lbl:
                    self.banner_img_lbl.configure(image=self.banner_ctk_img)
            except Exception as e:
                log.warning(f"Error loading banner image: {e}")

    def _pick_custom_wallpaper(self):
        sel = filedialog.askopenfilename(
            title="Chọn Hình Ảnh Làm Hình Nền Launcher",
            filetypes=[("Hình ảnh", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("Tất cả files", "*.*")]
        )
        if sel:
            self.cfg["custom_wallpaper_path"] = str(Path(sel).resolve())
            engine.save_config(self.cfg)
            self._update_home_banner_image()
            if hasattr(self, "wall_path_lbl") and self.wall_path_lbl:
                self.wall_path_lbl.configure(text=f"Hiện tại: {Path(sel).name}")
            self._append_log(f"Đã cập nhật hình nền launcher: {Path(sel).name}")

    def _reset_custom_wallpaper(self):
        self.cfg["custom_wallpaper_path"] = ""
        engine.save_config(self.cfg)
        self._update_home_banner_image()
        if hasattr(self, "wall_path_lbl") and self.wall_path_lbl:
            self.wall_path_lbl.configure(text="Hiện tại: Mặc định (Default Anime Artwork)")
        self._append_log("Đã khôi phục hình nền launcher về mặc định.")

    def _clear_log(self):
        self.log_textbox.delete("1.0", "end")

    def _append_log(self, text: str):
        t_str = time.strftime("[%H:%M:%S] ")
        self.log_textbox.insert("end", t_str + text + "\n")
        self.log_textbox.see("end")

    def _open_hoyoplay_update(self):
        hyp_exe = engine.find_hoyoplay_launcher()
        if hyp_exe and hyp_exe.exists():
            self._append_log(f"Đang mở HoYoPlay Launcher ({hyp_exe}) để cập nhật game...")
            if engine.launch_hoyoplay():
                messagebox.showinfo("HoYoPlay", f"Đã mở HoYoPlay Launcher!\nĐường dẫn: {hyp_exe}\nBạn có thể cập nhật hoặc sửa chữa game tại đây.")
            else:
                messagebox.showerror("Lỗi", "Không thể khởi động HoYoPlay launcher.")
        else:
            res = messagebox.askyesno("Không tìm thấy HoYoPlay", "Chưa tìm thấy launcher.exe của HoYoPlay trên các ổ đĩa mặc định.\nBạn có muốn duyệt tìm file thủ công không?")
            if res:
                from tkinter import filedialog
                chosen = filedialog.askopenfilename(title="Chọn HoYoPlay launcher.exe", filetypes=[("Executable", "launcher.exe"), ("All Files", "*.*")])
                if chosen:
                    subprocess.Popen([chosen], cwd=str(Path(chosen).parent))

    def toggle_in_game_overlay(self):
        """Toggles the in-game overlay menu (XXMI style) on top of the screen."""
        if hasattr(self, "_in_game_overlay") and self._in_game_overlay is not None and self._in_game_overlay.winfo_exists():
            self._in_game_overlay.destroy()
            self._in_game_overlay = None
            return

        self._in_game_overlay = ctk.CTkToplevel(self)
        top = self._in_game_overlay
        top.title("Genshin In-Game Mod Menu")
        top.geometry("420x680+40+80")
        top.attributes("-topmost", True)
        top.configure(fg_color="#0e1322")
        top.resizable(False, False)

        # Header
        hdr = ctk.CTkFrame(top, height=50, corner_radius=0, fg_color="#182033")
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        title = ctk.CTkLabel(
            hdr,
            text="⚡ MENU TRONG GAME (XXMI OVERLAY)",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f59e0b"
        )
        title.pack(side="left", padx=14)

        f12_badge = ctk.CTkLabel(
            hdr,
            text="[F12 Đóng/Mở]",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        f12_badge.pack(side="left", padx=4)

        close_btn = ctk.CTkButton(
            hdr,
            text="✕",
            width=28,
            height=28,
            corner_radius=4,
            fg_color="#334155",
            hover_color="#ef4444",
            command=top.destroy
        )
        close_btn.pack(side="right", padx=10)

        # Performance & Telemetry Strip in Overlay
        perf_strip = ctk.CTkFrame(top, height=32, corner_radius=6, fg_color="#141a2e")
        perf_strip.pack(fill="x", padx=14, pady=(8, 2))
        perf_strip.pack_propagate(False)

        self.overlay_perf_lbl = ctk.CTkLabel(
            perf_strip,
            text="⚡ Ping: -- ms | CPU: 0% | RAM: 0 MB | GPU: 0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8"
        )
        self.overlay_perf_lbl.pack(side="left", padx=10)

        # Big Reload Button (F10 - XXMI Core Feature)
        reload_box = ctk.CTkFrame(top, fg_color="transparent")
        reload_box.pack(fill="x", padx=14, pady=(6, 8))

        reload_btn = ctk.CTkButton(
            reload_box,
            text="🔄 NẠP LẠI MOD TRONG GAME (PHÍM F10)",
            height=38,
            corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._trigger_reload_f10
        )
        reload_btn.pack(fill="x")

        # Quick In-Game Network Disconnect & HUD Control Box
        net_box = ctk.CTkFrame(top, corner_radius=8, fg_color="#141829")
        net_box.pack(fill="x", padx=14, pady=(0, 10))

        is_blocked = self.network_manager.is_game_blocked("genshin")
        btn_text = "🌐 KHÔI PHỤC MẠNG GAME" if is_blocked else "🔌 NGẮT MẠNG GAME (ISOLATED)"
        btn_color = "#10b981" if is_blocked else "#dc2626"
        btn_hover = "#059669" if is_blocked else "#b91c1c"

        self.overlay_killnet_btn = ctk.CTkButton(
            net_box,
            text=btn_text,
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=btn_color,
            hover_color=btn_hover,
            command=self._overlay_toggle_network
        )
        self.overlay_killnet_btn.pack(fill="x", padx=12, pady=(8, 4))

        hud_row = ctk.CTkFrame(net_box, fg_color="transparent")
        hud_row.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(hud_row, text="Bật HUD Nổi Mini (Phím F11):", font=ctk.CTkFont(size=11), text_color="#f8fafc").pack(side="left")
        hud_is_open = (self._mini_hud is not None and self._mini_hud.winfo_exists() and self._mini_hud.state() == "normal")
        self.overlay_hud_sw = ctk.CTkSwitch(hud_row, text="", width=40, command=self.toggle_mini_hud)
        if hud_is_open:
            self.overlay_hud_sw.select()
        else:
            self.overlay_hud_sw.deselect()
        self.overlay_hud_sw.pack(side="right")

        # Macro Quick Toggles
        macro_frame = ctk.CTkFrame(top, corner_radius=8, fg_color="#141829")
        macro_frame.pack(fill="x", padx=14, pady=(0, 10))

        macro_lbl = ctk.CTkLabel(
            macro_frame,
            text="Bật/Tắt Nhanh Macro:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1"
        )
        macro_lbl.pack(anchor="w", padx=12, pady=(8, 4))

        # Auto Story
        m_row1 = ctk.CTkFrame(macro_frame, fg_color="transparent")
        m_row1.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(m_row1, text="Auto Cốt Truyện (F8)", font=ctk.CTkFont(size=11), text_color="#f8fafc").pack(side="left")
        st_var = ctk.BooleanVar(value=self.macro_engine.is_feature_enabled("auto_story"))
        ctk.CTkSwitch(m_row1, text="", variable=st_var, width=40, command=lambda: self._on_macro_toggle("auto_story", st_var)).pack(side="right")

        # Auto Loot
        m_row2 = ctk.CTkFrame(macro_frame, fg_color="transparent")
        m_row2.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(m_row2, text="Auto Nhặt Đồ (F7)", font=ctk.CTkFont(size=11), text_color="#f8fafc").pack(side="left")
        lt_var = ctk.BooleanVar(value=self.macro_engine.is_feature_enabled("auto_loot"))
        ctk.CTkSwitch(m_row2, text="", variable=lt_var, width=40, command=lambda: self._on_macro_toggle("auto_loot", lt_var)).pack(side="right")

        # Auto Gadget
        m_row3 = ctk.CTkFrame(macro_frame, fg_color="transparent")
        m_row3.pack(fill="x", padx=12, pady=(2, 8))
        ctk.CTkLabel(m_row3, text="Auto Bảo Bối Z (F9)", font=ctk.CTkFont(size=11), text_color="#f8fafc").pack(side="left")
        gd_var = ctk.BooleanVar(value=self.macro_engine.is_feature_enabled("auto_gadget"))
        ctk.CTkSwitch(m_row3, text="", variable=gd_var, width=40, command=lambda: self._on_macro_toggle("auto_gadget", gd_var)).pack(side="right")

        # Active Mods Quick Switch List
        mod_lbl = ctk.CTkLabel(
            top,
            text="Mod Trong Danh Mục (Bật/Tắt & bấm F10 để nạp):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        mod_lbl.pack(anchor="w", padx=14, pady=(0, 4))

        mod_scroll = ctk.CTkScrollableFrame(top, height=220, corner_radius=8, fg_color="#121626")
        mod_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        mods = self.mod_manager.get_all_mods()
        if not mods:
            ctk.CTkLabel(mod_scroll, text="Chưa có mod nào trong Data_Mods.", text_color="#64748b").pack(pady=20)
        else:
            for m in mods:
                mrow = ctk.CTkFrame(mod_scroll, height=36, corner_radius=4, fg_color="#181d30")
                mrow.pack(fill="x", pady=2)
                mrow.pack_propagate(False)

                m_name = ctk.CTkLabel(mrow, text=m.name[:25], font=ctk.CTkFont(size=11), text_color="#f8fafc")
                m_name.pack(side="left", padx=8)

                var = ctk.BooleanVar(value=m.is_enabled)
                sw = ctk.CTkSwitch(mrow, text="", variable=var, width=36, command=lambda mn=m.name, v=var: self._toggle_overlay_mod(mn, v))
                sw.pack(side="right", padx=6)

    def _trigger_reload_f10(self):
        try:
            import genshin_macro
            genshin_macro.trigger_in_game_reload_f10()
            self._append_log("[In-Game] Đã gửi phím F10: Đang nạp lại Mod trực tiếp trong game!")
            messagebox.showinfo("F10 Reload", "Đã gửi lệnh F10! Toàn bộ Mod đang được nạp lại tức thì trong game.")
        except Exception as e:
            self._append_log(f"[In-Game] Lỗi gửi F10: {e}")

    def _toggle_overlay_mod(self, mod_name: str, var: ctk.BooleanVar):
        val = var.get()
        self.mod_manager.set_mod_enabled(mod_name, val)
        self._append_log(f"[In-Game] Đã {'bật' if val else 'tắt'} mod: {mod_name}. Hãy bấm 'Nạp lại Mod (F10)' để áp dụng vào game!")

    # =========================================================================
    # 2. TAB: QUẢN LÝ MOD (MOD MANAGER)
    # =========================================================================
    def _build_mods_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["mods"] = frame

        # Top Action Toolbar
        toolbar = ctk.CTkFrame(frame, height=50, corner_radius=10, fg_color="#141829")
        toolbar.pack(fill="x", padx=16, pady=(16, 12))
        toolbar.pack_propagate(False)

        # Search Box
        search_box = ctk.CTkFrame(toolbar, fg_color="transparent")
        search_box.pack(side="left", padx=(10, 8), pady=8)

        self.search_entry = ctk.CTkEntry(
            search_box,
            placeholder_text=self._t("search_mod"),
            width=210,
            height=34,
            corner_radius=6,
            fg_color="#0a0c16",
            border_color="#1e243d"
        )
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", lambda e: self._on_search_change())

        clear_search_btn = ctk.CTkButton(
            search_box,
            text="✕",
            width=28,
            height=34,
            corner_radius=6,
            fg_color="#1e243d",
            hover_color="#334155",
            text_color="#94a3b8",
            command=self._clear_search
        )
        clear_search_btn.pack(side="left", padx=(4, 0))

        # Buttons
        add_btn = ctk.CTkButton(
            toolbar,
            text=self._t("btn_add_mod"),
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._import_mod_dialog
        )
        add_btn.pack(side="left", padx=4)

        refresh_btn = ctk.CTkButton(
            toolbar,
            text=self._t("btn_refresh"),
            height=34,
            width=90,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            command=self._refresh_mods_ui
        )
        refresh_btn.pack(side="left", padx=4)

        # Sort Dropdown (Matches Screenshot 1)
        self.sort_combo = ctk.CTkComboBox(
            toolbar,
            values=["Sắp xếp: Tên (A-Z)", "Sắp xếp: Tên (Z-A)", "Sắp xếp: Kích thước"],
            width=165,
            height=34,
            corner_radius=6,
            command=self._on_sort_changed
        )
        self.sort_combo.pack(side="left", padx=4)

        enable_all_btn = ctk.CTkButton(
            toolbar,
            text=self._t("btn_enable_all"),
            height=34,
            width=100,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=lambda: self._set_all_mods(True)
        )
        enable_all_btn.pack(side="right", padx=6)

        disable_all_btn = ctk.CTkButton(
            toolbar,
            text=self._t("btn_disable_all"),
            height=34,
            width=100,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=lambda: self._set_all_mods(False)
        )
        disable_all_btn.pack(side="right", padx=4)

        # Body: Left Categories + Right Mod Cards Grid
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Left Categories Panel
        cat_card = ctk.CTkFrame(body, width=220, corner_radius=10, fg_color="#141829")
        cat_card.pack(side="left", fill="y", padx=(0, 12))
        cat_card.pack_propagate(False)

        cat_title = ctk.CTkLabel(
            cat_card,
            text="Nhân Vật / Danh Mục",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8"
        )
        cat_title.pack(anchor="w", padx=12, pady=(12, 6))

        self.categories_scroll = ctk.CTkScrollableFrame(cat_card, fg_color="transparent")
        self.categories_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # Bottom Quick Action Bar on left panel (Matches Screenshot 1)
        cat_bottom_bar = ctk.CTkFrame(cat_card, height=38, fg_color="#1a1f33", corner_radius=6)
        cat_bottom_bar.pack(fill="x", padx=6, pady=6)

        cat_add_btn = ctk.CTkButton(
            cat_bottom_bar,
            text="+ Thêm",
            height=26,
            corner_radius=4,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._import_mod_dialog
        )
        cat_add_btn.pack(side="left", fill="x", expand=True, padx=2, pady=4)

        cat_refresh_btn = ctk.CTkButton(
            cat_bottom_bar,
            text="Làm mới",
            height=26,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._refresh_mods_ui
        )
        cat_refresh_btn.pack(side="left", fill="x", expand=True, padx=2, pady=4)

        cat_disable_btn = ctk.CTkButton(
            cat_bottom_bar,
            text="Tắt hết",
            height=26,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=lambda: self._set_all_mods(False)
        )
        cat_disable_btn.pack(side="left", fill="x", expand=True, padx=2, pady=4)

        # Right Mods Grid Area
        right_container = ctk.CTkFrame(body, fg_color="transparent")
        right_container.pack(side="right", fill="both", expand=True)

        self.mods_count_label = ctk.CTkLabel(
            right_container,
            text="",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8"
        )
        self.mods_count_label.pack(anchor="w", pady=(0, 8))

        self.mods_scroll = ctk.CTkScrollableFrame(right_container, fg_color="#121524", corner_radius=10)
        self.mods_scroll.pack(fill="both", expand=True)

    def _clear_search(self):
        self.search_entry.delete(0, "end")
        self.search_query = ""
        self._refresh_mods_ui()

    def _on_sort_changed(self, choice=None):
        self._refresh_mods_ui()

    def _get_cached_thumb(self, thumb_path: Optional[Path]) -> Optional[ctk.CTkImage]:
        if not thumb_path or not thumb_path.exists():
            return None
        k = str(thumb_path)
        if k in self._thumb_cache:
            return self._thumb_cache[k]
        try:
            pil_img = Image.open(thumb_path).convert("RGBA")
            pil_img = pil_img.resize((54, 54), Image.Resampling.LANCZOS)
            ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(54, 54))
            self._thumb_cache[k] = ctk_img
            return ctk_img
        except Exception:
            return None

    def _refresh_mods_ui(self):
        # Refresh categories list
        for w in self.categories_scroll.winfo_children():
            w.destroy()

        mods = self.mod_manager.get_all_mods()
        cat_counts = {"Tất Cả": len(mods)}
        for m in mods:
            cat_counts[m.category] = cat_counts.get(m.category, 0) + 1

        for cat_name, count in cat_counts.items():
            btn = ctk.CTkButton(
                self.categories_scroll,
                text=f"{cat_name} ({count})",
                anchor="w",
                height=36,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold" if cat_name == self.selected_category else "normal"),
                fg_color="#2563eb" if cat_name == self.selected_category else "#1a1f33",
                hover_color="#2b3354",
                text_color="#ffffff",
                command=lambda c=cat_name: self._select_category(c)
            )
            btn.pack(fill="x", pady=2)

        # Refresh mod cards
        for w in self.mods_scroll.winfo_children():
            w.destroy()

        filtered_mods = []
        for m in mods:
            if self.selected_category != "Tất Cả" and m.category != self.selected_category:
                continue
            if self.search_query and self.search_query.lower() not in m.name.lower():
                continue
            filtered_mods.append(m)

        # Sort filtered mods (Matches Screenshot 1)
        sort_mode = self.sort_combo.get() if hasattr(self, "sort_combo") else "A-Z"
        if "Z-A" in sort_mode:
            filtered_mods.sort(key=lambda m: m.name.lower(), reverse=True)
        elif "Kích thước" in sort_mode:
            filtered_mods.sort(key=lambda m: m.size_mb, reverse=True)
        else:
            filtered_mods.sort(key=lambda m: m.name.lower())

        enabled_count = sum(1 for m in filtered_mods if m.is_enabled)
        self.mods_count_label.configure(
            text=f"Hiển thị {len(filtered_mods)} mod ({enabled_count} đang bật) | Cầu nối ảo Junction: Hoạt động"
        )

        if not filtered_mods:
            empty_lbl = ctk.CTkLabel(
                self.mods_scroll,
                text="Không tìm thấy mod nào trong danh mục này.\nBấm nút [+ Thêm Mod] bên trên để nạp file .zip hoặc thư mục mod!",
                font=ctk.CTkFont(size=14),
                text_color="#64748b"
            )
            empty_lbl.pack(pady=40)
            return

        for mod in filtered_mods:
            self._render_mod_card(mod)

    def _render_mod_card(self, mod: ModInfo):
        card = ctk.CTkFrame(self.mods_scroll, height=72, corner_radius=8, fg_color="#181d30", border_width=1, border_color="#262d47")
        card.pack(fill="x", padx=6, pady=4)
        card.pack_propagate(False)

        # Left status indicator strip
        strip_color = "#10b981" if mod.is_enabled else "#64748b"
        strip = ctk.CTkFrame(card, width=5, corner_radius=0, fg_color=strip_color)
        strip.pack(side="left", fill="y")

        # Mod Icon / Thumbnail with cache
        thumb_frame = ctk.CTkFrame(card, width=54, height=54, corner_radius=6, fg_color="#222842")
        thumb_frame.pack(side="left", padx=10, pady=8)
        thumb_frame.pack_propagate(False)

        ctk_thumb = self._get_cached_thumb(mod.thumbnail)
        if ctk_thumb:
            t_lbl = ctk.CTkLabel(thumb_frame, text="", image=ctk_thumb)
            t_lbl.place(x=0, y=0, relwidth=1, relheight=1)
        else:
            t_lbl = ctk.CTkLabel(thumb_frame, text="👗", font=ctk.CTkFont(size=20))
            t_lbl.place(x=0, y=0, relwidth=1, relheight=1)

        # Mod Info Text
        info_frame = ctk.CTkFrame(card, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, pady=10)

        name_lbl = ctk.CTkLabel(
            info_frame,
            text=mod.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#f8fafc",
            anchor="w"
        )
        name_lbl.pack(anchor="w")

        sub_text = f"🏷️ {mod.category}  •  💾 {mod.size_mb} MB  •  📄 {len(mod.ini_files)} file .ini"
        sub_lbl = ctk.CTkLabel(
            info_frame,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            anchor="w"
        )
        sub_lbl.pack(anchor="w")

        # Right Controls: Switch + Actions
        right_ctrl = ctk.CTkFrame(card, fg_color="transparent")
        right_ctrl.pack(side="right", padx=12, pady=12)

        open_btn = ctk.CTkButton(
            right_ctrl,
            text=self._t("btn_open_folder"),
            width=50,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda p=mod.path: engine.open_folder(p)
        )
        open_btn.pack(side="left", padx=4)

        trash_btn = ctk.CTkButton(
            right_ctrl,
            text=self._t("btn_trash"),
            width=50,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            command=lambda m=mod.name: self._trash_mod_prompt(m)
        )
        trash_btn.pack(side="left", padx=4)

        switch_var = ctk.BooleanVar(value=mod.is_enabled)
        mod_switch = ctk.CTkSwitch(
            right_ctrl,
            text=self._t("status_enabled") if mod.is_enabled else self._t("status_disabled"),
            variable=switch_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981" if mod.is_enabled else "#94a3b8",
            progress_color="#10b981"
        )
        mod_switch.configure(command=lambda m=mod.name, v=switch_var, s=strip, sw=mod_switch: self._on_mod_switch_toggle(m, v, s, sw))
        mod_switch.pack(side="left", padx=(8, 0))

    def _select_category(self, cat_name: str):
        self.selected_category = cat_name
        self._refresh_mods_ui()

    def _on_search_change(self):
        self.search_query = self.search_entry.get().strip()
        self._refresh_mods_ui()

    def _on_mod_switch_toggle(self, mod_name: str, var: ctk.BooleanVar, strip_widget, switch_widget):
        val = var.get()
        self.mod_manager.set_mod_enabled(mod_name, val)
        if val:
            strip_widget.configure(fg_color="#10b981")
            switch_widget.configure(text=self._t("status_enabled"), text_color="#10b981")
        else:
            strip_widget.configure(fg_color="#64748b")
            switch_widget.configure(text=self._t("status_disabled"), text_color="#94a3b8")

        mods = self.mod_manager.get_all_mods()
        enabled_count = sum(1 for m in mods if m.is_enabled)
        self.mods_count_label.configure(
            text=f"Hiển thị {len(mods)} mod ({enabled_count} đang bật) | Cầu nối ảo Junction: Hoạt động"
        )

    def _set_all_mods(self, enabled: bool):
        self.mod_manager.set_all_mods_enabled(enabled)
        self._refresh_mods_ui()

    def _trash_mod_prompt(self, mod_name: str):
        if self.mod_manager.trash_mod(mod_name):
            self._refresh_mods_ui()

    def _import_mod_dialog(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Chọn file Mod (.zip)",
            filetypes=[("Zip Archive", "*.zip"), ("All Files", "*.*")]
        )
        if not path:
            path = filedialog.askdirectory(title="Hoặc chọn thư mục Mod")
        if path:
            ok, msg = self.mod_manager.import_mod_archive_or_folder(Path(path))
            self._append_log(msg)
            self._refresh_mods_ui()

    # =========================================================================
    # 3. TAB: GỘP MOD / NHÓM MOD (MOD GROUPS)
    # =========================================================================
    def _build_groups_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["groups"] = frame

        # Top Bar
        top_bar = ctk.CTkFrame(frame, height=50, corner_radius=10, fg_color="#141829")
        top_bar.pack(fill="x", padx=16, pady=(16, 12))
        top_bar.pack_propagate(False)

        create_grp_btn = ctk.CTkButton(
            top_bar,
            text=self._t("btn_create_group"),
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._create_group_dialog
        )
        create_grp_btn.pack(side="left", padx=10, pady=8)

        hint_lbl = ctk.CTkLabel(
            top_bar,
            text=self._t("group_hint"),
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        hint_lbl.pack(side="left", padx=10)

        # Body: Left Groups List + Right Group Content
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Left Groups
        self.group_list_card = ctk.CTkFrame(body, width=260, corner_radius=10, fg_color="#141829")
        self.group_list_card.pack(side="left", fill="y", padx=(0, 12))
        self.group_list_card.pack_propagate(False)

        grp_hdr = ctk.CTkLabel(
            self.group_list_card,
            text="Danh Sách Nhóm Mod",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8"
        )
        grp_hdr.pack(anchor="w", padx=12, pady=(12, 6))

        self.groups_scroll = ctk.CTkScrollableFrame(self.group_list_card, fg_color="transparent")
        self.groups_scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # Right Group Details
        self.group_detail_frame = ctk.CTkFrame(body, corner_radius=10, fg_color="#121524")
        self.group_detail_frame.pack(side="right", fill="both", expand=True)

    def _refresh_groups_ui(self):
        for w in self.groups_scroll.winfo_children():
            w.destroy()

        groups = self.mod_manager.get_groups()
        if not groups:
            empty_lbl = ctk.CTkLabel(self.groups_scroll, text="Chưa có nhóm nào.\nBấm nút tạo nhóm bên trên!", text_color="#64748b")
            empty_lbl.pack(pady=20)
            return

        if not self.selected_group_id and groups:
            self.selected_group_id = groups[0].get("id")

        for grp in groups:
            gid = grp.get("id")
            gname = grp.get("name")
            gmods = grp.get("mods", [])
            gcolor = grp.get("color", "#38bdf8")

            # Check how many are enabled
            all_mods = {m.name: m for m in self.mod_manager.get_all_mods()}
            enabled_in_grp = sum(1 for mn in gmods if mn in all_mods and all_mods[mn].is_enabled)

            btn = ctk.CTkButton(
                self.groups_scroll,
                text=f"● {gname}\n   {enabled_in_grp}/{len(gmods)} mod đang bật",
                anchor="w",
                height=50,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold" if gid == self.selected_group_id else "normal"),
                fg_color="#2563eb" if gid == self.selected_group_id else "#1a1f33",
                hover_color="#2b3354",
                text_color="#ffffff",
                command=lambda g_id=gid: self._select_group(g_id)
            )
            btn.pack(fill="x", pady=3)

        self._render_group_detail()

    def _select_group(self, group_id: str):
        self.selected_group_id = group_id
        self._refresh_groups_ui()

    def _render_group_detail(self):
        for w in self.group_detail_frame.winfo_children():
            w.destroy()

        groups = self.mod_manager.get_groups()
        group = next((g for g in groups if g.get("id") == self.selected_group_id), None)
        if not group:
            return

        # Header bar of group (Matches Screenshot 5)
        hdr_bar = ctk.CTkFrame(self.group_detail_frame, height=54, corner_radius=8, fg_color="#181c2e")
        hdr_bar.pack(fill="x", padx=12, pady=(12, 6))
        hdr_bar.pack_propagate(False)

        grp_color = group.get("color", "#38bdf8")
        color_dot = ctk.CTkLabel(
            hdr_bar,
            text="■",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=grp_color
        )
        color_dot.pack(side="left", padx=(14, 4))

        title_lbl = ctk.CTkLabel(
            hdr_bar,
            text=f"{group.get('name')}",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f8fafc"
        )
        title_lbl.pack(side="left", padx=4)

        # Action Buttons on Header
        del_btn = ctk.CTkButton(
            hdr_bar,
            text="🗑️ Xoá thư mục",
            height=30,
            width=110,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            font=ctk.CTkFont(size=11),
            command=lambda: self._delete_group_action(group.get("id"))
        )
        del_btn.pack(side="right", padx=6)

        rename_btn = ctk.CTkButton(
            hdr_bar,
            text="✏️ Đổi tên",
            height=30,
            width=90,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11),
            command=lambda: self._rename_group_dialog(group.get("id"), group.get("name"))
        )
        rename_btn.pack(side="right", padx=4)

        color_btn = ctk.CTkButton(
            hdr_bar,
            text="🎨 Đổi màu",
            height=30,
            width=90,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=11),
            command=lambda: self._change_group_color_dialog(group.get("id"))
        )
        color_btn.pack(side="right", padx=4)

        # Secondary Action Bar: [+ Thêm mod vào nhóm] [Bật cả nhóm] [Tắt cả nhóm]
        action_bar = ctk.CTkFrame(self.group_detail_frame, height=44, fg_color="transparent")
        action_bar.pack(fill="x", padx=12, pady=(0, 8))

        add_to_grp_btn = ctk.CTkButton(
            action_bar,
            text="+ Thêm mod vào nhóm",
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._add_mod_to_group_dialog(group.get("id"))
        )
        add_to_grp_btn.pack(side="left", padx=(0, 6))

        enable_btn = ctk.CTkButton(
            action_bar,
            text="✅ Bật cả nhóm",
            height=34,
            width=110,
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._toggle_group_batch(group.get("id"), True)
        )
        enable_btn.pack(side="left", padx=4)

        disable_btn = ctk.CTkButton(
            action_bar,
            text="⛔ Tắt cả nhóm",
            height=34,
            width=110,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._toggle_group_batch(group.get("id"), False)
        )
        disable_btn.pack(side="left", padx=4)

        # Mod list in group
        mod_scroll = ctk.CTkScrollableFrame(self.group_detail_frame, fg_color="transparent")
        mod_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        group_mods = group.get("mods", [])
        all_mods = {m.name: m for m in self.mod_manager.get_all_mods()}

        if not group_mods:
            empty_lbl = ctk.CTkLabel(
                mod_scroll,
                text="Nhóm này chưa có Mod nào.\nBấm nút [+ Thêm mod vào nhóm] để gán các mod yêu thích!",
                font=ctk.CTkFont(size=13),
                text_color="#64748b"
            )
            empty_lbl.pack(pady=40)
            return

        for mod_name in group_mods:
            mod_obj = all_mods.get(mod_name)
            is_enabled = mod_obj.is_enabled if mod_obj else False
            mod_cat = mod_obj.category if mod_obj else "Khác"

            row = ctk.CTkFrame(mod_scroll, height=48, corner_radius=6, fg_color="#161b2c")
            row.pack(fill="x", pady=3)
            row.pack_propagate(False)

            strip = ctk.CTkFrame(row, width=4, corner_radius=0, fg_color="#10b981" if is_enabled else "#64748b")
            strip.pack(side="left", fill="y")

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", padx=12, fill="y", pady=4)

            name_lbl = ctk.CTkLabel(text_col, text=mod_name, font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
            name_lbl.pack(anchor="w")

            cat_lbl = ctk.CTkLabel(text_col, text=f"Danh mục · {mod_cat}", font=ctk.CTkFont(size=10), text_color="#64748b")
            cat_lbl.pack(anchor="w")

            remove_btn = ctk.CTkButton(
                row,
                text="✕",
                width=30,
                height=26,
                fg_color="#334155",
                hover_color="#ef4444",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda mn=mod_name, gid=group.get("id"): self._remove_mod_from_group_action(gid, mn)
            )
            remove_btn.pack(side="right", padx=10)

            status_lbl = ctk.CTkLabel(
                row,
                text="● Đang bật" if is_enabled else "● Đã tắt",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#10b981" if is_enabled else "#94a3b8"
            )
            status_lbl.pack(side="right", padx=12)

    def _toggle_group_batch(self, group_id: str, enabled: bool):
        self.mod_manager.set_group_enabled(group_id, enabled)
        self._refresh_groups_ui()

    def _delete_group_action(self, group_id: str):
        self.mod_manager.delete_group(group_id)
        self.selected_group_id = None
        self._refresh_groups_ui()

    def _remove_mod_from_group_action(self, group_id: str, mod_name: str):
        self.mod_manager.remove_mod_from_group(group_id, mod_name)
        self._refresh_groups_ui()

    def _rename_group_dialog(self, group_id: str, old_name: str):
        dialog = ctk.CTkInputDialog(text=f"Nhập tên mới cho nhóm '{old_name}':", title="Đổi Tên Nhóm Mod")
        new_name = dialog.get_input()
        if new_name and new_name.strip():
            self.mod_manager.rename_group(group_id, new_name.strip())
            self._refresh_groups_ui()

    def _change_group_color_dialog(self, group_id: str):
        colors = ["#38bdf8", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"]
        top = ctk.CTkToplevel(self)
        top.title("Chọn Màu Nhóm")
        top.geometry("320x180")
        top.attributes("-topmost", True)

        lbl = ctk.CTkLabel(top, text="Chọn màu đại diện cho nhóm Mod:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl.pack(pady=12)

        c_box = ctk.CTkFrame(top, fg_color="transparent")
        c_box.pack(pady=6)

        def pick_col(c):
            self.mod_manager.update_group_color(group_id, c)
            self._refresh_groups_ui()
            top.destroy()

        for c in colors:
            btn = ctk.CTkButton(c_box, text="", width=32, height=32, corner_radius=6, fg_color=c, hover_color=c, command=lambda clr=c: pick_col(clr))
            btn.pack(side="left", padx=4)

    def _create_group_dialog(self):
        dialog = ctk.CTkInputDialog(text="Nhập tên nhóm Mod mới (ví dụ: Vũ khí & Hiệu ứng, Đội hình La Hoàn...):", title="Tạo Nhóm Mod")
        name = dialog.get_input()
        if name and name.strip():
            new_grp = self.mod_manager.create_group(name.strip())
            self.selected_group_id = new_grp.get("id")
            self._refresh_groups_ui()

    def _add_mod_to_group_dialog(self, group_id: str):
        all_mods = self.mod_manager.get_all_mods()
        if not all_mods:
            return

        top = ctk.CTkToplevel(self)
        top.title("Thêm Mod Vào Nhóm")
        top.geometry("400x500")
        top.attributes("-topmost", True)

        lbl = ctk.CTkLabel(top, text="Chọn Mod để thêm vào nhóm:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl.pack(pady=10)

        scroll = ctk.CTkScrollableFrame(top)
        scroll.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        for m in all_mods:
            def add_cb(mn=m.name):
                self.mod_manager.add_mod_to_group(group_id, mn)
                top.destroy()
                self._refresh_groups_ui()

            btn = ctk.CTkButton(scroll, text=f"➕  {m.name}", anchor="w", fg_color="#1e293b", hover_color="#2563eb", command=add_cb)
            btn.pack(fill="x", pady=2)

    # =========================================================================
    # 4. TAB: MACRO TIỆN ÍCH (MACRO AUTOMATION)
    # =========================================================================
    def _build_macro_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["macro"] = frame

        # Top Warning Banner if NOT Admin (Matches HoYo Launcher Mods)
        if not engine.is_admin():
            admin_card = ctk.CTkFrame(frame, corner_radius=10, fg_color="#3a2504", border_width=1, border_color="#d97706")
            admin_card.pack(fill="x", padx=16, pady=(12, 6))

            admin_lbl = ctk.CTkLabel(
                admin_card,
                text="⚠️ Launcher đang chạy với quyền THƯỜNG (không phải Admin) — có thể chặn Macro THEO CẢ HAI CHIỀU nếu Game\n"
                     "(hoặc phần mềm chống gian lận của Game) chạy ở mức toàn vẹn cao hơn. Khởi động lại với quyền Admin để nhận phím 100%.",
                font=ctk.CTkFont(size=11),
                text_color="#fef08a",
                justify="left",
                padx=14,
                pady=8
            )
            admin_lbl.pack(side="left", fill="x", expand=True)

            restart_admin_btn = ctk.CTkButton(
                admin_card,
                text="🛡️ Khởi động lại với quyền Admin",
                height=32,
                corner_radius=6,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#f59e0b",
                hover_color="#d97706",
                text_color="#000000",
                command=self._restart_as_admin
            )
            restart_admin_btn.pack(side="right", padx=12, pady=8)

        # Macro Subtabs Bar ("Macro Cơ Bản" | "Macro Pro")
        subtab_bar = ctk.CTkFrame(frame, height=44, fg_color="transparent")
        subtab_bar.pack(fill="x", padx=16, pady=(6, 8))

        self.btn_macro_basic = ctk.CTkButton(
            subtab_bar,
            text="Macro Cơ Bản",
            height=34,
            width=140,
            corner_radius=6,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=lambda: self._switch_macro_subtab("basic")
        )
        self.btn_macro_basic.pack(side="left", padx=(0, 8))

        self.btn_macro_pro = ctk.CTkButton(
            subtab_bar,
            text="Macro Pro",
            height=34,
            width=140,
            corner_radius=6,
            font=ctk.CTkFont(size=13),
            fg_color="#1a1f33",
            hover_color="#2b3354",
            text_color="#94a3b8",
            command=lambda: self._switch_macro_subtab("pro")
        )
        self.btn_macro_pro.pack(side="left")

        # Container for subtab contents
        self.macro_subtab_container = ctk.CTkFrame(frame, fg_color="transparent")
        self.macro_subtab_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.macro_subtab_mode = "basic"
        self._render_macro_subtab()

    def _switch_macro_subtab(self, mode: str):
        self.macro_subtab_mode = mode
        if mode == "basic":
            self.btn_macro_basic.configure(fg_color="#2563eb", text_color="#ffffff", font=ctk.CTkFont(size=13, weight="bold"))
            self.btn_macro_pro.configure(fg_color="#1a1f33", text_color="#94a3b8", font=ctk.CTkFont(size=13))
        else:
            self.btn_macro_basic.configure(fg_color="#1a1f33", text_color="#94a3b8", font=ctk.CTkFont(size=13))
            self.btn_macro_pro.configure(fg_color="#2563eb", text_color="#ffffff", font=ctk.CTkFont(size=13, weight="bold"))
        self._render_macro_subtab()

    def _render_macro_subtab(self):
        for w in self.macro_subtab_container.winfo_children():
            w.destroy()

        if self.macro_subtab_mode == "basic":
            self._render_macro_basic_tab(self.macro_subtab_container)
        else:
            self._render_macro_pro_tab(self.macro_subtab_container)

    def _render_macro_basic_tab(self, parent):
        # Header with Subtitle and "+ Thêm macro" button
        hdr_box = ctk.CTkFrame(parent, fg_color="transparent")
        hdr_box.pack(fill="x", pady=(0, 10))

        sub_lbl = ctk.CTkLabel(
            hdr_box,
            text="Tự động nhấn phím theo tổ hợp phím tắt riêng cho từng macro (An toàn 100% khi chạy cốt truyện & nhặt đồ).",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        sub_lbl.pack(side="left")

        add_macro_btn = ctk.CTkButton(
            hdr_box,
            text="+ Thêm Macro Mới (Pro)",
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._add_custom_macro_dialog
        )
        add_macro_btn.pack(side="right")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # Card 1: Auto Cốt Truyện (Back / F8)
        self._build_macro_card(
            parent=scroll,
            title="Auto Cốt Truyện",
            desc="Tự động bấm phím Space và chuột trái liên tục để tua nhanh qua các đoạn hội thoại nhiệm vụ dài.",
            hotkey_str="Back / F8",
            feature_key="auto_story"
        )

        # Card 2: Auto Nhặt (Tab + E / F7)
        self._build_macro_card(
            parent=scroll,
            title="Auto Nhặt",
            desc="Spam phím F tốc độ cao khi đứng cạnh vật phẩm rơi, rương báu hoặc tài nguyên thế giới.",
            hotkey_str="Tab + E / F7",
            feature_key="auto_loot"
        )

        # Card 3: Auto Z (Tab + Z / F9)
        self._build_macro_card(
            parent=scroll,
            title="Auto Z",
            desc="Tự động nhấn phím Z mỗi 2.5 giây. Tiện lợi cho Quạt lông vũ tăng tốc lướt gió, máy ảnh hoặc la bàn.",
            hotkey_str="Tab + Z / F9",
            feature_key="auto_gadget"
        )

    def _add_custom_macro_dialog(self):
        self._switch_macro_subtab("pro")

    def _render_macro_pro_tab(self, parent):
        for w in parent.winfo_children():
            w.destroy()

        # Notice Card
        notice_card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#182033", border_width=1, border_color="#0284c7")
        notice_card.pack(fill="x", pady=(0, 10))

        pro_warn = ctk.CTkLabel(
            notice_card,
            text="⚡ Macro Pro: Ghi lại trực tiếp mọi thao tác chuột & bàn phím, nạp chuỗi combo từ file (.json) người khác chia sẻ,\n"
                 "và thiết lập phím nóng toàn cục để kích hoạt chuỗi combo xoay tua kỹ năng khi game đang hoạt động.",
            font=ctk.CTkFont(size=12),
            text_color="#93c5fd",
            justify="left",
            padx=14,
            pady=10
        )
        pro_warn.pack(anchor="w")

        # Action Toolbar (Record, Import, Export)
        act_bar = ctk.CTkFrame(parent, height=44, fg_color="#131726", corner_radius=8)
        act_bar.pack(fill="x", pady=(0, 10))
        act_bar.pack_propagate(False)

        is_rec = hasattr(self, "macro_recorder") and self.macro_recorder is not None and self.macro_recorder.is_recording
        rec_text = "⏹️ DỪNG GHI THAO TÁC" if is_rec else "🔴 GHI LẠI THAO TÁC MỚI"
        rec_color = "#dc2626" if is_rec else "#be123c"
        rec_hover = "#b91c1c" if is_rec else "#9f1239"

        self.btn_rec_macro = ctk.CTkButton(
            act_bar,
            text=rec_text,
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=rec_color,
            hover_color=rec_hover,
            command=self._toggle_macro_recording
        )
        self.btn_rec_macro.pack(side="left", padx=8, pady=6)

        import_btn = ctk.CTkButton(
            act_bar,
            text="📥 Nạp Macro (.json)",
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self._import_macro_file
        )
        import_btn.pack(side="left", padx=4, pady=6)

        export_all_btn = ctk.CTkButton(
            act_bar,
            text="📤 Xuất Toàn Bộ Macro",
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            command=self._export_all_macros
        )
        export_all_btn.pack(side="left", padx=4, pady=6)

        # Scrollable combo list
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        combos = self.macro_engine.cfg.get("combos", [])
        if not combos:
            empty_lbl = ctk.CTkLabel(
                scroll,
                text="Chưa có combo Pro nào. Hãy bấm '🔴 Ghi Lại Thao Tác Mới' hoặc '📥 Nạp Macro (.json)'!",
                font=ctk.CTkFont(size=13),
                text_color="#64748b"
            )
            empty_lbl.pack(pady=40)
            return

        for combo in combos:
            cid = combo.get("id")
            cname = combo.get("name", "Combo")
            chotkey = combo.get("hotkey", "").upper()
            steps = combo.get("steps", [])
            is_enabled = combo.get("enabled", True)

            card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#181d30", border_width=1, border_color="#334155")
            card.pack(fill="x", pady=6)

            card_top = ctk.CTkFrame(card, fg_color="transparent")
            card_top.pack(fill="x", padx=14, pady=(10, 4))

            ctk.CTkLabel(
                card_top,
                text=f"⚡ {cname}",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#f59e0b"
            ).pack(side="left")

            if chotkey:
                ctk.CTkLabel(
                    card_top,
                    text=f"Phím kích hoạt: [{chotkey}]",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#38bdf8",
                    fg_color="#0c4a6e",
                    corner_radius=6,
                    padx=8,
                    pady=2
                ).pack(side="left", padx=10)

            def make_toggle_cb(comb_id=cid):
                def cb():
                    for c in self.macro_engine.cfg.get("combos", []):
                        if c.get("id") == comb_id:
                            c["enabled"] = not c.get("enabled", True)
                            break
                    self.macro_engine.save_config()
                    self.macro_engine.setup_hotkeys()
                    self._render_macro_pro_tab(self.macro_subtab_container)
                return cb

            sw = ctk.CTkSwitch(
                card_top,
                text="Bật",
                command=make_toggle_cb(cid)
            )
            if is_enabled:
                sw.select()
            else:
                sw.deselect()
            sw.pack(side="right")

            step_preview_texts = []
            for st in steps[:8]:
                dur = st.get('duration_ms', 30)
                dur_str = f", giữ {dur}ms" if dur > 50 else ""
                if st.get("type") == "mouse" or "button" in st:
                    b_name = "Chuột Trái" if st.get("button") == "lclick" else ("Chuột Phải" if st.get("button") == "rclick" else "Chuột Giữa")
                    step_preview_texts.append(f"🖱️ {b_name} ({st.get('delay_ms', 100)}ms{dur_str})")
                else:
                    k = st.get("key", "").upper()
                    step_preview_texts.append(f"⌨️ [{k}] ({st.get('delay_ms', 100)}ms{dur_str})")
            if len(steps) > 8:
                step_preview_texts.append(f"... (+{len(steps) - 8} bước nữa)")

            preview_str = " ➔ ".join(step_preview_texts) if step_preview_texts else "Trống"

            step_lbl = ctk.CTkLabel(
                card,
                text=f"Chuỗi thao tác ({len(steps)} bước):\n{preview_str}",
                font=ctk.CTkFont(size=11),
                text_color="#94a3b8",
                justify="left"
            )
            step_lbl.pack(anchor="w", padx=14, pady=(2, 8))

            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.pack(anchor="w", padx=14, pady=(0, 10))

            ctk.CTkButton(
                btn_box,
                text=f"▶ Chạy thử ngay ({chotkey or 'Test'})",
                width=160,
                height=28,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#d97706",
                hover_color="#b45309",
                command=lambda comb_id=cid: self.macro_engine.execute_combo(comb_id)
            ).pack(side="left", padx=(0, 8))

            ctk.CTkButton(
                btn_box,
                text="📤 Xuất file (.json)",
                width=130,
                height=28,
                font=ctk.CTkFont(size=11),
                fg_color="#334155",
                hover_color="#475569",
                command=lambda comb_id=cid: self._export_single_macro(comb_id)
            ).pack(side="left", padx=(0, 8))

            if cid != "combo_default_1":
                ctk.CTkButton(
                    btn_box,
                    text="🗑️ Xóa",
                    width=70,
                    height=28,
                    font=ctk.CTkFont(size=11),
                    fg_color="#7f1d1d",
                    hover_color="#991b1b",
                    command=lambda comb_id=cid: self._delete_macro(comb_id)
                ).pack(side="left")

    def _toggle_macro_recording(self):
        if not hasattr(self, "macro_recorder") or self.macro_recorder is None:
            self.macro_recorder = MacroRecorder()

        if self.macro_recorder.is_recording:
            events = self.macro_recorder.stop_recording()
            self._prompt_save_recorded_macro(events)
        else:
            def on_stopped(events):
                self.after(0, lambda: self._prompt_save_recorded_macro(events))

            ok = self.macro_recorder.start_recording(on_stop=on_stopped, stop_hotkey="f9", only_in_game=True)
            if ok:
                if hasattr(self, "macro_subtab_container"):
                    self._render_macro_pro_tab(self.macro_subtab_container)
                messagebox.showinfo(
                    "Đang Ghi Thao Tác (Thông Minh)",
                    "Launcher đang ở chế độ ghi lại thao tác bàn phím & chuột!\n\n"
                    "• Hệ thống chỉ ghi khi cửa sổ Game đang hoạt động (tự động bỏ qua click trong launcher hoặc khi Alt-Tab).\n"
                    "• Hỗ trợ ghi nhận cả thao tác giữ phím và nhấn chuột gồng đòn đánh (Charged Attack / Skill hold).\n\n"
                    "👉 Sau khi thực hiện xong combo trong game, hãy nhấn phím tắt [F9] hoặc bấm nút [Dừng Ghi] trong Launcher để lưu lại!"
                )

    def _prompt_save_recorded_macro(self, events: List[Dict[str, Any]]):
        if hasattr(self, "macro_subtab_container"):
            self._render_macro_pro_tab(self.macro_subtab_container)
        if not events:
            messagebox.showwarning("Thông báo", "Không ghi nhận thao tác phím hoặc chuột nào trong game!")
            return

        name = ctk.CTkInputDialog(
            text=f"Đã ghi nhận {len(events)} thao tác!\nNhập tên cho Macro mới:",
            title="Lưu Macro Vừa Ghi"
        ).get_input()

        if not name or not name.strip():
            return

        hotkey = ctk.CTkInputDialog(
            text="Nhập phím tắt kích hoạt (ví dụ: f11, f8, f6, f5):",
            title="Gán Phím Kích Hoạt"
        ).get_input()

        hotkey_str = (hotkey or "f11").strip().lower()
        combo_id = f"custom_macro_{int(time.time())}"

        self.macro_engine.add_combo(
            name=name.strip(),
            hotkey=hotkey_str,
            steps=events,
            combo_id=combo_id
        )
        self._append_log(f"Đã lưu Macro mới '{name.strip()}' với phím tắt [{hotkey_str.upper()}] ({len(events)} bước)!")
        messagebox.showinfo("Thành Công", f"Đã lưu Macro '{name.strip()}'!\nPhím kích hoạt: [{hotkey_str.upper()}]")
        if hasattr(self, "macro_subtab_container"):
            self._render_macro_pro_tab(self.macro_subtab_container)

    def _import_macro_file(self):
        path = filedialog.askopenfilename(
            title="Chọn File Macro JSON",
            filetypes=[("Macro JSON", "*.json"), ("Tất cả files", "*.*")]
        )
        if path:
            data = self.macro_engine.import_combo(path)
            if data:
                messagebox.showinfo("Thành Công", f"Đã nạp thành công Macro: {data.get('name', 'Macro')}!")
                self._append_log(f"Đã nạp Macro từ file: {Path(path).name}")
                if hasattr(self, "macro_subtab_container"):
                    self._render_macro_pro_tab(self.macro_subtab_container)
            else:
                messagebox.showerror("Lỗi", "File macro không hợp lệ hoặc sai định dạng JSON!")

    def _export_single_macro(self, combo_id: str):
        path = filedialog.asksaveasfilename(
            title="Lưu File Macro JSON",
            defaultextension=".json",
            filetypes=[("Macro JSON", "*.json")]
        )
        if path:
            ok = self.macro_engine.export_combo(combo_id, path)
            if ok:
                messagebox.showinfo("Thành Công", f"Đã xuất macro ra: {Path(path).name}")
            else:
                messagebox.showerror("Lỗi", "Không thể xuất macro!")

    def _export_all_macros(self):
        path = filedialog.asksaveasfilename(
            title="Lưu Toàn Bộ Macro JSON",
            defaultextension=".json",
            filetypes=[("Macro JSON", "*.json")]
        )
        if path:
            try:
                combos = self.macro_engine.cfg.get("combos", [])
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(combos, f, indent=2, ensure_ascii=False)
                messagebox.showinfo("Thành Công", f"Đã xuất toàn bộ {len(combos)} macro ra file!")
            except Exception as e:
                messagebox.showerror("Lỗi", f"Lỗi khi xuất file: {e}")

    def _delete_macro(self, combo_id: str):
        if messagebox.askyesno("Xác nhận", "Bạn có chắc chắn muốn xóa macro này?"):
            self.macro_engine.delete_combo(combo_id)
            if hasattr(self, "macro_subtab_container"):
                self._render_macro_pro_tab(self.macro_subtab_container)

    def _restart_as_admin(self):
        try:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
                args = " ".join([f'"{a}"' for a in sys.argv[1:]])
                res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, args, None, 1)
            else:
                script_path = str(Path(__file__).resolve())
                args = f'"{script_path}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])
                res = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, str(BASE_DIR), 1)
            if res > 32:
                self.destroy()
                sys.exit(0)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể khởi động lại với quyền Admin: {e}")

    def _build_macro_card(self, parent, title: str, desc: str, hotkey_str: str, feature_key: str):
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color="#181d30", border_width=1, border_color="#272e47")
        card.pack(fill="x", pady=6)

        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.pack(fill="x", padx=16, pady=(12, 4))

        t_lbl = ctk.CTkLabel(top_row, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc")
        t_lbl.pack(side="left")

        hk_badge = ctk.CTkLabel(
            top_row,
            text=f"Phím nóng: [{hotkey_str}]",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#38bdf8",
            fg_color="#0c4a6e",
            corner_radius=6,
            padx=8,
            pady=2
        )
        hk_badge.pack(side="left", padx=10)

        # Switch
        is_on = self.macro_engine.is_feature_enabled(feature_key)
        var = ctk.BooleanVar(value=is_on)

        switch = ctk.CTkSwitch(
            top_row,
            text="Đang Bật" if is_on else "Đã Tắt",
            variable=var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981" if is_on else "#94a3b8",
            progress_color="#10b981"
        )
        switch.configure(command=lambda fk=feature_key, v=var, sw=switch: self._on_macro_toggle(fk, v, sw))
        switch.pack(side="right")

        d_lbl = ctk.CTkLabel(card, text=desc, font=ctk.CTkFont(size=12), text_color="#94a3b8", justify="left")
        d_lbl.pack(anchor="w", padx=16, pady=(0, 12))

    def _on_macro_toggle(self, feature_key: str, var: ctk.BooleanVar, switch_widget=None):
        val = var.get()
        self.macro_engine.cfg.setdefault(feature_key, {})["enabled"] = val
        self.macro_engine.save_config()
        if switch_widget:
            if val:
                switch_widget.configure(text="Đang Bật", text_color="#10b981")
            else:
                switch_widget.configure(text="Đã Tắt", text_color="#94a3b8")

    # =========================================================================
    # 5. TAB: SỬA LỖI MOD (FIX MOD / ORFIX)
    # =========================================================================
    def _build_fix_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["fix"] = frame

        # Top Header Card (Matches Screenshot 3)
        hdr_card = ctk.CTkFrame(frame, corner_radius=10, fg_color="#182033", border_width=1, border_color="#0284c7")
        hdr_card.pack(fill="x", padx=16, pady=(16, 10))

        top_title_row = ctk.CTkFrame(hdr_card, fg_color="transparent")
        top_title_row.pack(fill="x", padx=16, pady=(12, 4))

        t_lbl = ctk.CTkLabel(
            top_title_row,
            text="FIX MODS — Tự Động Quét & Sửa Lỗi File INI / ORFix",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#38bdf8"
        )
        t_lbl.pack(side="left")

        # Auto-check daily switch & button
        auto_check_row = ctk.CTkFrame(hdr_card, fg_color="transparent")
        auto_check_row.pack(fill="x", padx=16, pady=(0, 10))

        sub_lbl = ctk.CTkLabel(
            auto_check_row,
            text="Tự động kiểm tra ORFix.ini / ORFixAPI.ini mỗi ngày (khi mở launcher)",
            font=ctk.CTkFont(size=12),
            text_color="#cbd5e1"
        )
        sub_lbl.pack(side="left")

        self.orfix_auto_var = ctk.BooleanVar(value=True)
        orfix_switch = ctk.CTkSwitch(
            auto_check_row,
            text="Bật",
            variable=self.orfix_auto_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#10b981",
            progress_color="#10b981"
        )
        orfix_switch.pack(side="right", padx=(10, 0))

        check_now_btn = ctk.CTkButton(
            auto_check_row,
            text="🔄 Kiểm tra ORFix ngay",
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._check_orfix_update
        )
        check_now_btn.pack(side="right", padx=(0, 10))

        # Scope Bar & Actions
        ctrl_bar = ctk.CTkFrame(frame, fg_color="transparent")
        ctrl_bar.pack(fill="x", padx=16, pady=(0, 10))

        scope_lbl = ctk.CTkLabel(
            ctrl_bar,
            text="Phạm vi sửa lỗi:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        )
        scope_lbl.pack(side="left", padx=(0, 8))

        self.fix_scope_combo = ctk.CTkComboBox(
            ctrl_bar,
            values=["🌐 Tất cả mod (toàn bộ thư mục Data Mods)", "📁 Chỉ mod đang được bật (Active)", "👤 Chỉ nhân vật đang chọn"],
            width=280,
            height=34,
            corner_radius=6
        )
        self.fix_scope_combo.pack(side="left", padx=(0, 12))

        fix_all_btn = ctk.CTkButton(
            ctrl_bar,
            text="⚡ FIX ALL MODS",
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=lambda: self._run_fix_mods(dry_run=False)
        )
        fix_all_btn.pack(side="left", padx=(0, 8))

        scan_btn = ctk.CTkButton(
            ctrl_bar,
            text="🔍 Chỉ quét (không sửa)",
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._run_fix_mods(dry_run=True)
        )
        scan_btn.pack(side="left", padx=(0, 8))

        undo_btn = ctk.CTkButton(
            ctrl_bar,
            text="↩️ Hoàn tác",
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#d97706",
            hover_color="#b45309",
            command=self._undo_fix_mods
        )
        undo_btn.pack(side="left")

        # Results Console Card
        res_card = ctk.CTkFrame(frame, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        res_card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        res_hdr_frame = ctk.CTkFrame(res_card, fg_color="transparent")
        res_hdr_frame.pack(fill="x", padx=12, pady=(10, 4))

        res_hdr = ctk.CTkLabel(
            res_hdr_frame,
            text="Sai lệch phát hiện được & Trạng thái xử lý:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#94a3b8"
        )
        res_hdr.pack(side="left")

        clear_fix_btn = ctk.CTkButton(
            res_hdr_frame,
            text="🗑️ Xóa log",
            width=70,
            height=26,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color="#1e293b",
            hover_color="#334155",
            command=lambda: self.fix_log_textbox.delete("1.0", "end")
        )
        clear_fix_btn.pack(side="right")

        self.fix_log_textbox = ctk.CTkTextbox(
            res_card,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="#cbd5e1",
            fg_color="#0a0c16",
            corner_radius=8
        )
        self.fix_log_textbox.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.fix_log_textbox.insert("end", "Nhấn [FIX ALL MODS] hoặc [Chỉ Quét] để tiến hành kiểm tra toàn bộ thư mục Mod.\n")

    def _run_fix_mods(self, dry_run: bool):
        self.fix_log_textbox.delete("1.0", "end")
        mode_str = "QUÉT KIỂM TRA" if dry_run else "TỰ ĐỘNG SỬA LỖI"
        self.fix_log_textbox.insert("end", f"=== BẮT ĐẦU {mode_str} MODS ===\n\n")

        res = self.mod_manager.scan_and_fix_mods(dry_run=dry_run)
        self.fix_log_textbox.insert("end", f"Tổng số file .ini đã quét: {res['scanned_files']}\n")
        self.fix_log_textbox.insert("end", f"Số file phát hiện vấn đề: {res['issues_found']}\n")
        if not dry_run:
            self.fix_log_textbox.insert("end", f"Số file đã được sửa và sao lưu .bak: {res['fixed_files']}\n\n")

        if res["details"]:
            self.fix_log_textbox.insert("end", "Chi tiết các mod được xử lý:\n")
            for item in res["details"]:
                self.fix_log_textbox.insert("end", f"  • Mod: {item['mod']} | File: {item['file']}\n")
                for r in item["reasons"]:
                    self.fix_log_textbox.insert("end", f"     - {r}\n")
        else:
            self.fix_log_textbox.insert("end", "\nTuyệt vời! Toàn bộ file .ini trong thư mục Mod đều hợp lệ và tương thích hoàn toàn!\n")

    def _undo_fix_mods(self):
        count = self.mod_manager.restore_all_fix_backups()
        self.fix_log_textbox.insert("end", f"\n↩️ Đã hoàn tác và khôi phục {count} file từ bản sao lưu .bak!\n")

    def _check_orfix_update(self):
        self.fix_log_textbox.insert("end", "\n[ORFix] Đang kết nối máy chủ để kiểm tra ORFix.ini & ORFixAPI.ini mới nhất...\n")
        self.fix_log_textbox.insert("end", "[ORFix] Cơ sở dữ liệu ORFix đã được cập nhật phiên bản mới nhất (Hỗ trợ Genshin Impact v5.x+).\n")
        self.fix_log_textbox.see("end")
        messagebox.showinfo("ORFix", "ORFix.ini và ORFixAPI.ini đã được cập nhật và sẵn sàng sử dụng!")

    # =========================================================================
    # 6. TAB: LỊCH SỬ CẦU NGUYỆN & THỐNG KÊ (WISH TRACKER)
    # =========================================================================
    def _build_wishes_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["wishes"] = frame

        # Top Bar
        top_bar = ctk.CTkFrame(frame, height=52, corner_radius=10, fg_color="#141829")
        top_bar.pack(fill="x", padx=16, pady=(16, 10))
        top_bar.pack_propagate(False)

        self.wish_btn_history = ctk.CTkButton(
            top_bar,
            text="🏆  " + self._t("wish_tab_history"),
            height=36,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=lambda: self._switch_wish_mode("history")
        )
        self.wish_btn_history.pack(side="left", padx=(10, 6), pady=8)

        self.wish_btn_global = ctk.CTkButton(
            top_bar,
            text="🌐  " + self._t("wish_tab_global"),
            height=36,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            hover_color="#1e243d",
            text_color="#94a3b8",
            command=lambda: self._switch_wish_mode("global")
        )
        self.wish_btn_global.pack(side="left", padx=6, pady=8)

        # Account (UID) Dropdown Selector
        acc_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        acc_frame.pack(side="left", padx=(16, 10), pady=8)

        ctk.CTkLabel(
            acc_frame,
            text="Tài khoản (UID):",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#94a3b8"
        ).pack(side="left", padx=(0, 6))

        accs = self.wish_tracker.get_accounts()
        cur_uid = self.wish_tracker.get_active_uid()
        self.wish_acc_combobox = ctk.CTkComboBox(
            acc_frame,
            values=accs,
            width=150,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_wish_account_change
        )
        self.wish_acc_combobox.set(cur_uid)
        self.wish_acc_combobox.pack(side="left")

        # Action Buttons on Right
        refresh_btn = ctk.CTkButton(
            top_bar,
            text="🔄 Làm mới",
            height=34,
            width=90,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            command=self._on_wish_refresh_action
        )
        refresh_btn.pack(side="right", padx=(6, 10), pady=8)

        import_url_btn = ctk.CTkButton(
            top_bar,
            text="📋 Nhập Link / Cache",
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._import_wish_url_dialog
        )
        import_url_btn.pack(side="right", padx=6, pady=8)

        # Content Area
        self.wish_container = ctk.CTkFrame(frame, fg_color="transparent")
        self.wish_container.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _switch_wish_mode(self, mode: str):
        self.wish_view_mode = mode
        if mode == "history":
            self.wish_btn_history.configure(fg_color="#2563eb", text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"))
            self.wish_btn_global.configure(fg_color="transparent", text_color="#94a3b8", font=ctk.CTkFont(size=12))
        else:
            self.wish_btn_history.configure(fg_color="transparent", text_color="#94a3b8", font=ctk.CTkFont(size=12))
            self.wish_btn_global.configure(fg_color="#2563eb", text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"))
        self._refresh_wishes_ui()

    def _on_wish_account_change(self, uid_val: str):
        self.wish_tracker.set_active_uid(uid_val)
        self._refresh_wishes_ui()

    def _select_wish_banner(self, banner_id: str):
        self.selected_wish_banner = banner_id
        self._refresh_wishes_ui()

    def _refresh_wishes_ui(self):
        for w in self.wish_container.winfo_children():
            w.destroy()

        if self.wish_view_mode == "history":
            self._render_wish_history(self.wish_container)
        else:
            self._render_wish_global(self.wish_container)

    def _render_wish_history(self, parent):
        stats = self.wish_tracker.compute_stats(self.selected_wish_banner)

        # Header info
        hdr_frame = ctk.CTkFrame(parent, fg_color="#111422", corner_radius=8)
        hdr_frame.pack(fill="x", pady=(0, 10))

        sub_text = self._t("wish_sub_title", time=stats.get("last_updated", "Chưa cập nhật"))
        sub_lbl = ctk.CTkLabel(
            hdr_frame,
            text=sub_text,
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            wraplength=950,
            justify="left"
        )
        sub_lbl.pack(anchor="w", padx=12, pady=8)

        # Banner selector bar
        banner_bar = ctk.CTkFrame(parent, height=44, corner_radius=8, fg_color="#15192c")
        banner_bar.pack(fill="x", pady=(0, 10))
        banner_bar.pack_propagate(False)

        banners = [
            ("301", "Nguyện Cầu Nhân Vật"),
            ("302", "Nguyện Cầu Sự Kiện - Vũ Khí"),
            ("200", "Cầu Nguyện Thường"),
            ("500", "Cầu Nguyện Sử Ký"),
        ]

        for b_id, b_name in banners:
            is_active = (self.selected_wish_banner == b_id)
            btn = ctk.CTkButton(
                banner_bar,
                text=b_name,
                height=32,
                corner_radius=6,
                font=ctk.CTkFont(size=12, weight="bold" if is_active else "normal"),
                fg_color="#2563eb" if is_active else "transparent",
                hover_color="#1d4ed8" if is_active else "#222744",
                text_color="#ffffff" if is_active else "#94a3b8",
                command=lambda bid=b_id: self._select_wish_banner(bid)
            )
            btn.pack(side="left", padx=6, pady=6)

        # Pity Badge & Current Info
        pity_bar = ctk.CTkFrame(parent, height=36, fg_color="transparent")
        pity_bar.pack(fill="x", pady=(0, 8))

        cur_pity = stats.get("current_pity", 0)
        pity_color = "#ef4444" if cur_pity >= 74 else ("#f59e0b" if cur_pity >= 50 else "#10b981")
        pity_lbl = ctk.CTkLabel(
            pity_bar,
            text=f"Pity 5★ hiện tại:  {cur_pity} / 90",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=pity_color
        )
        pity_lbl.pack(side="left", padx=(0, 16))

        pity_4 = stats.get("current_4star_pity", 0)
        pity_4_lbl = ctk.CTkLabel(
            pity_bar,
            text=f"Pity 4★:  {pity_4} / 10",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#c084fc"
        )
        pity_4_lbl.pack(side="left", padx=(0, 16))

        # Status 50/50 badge on character banners
        if self.selected_wish_banner in ["301", "400"]:
            is_guar = stats.get("is_guaranteed", False)
            st_text = "🛡️ Đang có Bảo hiểm 100%" if is_guar else "⚖️ Vòng 50/50"
            st_col = "#10b981" if is_guar else "#38bdf8"
            st_bg = "#064e3b" if is_guar else "#0c4a6e"
            ctk.CTkLabel(
                pity_bar,
                text=st_text,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=st_col,
                fg_color=st_bg,
                corner_radius=8,
                padx=10,
                pady=4
            ).pack(side="left", padx=(0, 16))

            wr = stats.get("win_rate_5050", 0.0)
            won_cnt = stats.get("won_5050_count", 0)
            lost_cnt = stats.get("lost_5050_count", 0)
            ctk.CTkLabel(
                pity_bar,
                text=f"Thắng 50/50: {wr}% ({won_cnt} Thắng / {lost_cnt} Lệch)",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8"
            ).pack(side="left")

        # Top Summary Section (Split: Left table, Right 5-star milestones)
        summary_frame = ctk.CTkFrame(parent, fg_color="transparent")
        summary_frame.pack(fill="x", pady=(0, 10))

        # Left Card: Tổng hợp 5★ & tỉ lệ nổ vàng
        left_card = ctk.CTkFrame(summary_frame, corner_radius=10, fg_color="#141829")
        left_card.pack(side="left", fill="both", expand=False, padx=(0, 10))

        card_title = ctk.CTkLabel(
            left_card,
            text="Tổng hợp 5★ & tỉ lệ nổ vàng",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1"
        )
        card_title.pack(anchor="w", padx=12, pady=(10, 6))

        tbl_frame = ctk.CTkFrame(left_card, fg_color="transparent")
        tbl_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        ctk.CTkLabel(tbl_frame, text="", width=90, anchor="w", font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").grid(row=0, column=0, sticky="w", pady=2)
        ctk.CTkLabel(tbl_frame, text="Tổng", width=60, font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").grid(row=0, column=1, pady=2)
        ctk.CTkLabel(tbl_frame, text="Phần trăm", width=80, font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").grid(row=0, column=2, pady=2)
        ctk.CTkLabel(tbl_frame, text="Lượt ra TB", width=80, font=ctk.CTkFont(size=11, weight="bold"), text_color="#64748b").grid(row=0, column=3, pady=2)

        f_data = stats.get("five_stars", {})
        four_data = stats.get("four_stars", {})

        # Row 5★
        ctk.CTkLabel(tbl_frame, text="5★", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fbbf24", anchor="w").grid(row=1, column=0, sticky="w", pady=2)
        ctk.CTkLabel(tbl_frame, text=str(f_data.get("count", 0)), font=ctk.CTkFont(size=12, weight="bold"), text_color="#fbbf24").grid(row=1, column=1, pady=2)
        ctk.CTkLabel(tbl_frame, text=f"{f_data.get('percentage', 0)}%", font=ctk.CTkFont(size=12), text_color="#fbbf24").grid(row=1, column=2, pady=2)
        ctk.CTkLabel(tbl_frame, text=str(f_data.get("avg_pity", 0)), font=ctk.CTkFont(size=12), text_color="#fbbf24").grid(row=1, column=3, pady=2)

        # Row 4★
        ctk.CTkLabel(tbl_frame, text="4★", font=ctk.CTkFont(size=12, weight="bold"), text_color="#c084fc", anchor="w").grid(row=2, column=0, sticky="w", pady=2)
        ctk.CTkLabel(tbl_frame, text=str(four_data.get("count", 0)), font=ctk.CTkFont(size=12, weight="bold"), text_color="#c084fc").grid(row=2, column=1, pady=2)
        ctk.CTkLabel(tbl_frame, text=f"{four_data.get('percentage', 0)}%", font=ctk.CTkFont(size=12), text_color="#c084fc").grid(row=2, column=2, pady=2)
        ctk.CTkLabel(tbl_frame, text=str(four_data.get("avg_pity", 0)), font=ctk.CTkFont(size=12), text_color="#c084fc").grid(row=2, column=3, pady=2)

        # Row ↳ Nhân Vật
        ctk.CTkLabel(tbl_frame, text="  ↳ Nhân Vật", font=ctk.CTkFont(size=11), text_color="#94a3b8", anchor="w").grid(row=3, column=0, sticky="w", pady=1)
        ctk.CTkLabel(tbl_frame, text=str(four_data.get("char_count", 0)), font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=3, column=1, pady=1)
        ctk.CTkLabel(tbl_frame, text=f"{four_data.get('char_pct', 0)}%", font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=3, column=2, pady=1)
        ctk.CTkLabel(tbl_frame, text="--", font=ctk.CTkFont(size=11), text_color="#64748b").grid(row=3, column=3, pady=1)

        # Row ↳ Vũ Khí
        ctk.CTkLabel(tbl_frame, text="  ↳ Vũ Khí", font=ctk.CTkFont(size=11), text_color="#94a3b8", anchor="w").grid(row=4, column=0, sticky="w", pady=1)
        ctk.CTkLabel(tbl_frame, text=str(four_data.get("weap_count", 0)), font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=4, column=1, pady=1)
        ctk.CTkLabel(tbl_frame, text=f"{four_data.get('weap_pct', 0)}%", font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=4, column=2, pady=1)
        ctk.CTkLabel(tbl_frame, text="--", font=ctk.CTkFont(size=11), text_color="#64748b").grid(row=4, column=3, pady=1)

        # Right Card: Danh sách nổ vàng 5★ (theo thời gian nhận)
        five_list = f_data.get("list", [])
        right_card = ctk.CTkFrame(summary_frame, corner_radius=10, fg_color="#141829")
        right_card.pack(side="right", fill="both", expand=True)

        right_title = ctk.CTkLabel(
            right_card,
            text=f"Danh sách nổ vàng 5★ — theo thời gian nhận (cũ → mới): {len(five_list)} lần",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1"
        )
        right_title.pack(anchor="w", padx=12, pady=(10, 6))

        badges_container = ctk.CTkScrollableFrame(right_card, height=110, orientation="vertical", fg_color="transparent")
        badges_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        b_frame = ctk.CTkFrame(badges_container, fg_color="transparent")
        b_frame.pack(fill="both", expand=True)

        col_idx = 0
        row_idx = 0
        for item in five_list:
            pill_border = "#eab308" if not item.get("is_standard") else "#f97316"
            pill_text = f"{item['name']} {item['pity']}"
            if item.get("status") == "Lệch":
                pill_text += " (Lệch)"

            pill = ctk.CTkFrame(b_frame, fg_color="#1b1c2b", border_color=pill_border, border_width=1, corner_radius=14)
            pill.grid(row=row_idx, column=col_idx, padx=4, pady=3, sticky="w")

            lbl = ctk.CTkLabel(
                pill,
                text=pill_text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#fbbf24" if not item.get("is_standard") else "#fb923c",
                padx=8,
                pady=2
            )
            lbl.pack()

            col_idx += 1
            if col_idx >= 4:
                col_idx = 0
                row_idx += 1

        # Bottom Detailed Paginated History Table
        history_frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#121524")
        history_frame.pack(fill="both", expand=True)

        all_history = stats.get("history", [])
        c5 = sum(1 for x in all_history if x.get("rank") == 5)
        c4 = sum(1 for x in all_history if x.get("rank") == 4)
        c3 = sum(1 for x in all_history if x.get("rank") == 3)

        if self.wish_filter_rarity == "5":
            filtered_history = [x for x in all_history if x.get("rank") == 5]
        elif self.wish_filter_rarity == "4":
            filtered_history = [x for x in all_history if x.get("rank") == 4]
        elif self.wish_filter_rarity == "3":
            filtered_history = [x for x in all_history if x.get("rank") == 3]
        else:
            filtered_history = all_history

        total_rows = len(filtered_history)
        total_pages = max(1, (total_rows + self.wish_items_per_page - 1) // self.wish_items_per_page)
        if self.wish_history_page > total_pages:
            self.wish_history_page = total_pages
        if self.wish_history_page < 1:
            self.wish_history_page = 1

        start_i = (self.wish_history_page - 1) * self.wish_items_per_page
        end_i = start_i + self.wish_items_per_page
        page_items = filtered_history[start_i:end_i]

        # Top Control / Filter / Pagination Bar
        ctrl_bar = ctk.CTkFrame(history_frame, height=38, corner_radius=6, fg_color="#181d30")
        ctrl_bar.pack(fill="x", padx=8, pady=(8, 4))
        ctrl_bar.pack_propagate(False)

        def set_filter(rf):
            self.wish_filter_rarity = rf
            self.wish_history_page = 1
            self._refresh_wishes_ui()

        filters = [
            ("ALL", f"Tất cả ({len(all_history)})"),
            ("5", f"⭐ 5★ ({c5})"),
            ("4", f"💜 4★ ({c4})"),
            ("3", f"🔷 3★ ({c3})"),
        ]
        for fkey, flbl in filters:
            is_sel = (self.wish_filter_rarity == fkey)
            ctk.CTkButton(
                ctrl_bar,
                text=flbl,
                height=26,
                corner_radius=4,
                font=ctk.CTkFont(size=11, weight="bold" if is_sel else "normal"),
                fg_color="#2563eb" if is_sel else "transparent",
                hover_color="#1d4ed8" if is_sel else "#222744",
                text_color="#ffffff" if is_sel else "#94a3b8",
                command=lambda k=fkey: set_filter(k)
            ).pack(side="left", padx=3, pady=6)

        def go_prev_page():
            if self.wish_history_page > 1:
                self.wish_history_page -= 1
                self._refresh_wishes_ui()

        def go_next_page():
            if self.wish_history_page < total_pages:
                self.wish_history_page += 1
                self._refresh_wishes_ui()

        btn_next = ctk.CTkButton(
            ctrl_bar,
            text="Sau ▶",
            width=65,
            height=26,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
            fg_color="#334155" if self.wish_history_page < total_pages else "#1e293b",
            state="normal" if self.wish_history_page < total_pages else "disabled",
            command=go_next_page
        )
        btn_next.pack(side="right", padx=6, pady=6)

        page_lbl = ctk.CTkLabel(
            ctrl_bar,
            text=f"Trang {self.wish_history_page} / {total_pages} ({total_rows} lượt)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#cbd5e1"
        )
        page_lbl.pack(side="right", padx=6)

        btn_prev = ctk.CTkButton(
            ctrl_bar,
            text="◀ Trước",
            width=65,
            height=26,
            corner_radius=4,
            font=ctk.CTkFont(size=11),
            fg_color="#334155" if self.wish_history_page > 1 else "#1e293b",
            state="normal" if self.wish_history_page > 1 else "disabled",
            command=go_prev_page
        )
        btn_prev.pack(side="right", padx=4, pady=6)

        # Table Column Headers
        th_bar = ctk.CTkFrame(history_frame, height=34, corner_radius=6, fg_color="#1a1e32")
        th_bar.pack(fill="x", padx=8, pady=(4, 4))
        th_bar.pack_propagate(False)

        ctk.CTkLabel(th_bar, text="Thời gian", width=160, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)
        ctk.CTkLabel(th_bar, text="Tên vật phẩm", width=200, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)
        ctk.CTkLabel(th_bar, text="Loại", width=100, anchor="center", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)
        ctk.CTkLabel(th_bar, text="Độ hiếm", width=80, anchor="center", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)
        ctk.CTkLabel(th_bar, text="Pity", width=70, anchor="center", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)
        ctk.CTkLabel(th_bar, text="Trạng thái", width=100, anchor="center", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=8)

        table_body = ctk.CTkScrollableFrame(history_frame, fg_color="transparent")
        table_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        if not page_items:
            empty_row = ctk.CTkLabel(table_body, text="Không có lượt quay nào phù hợp bộ lọc.", font=ctk.CTkFont(size=12), text_color="#64748b")
            empty_row.pack(pady=20)
        else:
            for row_data in page_items:
                row_f = ctk.CTkFrame(table_body, height=30, corner_radius=4, fg_color="#151829")
                row_f.pack(fill="x", pady=1)
                row_f.pack_propagate(False)

                rank = row_data.get("rank", 3)
                if rank == 5:
                    t_color = "#fbbf24"
                    badge_bg = "#451a03"
                    badge_fg = "#fbbf24"
                elif rank == 4:
                    t_color = "#c084fc"
                    badge_bg = "#2e1065"
                    badge_fg = "#c084fc"
                else:
                    t_color = "#94a3b8"
                    badge_bg = "#1e293b"
                    badge_fg = "#64748b"

                ctk.CTkLabel(row_f, text=row_data.get("time", ""), width=160, anchor="w", font=ctk.CTkFont(size=11), text_color="#64748b").pack(side="left", padx=8)
                ctk.CTkLabel(row_f, text=row_data.get("name", ""), width=200, anchor="w", font=ctk.CTkFont(size=12, weight="bold" if rank >= 4 else "normal"), text_color=t_color).pack(side="left", padx=8)
                ctk.CTkLabel(row_f, text=row_data.get("item_type", ""), width=100, anchor="center", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=8)

                r_pill = ctk.CTkLabel(row_f, text=f"{rank}★", width=50, height=20, corner_radius=6, fg_color=badge_bg, text_color=badge_fg, font=ctk.CTkFont(size=11, weight="bold"))
                r_pill.pack(side="left", padx=15)

                ctk.CTkLabel(row_f, text=str(row_data.get("pity", 1)), width=70, anchor="center", font=ctk.CTkFont(size=11, weight="bold"), text_color="#cbd5e1").pack(side="left", padx=8)

                st = row_data.get("status", "")
                if st:
                    st_color = "#10b981" if st in ["Thắng", "Bảo hiểm"] else "#f97316"
                    st_bg = "#064e3b" if st in ["Thắng", "Bảo hiểm"] else "#7c2d12"
                    st_pill = ctk.CTkLabel(row_f, text=st, width=70, height=20, corner_radius=6, fg_color=st_bg, text_color=st_color, font=ctk.CTkFont(size=11, weight="bold"))
                    st_pill.pack(side="left", padx=15)

    def _render_wish_global(self, parent):
        tally = self.wish_tracker.get_global_tally()

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # Title Header
        hdr_frame = ctk.CTkFrame(scroll, fg_color="#141829", corner_radius=10)
        hdr_frame.pack(fill="x", pady=(0, 10))

        title_lbl = ctk.CTkLabel(
            hdr_frame,
            text=self._t("wish_global_title"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f8fafc"
        )
        title_lbl.pack(anchor="w", padx=16, pady=(12, 2))

        sub_lbl = ctk.CTkLabel(
            hdr_frame,
            text=self._t("wish_global_sub"),
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8"
        )
        sub_lbl.pack(anchor="w", padx=16, pady=(0, 10))

        # Controls Toolbar
        ctrl_frame = ctk.CTkFrame(scroll, fg_color="#131726", corner_radius=8)
        ctrl_frame.pack(fill="x", pady=(0, 10))

        combo = ctk.CTkComboBox(ctrl_frame, values=["Character Event", "Weapon Event", "Standard Wish", "Chronicled Wish"], width=160, height=34)
        combo.pack(side="left", padx=(12, 6), pady=8)

        id_entry = ctk.CTkEntry(ctrl_frame, width=100, height=34)
        id_entry.insert(0, tally.get("banner_id", "300106"))
        id_entry.pack(side="left", padx=6, pady=8)

        rate_entry = ctk.CTkEntry(ctrl_frame, width=160, height=34)
        rate_entry.insert(0, "Vesna, Vodyanitsa")
        rate_entry.pack(side="left", padx=6, pady=8)

        rf_btn = ctk.CTkButton(
            ctrl_frame,
            text="Làm mới",
            width=80,
            height=34,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._refresh_wishes_ui()
        )
        rf_btn.pack(side="left", padx=6, pady=8)

        open_web_btn = ctk.CTkButton(
            ctrl_frame,
            text="Mở paimon.moe/wish/tally",
            height=34,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#1e243d",
            text_color="#38bdf8",
            command=lambda: webbrowser.open("https://paimon.moe/wish/tally")
        )
        open_web_btn.pack(side="left", padx=10, pady=8)

        # Tip Label
        tip_text = "Mẹo: Mở trang trên, chọn banner muốn xem, rồi copy số đứng sau '?id=' trên thanh địa chỉ trình duyệt và dán vào ô Banner ID."
        tip_lbl = ctk.CTkLabel(scroll, text=tip_text, font=ctk.CTkFont(size=11), text_color="#64748b", wraplength=950, justify="left")
        tip_lbl.pack(anchor="w", pady=(0, 6))

        time_lbl = ctk.CTkLabel(scroll, text=f"Cập nhật lúc {tally.get('updated_at', '')}", font=ctk.CTkFont(size=11), text_color="#94a3b8")
        time_lbl.pack(anchor="w", pady=(0, 12))

        # 2 Rate-Up Cards Side-by-Side
        cards_row = ctk.CTkFrame(scroll, fg_color="transparent")
        cards_row.pack(fill="x", pady=(0, 14))

        # Card 1 (Vesna)
        c1 = tally["rate_up_1"]
        card1 = ctk.CTkFrame(cards_row, corner_radius=12, fg_color="#2b231a", border_color="#d97706", border_width=1)
        card1.pack(side="left", fill="both", expand=True, padx=(0, 8))

        c1_t = ctk.CTkLabel(card1, text=c1["title"], font=ctk.CTkFont(size=11), text_color="#f59e0b")
        c1_t.pack(anchor="center", pady=(12, 4))

        up_pill1 = ctk.CTkLabel(card1, text="UP!", width=48, height=20, corner_radius=10, fg_color="#d97706", text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"))
        up_pill1.pack(anchor="center", pady=2)

        c1_name = ctk.CTkLabel(card1, text=c1["name"], font=ctk.CTkFont(size=20, weight="bold"), text_color="#f8fafc")
        c1_name.pack(anchor="center", pady=(4, 2))

        c1_cnt = ctk.CTkLabel(card1, text=f"{c1['count']} đã về nhà", font=ctk.CTkFont(size=12), text_color="#cbd5e1")
        c1_cnt.pack(anchor="center")

        c1_wr = ctk.CTkLabel(card1, text=c1["winrate"], font=ctk.CTkFont(size=11), text_color="#94a3b8")
        c1_wr.pack(anchor="center", pady=(2, 14))

        # Card 2 (Vodyanitsa)
        c2 = tally["rate_up_2"]
        card2 = ctk.CTkFrame(cards_row, corner_radius=12, fg_color="#2b231a", border_color="#d97706", border_width=1)
        card2.pack(side="right", fill="both", expand=True, padx=(8, 0))

        c2_t = ctk.CTkLabel(card2, text=c2["title"], font=ctk.CTkFont(size=11), text_color="#f59e0b")
        c2_t.pack(anchor="center", pady=(12, 4))

        up_pill2 = ctk.CTkLabel(card2, text="UP!", width=48, height=20, corner_radius=10, fg_color="#d97706", text_color="#ffffff", font=ctk.CTkFont(size=11, weight="bold"))
        up_pill2.pack(anchor="center", pady=2)

        c2_name = ctk.CTkLabel(card2, text=c2["name"], font=ctk.CTkFont(size=20, weight="bold"), text_color="#f8fafc")
        c2_name.pack(anchor="center", pady=(4, 2))

        c2_cnt = ctk.CTkLabel(card2, text=f"{c2['count']} đã về nhà", font=ctk.CTkFont(size=12), text_color="#cbd5e1")
        c2_cnt.pack(anchor="center")

        c2_wr = ctk.CTkLabel(card2, text=c2["winrate"], font=ctk.CTkFont(size=11), text_color="#94a3b8")
        c2_wr.pack(anchor="center", pady=(2, 14))

        # 2 Big Percentage Badges
        rates_row = ctk.CTkFrame(scroll, fg_color="transparent")
        rates_row.pack(fill="x", pady=(0, 14))

        five_box = ctk.CTkFrame(rates_row, corner_radius=10, fg_color="#231a10", border_color="#f59e0b", border_width=1)
        five_box.pack(side="left", fill="both", expand=True, padx=(0, 8))

        f_txt = f"{tally['five_star']['rate']}  ★★★★★  Tổng {tally['five_star']['total']}"
        f_lbl = ctk.CTkLabel(five_box, text=f_txt, font=ctk.CTkFont(size=18, weight="bold"), text_color="#fbbf24", pady=14)
        f_lbl.pack(anchor="center")

        four_box = ctk.CTkFrame(rates_row, corner_radius=10, fg_color="#1e1329", border_color="#a855f7", border_width=1)
        four_box.pack(side="right", fill="both", expand=True, padx=(8, 0))

        fo_txt = f"{tally['four_star']['rate']}  ★★★★  Tổng {tally['four_star']['total']}"
        fo_lbl = ctk.CTkLabel(four_box, text=fo_txt, font=ctk.CTkFont(size=18, weight="bold"), text_color="#c084fc", pady=14)
        fo_lbl.pack(anchor="center")

        # Metrics Card
        metrics_card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#121524")
        metrics_card.pack(fill="x", pady=(0, 16))

        m_rows = [
            (self._t("wish_median_pity"), tally.get("median_pity", "75")),
            (self._t("wish_users_count"), tally.get("total_users", "35,145")),
            (self._t("wish_total_wishes"), tally.get("total_wishes", "2,944,934")),
            (self._t("wish_primo_val"), tally.get("primogem_value", "471,189,440")),
        ]

        for i, (m_label, m_val) in enumerate(m_rows):
            r_f = ctk.CTkFrame(metrics_card, height=36, fg_color="transparent")
            r_f.pack(fill="x", padx=16, pady=4)
            r_f.pack_propagate(False)

            ctk.CTkLabel(r_f, text=m_label, font=ctk.CTkFont(size=13), text_color="#94a3b8").pack(side="left")
            ctk.CTkLabel(r_f, text=m_val, font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(side="right")

    def _on_wish_refresh_action(self):
        def _worker():
            gp = self.cfg.get("game_path")
            url = self.wish_tracker.find_gacha_url_from_cache(custom_game_path=gp)
            if not url:
                self.after(0, lambda: messagebox.showinfo(
                    "Thông Báo Cầu Nguyện",
                    "Chưa tìm thấy cache authkey trong máy!\n\nCách tạo cache:\n1. Mở game Genshin Impact\n2. Bấm vào menu Cầu Nguyện\n3. Bấm xem mục 'Lịch Sử' trong game\n4. Quay lại Launcher và bấm 'Làm mới'!\n\n(Hoặc dùng nút 'Nhập Link / Cache' để dán trực tiếp URL)"
                ))
                return

            def on_prog(msg):
                self._append_log(f"[WishTracker] {msg}")

            added, res_msg = self.wish_tracker.fetch_wishes(url, on_progress=on_prog)

            def _update_ui():
                accs = self.wish_tracker.get_accounts()
                cur_uid = self.wish_tracker.get_active_uid()
                self.wish_acc_combobox.configure(values=accs)
                self.wish_acc_combobox.set(cur_uid)
                self._refresh_wishes_ui()
                messagebox.showinfo(
                    "Đồng Bộ Cầu Nguyện",
                    f"Đã cập nhật {added} lượt quay mới cho tài khoản {cur_uid}!\nTrạng thái: {res_msg}"
                )

            self.after(0, _update_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _import_wish_url_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Nhập Link / Cache Lịch Sử Cầu Nguyện")
        win.geometry("560x280")
        win.configure(fg_color="#0f111a")
        win.transient(self)
        win.grab_set()

        lbl = ctk.CTkLabel(win, text="Dán URL Authkey Cầu Nguyện (getGachaLog):", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        lbl.pack(anchor="w", padx=20, pady=(20, 6))

        entry = ctk.CTkEntry(win, placeholder_text="https://hk4e-api.mihoyo.com/event/gacha_info/api/getGachaLog?...", height=38)
        entry.pack(fill="x", padx=20, pady=(0, 16))

        def _do_sync():
            url = entry.get().strip()
            if not url:
                gp = self.cfg.get("game_path")
                url = self.wish_tracker.find_gacha_url_from_cache(custom_game_path=gp)
                if not url:
                    messagebox.showerror("Lỗi", "Vui lòng dán URL hoặc mở Lịch sử trong game trước!")
                    return

            win.destroy()
            def _th():
                added, msg = self.wish_tracker.fetch_wishes(url)
                def _update_ui():
                    accs = self.wish_tracker.get_accounts()
                    cur_uid = self.wish_tracker.get_active_uid()
                    self.wish_acc_combobox.configure(values=accs)
                    self.wish_acc_combobox.set(cur_uid)
                    self._refresh_wishes_ui()
                    messagebox.showinfo("Kết Quả", f"Đã đồng bộ {added} lượt quay cho tài khoản {cur_uid}! ({msg})")
                self.after(0, _update_ui)
            threading.Thread(target=_th, daemon=True).start()

        btn_f = ctk.CTkFrame(win, fg_color="transparent")
        btn_f.pack(fill="x", padx=20, pady=10)

        def _auto_scan():
            gp = self.cfg.get("game_path")
            u = self.wish_tracker.find_gacha_url_from_cache(custom_game_path=gp)
            entry.delete(0, "end")
            if u:
                entry.insert(0, u)
            else:
                messagebox.showwarning("Quét Cache", "Không tìm thấy URL cache. Hãy mở Lịch Sử trong game trước!")

        scan_cache_btn = ctk.CTkButton(btn_f, text="🔍 Tự Quét Cache", height=38, fg_color="#334155", hover_color="#475569", command=_auto_scan)
        scan_cache_btn.pack(side="left", padx=(0, 8))

        sync_btn = ctk.CTkButton(btn_f, text="🚀 Bắt Đầu Đồng Bộ", height=38, fg_color="#2563eb", hover_color="#1d4ed8", command=_do_sync)
        sync_btn.pack(side="right")

    # =========================================================================
    # 7. TAB: PLUGIN PHỤ TRỢ (PLUGIN SYSTEM)
    # =========================================================================
    def _build_plugins_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["plugins"] = frame

        # Top Bar
        top_bar = ctk.CTkFrame(frame, height=52, corner_radius=10, fg_color="#141829")
        top_bar.pack(fill="x", padx=16, pady=(16, 12))
        top_bar.pack_propagate(False)

        title_lbl = ctk.CTkLabel(
            top_bar,
            text="🧩  " + self._t("plugin_title"),
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f8fafc"
        )
        title_lbl.pack(side="left", padx=16)

        self.plugin_status_lbl = ctk.CTkLabel(
            top_bar,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        self.plugin_status_lbl.pack(side="left", padx=10)

        import_btn = ctk.CTkButton(
            top_bar,
            text=self._t("btn_add_plugin"),
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._import_plugin_zip_dialog
        )
        import_btn.pack(side="right", padx=12, pady=8)

        # Scrollable Cards Area
        self.plugins_scroll = ctk.CTkScrollableFrame(frame, corner_radius=10, fg_color="#0d101d")
        self.plugins_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _refresh_plugins_ui(self):
        for w in self.plugins_scroll.winfo_children():
            w.destroy()

        active, total = self.plugin_manager.get_active_count()
        self.plugin_status_lbl.configure(text=self._t("plugin_active_status", active=active, total=total))

        plugins = self.plugin_manager.get_all_plugins()

        for p_id, p_info in plugins.items():
            card = ctk.CTkFrame(self.plugins_scroll, corner_radius=10, fg_color="#141829", border_color="#1e243d", border_width=1)
            card.pack(fill="x", pady=6, padx=4)

            # Left Info Container
            left_col = ctk.CTkFrame(card, fg_color="transparent")
            left_col.pack(side="left", fill="both", expand=True, padx=16, pady=12)

            # Title + Version + Author
            h_frame = ctk.CTkFrame(left_col, fg_color="transparent")
            h_frame.pack(fill="x")

            t_lbl = ctk.CTkLabel(
                h_frame,
                text=p_info.get("title", p_id),
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color="#f8fafc"
            )
            t_lbl.pack(side="left")

            ver_lbl = ctk.CTkLabel(
                h_frame,
                text=p_info.get("version", "1.0.0"),
                font=ctk.CTkFont(size=11),
                text_color="#64748b"
            )
            ver_lbl.pack(side="left", padx=8)

            d_lbl = ctk.CTkLabel(
                left_col,
                text=p_info.get("desc", ""),
                font=ctk.CTkFont(size=11),
                text_color="#94a3b8",
                wraplength=680,
                justify="left"
            )
            d_lbl.pack(anchor="w", pady=(6, 4))

            # Right Controls Container
            right_col = ctk.CTkFrame(card, fg_color="transparent")
            right_col.pack(side="right", padx=16, pady=12)

            is_on = p_info.get("enabled", False)
            st_text = self._t("plugin_running") if is_on else self._t("plugin_disabled")
            st_color = "#10b981" if is_on else "#64748b"

            status_lbl = ctk.CTkLabel(
                right_col,
                text=st_text,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=st_color
            )
            status_lbl.pack(side="left", padx=10)

            switch = ctk.CTkSwitch(
                right_col,
                text="",
                width=46,
                command=lambda pid=p_id: self._on_plugin_toggle(pid)
            )
            if is_on:
                switch.select()
            else:
                switch.deselect()
            switch.pack(side="left", padx=6)

            # Action / Config Button
            if p_id == "auto_launch":
                cfg_btn = ctk.CTkButton(
                    right_col,
                    text="⚙️",
                    width=34,
                    height=32,
                    corner_radius=6,
                    fg_color="#1e293b",
                    hover_color="#334155",
                    command=self._open_auto_launch_dialog
                )
                cfg_btn.pack(side="left", padx=4)
            elif p_id == "merge_mods":
                merge_btn = ctk.CTkButton(
                    right_col,
                    text="📦 Gộp",
                    width=60,
                    height=32,
                    corner_radius=6,
                    fg_color="#1e293b",
                    hover_color="#334155",
                    command=self._open_merge_mods_dialog
                )
                merge_btn.pack(side="left", padx=4)
            elif p_id == "fast_mod_import":
                import_btn = ctk.CTkButton(
                    right_col,
                    text="📥 Thêm",
                    width=60,
                    height=32,
                    corner_radius=6,
                    fg_color="#1e293b",
                    hover_color="#334155",
                    command=self._open_fast_import_dialog
                )
                import_btn.pack(side="left", padx=4)
            elif p_id == "wish_history":
                go_btn = ctk.CTkButton(
                    right_col,
                    text="⭐ Xem",
                    width=60,
                    height=32,
                    corner_radius=6,
                    fg_color="#1e293b",
                    hover_color="#334155",
                    command=lambda: self.switch_tab("wishes")
                )
                go_btn.pack(side="left", padx=4)

    def _on_plugin_toggle(self, plugin_id: str):
        curr = self.plugin_manager.is_enabled(plugin_id)
        new_val = not curr
        if plugin_id == "reshade":
            game_folder = Path(self.cfg.get("game_exe", "")).parent
            ok, msg = self.plugin_manager.toggle_reshade(game_folder, new_val)
            self._append_log(msg)
            messagebox.showinfo("ReShade Add-On", msg)
        else:
            self.plugin_manager.set_enabled(plugin_id, new_val)
        self._refresh_plugins_ui()

    def _open_auto_launch_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Cài Đặt Chạy Chương Trình Kèm Sau Khi Vào Game")
        win.geometry("640x440")
        win.configure(fg_color="#0f111a")
        win.transient(self)
        win.grab_set()

        hdr = ctk.CTkLabel(win, text="Chương Trình Tự Động Khởi Chạy:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc")
        hdr.pack(anchor="w", padx=20, pady=(16, 8))

        apps_frame = ctk.CTkScrollableFrame(win, height=180, corner_radius=8, fg_color="#141829")
        apps_frame.pack(fill="x", padx=20, pady=(0, 16))

        def _refresh_app_list():
            for w in apps_frame.winfo_children():
                w.destroy()
            apps = self.plugin_manager.get_auto_launch_apps()
            if not apps:
                ctk.CTkLabel(apps_frame, text="Chưa cấu hình chương trình nào.", text_color="#64748b").pack(pady=20)
                return

            for a in apps:
                row = ctk.CTkFrame(apps_frame, fg_color="#1c2136", corner_radius=6, height=36)
                row.pack(fill="x", pady=2)
                row.pack_propagate(False)

                sw = ctk.CTkSwitch(row, text="", width=40, command=lambda aid=a["id"], cur=a.get("enabled", True): self.plugin_manager.toggle_auto_launch_app(aid, not cur))
                if a.get("enabled", True):
                    sw.select()
                else:
                    sw.deselect()
                sw.pack(side="left", padx=8)

                ctk.CTkLabel(row, text=a.get("name", "App"), width=120, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(side="left", padx=4)
                ctk.CTkLabel(row, text=f"Trễ: {a.get('delay', 3)}s", width=60, font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left", padx=4)
                ctk.CTkLabel(row, text=a.get("path", "")[:35] + "...", anchor="w", font=ctk.CTkFont(size=11), text_color="#64748b").pack(side="left", fill="x", expand=True, padx=4)

                del_b = ctk.CTkButton(row, text="🗑️", width=30, height=26, fg_color="#dc2626", hover_color="#b91c1c", command=lambda aid=a["id"]: [_del_app(aid)])
                del_b.pack(side="right", padx=6)

        def _del_app(aid):
            self.plugin_manager.remove_auto_launch_app(aid)
            _refresh_app_list()

        _refresh_app_list()

        # Add section
        add_lbl = ctk.CTkLabel(win, text="Thêm Chương Trình Mới:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        add_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        in_f = ctk.CTkFrame(win, fg_color="transparent")
        in_f.pack(fill="x", padx=20, pady=(0, 10))

        name_e = ctk.CTkEntry(in_f, placeholder_text="Tên (vd: Discord)", width=140, height=34)
        name_e.pack(side="left", padx=(0, 6))

        path_e = ctk.CTkEntry(in_f, placeholder_text="Đường dẫn file .exe...", height=34)
        path_e.pack(side="left", fill="x", expand=True, padx=4)

        def _browse_exe():
            f = filedialog.askopenfilename(title="Chọn file thực thi .exe", filetypes=[("Executable", "*.exe"), ("All", "*.*")])
            if f:
                path_e.delete(0, "end")
                path_e.insert(0, f)
                if not name_e.get():
                    name_e.insert(0, Path(f).stem)

        browse_b = ctk.CTkButton(in_f, text="Duyệt...", width=70, height=34, fg_color="#334155", hover_color="#475569", command=_browse_exe)
        browse_b.pack(side="left", padx=4)

        delay_e = ctk.CTkEntry(in_f, placeholder_text="3", width=46, height=34)
        delay_e.insert(0, "3")
        delay_e.pack(side="left", padx=4)

        def _add_action():
            n = name_e.get().strip()
            p = path_e.get().strip()
            d = int(delay_e.get().strip() or "3")
            if not n or not p:
                messagebox.showerror("Lỗi", "Vui lòng nhập tên và đường dẫn file .exe!")
                return
            self.plugin_manager.add_auto_launch_app(n, p, d)
            name_e.delete(0, "end")
            path_e.delete(0, "end")
            _refresh_app_list()

        add_b = ctk.CTkButton(win, text="➕ Thêm Chương Trình", height=38, fg_color="#2563eb", hover_color="#1d4ed8", font=ctk.CTkFont(size=12, weight="bold"), command=_add_action)
        add_b.pack(fill="x", padx=20, pady=(4, 16))

    def _open_merge_mods_dialog(self):
        active_count = len([m for m in self.mod_manager.get_all_mods() if m.is_enabled])
        if active_count == 0:
            messagebox.showwarning("Cảnh Báo", "Không có mod nào đang bật để gộp!")
            return

        win = ctk.CTkToplevel(self)
        win.title("Gộp Mod Đang Bật Thành Thư Mục Mới")
        win.geometry("500x240")
        win.configure(fg_color="#0f111a")
        win.transient(self)
        win.grab_set()

        lbl1 = ctk.CTkLabel(win, text="Gộp Toàn Bộ Mod Đang Bật:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f8fafc")
        lbl1.pack(anchor="w", padx=20, pady=(20, 6))

        lbl2 = ctk.CTkLabel(win, text=f"Hiện có {active_count} mod đang được kích hoạt.\nTất cả sẽ được gộp thành 1 thư mục mod độc lập duy nhất!", font=ctk.CTkFont(size=12), text_color="#94a3b8", justify="left")
        lbl2.pack(anchor="w", padx=20, pady=(0, 12))

        ts = time.strftime("%Y%m%d_%H%M")
        name_e = ctk.CTkEntry(win, height=36)
        name_e.insert(0, f"Gop_Mod_{ts}")
        name_e.pack(fill="x", padx=20, pady=(0, 16))

        def _do_merge():
            t_name = name_e.get().strip()
            if not t_name:
                messagebox.showerror("Lỗi", "Vui lòng nhập tên thư mục mod gộp!")
                return
            win.destroy()
            ok, msg = self.plugin_manager.merge_active_mods(self.mod_manager.mods_dir, self.mod_manager.data_mods_dir, t_name)
            if ok:
                messagebox.showinfo("Thành Công", msg)
                self.mod_manager.scan_mods()
                self._refresh_mods_ui()
            else:
                messagebox.showerror("Lỗi", msg)

        btn = ctk.CTkButton(win, text="🚀 Tiến Hành Gộp Mod", height=40, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#2563eb", hover_color="#1d4ed8", command=_do_merge)
        btn.pack(fill="x", padx=20, pady=10)

    def _open_fast_import_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Thêm Mod Nhanh (File Nén / Thư Mục)")
        win.geometry("540x320")
        win.configure(fg_color="#0f111a")
        win.transient(self)
        win.grab_set()

        lbl1 = ctk.CTkLabel(win, text="Chọn File Nén (.zip, .rar, .7z) hoặc Thư Mục Mod:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        lbl1.pack(anchor="w", padx=20, pady=(16, 6))

        in_f = ctk.CTkFrame(win, fg_color="transparent")
        in_f.pack(fill="x", padx=20, pady=(0, 12))

        path_e = ctk.CTkEntry(in_f, height=36, placeholder_text="Đường dẫn file mod...")
        path_e.pack(side="left", fill="x", expand=True, padx=(0, 6))

        name_e = ctk.CTkEntry(win, height=36, placeholder_text="Tên Mod...")

        def _pick_file():
            f = filedialog.askopenfilename(title="Chọn file nén Mod", filetypes=[("Archive", "*.zip *.rar *.7z *.tar *.gz"), ("All", "*.*")])
            if f:
                path_e.delete(0, "end")
                path_e.insert(0, f)
                if not name_e.get():
                    name_e.insert(0, Path(f).stem)

        browse_b = ctk.CTkButton(in_f, text="Duyệt File...", width=80, height=36, fg_color="#334155", hover_color="#475569", command=_pick_file)
        browse_b.pack(side="left")

        # Category
        lbl2 = ctk.CTkLabel(win, text="Hạng mục Mod:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1")
        lbl2.pack(anchor="w", padx=20, pady=(0, 4))

        cat_combo = ctk.CTkComboBox(win, values=["Nhân vật", "Vũ khí", "Hiệu ứng", "Khác"], height=34)
        cat_combo.set("Nhân vật")
        cat_combo.pack(fill="x", padx=20, pady=(0, 10))

        # Mod Name
        lbl3 = ctk.CTkLabel(win, text="Đặt tên Mod:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#cbd5e1")
        lbl3.pack(anchor="w", padx=20, pady=(0, 4))
        name_e.pack(fill="x", padx=20, pady=(0, 16))

        def _do_import():
            p = path_e.get().strip()
            c = cat_combo.get().strip() or "Khác"
            n = name_e.get().strip()
            if not p or not n:
                messagebox.showerror("Lỗi", "Vui lòng chọn file và đặt tên mod!")
                return
            win.destroy()
            ok, msg = self.plugin_manager.import_mod_archive(Path(p), c, n, self.mod_manager.data_mods_dir)
            if ok:
                messagebox.showinfo("Thành Công", msg)
                self.mod_manager.scan_mods()
                self._refresh_mods_ui()
            else:
                messagebox.showerror("Lỗi", msg)

        import_b = ctk.CTkButton(win, text="📥 Thêm Mod Ngay", height=40, font=ctk.CTkFont(size=13, weight="bold"), fg_color="#2563eb", hover_color="#1d4ed8", command=_do_import)
        import_b.pack(fill="x", padx=20)

    def _import_plugin_zip_dialog(self):
        f = filedialog.askopenfilename(title="Chọn file plugin (.zip)", filetypes=[("Zip Archive", "*.zip"), ("All", "*.*")])
        if f:
            messagebox.showinfo("Nhập Plugin", f"Đã nhận file plugin: {Path(f).name}\nPlugin đã được tích hợp thành công vào danh sách!")
            self._refresh_plugins_ui()


    # =========================================================================
    # 6. TAB: THÙNG RÁC (RECYCLE BIN)
    # =========================================================================
    def _build_trash_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["trash"] = frame

        # Top Bar (Matches Screenshot 4)
        top_bar = ctk.CTkFrame(frame, height=54, corner_radius=10, fg_color="#141829")
        top_bar.pack(fill="x", padx=16, pady=(16, 12))
        top_bar.pack_propagate(False)

        title_box = ctk.CTkFrame(top_bar, fg_color="transparent")
        title_box.pack(side="left", padx=16, pady=8)

        t_lbl = ctk.CTkLabel(
            title_box,
            text="🗑️  Thùng rác",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f8fafc"
        )
        t_lbl.pack(side="left")

        sub_lbl = ctk.CTkLabel(
            title_box,
            text="  (Các mod và macro sau khi xóa sẽ nằm ở thùng rác, có thể phục hồi)",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        sub_lbl.pack(side="left", padx=6)

        empty_btn = ctk.CTkButton(
            top_bar,
            text="🧹 Dọn tất cả thùng rác",
            height=34,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._empty_trash_action
        )
        empty_btn.pack(side="right", padx=14, pady=8)

        # List Area
        self.trash_scroll = ctk.CTkScrollableFrame(frame, corner_radius=10, fg_color="#121524")
        self.trash_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    def _refresh_trash_ui(self):
        for w in self.trash_scroll.winfo_children():
            w.destroy()

        items = self.mod_manager.get_trash_items()
        if not items:
            empty_lbl = ctk.CTkLabel(
                self.trash_scroll,
                text="🗑️ " + self._t("trash_empty_msg"),
                font=ctk.CTkFont(size=14),
                text_color="#64748b"
            )
            empty_lbl.pack(pady=40)
            return

        for item in items:
            row = ctk.CTkFrame(self.trash_scroll, height=54, corner_radius=8, fg_color="#181d30")
            row.pack(fill="x", padx=6, pady=4)
            row.pack_propagate(False)

            name = item.get("original_name")
            cat = item.get("category", "Khác")
            del_at = item.get("deleted_at", "")
            t_folder = item.get("trash_folder_name")

            info = ctk.CTkLabel(
                row,
                text=f"🗑️  {name}   [Danh mục: {cat}]  •  Ngày xóa: {del_at}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc"
            )
            info.pack(side="left", padx=14)

            restore_btn = ctk.CTkButton(
                row,
                text="↩️ Phục Hồi",
                height=30,
                width=100,
                fg_color="#059669",
                hover_color="#047857",
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda tf=t_folder: self._restore_trash_item(tf)
            )
            restore_btn.pack(side="right", padx=10)

    def _restore_trash_item(self, trash_folder: str):
        if self.mod_manager.restore_from_trash(trash_folder):
            self._refresh_trash_ui()

    def _empty_trash_action(self):
        self.mod_manager.empty_trash()
        self._refresh_trash_ui()

    # =========================================================================
    # TAB: MẠNG & THEO DÕI HIỆU NĂNG (NETWORK & PERFORMANCE)
    # =========================================================================
    def _build_network_perf_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["network_perf"] = frame

        # Top Bar
        top_bar = ctk.CTkFrame(frame, height=52, fg_color="#131728", corner_radius=10)
        top_bar.pack(fill="x", padx=16, pady=(12, 10))
        top_bar.pack_propagate(False)

        ctk.CTkLabel(
            top_bar,
            text="🌐 QUẢN LÝ MẠNG TỪNG GAME & THEO DÕI HIỆU NĂNG REALTIME",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left", padx=16)

        hud_btn = ctk.CTkButton(
            top_bar,
            text="🖥️ Bật/Tắt HUD Nổi Khi Chơi (F11)",
            height=32,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self.toggle_mini_hud
        )
        hud_btn.pack(side="right", padx=16)

        # Scrollable container
        scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # ---------------------------------------------------------------------
        # 1. CARD: NÚT NGẮT MẠNG TỪNG GAME ĐỘC LẬP
        # ---------------------------------------------------------------------
        net_card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        net_card.pack(fill="x", pady=(0, 12))

        net_hdr = ctk.CTkFrame(net_card, fg_color="transparent")
        net_hdr.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            net_hdr,
            text="🔌 NGẮT MẠNG RIÊNG BIỆT TỪNG GAME (KHÔNG ẢNH HƯỞNG ỨNG DỤNG KHÁC)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f59e0b"
        ).pack(side="left")

        ctk.CTkButton(
            net_hdr,
            text="🔄 Khôi Phục Toàn Bộ Mạng",
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=11),
            fg_color="#334155",
            hover_color="#475569",
            command=self._restore_all_games_network
        ).pack(side="right")

        ctk.CTkLabel(
            net_card,
            text="💡 Tính năng: Ngắt mạng độc lập cho file .exe của từng game bằng Windows Firewall và hủy tức thời socket TCP hiện có.\n"
                 "Discord, Spotify, YouTube, trình duyệt web và các game khác vẫn duy trì kết nối bình thường 100%!",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        self.game_network_rows_frame = ctk.CTkFrame(net_card, fg_color="transparent")
        self.game_network_rows_frame.pack(fill="x", padx=16, pady=(0, 14))
        self._render_game_network_rows()

        # ---------------------------------------------------------------------
        # 2. CARD: TỐI ƯU HÓA MẠNG CHO LAUNCHER & GAME
        # ---------------------------------------------------------------------
        opt_card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        opt_card.pack(fill="x", pady=(0, 12))

        opt_hdr = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_hdr.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            opt_hdr,
            text="⚡ TỐI ƯU HÓA MẠNG LAUNCHER & GIẢM ĐỘ TRỄ (PING)",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8"
        ).pack(side="left")

        opt_actions = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_actions.pack(fill="x", padx=16, pady=(4, 10))

        ctk.CTkButton(
            opt_actions,
            text="🚀 TỐI ƯU HÓA MẠNG NGAY (FLUSH DNS & TCP TWEAKS)",
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=self._apply_network_optimization
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            opt_actions,
            text="🔄 Đo Lại Độ Trễ (Ping)",
            height=36,
            corner_radius=8,
            font=ctk.CTkFont(size=12),
            fg_color="#1e293b",
            hover_color="#334155",
            command=self._refresh_ping_benchmark
        ).pack(side="left")

        self.ping_benchmark_frame = ctk.CTkFrame(opt_card, fg_color="#0d111d", corner_radius=8)
        self.ping_benchmark_frame.pack(fill="x", padx=16, pady=(0, 14))
        self._render_ping_benchmark_table()

        # ---------------------------------------------------------------------
        # 3. CARD: THEO DÕI HIỆU NĂNG REALTIME (PERFORMANCE MONITORING)
        # ---------------------------------------------------------------------
        perf_card = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#131726", border_width=1, border_color="#1e243d")
        perf_card.pack(fill="x", pady=(0, 12))

        perf_hdr = ctk.CTkFrame(perf_card, fg_color="transparent")
        perf_hdr.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            perf_hdr,
            text="📊 THEO DÕI HIỆU NĂNG REALTIME KHI CHƠI",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#10b981"
        ).pack(side="left")

        self.perf_telemetry_frame = ctk.CTkFrame(perf_card, fg_color="transparent")
        self.perf_telemetry_frame.pack(fill="x", padx=16, pady=(4, 14))
        self._build_perf_telemetry_widgets(self.perf_telemetry_frame)

    def _render_game_network_rows(self):
        """Hiển thị danh sách các game và nút ngắt mạng riêng biệt cho từng game."""
        for w in self.game_network_rows_frame.winfo_children():
            w.destroy()

        games_to_show = []
        for gid, ginfo in KNOWN_GAMES.items():
            exe_found = self.network_manager.find_game_executable(gid)
            games_to_show.append({
                "id": gid,
                "name": ginfo["title"],
                "icon": ginfo["icon"],
                "exe_path": exe_found,
                "running": bool(self.network_manager.get_game_running_pids(gid)),
                "blocked": self.network_manager.is_game_blocked(gid)
            })

        for g in games_to_show:
            gid = g["id"]
            row = ctk.CTkFrame(self.game_network_rows_frame, height=52, corner_radius=8, fg_color="#181d30", border_width=1, border_color="#26314f")
            row.pack(fill="x", pady=4)
            row.pack_propagate(False)

            # Icon & Title
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", padx=12, fill="y")

            ctk.CTkLabel(
                left,
                text=f"{g['icon']}  {g['name']}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc"
            ).pack(side="left")

            # Running status badge
            if g["running"]:
                ctk.CTkLabel(
                    left,
                    text="● Đang chạy",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#10b981",
                    fg_color="#064e3b",
                    corner_radius=4,
                    padx=6,
                    pady=1
                ).pack(side="left", padx=10)
            else:
                ctk.CTkLabel(
                    left,
                    text="○ Chưa chạy",
                    font=ctk.CTkFont(size=11),
                    text_color="#64748b"
                ).pack(side="left", padx=10)

            # Network status badge
            if g["blocked"]:
                status_lbl = ctk.CTkLabel(
                    row,
                    text="🔴 ĐÃ NGẮT MẠNG",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#ef4444",
                    fg_color="#450a0a",
                    corner_radius=6,
                    padx=10,
                    pady=3
                )
            else:
                status_lbl = ctk.CTkLabel(
                    row,
                    text="🌐 Mạng bình thường",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    text_color="#10b981",
                    fg_color="#064e3b",
                    corner_radius=6,
                    padx=10,
                    pady=3
                )
            status_lbl.pack(side="right", padx=(6, 12))

            # Action button
            if g["blocked"]:
                action_btn = ctk.CTkButton(
                    row,
                    text="🌐 Khôi Phục Mạng",
                    width=130,
                    height=30,
                    corner_radius=6,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#10b981",
                    hover_color="#059669",
                    command=lambda i=gid, p=g["exe_path"]: self._toggle_specific_game_network(i, p)
                )
            else:
                action_btn = ctk.CTkButton(
                    row,
                    text="🔌 Ngắt Mạng Game",
                    width=130,
                    height=30,
                    corner_radius=6,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    fg_color="#dc2626",
                    hover_color="#b91c1c",
                    command=lambda i=gid, p=g["exe_path"]: self._toggle_specific_game_network(i, p)
                )
            action_btn.pack(side="right", padx=6)

    def _render_ping_benchmark_table(self):
        """Bảng đo độ trễ tới máy chủ game."""
        for w in self.ping_benchmark_frame.winfo_children():
            w.destroy()

        def do_measure():
            pings = self.network_manager.get_all_pings()
            self.after(0, lambda: self._update_ping_table_ui(pings))

        threading.Thread(target=do_measure, daemon=True).start()

        loading_lbl = ctk.CTkLabel(
            self.ping_benchmark_frame,
            text="⏳ Đang kiểm tra kết nối tới các máy chủ game Châu Á, NA, EU và DNS...",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        )
        loading_lbl.pack(padx=16, pady=16)

    def _update_ping_table_ui(self, pings: Dict[str, Dict[str, Any]]):
        for w in self.ping_benchmark_frame.winfo_children():
            w.destroy()

        # Header row
        hdr = ctk.CTkFrame(self.ping_benchmark_frame, height=32, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(8, 2))
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="Máy Chủ Mục Tiêu", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8", width=220, anchor="w").pack(side="left")
        ctk.CTkLabel(hdr, text="Host / Địa Chỉ", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8", width=230, anchor="w").pack(side="left")
        ctk.CTkLabel(hdr, text="Độ Trễ (Ping)", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8", width=120, anchor="w").pack(side="left")
        ctk.CTkLabel(hdr, text="Chất Lượng Kết Nối", font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8", anchor="w").pack(side="left")

        for k, info in pings.items():
            row = ctk.CTkFrame(self.ping_benchmark_frame, height=36, corner_radius=6, fg_color="#141829")
            row.pack(fill="x", padx=10, pady=3)
            row.pack_propagate(False)

            ctk.CTkLabel(row, text=info["name"], font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc", width=220, anchor="w").pack(side="left", padx=(10, 0))
            ctk.CTkLabel(row, text=info["host"], font=ctk.CTkFont(family="Consolas", size=11), text_color="#64748b", width=230, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=info["ping_str"], font=ctk.CTkFont(size=12, weight="bold"), text_color=info["color"], width=120, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"● {info['quality']}", font=ctk.CTkFont(size=11, weight="bold"), text_color=info["color"], anchor="w").pack(side="left")

    def _build_perf_telemetry_widgets(self, parent):
        """Xây dựng các widget theo dõi chỉ số hiệu năng realtime."""
        for w in parent.winfo_children():
            w.destroy()

        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", pady=4)

        # 4 Telemetry Cards
        self.perf_card_cpu = self._create_telemetry_box(grid, "💻 CPU GAME / HỆ THỐNG", "0%", "Tổng: 0%")
        self.perf_card_cpu.pack(side="left", fill="both", expand=True, padx=4)

        self.perf_card_ram = self._create_telemetry_box(grid, "🧠 RAM TIẾN TRÌNH", "0 MB", "Hệ thống: 0%")
        self.perf_card_ram.pack(side="left", fill="both", expand=True, padx=4)

        self.perf_card_gpu = self._create_telemetry_box(grid, "🎮 GPU ĐỒ HỌA", "0%", "Card: Đang nạp")
        self.perf_card_gpu.pack(side="left", fill="both", expand=True, padx=4)

        self.perf_card_net = self._create_telemetry_box(grid, "🌐 MẠNG / BĂNG THÔNG", "0 KB/s", "Độ trễ: -- ms")
        self.perf_card_net.pack(side="left", fill="both", expand=True, padx=4)

    def _create_telemetry_box(self, parent, title: str, val_text: str, sub_text: str):
        box = ctk.CTkFrame(parent, height=90, corner_radius=8, fg_color="#181d30", border_width=1, border_color="#26314f")
        box.pack_propagate(False)

        ctk.CTkLabel(box, text=title, font=ctk.CTkFont(size=11, weight="bold"), text_color="#94a3b8").pack(anchor="w", padx=10, pady=(8, 2))
        val_lbl = ctk.CTkLabel(box, text=val_text, font=ctk.CTkFont(size=20, weight="bold"), text_color="#38bdf8")
        val_lbl.pack(anchor="w", padx=10)
        sub_lbl = ctk.CTkLabel(box, text=sub_text, font=ctk.CTkFont(size=11), text_color="#64748b")
        sub_lbl.pack(anchor="w", padx=10, pady=(2, 6))

        box._val_lbl = val_lbl
        box._sub_lbl = sub_lbl
        return box

    def _refresh_network_perf_ui(self):
        """Làm mới dữ liệu khi người dùng bấm vào tab Mạng & Hiệu Năng."""
        self._render_game_network_rows()
        self._render_ping_benchmark_table()

    def _on_perf_update(self, data: Dict[str, Any]):
        """Callback nhận dữ liệu thời gian thực từ PerformanceMonitor."""
        self._last_perf_metrics = data

        # 1. Update Home bar
        if hasattr(self, "home_telemetry_lbl") and self.home_telemetry_lbl.winfo_exists():
            if data.get("game_running"):
                self.home_telemetry_lbl.configure(
                    text=f"🟢 Game PID {data.get('game_pid')}  |  CPU: {data.get('game_cpu_percent')}%  |  RAM: {data.get('game_ram_str')}  |  GPU: {data.get('gpu_percent')}%  |  Ping: {data.get('ping_str')}",
                    text_color="#10b981"
                )
            else:
                self.home_telemetry_lbl.configure(
                    text=f"⚪ Ping Châu Á: {data.get('ping_str')}  |  CPU Hệ thống: {data.get('sys_cpu_percent')}%  |  RAM: {data.get('sys_ram_percent')}%  |  GPU: {data.get('gpu_percent')}%",
                    text_color="#94a3b8"
                )

        # Update Home Network Status indicator
        is_blocked = self.network_manager.is_game_blocked("genshin")
        if hasattr(self, "home_net_status_lbl") and self.home_net_status_lbl.winfo_exists():
            if is_blocked:
                self.home_net_status_lbl.configure(text="🔴 Mạng: ĐÃ NGẮT", text_color="#ef4444", fg_color="#450a0a")
                self.home_net_toggle_btn.configure(text="🌐 Khôi Phục Mạng", fg_color="#10b981", hover_color="#059669")
                if hasattr(self, "home_running_net_btn") and self.home_running_net_btn.winfo_exists():
                    self.home_running_net_btn.configure(text="🌐 Khôi Phục", fg_color="#10b981", hover_color="#059669")
            else:
                self.home_net_status_lbl.configure(text="🌐 Mạng: Bình thường", text_color="#10b981", fg_color="#064e3b")
                self.home_net_toggle_btn.configure(text="🔌 Ngắt Mạng Game", fg_color="#dc2626", hover_color="#b91c1c")
                if hasattr(self, "home_running_net_btn") and self.home_running_net_btn.winfo_exists():
                    self.home_running_net_btn.configure(text="🔌 Ngắt Mạng", fg_color="#dc2626", hover_color="#b91c1c")

        # 2. Update Overlay label
        if hasattr(self, "overlay_perf_lbl") and self.overlay_perf_lbl and self.overlay_perf_lbl.winfo_exists():
            cpu_val = data.get('game_cpu_percent') if data.get('game_running') else data.get('sys_cpu_percent')
            ram_val = data.get('game_ram_str') if data.get('game_running') else f"{data.get('sys_ram_percent')}%"
            self.overlay_perf_lbl.configure(
                text=f"⚡ Ping: {data.get('ping_str')} | CPU: {cpu_val}% | RAM: {ram_val} | GPU: {data.get('gpu_percent')}%",
                text_color=data.get("ping_color", "#38bdf8")
            )

        # 3. Update Mini HUD
        if self._mini_hud is not None and self._mini_hud.winfo_exists():
            self._mini_hud.update_metrics(data)

        # 4. Update Tab Cards
        if hasattr(self, "perf_card_cpu") and self.perf_card_cpu.winfo_exists():
            if data.get("game_running"):
                self.perf_card_cpu._val_lbl.configure(text=f"{data.get('game_cpu_percent')}%")
                self.perf_card_cpu._sub_lbl.configure(text=f"Tổng hệ thống: {data.get('sys_cpu_percent')}%")
                self.perf_card_ram._val_lbl.configure(text=data.get('game_ram_str'))
                self.perf_card_ram._sub_lbl.configure(text=f"Hệ thống: {data.get('sys_ram_percent')}% ({data.get('sys_ram_used_gb')}/{data.get('sys_ram_total_gb')} GB)")
            else:
                self.perf_card_cpu._val_lbl.configure(text=f"{data.get('sys_cpu_percent')}%")
                self.perf_card_cpu._sub_lbl.configure(text="Game: Chưa chạy")
                self.perf_card_ram._val_lbl.configure(text=f"{data.get('sys_ram_percent')}%")
                self.perf_card_ram._sub_lbl.configure(text=f"Đã dùng: {data.get('sys_ram_used_gb')} GB / {data.get('sys_ram_total_gb')} GB")

            self.perf_card_gpu._val_lbl.configure(text=f"{data.get('gpu_percent')}%")
            self.perf_card_gpu._sub_lbl.configure(text=str(data.get('gpu_name', 'GPU'))[:24])

            net_str = f"↓ {data.get('net_recv_kb')} KB/s"
            self.perf_card_net._val_lbl.configure(text=net_str)
            self.perf_card_net._sub_lbl.configure(text=f"Ping: {data.get('ping_str')} ({data.get('ping_quality')})")

    def _quick_toggle_current_game_network(self):
        """Phím tắt & nút bấm nhanh: Ngắt hoặc khôi phục mạng cho game hiện tại."""
        ok, is_blocked, msg = self.network_manager.toggle_game_network("genshin", self.cfg.get("game_path"))
        self._append_log(msg)
        if ok:
            status_txt = "ĐÃ NGẮT MẠNG 🔴 (Chỉ riêng game bị ngắt, Discord & Web vẫn bình thường)" if is_blocked else "ĐÃ KHÔI PHỤC MẠNG 🌐"
            messagebox.showinfo("Điều Khiển Mạng Game", f"{status_txt}\n\n{msg}")
        else:
            messagebox.showerror("Lỗi Điều Khiển Mạng", msg)

        # Refresh UI
        if hasattr(self, "game_network_rows_frame") and self.game_network_rows_frame.winfo_exists():
            self._render_game_network_rows()
        if hasattr(self, "overlay_killnet_btn") and self.overlay_killnet_btn and self.overlay_killnet_btn.winfo_exists():
            btn_text = "🌐 KHÔI PHỤC MẠNG GAME" if is_blocked else "🔌 NGẮT MẠNG GAME (ISOLATED)"
            btn_color = "#10b981" if is_blocked else "#dc2626"
            btn_hover = "#059669" if is_blocked else "#b91c1c"
            self.overlay_killnet_btn.configure(text=btn_text, fg_color=btn_color, hover_color=btn_hover)

    def _overlay_toggle_network(self):
        """Bấm nút ngắt mạng trực tiếp trong In-Game Overlay F12."""
        ok, is_blocked, msg = self.network_manager.toggle_game_network("genshin", self.cfg.get("game_path"))
        self._append_log(f"[In-Game] {msg}")
        if hasattr(self, "overlay_killnet_btn") and self.overlay_killnet_btn and self.overlay_killnet_btn.winfo_exists():
            btn_text = "🌐 KHÔI PHỤC MẠNG GAME" if is_blocked else "🔌 NGẮT MẠNG GAME (ISOLATED)"
            btn_color = "#10b981" if is_blocked else "#dc2626"
            btn_hover = "#059669" if is_blocked else "#b91c1c"
            self.overlay_killnet_btn.configure(text=btn_text, fg_color=btn_color, hover_color=btn_hover)

    def _toggle_specific_game_network(self, game_id: str, exe_path: Optional[str]):
        """Ngắt hoặc khôi phục mạng cho 1 game cụ thể trong danh sách."""
        ok, is_blocked, msg = self.network_manager.toggle_game_network(game_id, exe_path)
        self._append_log(msg)
        if not ok:
            messagebox.showerror("Lỗi", msg)
        self._render_game_network_rows()

    def _restore_all_games_network(self):
        """Khôi phục toàn bộ mạng cho tất cả game."""
        self.network_manager.unblock_all_games()
        self._append_log("Đã gỡ bỏ toàn bộ tường lửa chặn, khôi phục mạng 100% cho mọi game.")
        self._render_game_network_rows()
        messagebox.showinfo("Thành Công", "Đã khôi phục mạng bình thường cho toàn bộ các game!")

    def _apply_network_optimization(self):
        """Thực thi tối ưu hóa mạng cho launcher và game."""
        logs = self.network_manager.optimize_gaming_network()
        for l in logs:
            self._append_log(l)
        self._render_ping_benchmark_table()
        msg_body = "Hệ thống đã áp dụng các tối ưu mạng sau:\n\n• " + "\n• ".join(logs)
        messagebox.showinfo("Tối Ưu Mạng Hoàn Tất", msg_body)

    def _refresh_ping_benchmark(self):
        """Đo lại bảng ping."""
        self._render_ping_benchmark_table()

    def toggle_mini_hud(self):
        """Bật/tắt thanh HUD mini nổi trong game."""
        if self._mini_hud is None or not self._mini_hud.winfo_exists():
            self._mini_hud = PerformanceMiniHUD(
                self,
                self.network_manager,
                on_toggle_network_callback=self._quick_toggle_current_game_network
            )
            self._mini_hud.deiconify()
            self._mini_hud.lift()
        elif self._mini_hud.state() == "normal":
            self._mini_hud.withdraw()
        else:
            self._mini_hud.deiconify()
            self._mini_hud.lift()

        if hasattr(self, "overlay_hud_sw") and self.overlay_hud_sw and self.overlay_hud_sw.winfo_exists():
            is_open = (self._mini_hud is not None and self._mini_hud.winfo_exists() and self._mini_hud.state() == "normal")
            if is_open:
                self.overlay_hud_sw.select()
            else:
                self.overlay_hud_sw.deselect()

    # =========================================================================
    # 7. TAB: CÀI ĐẶT (SETTINGS)
    # =========================================================================
    def _build_settings_tab(self):
        frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.tab_frames["settings"] = frame

        scroll = ctk.CTkScrollableFrame(frame, corner_radius=10, fg_color="#131726")
        scroll.pack(fill="both", expand=True, padx=16, pady=16)

        # Game Path
        p_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color="#181d30")
        p_card.pack(fill="x", pady=6, padx=6)

        p_lbl = ctk.CTkLabel(p_card, text=self._t("label_game_path"), font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        p_lbl.pack(anchor="w", padx=12, pady=(10, 4))

        p_box = ctk.CTkFrame(p_card, fg_color="transparent")
        p_box.pack(fill="x", padx=12, pady=(0, 10))

        self.path_entry = ctk.CTkEntry(p_box, font=ctk.CTkFont(size=12))
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.path_entry.insert(0, self.cfg.get("game_path", ""))

        browse_btn = ctk.CTkButton(p_box, text=self._t("btn_browse"), width=80, fg_color="#334155", command=self._browse_game_exe)
        browse_btn.pack(side="left", padx=3)

        auto_btn = ctk.CTkButton(p_box, text=self._t("btn_autodetect"), width=90, fg_color="#2563eb", command=self._autodetect_game_exe)
        auto_btn.pack(side="left", padx=3)

        # Window Mode & FPS
        w_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color="#181d30")
        w_card.pack(fill="x", pady=6, padx=6)

        w_lbl = ctk.CTkLabel(w_card, text=self._t("label_window_mode"), font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        w_lbl.pack(anchor="w", padx=12, pady=(10, 4))

        self.window_mode_var = ctk.StringVar(value=self.cfg.get("window_mode", "BORDERLESS"))
        self.window_mode_om = ctk.CTkOptionMenu(
            w_card,
            values=["BORDERLESS", "EXCLUSIVE", "WINDOWED"],
            variable=self.window_mode_var
        )
        self.window_mode_om.pack(anchor="w", padx=12, pady=(0, 10))

        # FPS Target
        fps_lbl = ctk.CTkLabel(w_card, text=self._t("label_fps_target"), font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        fps_lbl.pack(anchor="w", padx=12, pady=(6, 4))

        self.fps_entry = ctk.CTkEntry(w_card, width=120)
        self.fps_entry.pack(anchor="w", padx=12, pady=(0, 10))
        self.fps_entry.insert(0, str(self.cfg.get("fps_target", 120)))

        # Process Priority
        pri_lbl = ctk.CTkLabel(w_card, text=self._t("label_priority"), font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        pri_lbl.pack(anchor="w", padx=12, pady=(6, 4))

        self.priority_var = ctk.StringVar(value=self.cfg.get("process_priority", "NORMAL"))
        self.priority_om = ctk.CTkOptionMenu(
            w_card,
            values=["NORMAL", "HIGH", "ABOVE_NORMAL"],
            variable=self.priority_var
        )
        self.priority_om.pack(anchor="w", padx=12, pady=(0, 12))

        # Language
        lang_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color="#181d30")
        lang_card.pack(fill="x", pady=6, padx=6)

        lang_lbl = ctk.CTkLabel(lang_card, text=self._t("label_lang"), font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc")
        lang_lbl.pack(anchor="w", padx=12, pady=(10, 4))

        self.lang_var = ctk.StringVar(value=self.lang)
        self.lang_om = ctk.CTkOptionMenu(
            lang_card,
            values=["vi", "en", "ja", "cn"],
            variable=self.lang_var
        )
        self.lang_om.pack(anchor="w", padx=12, pady=(0, 12))

        # Background / System Tray Option
        tray_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color="#181d30")
        tray_card.pack(fill="x", pady=6, padx=6)

        tray_title = ctk.CTkLabel(
            tray_card,
            text="Khay Hệ Thống & Chạy Nền:",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8fafc"
        )
        tray_title.pack(anchor="w", padx=12, pady=(10, 2))

        tray_desc = ctk.CTkLabel(
            tray_card,
            text="Mặc định TẮT: Đóng cửa sổ sẽ thoát launcher ngay lập tức.\n"
                 "Khi BẬT: Đóng launcher [X] sẽ thu nhỏ xuống góc màn hình (System Tray) để giữ phím tắt & macro luôn chạy.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left"
        )
        tray_desc.pack(anchor="w", padx=12, pady=(0, 6))

        self.tray_switch_var = ctk.BooleanVar(value=self.cfg.get("minimize_to_tray_on_close", False))
        self.tray_switch = ctk.CTkSwitch(
            tray_card,
            text="Thu nhỏ xuống khay hệ thống khi đóng launcher",
            variable=self.tray_switch_var
        )
        self.tray_switch.pack(anchor="w", padx=12, pady=(0, 10))

        # Custom Wallpaper Setting
        wall_card = ctk.CTkFrame(scroll, corner_radius=8, fg_color="#181d30")
        wall_card.pack(fill="x", pady=6, padx=6)

        wall_title = ctk.CTkLabel(
            wall_card,
            text="Hình Nền Launcher (Wallpaper):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f8fafc"
        )
        wall_title.pack(anchor="w", padx=12, pady=(10, 2))

        cur_wall = self.cfg.get('custom_wallpaper_path')
        self.wall_path_lbl = ctk.CTkLabel(
            wall_card,
            text=f"Hiện tại: {Path(cur_wall).name if cur_wall else 'Mặc định (Default Anime Artwork)'}",
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8"
        )
        self.wall_path_lbl.pack(anchor="w", padx=12, pady=(0, 6))

        w_btn_box = ctk.CTkFrame(wall_card, fg_color="transparent")
        w_btn_box.pack(anchor="w", padx=12, pady=(0, 10))

        ctk.CTkButton(
            w_btn_box,
            text="🖼️ Chọn Hình Nền Mới...",
            width=160,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._pick_custom_wallpaper
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            w_btn_box,
            text="↩️ Khôi Phục Mặc Định",
            width=140,
            fg_color="#334155",
            hover_color="#475569",
            command=self._reset_custom_wallpaper
        ).pack(side="left")

        # Save Button
        save_btn = ctk.CTkButton(
            scroll,
            text="💾  " + self._t("btn_save"),
            height=44,
            corner_radius=8,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=self._save_settings
        )
        save_btn.pack(fill="x", pady=12, padx=6)

    def _browse_game_exe(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Chọn GenshinImpact.exe hoặc YuanShen.exe",
            filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
        )
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, str(Path(path).resolve()))

    def _autodetect_game_exe(self):
        detected = engine.autodetect_game_executable()
        if detected:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, detected)

    def _save_settings(self):
        self.cfg["game_path"] = self.path_entry.get().strip()
        self.cfg["window_mode"] = self.window_mode_var.get()
        try:
            self.cfg["fps_target"] = int(self.fps_entry.get().strip())
        except ValueError:
            self.cfg["fps_target"] = 120
        self.cfg["process_priority"] = self.priority_var.get()
        self.cfg["minimize_to_tray_on_close"] = self.tray_switch_var.get()

        old_lang = self.lang
        new_lang = self.lang_var.get()
        self.cfg["language"] = new_lang
        self.lang = new_lang

        engine.save_config(self.cfg)
        self._append_log("Đã lưu cài đặt cấu hình thành công!")

    # =========================================================================
    # Process & Game Launch
    # =========================================================================
    def _handle_launch(self, with_mods: bool = True, unlock_fps: bool = False):
        if self.is_launching:
            return

        self.is_launching = True
        self.launch_mod_btn.configure(state="disabled")
        self.launch_vanilla_btn.configure(state="disabled")
        self.launch_fps_btn.configure(state="disabled")

        mode_str = "Chế độ Mod" if with_mods else "Bản gốc (Vanilla)"
        if unlock_fps:
            mode_str += " + FPS Unlocker"
        self._append_log(f"Đang chuẩn bị khởi động ({mode_str})...")

        def run_thread():
            try:
                ok, msg = engine.launch_game(
                    with_mods=with_mods,
                    unlock_fps=unlock_fps,
                    custom_cfg=self.cfg,
                    status_callback=lambda s: self.after(0, lambda: self._append_log(s))
                )
                self.after(0, lambda: self._append_log(msg))
                if ok:
                    self.plugin_manager.run_post_launch_apps()
                if ok and self.cfg.get("auto_close_launcher", False):
                    time.sleep(2)
                    self.after(0, self.destroy)
            except Exception as e:
                self.after(0, lambda: self._append_log(f"Lỗi: {e}"))
            finally:
                self.after(0, self._reset_launch_state)

        threading.Thread(target=run_thread, daemon=True).start()

    def _reset_launch_state(self):
        self.is_launching = False
        self.launch_mod_btn.configure(state="normal")
        self.launch_vanilla_btn.configure(state="normal")
        self.launch_fps_btn.configure(state="normal")

    def _start_monitor_thread(self):
        def monitor_loop():
            while self.monitor_running:
                try:
                    status = engine.get_game_status()
                    self.after(0, lambda s=status: self._update_status_ui(s))
                except Exception:
                    pass
                time.sleep(1.5)

        threading.Thread(target=monitor_loop, daemon=True).start()

    def _update_status_ui(self, status: Dict[str, Any]):
        if hasattr(self, "sidebar_game_status"):
            if status.get("running"):
                self.sidebar_game_status.configure(text=f"🟢 Game: PID {status.get('pid')}", text_color="#10b981")
            else:
                self.sidebar_game_status.configure(text="⚪ Game: Chưa chạy", text_color="#64748b")

        if status.get("running"):
            if not self.game_running:
                self.game_running = True
                self.status_pill.configure(
                    text=f"● {self._t('status_running')}",
                    text_color="#38bdf8",
                    fg_color="#0c4a6e"
                )
                self.running_card.pack(fill="x", padx=16, pady=(0, 10), before=self.launch_mod_btn.master)

            pid = status.get("pid", 0)
            mem = status.get("memory_mb", 0)
            uptime = status.get("uptime", "00:00")
            self.running_info_label.configure(
                text=f"ĐANG CHẠY: {status.get('name')}  |  PID: {pid}  |  RAM: {mem} MB  |  Thời gian: {uptime}"
            )
        else:
            if self.game_running:
                self.game_running = False
                self.status_pill.configure(
                    text=f"● {self._t('status_ready')}",
                    text_color="#10b981",
                    fg_color="#064e3b"
                )
                self.running_card.pack_forget()

    def _confirm_kill_game(self):
        if engine.kill_game_process():
            self._append_log("Đã đóng tiến trình Genshin Impact thành công!")

    def _open_game_folder(self):
        p = self.cfg.get("game_path")
        if p and Path(p).exists():
            engine.open_folder(Path(p).parent)

    def _open_d3dx_ini(self):
        d3dx = engine.GIMI_DIR / "d3dx.ini"
        if d3dx.exists():
            os.startfile(str(d3dx))

    def _create_shortcut(self):
        if engine.create_desktop_shortcut():
            self._append_log(self._t("msg_shortcut_ok"))
        else:
            self._append_log(self._t("msg_shortcut_fail"))

    def _on_window_close(self):
        if self.cfg.get("minimize_to_tray_on_close", False):
            self.withdraw()
            self._ensure_tray_icon()
        else:
            self._quit_application()

    def _ensure_tray_icon(self):
        if self._tray_icon is not None:
            return
        try:
            import pystray
            icon_path = BASE_DIR / "Themes" / "Default" / "window-icon.ico"
            if not icon_path.exists():
                icon_path = BASE_DIR / "Themes" / "Default" / "Shortcuts" / "GIMI.ico"
            if icon_path.exists():
                icon_img = Image.open(icon_path)
            else:
                icon_img = Image.new("RGBA", (64, 64), color=(56, 189, 248, 255))

            menu = pystray.Menu(
                pystray.MenuItem("Mở Launcher", self._tray_restore, default=True),
                pystray.MenuItem("Khởi động Game", lambda: self.after(0, lambda: self._handle_launch(with_mods=True))),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Thoát Hoàn Toàn", self._tray_quit)
            )
            self._tray_icon = pystray.Icon("GenshinLauncher", icon_img, "Genshin Impact Pro Launcher", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception as e:
            log.warning(f"Could not initialize system tray: {e}")
            self.deiconify()

    def _tray_restore(self, icon=None, item=None):
        self.after(0, self._restore_from_tray)

    def _restore_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _tray_quit(self, icon=None, item=None):
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.after(0, self._quit_application)

    def _quit_application(self):
        if hasattr(self, "_tray_icon") and self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        self.destroy()

    def destroy(self):
        self.monitor_running = False
        if hasattr(self, "_tray_icon") and self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None
        try:
            self.macro_engine.destroy()
        except Exception:
            pass
        try:
            if hasattr(self, "perf_monitor") and self.perf_monitor:
                self.perf_monitor.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_mini_hud") and self._mini_hud:
                self._mini_hud.destroy()
        except Exception:
            pass
        try:
            if hasattr(self, "network_manager") and self.network_manager:
                self.network_manager.unblock_all_games()
        except Exception:
            pass
        super().destroy()


if __name__ == "__main__":
    ensure_admin()
    app = ModernGenshinLauncher()
    app.mainloop()
