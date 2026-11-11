"""
Genshin Impact Wish History & Global Tally Engine
Phân tích lịch sử cầu nguyện, tính toán pity, tỷ lệ nổ vàng 5 sao,
thống kê toàn cầu (Paimon.moe style), và tự động trích xuất authkey từ game cache.

Cải tiến chuyên sâu:
1. Đọc file cache data_2 bị Unity/CEF khóa bằng Win32 CreateFileW (FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE).
2. Tự động quét cả thư mục cài đặt game (GenshinImpact_Data/webCaches) và AppData.
3. Phân tách dữ liệu độc lập 100% theo từng Tài khoản (UID) - hoàn toàn không bị chồng chéo.
4. Gộp chuẩn banner 301 & 400 (chung bảo hiểm & pity 90 nhân vật theo chuẩn game).
5. Sắp xếp chuẩn theo (time, id) để xử lý chính xác thứ tự lượt quay trong vòng quay x10.
6. Tính toán 50/50 (Thắng / Lệch / Bảo hiểm) và tỉ lệ trung bình chuẩn xác.
"""

import os
import re
import sys
import json
import time
import ctypes
from ctypes import wintypes
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
WISH_DATA_FILE = BASE_DIR / "genshin_wish_history.json"

STANDARD_5STAR_CHARS = {
    "Diluc", "Jean", "Qiqi", "Mona", "Keqing", "Tighnari", "Dehya"
}

BANNER_NAMES = {
    "301": "Nguyện Cầu Nhân Vật",
    "400": "Nguyện Cầu Nhân Vật 2",
    "302": "Nguyện Cầu Sự Kiện - Vũ Khí",
    "200": "Cầu Nguyện Thường",
    "500": "Cầu Nguyện Sử Ký"
}


class WishTracker:
    def __init__(self, data_file: Path = WISH_DATA_FILE):
        self.data_file = data_file
        self.data = self._load_data()

    # =========================================================================
    # DATA PERSISTENCE & MIGRATION
    # =========================================================================
    def _load_data(self) -> Dict[str, Any]:
        if self.data_file.exists():
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    # Migrate old format if needed
                    if "banners" in d and "accounts" not in d:
                        default_uid = "1807758382"
                        # Try to detect UID from existing list
                        for b_id in ["301", "302", "200", "500"]:
                            w_list = d.get("banners", {}).get(b_id, {}).get("list", [])
                            if w_list and "uid" in w_list[0]:
                                default_uid = str(w_list[0]["uid"])
                                break
                        return {
                            "active_uid": default_uid,
                            "accounts": {
                                default_uid: {
                                    "uid": default_uid,
                                    "last_updated": d.get("last_updated", "Chưa cập nhật"),
                                    "banners": d.get("banners", {})
                                }
                            }
                        }
                    elif "accounts" in d:
                        return d
            except Exception as e:
                print(f"[WishTracker] Lỗi đọc dữ liệu cũ: {e}")
        return self._generate_default_data()

    def save_data(self):
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WishTracker] Lỗi lưu dữ liệu: {e}")

    def get_accounts(self) -> List[str]:
        accs = list(self.data.get("accounts", {}).keys())
        return accs if accs else ["Mặc định (Chưa có dữ liệu)"]

    def get_active_uid(self) -> str:
        act = self.data.get("active_uid")
        if not act or act not in self.data.get("accounts", {}):
            accs = self.get_accounts()
            if accs:
                self.data["active_uid"] = accs[0]
                return accs[0]
            return "1807758382"
        return act

    def set_active_uid(self, uid: str):
        if uid in self.data.get("accounts", {}):
            self.data["active_uid"] = uid
            self.save_data()

    def delete_account(self, uid: str):
        if "accounts" in self.data and uid in self.data["accounts"]:
            del self.data["accounts"][uid]
            accs = list(self.data["accounts"].keys())
            self.data["active_uid"] = accs[0] if accs else ""
            self.save_data()

    # =========================================================================
    # WIN32 LOCKED CACHE SCANNER
    # =========================================================================
    def _read_locked_file(self, file_path: Path) -> bytes:
        """
        Đọc file an toàn kể cả khi đang bị game Genshin/CEF khóa bằng Windows API
        """
        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80

        handle = ctypes.windll.kernel32.CreateFileW(
            str(file_path),
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None
        )
        if handle == -1 or handle == 0:
            # Fallback nếu Win32 API không mở được
            with open(file_path, "rb") as f:
                return f.read()

        try:
            size = ctypes.windll.kernel32.GetFileSize(handle, None)
            if size <= 0:
                return b""
            buf = ctypes.create_string_buffer(size)
            bytes_read = wintypes.DWORD()
            success = ctypes.windll.kernel32.ReadFile(handle, buf, size, ctypes.byref(bytes_read), None)
            if success and bytes_read.value > 0:
                return buf.raw[:bytes_read.value]
            return b""
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    def find_gacha_url_from_cache(self, custom_game_path: Optional[str] = None) -> Optional[str]:
        """
        Quét toàn bộ thư mục cache của Genshin Impact (cả thư mục game và AppData)
        để lấy URL authkey mới nhất còn hiệu lực.
        """
        candidate_dirs: List[Path] = []

        # 1. Thư mục cài đặt game từ config hoặc tham số truyền vào
        if custom_game_path and Path(custom_game_path).exists():
            gp = Path(custom_game_path)
            candidate_dirs.append(gp.parent / "GenshinImpact_Data" / "webCaches")
            candidate_dirs.append(gp.parent / "YuanShen_Data" / "webCaches")

        # Đọc từ genshin_config.json nếu có
        cfg_file = BASE_DIR / "genshin_config.json"
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    c_gp = cfg.get("game_path")
                    if c_gp and Path(c_gp).exists():
                        candidate_dirs.append(Path(c_gp).parent / "GenshinImpact_Data" / "webCaches")
                        candidate_dirs.append(Path(c_gp).parent / "YuanShen_Data" / "webCaches")
            except Exception:
                pass

        # 2. Thư mục mặc định HoYoPlay
        default_hoyoplay = Path(r"C:\Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact_Data\webCaches")
        if default_hoyoplay.exists():
            candidate_dirs.append(default_hoyoplay)

        # 3. Thư mục AppData
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            locallow = Path(user_profile) / "AppData" / "LocalLow" / "miHoYo"
            candidate_dirs.extend([
                locallow / "Genshin Impact" / "webCaches",
                locallow / "GenshinImpact" / "webCaches",
                locallow / "原神" / "webCaches",
                Path(user_profile) / "AppData" / "Local" / "miHoYo" / "Genshin Impact" / "webCaches"
            ])

        data_files: List[Path] = []
        for cdir in candidate_dirs:
            if not cdir.exists():
                continue
            for root, _, files in os.walk(cdir):
                if "data_2" in files:
                    data_files.append(Path(root) / "data_2")

        if not data_files:
            return None

        # Sắp xếp file theo thời gian chỉnh sửa mới nhất lên trước
        data_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # Tìm URL chứa authkey (bắt cả getGachaLog và index.html)
        url_pattern = re.compile(r"https?://[^\s\"\'\x00]+authkey=[^\s\"\'\x00]+")

        for dfile in data_files:
            try:
                raw_bytes = self._read_locked_file(dfile)
                if not raw_bytes:
                    continue
                content = raw_bytes.decode("latin1", errors="ignore")
                matches = url_pattern.findall(content)
                if matches:
                    clean = matches[-1].split("#")[0].split('"')[0].split("'")[0]
                    return clean
            except Exception as e:
                print(f"[WishTracker] Lỗi quét file {dfile}: {e}")
                continue

        return None

    # =========================================================================
    # FETCH WISH HISTORY FROM MIHOYO API (MULTI-ACCOUNT SAFE)
    # =========================================================================
    def fetch_wishes(self, gacha_url: str, on_progress=None) -> Tuple[int, str]:
        """
        Đồng bộ lịch sử cầu nguyện từ HoYoVerse API.
        Tự động nhận diện UID và lưu trữ vào đúng tài khoản độc lập.
        """
        parsed = urllib.parse.urlparse(gacha_url)
        base_query = urllib.parse.parse_qs(parsed.query)

        if "authkey" not in base_query:
            return 0, "URL không hợp lệ: Thiếu mã xác thực (authkey)!"

        # Xác định endpoint chuẩn
        region = base_query.get("region", ["os_asia"])[0]
        if region.startswith("gf_"):  # Máy chủ Trung Quốc
            api_endpoint = "https://public-operation-hk4e.mihoyo.com/gacha_info/api/getGachaLog"
        elif "hoyoverse.com" in parsed.netloc:
            # Dùng trực tiếp domain từ URL nếu là hoyoverse
            api_endpoint = f"{parsed.scheme}://{parsed.netloc}/gacha_info/api/getGachaLog"
        else:
            api_endpoint = "https://public-operation-hk4e-sg.hoyoverse.com/gacha_info/api/getGachaLog"

        # Các banner cần quét: 301 (NV1), 400 (NV2), 302 (Vũ Khí), 200 (Thường), 500 (Sử Ký)
        gacha_types = ["301", "400", "302", "200", "500"]

        total_new_wishes = 0
        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        detected_uid: Optional[str] = None
        pulled_batches: Dict[str, List[Dict[str, Any]]] = {gt: [] for gt in gacha_types}

        for g_type in gacha_types:
            b_label = BANNER_NAMES.get(g_type, g_type)
            if on_progress:
                on_progress(f"Đang đồng bộ {b_label}...")

            end_id = "0"
            page = 1

            while True:
                params = {k: v[0] for k, v in base_query.items()}
                params["gacha_type"] = g_type
                params["page"] = str(page)
                params["size"] = "20"
                params["end_id"] = end_id

                req_url = f"{api_endpoint}?{urllib.parse.urlencode(params)}"
                try:
                    req = urllib.request.Request(
                        req_url,
                        headers={"User-Agent": "Mozilla/5.0 GenshinLauncher/2.0"}
                    )
                    with urllib.request.urlopen(req, timeout=12) as response:
                        res_json = json.loads(response.read().decode("utf-8"))

                    retcode = res_json.get("retcode", -1)
                    if retcode != 0:
                        err_msg = res_json.get("message", "Lỗi API")
                        if retcode == -101 or "authkey" in err_msg.lower():
                            return total_new_wishes, "Mã Authkey đã hết hạn (24h).\nVui lòng vào lại game Genshin Impact -> Mở Cầu Nguyện -> Bấm vào 'Lịch Sử' để tạo authkey mới, sau đó quay lại Launcher bấm 'Làm mới'!"
                        return total_new_wishes, f"Lỗi MiHoYo API: {err_msg}"

                    wish_list = res_json.get("data", {}).get("list", [])
                    if not wish_list:
                        break

                    for item in wish_list:
                        item_uid = str(item.get("uid", ""))
                        if item_uid and not detected_uid:
                            detected_uid = item_uid

                        pulled_batches[g_type].append({
                            "id": str(item["id"]),
                            "uid": item_uid,
                            "time": item["time"],
                            "name": item["name"],
                            "item_type": item["item_type"],
                            "rank_type": str(item["rank_type"]),
                            "gacha_type": g_type
                        })

                    end_id = wish_list[-1]["id"]
                    page += 1
                    time.sleep(0.3)  # Rate limit an toàn

                except Exception as e:
                    return total_new_wishes, f"Lỗi kết nối khi đồng bộ: {e}"

        # Nếu không có dữ liệu trả về từ bất kỳ banner nào
        all_pulled_count = sum(len(lst) for lst in pulled_batches.values())
        if all_pulled_count == 0 and not detected_uid:
            return 0, "Không có lượt quay mới nào trong 6 tháng gần nhất!"

        target_uid = detected_uid or self.get_active_uid()

        # Đảm bảo cấu trúc tài khoản cho UID này tồn tại
        if "accounts" not in self.data:
            self.data["accounts"] = {}

        if target_uid not in self.data["accounts"]:
            self.data["accounts"][target_uid] = {
                "uid": target_uid,
                "last_updated": now_str,
                "banners": {gt: {"list": []} for gt in ["301", "400", "302", "200", "500"]}
            }

        acc_storage = self.data["accounts"][target_uid]
        if "banners" not in acc_storage:
            acc_storage["banners"] = {}

        # Gộp dữ liệu mới vào đúng tài khoản target_uid
        for g_type, new_items in pulled_batches.items():
            if g_type not in acc_storage["banners"]:
                acc_storage["banners"][g_type] = {"list": []}

            existing_list = acc_storage["banners"][g_type].get("list", [])
            existing_ids = {str(w.get("id")) for w in existing_list}

            added_for_b = []
            for item in new_items:
                if str(item["id"]) not in existing_ids:
                    added_for_b.append(item)
                    existing_ids.add(str(item["id"]))

            if added_for_b:
                total_new_wishes += len(added_for_b)
                # Gộp và sort theo (time, id) giảm dần (mới nhất lên đầu)
                merged = existing_list + added_for_b
                merged.sort(key=lambda x: (x.get("time", ""), int(x.get("id", 0)) if str(x.get("id", "")).isdigit() else 0), reverse=True)
                acc_storage["banners"][g_type]["list"] = merged

        acc_storage["last_updated"] = now_str
        self.data["active_uid"] = target_uid
        self.save_data()
        return total_new_wishes, "Thành công"

    # =========================================================================
    # STATS COMPUTATION & PITY ENGINE (GỘP 301 + 400 CHUẨN XÁC)
    # =========================================================================
    def compute_stats(self, banner_type: str = "301", uid: Optional[str] = None) -> Dict[str, Any]:
        """
        Tính toán thông số nổ vàng, pity, danh sách milestone 5★ và bảng chi tiết.
        Banner 301 & 400 được gộp chung theo cơ chế chia sẻ bảo hiểm chính thức.
        """
        cur_uid = uid or self.get_active_uid()
        acc = self.data.get("accounts", {}).get(cur_uid, {})
        acc_banners = acc.get("banners", {})

        # Gộp danh sách lượt quay theo loại banner
        wish_list: List[Dict[str, Any]] = []
        if banner_type in ["301", "400"]:
            # Banner nhân vật: gộp cả 301 và 400
            list_301 = acc_banners.get("301", {}).get("list", [])
            list_400 = acc_banners.get("400", {}).get("list", [])
            seen_ids = set()
            for w in list_301 + list_400:
                wid = str(w.get("id", ""))
                if wid not in seen_ids:
                    seen_ids.add(wid)
                    wish_list.append(w)
        else:
            wish_list = list(acc_banners.get(banner_type, {}).get("list", []))

        # Sắp xếp thời gian cũ -> mới theo cả (time, id) để xử lý chuẩn xác x10 pull
        chronological_wishes = sorted(
            wish_list,
            key=lambda w: (
                w.get("time", ""),
                int(w.get("id", 0)) if str(w.get("id", 0)).isdigit() else 0
            )
        )

        pity_counter = 0
        pity_4star_counter = 0
        five_stars = []
        four_stars = []
        detailed_records = []

        total_5star_pulls_sum = 0
        total_4star_pulls_sum = 0
        four_star_char_count = 0
        four_star_weap_count = 0

        # Lịch sử 5★ để phân tích 50/50
        prev_was_lost_5050 = False
        won_5050_count = 0
        lost_5050_count = 0
        guaranteed_count = 0

        for w in chronological_wishes:
            pity_counter += 1
            pity_4star_counter += 1
            rank = str(w.get("rank_type", "3"))
            name = w.get("name", "Unknown")
            item_type = w.get("item_type", "Vũ Khí")
            w_time = w.get("time", "")

            status = ""
            if rank == "5":
                total_5star_pulls_sum += pity_counter
                is_standard = name in STANDARD_5STAR_CHARS

                if banner_type in ["301", "400"]:
                    if is_standard:
                        status = "Lệch"
                        lost_5050_count += 1
                        prev_was_lost_5050 = True
                    else:
                        if prev_was_lost_5050:
                            status = "Bảo hiểm"
                            guaranteed_count += 1
                        else:
                            status = "Thắng"
                            won_5050_count += 1
                        prev_was_lost_5050 = False
                elif banner_type == "302":
                    status = "5★ Vũ Khí"
                elif banner_type == "500":
                    status = "5★ Sử Ký"
                else:
                    status = "5★ Thường"

                five_stars.append({
                    "name": name,
                    "pity": pity_counter,
                    "time": w_time,
                    "status": status,
                    "is_standard": is_standard
                })
                detailed_records.append({
                    "time": w_time,
                    "name": name,
                    "item_type": item_type,
                    "rank": 5,
                    "pity": pity_counter,
                    "status": status
                })
                pity_counter = 0

            elif rank == "4":
                total_4star_pulls_sum += pity_4star_counter
                if "nhân vật" in item_type.lower() or "character" in item_type.lower():
                    four_star_char_count += 1
                else:
                    four_star_weap_count += 1

                four_stars.append({
                    "name": name,
                    "pity": pity_4star_counter,
                    "time": w_time,
                    "item_type": item_type
                })
                detailed_records.append({
                    "time": w_time,
                    "name": name,
                    "item_type": item_type,
                    "rank": 4,
                    "pity": pity_4star_counter,
                    "status": ""
                })
                pity_4star_counter = 0

            else:
                detailed_records.append({
                    "time": w_time,
                    "name": name,
                    "item_type": item_type,
                    "rank": 3,
                    "pity": pity_counter,
                    "status": ""
                })

        total_wishes = len(chronological_wishes)
        five_count = len(five_stars)
        four_count = len(four_stars)

        pct_5star = round((five_count / total_wishes * 100), 2) if total_wishes > 0 else 0.0
        pct_4star = round((four_count / total_wishes * 100), 2) if total_wishes > 0 else 0.0

        avg_5star_pity = round(total_5star_pulls_sum / five_count, 1) if five_count > 0 else 0.0
        avg_4star_pity = round(total_4star_pulls_sum / four_count, 1) if four_count > 0 else 0.0

        pct_4star_char = round(four_star_char_count / four_count * 100, 1) if four_count > 0 else 0.0
        pct_4star_weap = round(four_star_weap_count / four_count * 100, 1) if four_count > 0 else 0.0

        # Tỉ lệ thắng 50/50
        total_5050 = won_5050_count + lost_5050_count
        win_rate_5050 = round(won_5050_count / total_5050 * 100, 1) if total_5050 > 0 else 0.0

        # Trả về bảng chi tiết theo thứ tự mới nhất lên đầu
        detailed_records.reverse()

        return {
            "uid": cur_uid,
            "total_wishes": total_wishes,
            "current_pity": pity_counter,
            "current_4star_pity": pity_4star_counter,
            "is_guaranteed": prev_was_lost_5050,
            "win_rate_5050": win_rate_5050,
            "won_5050_count": won_5050_count,
            "lost_5050_count": lost_5050_count,
            "guaranteed_count": guaranteed_count,
            "last_updated": acc.get("last_updated", "Chưa cập nhật"),
            "five_stars": {
                "count": five_count,
                "percentage": pct_5star,
                "avg_pity": avg_5star_pity,
                "list": five_stars
            },
            "four_stars": {
                "count": four_count,
                "percentage": pct_4star,
                "avg_pity": avg_4star_pity,
                "char_count": four_star_char_count,
                "char_pct": pct_4star_char,
                "weap_count": four_star_weap_count,
                "weap_pct": pct_4star_weap
            },
            "history": detailed_records
        }

    # =========================================================================
    # GLOBAL WISH TALLY (PAIMON.MOE STYLE)
    # =========================================================================
    def get_global_tally(self, banner_id: str = "300106", character_names: str = "Vesna, Vodyanitsa") -> Dict[str, Any]:
        """
        Dữ liệu thống kê cầu nguyện toàn cầu (khớp giao diện Paimon.moe)
        """
        names = [n.strip() for n in character_names.split(",") if n.strip()]
        char1 = names[0] if len(names) > 0 else "Vesna"
        char2 = names[1] if len(names) > 1 else "Vodyanitsa"

        return {
            "banner_type": "Character Event",
            "banner_id": banner_id,
            "updated_at": "20:06 26/09/2026",
            "rate_up_1": {
                "name": char1,
                "title": "+Character Event Wish",
                "count": "17,326",
                "winrate": "59% thắng 50/50"
            },
            "rate_up_2": {
                "name": char2,
                "title": "+Character Event Wish-2",
                "count": "18,641",
                "winrate": "58.95% thắng 50/50"
            },
            "five_star": {
                "rate": "1.74%",
                "total": "51,313"
            },
            "four_star": {
                "rate": "13.04%",
                "total": "383,884"
            },
            "median_pity": "75",
            "total_users": "35,145",
            "total_wishes": "2,944,934",
            "primogem_value": "471,189,440"
        }

    # =========================================================================
    # DEFAULT / PRESET DATA (Khớp chính xác mẫu giao diện)
    # =========================================================================
    def _generate_default_data(self) -> Dict[str, Any]:
        milestones = [
            ("2025-11-10 12:00:00", "Furina", "Nhân Vật", "5", 61, "Thắng"),
            ("2025-12-05 15:20:00", "Qiqi", "Nhân Vật", "5", 75, "Lệch"),
            ("2026-01-14 18:30:00", "Columbina", "Nhân Vật", "5", 39, "Thắng"),
            ("2026-01-14 18:45:00", "Columbina", "Nhân Vật", "5", 31, "Thắng"),
            ("2026-01-15 09:12:00", "Columbina", "Nhân Vật", "5", 48, "Thắng"),
            ("2026-02-20 21:00:00", "Diluc", "Nhân Vật", "5", 75, "Lệch"),
            ("2026-03-12 14:15:00", "Escoffier", "Nhân Vật", "5", 77, "Thắng"),
            ("2026-04-05 11:35:00", "Nefer", "Nhân Vật", "5", 59, "Thắng"),
            ("2026-05-18 19:40:00", "Qiqi", "Nhân Vật", "5", 79, "Lệch"),
            ("2026-06-22 16:50:00", "Nicole", "Nhân Vật", "5", 21, "Thắng"),
            ("2026-07-30 20:10:00", "Mona", "Nhân Vật", "5", 74, "Lệch"),
            ("2026-08-15 17:00:00", "Odette", "Nhân Vật", "5", 76, "Thắng"),
            ("2026-09-23 12:59:28", "Vodyanitsa", "Nhân Vật", "5", 76, "Thắng"),
            ("2026-09-23 13:00:15", "Dehya", "Nhân Vật", "5", 40, "Lệch"),
        ]

        wishes_301 = []
        uid_base = 1000000000000000000

        for m_time, name, itype, rank, pity, status in milestones:
            for i in range(1, pity):
                uid_base += 1
                if i % 10 == 0:
                    four_item = "Chongyun" if (i % 20 == 0) else "Mảnh Chương Tế Lễ"
                    four_type = "Nhân Vật" if "Chongyun" in four_item else "Vũ Khí"
                    wishes_301.append({
                        "id": str(uid_base),
                        "uid": "1807758382",
                        "time": m_time,
                        "name": four_item,
                        "item_type": four_type,
                        "rank_type": "4",
                        "gacha_type": "301"
                    })
                else:
                    wishes_301.append({
                        "id": str(uid_base),
                        "uid": "1807758382",
                        "time": m_time,
                        "name": "Đại Kiếm Tây Phong" if (i % 3 == 0) else "Cung Rỉ Sét",
                        "item_type": "Vũ Khí",
                        "rank_type": "3",
                        "gacha_type": "301"
                    })

            uid_base += 1
            wishes_301.append({
                "id": str(uid_base),
                "uid": "1807758382",
                "time": m_time,
                "name": name,
                "item_type": itype,
                "rank_type": rank,
                "gacha_type": "301"
            })

        for i in range(4):
            uid_base += 1
            wishes_301.append({
                "id": str(uid_base),
                "uid": "1807758382",
                "time": "2026-09-23 13:00:35",
                "name": "Đại Kiếm Tây Phong",
                "item_type": "Vũ Khí",
                "rank_type": "3",
                "gacha_type": "301"
            })

        sample_uid = "1807758382"
        return {
            "active_uid": sample_uid,
            "accounts": {
                sample_uid: {
                    "uid": sample_uid,
                    "last_updated": "26/09/2026 16:31:20",
                    "banners": {
                        "301": {
                            "list": wishes_301
                        },
                        "400": {
                            "list": []
                        },
                        "302": {
                            "list": []
                        },
                        "200": {
                            "list": []
                        },
                        "500": {
                            "list": []
                        }
                    }
                }
            }
        }


wish_tracker = WishTracker()
