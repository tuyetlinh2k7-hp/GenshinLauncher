# 🌸 Genshin Impact Launcher - Advanced Edition

[![GitHub License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%20%2F%203.11%20%2F%203.12-yellow.svg)](https://www.python.org/)
[![UI Framework](https://img.shields.io/badge/UI-CustomTkinter-blueviolet.svg)](https://github.com/TomSchimansky/CustomTkinter)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)]()

> A modern, feature-packed launcher and mod manager for **Genshin Impact**, built with Python & CustomTkinter. Features instant NTFS Junction mod toggling, character/waifu mod filters, wish tracking analytics, automation macros, performance monitoring, and seamless GIMI integration.

---

## 🌟 Key Features (Tính Năng Nổi Bật)

### 1. 🚀 Game Launch & Live Process Monitor
- **Smart Game Detection**: Automatically locates game executable via Windows Registry or custom path.
- **Multiple Launch Modes**: Launch with GIMI 3DMigoto mod injector or pure Vanilla mode.
- **Advanced Launch Options**: Borderless Windowed mode, custom resolution, High Process Priority, and FPS configuration.
- **Real-Time Monitoring**: Tracks game lifecycle, CPU/RAM usage, and active mod status.

### 2. 🎭 Instant Mod Manager (NTFS Junction Links)
- **Zero-Copy Instant Toggle**: Uses Windows NTFS Junction Links to activate/deactivate mods instantly without copying gigabytes of files or wearing SSDs.
- **Waifu & Character Filter**: Browse and organize mods by character tags (Raiden Shogun, Hu Tao, Furina, etc.), weapon, UI, and environment.
- **Visual Mod Cards**: Clean card UI featuring mod preview thumbnails, author credits, and status toggles.
- **Mod Groups & Presets**: Save your favorite mod combinations into presets and switch entire setups with a single click.
- **Mod Auto-Fixer**: Built-in ORFix and `.ini` syntax validator to auto-repair incompatible mods.
- **Soft-Delete Recycle Bin**: Safely delete mods to an in-app trash folder with instant restore capability.

### 3. 🤖 Automation Macros (Hệ Thống Macro)
- **Auto Dialogue / Story**: Automatically progresses through long conversations and dialogue choices.
- **Auto Loot / Rapid F**: Fast item pickup and chest opening without key spamming.
- **Auto Gadget (Z)**: Quick-trigger utility gadget.
- **Custom Combo Recorder**: Record, edit, and play custom key sequences.

### 4. 🌠 Wish Tracker & Analytics (Thống Kê Gacha)
- **Auto-Fetch Wish History**: Extracts wish logs directly from the game's official web cache URL.
- **Pity Counter**: Accurate pity calculation for Character, Weapon, and Standard banners.
- **Gacha Statistics**: Visual distribution charts, 5-star luck percentage, and guarantee indicators.

### 5. 📊 Mini Performance HUD
- Lightweight on-screen overlay monitoring real-time FPS, CPU, GPU, and RAM usage while playing.

### 6. 🌐 Network & Multi-Language
- Built-in proxy configuration and game server ping monitor.
- Full localization support: **English**, **Tiếng Việt**, and extensible language files (`Locale/`).

---

## 🖥️ System Requirements (Yêu Cầu Hệ Thống)

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **OS** | Windows 10 (64-bit) | Windows 10 / 11 (64-bit) |
| **Python** | Python 3.10 | Python 3.11 or 3.12 |
| **Filesystem** | NTFS (Required for Junction Links) | NTFS on SSD |

---

## 💻 Installation & Running (Cài Đặt & Chạy)

### Option 1: Run from Source (Khuyên dùng cho Nhà phát triển)

```bash
# 1. Clone repository
git clone https://github.com/tuyetlinh2k7-hp/GenshinLauncher.git
cd GenshinLauncher

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the application
python genshin_launcher.py
# (Hoặc nhấp đúp vào file Run_Genshin_Launcher.bat)
```

### Option 2: Build Executable (.exe)

To build a standalone `.exe` using PyInstaller:

```bash
# Run the build script
python build_launcher.py
# (Hoặc nhấp đúp vào file build_exe.bat)
```

The output executable will be created in `dist/GenshinImpactLauncher/GenshinImpactLauncher.exe`.

---

## 📁 Project Structure (Cấu Trúc Thư Mục)

```
GenshinLauncher/
├── genshin_launcher.py      # Main GUI application entry point
├── genshin_engine.py        # Process monitor & game execution engine
├── genshin_mod_manager.py   # NTFS Junction mod management & card handling
├── genshin_macro.py         # Automation macros & key hooks
├── genshin_wishes.py        # Wish tracker & pity analytics
├── genshin_perf.py          # Performance HUD & hardware metrics
├── genshin_locales.py       # Multi-language translation engine
├── genshin_network.py       # Network & proxy manager
├── genshin_plugins.py       # Plugin architecture
├── build_launcher.py        # PyInstaller build pipeline
├── package_portable.py      # Portable zip packager
├── requirements.txt         # Python package dependencies
├── GIMI/                    # 3DMigoto GIMI core loader & shaders
├── Data_Mods/               # Storage directory for unlinked mods
├── Themes/                  # CustomTkinter theme assets & CSS
├── Resources/               # Application icons & visual media
├── Locale/                  # Language JSON/YAML localization files
├── src/                     # Modular backend packages
└── .github/workflows/       # GitHub Actions CI/CD auto-build
```

---

## 👥 Authors & Acknowledgments

- **Lead Developer**: Tuyết Linh ([@tuyetlinh2k7-hp](https://github.com/tuyetlinh2k7-hp))
- **Base Architecture**: Based on the XXMI / 3DMigoto GIMI modding ecosystem.
- **License**: Released under the [GNU General Public License v3.0 (GPL-3.0)](LICENSE).
