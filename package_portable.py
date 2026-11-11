"""
Tạo gói cài đặt Portable cho Genshin Impact Launcher.
Gói này có thể gửi qua máy khác chạy ngay 100% không cần cài Python hay tải thêm gì cả.
"""

import os
import sys
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist" / "GenshinImpactLauncher"
if not DIST_DIR.exists() and (BASE_DIR / "dist_release" / "GenshinImpactLauncher").exists():
    DIST_DIR = BASE_DIR / "dist_release" / "GenshinImpactLauncher"
DESKTOP_DIR = Path(r"C:\Users\Admin\OneDrive\Máy tính")
OUTPUT_ZIP = DESKTOP_DIR / "Genshin_Launcher_Portable.zip"


def create_portable_package():
    print("=" * 60)
    print("ĐANG TẠO GÓI PORTABLE CHO MÁY KHÁC DÙNG NGAY...")
    print("=" * 60)

    if not DIST_DIR.exists():
        print(f"Lỗi: Thư mục {DIST_DIR} không tồn tại. Vui lòng chạy build_launcher.py trước!")
        return

    # 1. Đảm bảo GIMI, Themes nằm ngay cạnh file .exe
    for extra in ["GIMI", "Themes", "Resources"]:
        dst_extra = DIST_DIR / extra
        src_extra = BASE_DIR / extra
        if src_extra.exists() and not dst_extra.exists():
            print(f"Đang sao chép {extra} vào thư mục phát hành...")
            shutil.copytree(src_extra, dst_extra, dirs_exist_ok=True)

    # Đảm bảo CustomTkinter assets (themes, blue.json, fonts) luôn có mặt
    try:
        import customtkinter
        ctk_assets = Path(customtkinter.__file__).resolve().parent / "assets"
        if ctk_assets.exists():
            for sub in [DIST_DIR / "_internal" / "customtkinter" / "assets", DIST_DIR / "customtkinter" / "assets"]:
                shutil.copytree(ctk_assets, sub, dirs_exist_ok=True)
            print("Đã đảm bảo CustomTkinter assets (blue.json) có trong gói Portable!")
    except Exception as e:
        print(f"Lỗi sao chép CustomTkinter assets: {e}")

    # 2. Đảm bảo Data_Mods nằm ngay cạnh file .exe để người dùng chép mod
    data_mods_dist = DIST_DIR / "Data_Mods"
    data_mods_dist.mkdir(parents=True, exist_ok=True)
    
    # Tạo sẵn các danh mục mẫu
    for cat in ["Nhân_Vật", "Vũ_Khí", "Hiệu_Ứng", "Khác"]:
        (data_mods_dist / cat).mkdir(parents=True, exist_ok=True)

    readme_mod = data_mods_dist / "HUONG_DAN_CHEP_MOD.txt"
    with open(readme_mod, "w", encoding="utf-8") as f:
        f.write(
            "=== HƯỚNG DẪN BỎ MOD VÀO ĐÂY ===\n\n"
            "1. Khi bạn tải một Mod nhân vật/vũ khí (file .zip hoặc thư mục):\n"
            "   - Hãy giải nén hoặc chép trực tiếp vào thư mục Data_Mods này (hoặc vào mục Nhân_Vật / Vũ_Khí tương ứng).\n"
            "2. Mở file GenshinImpactLauncher.exe:\n"
            "   - Launcher sẽ tự động quét và hiện toàn bộ Mod lên danh sách.\n"
            "   - Bạn chỉ cần bấm công tắc BẬT mod bạn muốn chơi rồi bấm BẮT ĐẦU GAME!\n"
            "3. Không cần chép đè vào thư mục gốc của game miHoYo, cực kỳ an toàn 100%.\n"
        )

    # 3. Tạo file Hướng dẫn sử dụng cho máy khác
    guide_file = DIST_DIR / "HUONG_DAN_SU_DUNG.txt"
    with open(guide_file, "w", encoding="utf-8") as f:
        f.write(
            "=================================================================\n"
            "       GENSHIN IMPACT PRO LAUNCHER - BẢN PORTABLE CHẠY NGAY      \n"
            "=================================================================\n\n"
            "★ ĐẶC ĐIỂM BẢN PORTABLE:\n"
            "  - KHÔNG CẦN CÀI PYTHON hay bất kỳ phần mềm nào khác.\n"
            "  - TỰ ĐỘNG TÌM GAME: Khi mở lần đầu, launcher sẽ tự quét ổ C, D, E... để tìm Genshin Impact.\n"
            "  - ĐẦY ĐỦ CÔNG CỤ: Quản lý Mod ảo hóa, Mở khóa FPS, Macro Pro Ghi Thao Tác, Nhật Ký Roll, Fix Mod.\n\n"
            "★ CÁCH SỬ DỤNG:\n"
            "  Bước 1: Giải nén file zip này ra bất kỳ đâu (ví dụ: Desktop hoặc ổ D:\\, E:\\).\n"
            "  Bước 2: Chép các thư mục Mod bạn muốn vào thư mục 'Data_Mods'.\n"
            "  Bước 3: Nhấp đúp vào file 'GenshinImpactLauncher.exe' (chọn Yes nếu Windows hỏi quyền Administrator).\n"
            "  Bước 4: Bật Mod bạn thích và bấm nút '▶ BẮT ĐẦU CHƠI (BẬT MOD)' để vào game!\n\n"
            "★ PHÍM TẮT TRONG GAME:\n"
            "  - [F10]: Nạp lại toàn bộ Mod trực tiếp mà không cần khởi động lại game.\n"
            "  - [F12]: Bật/tắt thanh Menu Trong Game.\n"
            "  - [F8] : Bật/tắt tự động tua đối thoại cốt truyện (Auto Story).\n"
            "  - [F7] : Tự động nhặt đồ (Auto Loot).\n"
            "  - [F9] : Tự động kích hoạt bảo bối (Auto Gadget phím Z).\n"
            "  - [F11]: Kích hoạt Macro Combo kỹ năng đội hình.\n"
            "=================================================================\n"
        )

    # 4. Nén toàn bộ thư mục DIST thành file ZIP độc lập
    print(f"Đang nén thành file zip tại: {OUTPUT_ZIP}...")
    if OUTPUT_ZIP.exists():
        OUTPUT_ZIP.unlink()

    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(DIST_DIR):
            for file in files:
                file_path = Path(root) / file
                # Bỏ qua các file log tạm
                if file.endswith((".log", ".tmp")):
                    continue
                rel_path = file_path.relative_to(DIST_DIR)
                arcname = Path("GenshinImpactLauncher") / rel_path
                z.write(file_path, str(arcname))

    zip_size_mb = OUTPUT_ZIP.stat().st_size / (1024 * 1024)
    print("=" * 60)
    print(" HOÀN TẤT ĐÓNG GÓI PORTABLE!")
    print(f"File ZIP thành phẩm: {OUTPUT_ZIP}")
    print(f"Dung lượng: {zip_size_mb:.1f} MB")
    print("=" * 60)
    print("Bạn chỉ cần gửi file .zip này cho máy khác, giải nén ra là chạy ngay!")


if __name__ == "__main__":
    create_portable_package()

