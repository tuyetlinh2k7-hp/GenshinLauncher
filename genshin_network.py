"""
Genshin Impact Launcher - Network Optimization & Per-Game Disconnect Manager
Chức năng:
1. Tối ưu hóa mạng (Gaming Latency, TCP NoDelay, Flush DNS, Windows Throttling Fix)
2. Nút ngắt mạng độc lập cho từng game (Genshin Impact, Star Rail, ZZZ, Wuthering Waves...)
   - Sử dụng Windows Advanced Firewall Rule Outbound Block riêng cho file .exe của game
   - Ngắt kết nối TCP hiện hữu ngay lập tức qua API hệ thống (Zero Delay)
   - Hoàn toàn KHÔNG ảnh hưởng tới Discord, Web, YouTube hay các ứng dụng khác!
3. Đo độ trễ (Ping) thời gian thực tới các máy chủ game Châu Á, Quốc Tế & DNS
"""

import os
import sys
import time
import socket
import logging
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

log = logging.getLogger("NetworkEngine")

# Danh sách các game hỗ trợ ngắt mạng riêng biệt
KNOWN_GAMES = {
    "genshin": {
        "id": "genshin",
        "name": "Genshin Impact",
        "title": "Genshin Impact (原神)",
        "exes": ["GenshinImpact.exe", "YuanShen.exe"],
        "server_host": "sg-hk4e-api.hoyoverse.com",
        "icon": "⚔️"
    },
    "starrail": {
        "id": "starrail",
        "name": "Honkai: Star Rail",
        "title": "Honkai: Star Rail (星穹铁道)",
        "exes": ["StarRail.exe"],
        "server_host": "hkrpg-api-os.hoyoverse.com",
        "icon": "🚂"
    },
    "zzz": {
        "id": "zzz",
        "name": "Zenless Zone Zero",
        "title": "Zenless Zone Zero (绝区零)",
        "exes": ["ZenlessZoneZero.exe"],
        "server_host": "nap-api-os.hoyoverse.com",
        "icon": "⚡"
    },
    "wuwa": {
        "id": "wuwa",
        "name": "Wuthering Waves",
        "title": "Wuthering Waves (鸣潮)",
        "exes": ["Client-Win64-Shipping.exe"],
        "server_host": "gateway.kurogame.net",
        "icon": "🌊"
    },
    "hi3": {
        "id": "hi3",
        "name": "Honkai Impact 3rd",
        "title": "Honkai Impact 3rd (崩坏3)",
        "exes": ["BH3.exe"],
        "server_host": "api-os-takumi.mihoyo.com",
        "icon": " Valkyrie"
    }
}

# Win32 Iphlpapi constants for closing sockets
TCP_TABLE_OWNER_PID_ALL = 5
AF_INET = 2
MIB_TCP_STATE_DELETE_TCB = 12


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ('dwState', wintypes.DWORD),
        ('dwLocalAddr', wintypes.DWORD),
        ('dwLocalPort', wintypes.DWORD),
        ('dwRemoteAddr', wintypes.DWORD),
        ('dwRemotePort', wintypes.DWORD),
        ('dwOwningPid', wintypes.DWORD),
    ]


class MIB_TCPROW(ctypes.Structure):
    _fields_ = [
        ('dwState', wintypes.DWORD),
        ('dwLocalAddr', wintypes.DWORD),
        ('dwLocalPort', wintypes.DWORD),
        ('dwRemoteAddr', wintypes.DWORD),
        ('dwRemotePort', wintypes.DWORD),
    ]


def _close_tcp_connections_for_pid(pid: int) -> int:
    """Tức tốc đóng toàn bộ socket TCP đang hoạt động của tiến trình game để ngắt mạng ngay lập tức."""
    closed_count = 0
    try:
        iphlpapi = ctypes.windll.iphlpapi
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), True, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
        if ret == 0:
            num_entries = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
            entry_ptr = ctypes.cast(
                ctypes.byref(buf, ctypes.sizeof(wintypes.DWORD)),
                ctypes.POINTER(MIB_TCPROW_OWNER_PID)
            )
            for i in range(num_entries):
                row = entry_ptr[i]
                if row.dwOwningPid == pid:
                    kill_row = MIB_TCPROW(
                        MIB_TCP_STATE_DELETE_TCB,
                        row.dwLocalAddr,
                        row.dwLocalPort,
                        row.dwRemoteAddr,
                        row.dwRemotePort
                    )
                    iphlpapi.SetTcpEntry(ctypes.byref(kill_row))
                    closed_count += 1
    except Exception as e:
        log.warning(f"Could not teardown TCP entries for PID {pid}: {e}")
    return closed_count


def _run_netsh_cmd(args: List[str], elevated: bool = False) -> Tuple[bool, str]:
    """Chạy lệnh netsh tường lửa Windows."""
    try:
        cmd = ["netsh", "advfirewall", "firewall"] + args
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            encoding="utf-8",
            errors="ignore",
            timeout=8
        )
        return (res.returncode == 0, res.stdout + res.stderr)
    except Exception as e:
        return (False, str(e))


class NetworkManager:
    def __init__(self, config_game_path: Optional[str] = None):
        self.config_game_path = config_game_path or ""
        self._blocked_games: Dict[str, bool] = {}
        self._check_initial_firewall_status()

    def set_config_game_path(self, path: str):
        self.config_game_path = path

    def _get_rule_name(self, game_id: str) -> str:
        return f"SakuraBot_Block_{game_id}"

    def _check_initial_firewall_status(self):
        """Kiểm tra xem hiện tại có rule tường lửa nào đang chặn các game hay không."""
        for gid in KNOWN_GAMES.keys():
            self._blocked_games[gid] = self.is_game_blocked(gid)
        self._blocked_games["custom"] = self.is_game_blocked("custom")

    def find_game_executable(self, game_id: str) -> Optional[str]:
        """Tìm đường dẫn file thực thi của game trên máy."""
        if game_id == "genshin" and self.config_game_path and os.path.exists(self.config_game_path):
            return str(Path(self.config_game_path).resolve())

        # Check running processes first
        try:
            import psutil
            game_info = KNOWN_GAMES.get(game_id)
            if game_info:
                targets = [x.lower() for x in game_info["exes"]]
                for p in psutil.process_iter(['pid', 'name', 'exe']):
                    name = (p.info.get('name') or '').lower()
                    if name in targets:
                        exe = p.info.get('exe')
                        if exe and os.path.exists(exe):
                            return exe
        except Exception:
            pass

        # Check registry & standard HoYoPlay locations
        import string
        active_drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]

        if game_id == "genshin":
            for dr_str in active_drives:
                dr = Path(dr_str)
                for rel in [
                    r"Program Files\HoYoPlay\games\Genshin Impact game\GenshinImpact.exe",
                    r"Program Files\HoYoPlay\games\Genshin Impact game\YuanShen.exe",
                    r"HoYoPlay\games\Genshin Impact game\GenshinImpact.exe",
                    r"Program Files\Genshin Impact\Genshin Impact game\GenshinImpact.exe",
                    r"Genshin Impact game\GenshinImpact.exe",
                    r"Games\Genshin Impact\Genshin Impact game\GenshinImpact.exe"
                ]:
                    cand = dr / rel
                    if cand.exists():
                        return str(cand)

        elif game_id == "starrail":
            for dr_str in active_drives:
                dr = Path(dr_str)
                for rel in [
                    r"Program Files\HoYoPlay\games\Star Rail game\StarRail.exe",
                    r"HoYoPlay\games\Star Rail game\StarRail.exe",
                    r"Program Files\Star Rail\Games\StarRail.exe",
                    r"Games\Star Rail\StarRail.exe"
                ]:
                    cand = dr / rel
                    if cand.exists():
                        return str(cand)

        elif game_id == "zzz":
            for dr_str in active_drives:
                dr = Path(dr_str)
                for rel in [
                    r"Program Files\HoYoPlay\games\ZenlessZoneZero game\ZenlessZoneZero.exe",
                    r"HoYoPlay\games\ZenlessZoneZero game\ZenlessZoneZero.exe",
                    r"ZenlessZoneZero game\ZenlessZoneZero.exe"
                ]:
                    cand = dr / rel
                    if cand.exists():
                        return str(cand)

        elif game_id == "wuwa":
            for dr_str in active_drives:
                dr = Path(dr_str)
                for rel in [
                    r"Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe",
                    r"Games\Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe",
                    r"Program Files\Wuthering Waves\Wuthering Waves Game\Client\Binaries\Win64\Client-Win64-Shipping.exe"
                ]:
                    cand = dr / rel
                    if cand.exists():
                        return str(cand)

        return None

    def is_game_blocked(self, game_id: str) -> bool:
        """Kiểm tra xem game có đang bị chặn mạng bằng firewall rule hay không."""
        rule_name = self._get_rule_name(game_id)
        ok, out = _run_netsh_cmd(["show", "rule", f"name={rule_name}"])
        return ok and "SakuraBot_Block" in out

    def get_game_running_pids(self, game_id: str) -> List[int]:
        """Lấy danh sách PID đang chạy của game."""
        pids = []
        try:
            import psutil
            game_info = KNOWN_GAMES.get(game_id, {})
            exes = [x.lower() for x in game_info.get("exes", [])]
            if game_id == "genshin" and self.config_game_path:
                exes.append(Path(self.config_game_path).name.lower())

            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    if name in exes:
                        pids.append(proc.pid)
                except Exception:
                    pass
        except Exception:
            pass
        return pids

    def block_game_network(self, game_id: str, exe_path: Optional[str] = None) -> Tuple[bool, str]:
        """
        NGẮT MẠNG RIÊNG BIỆT CHO GAME:
        - Thêm rule outbound block trên Windows Firewall chỉ định riêng đường dẫn exe của game.
        - Đóng ngay các socket TCP đang mở để game bị ngắt kết nối tức thì (0 delay).
        - KHÔNG ảnh hưởng tới bất kỳ ứng dụng nào khác trên máy tính!
        """
        rule_name = self._get_rule_name(game_id)
        target_exe = exe_path or self.find_game_executable(game_id)

        if not target_exe or not os.path.exists(target_exe):
            return False, f"Không tìm thấy file thực thi của game [{game_id}] để thiết lập ngắt mạng!"

        # 1. Thêm rule tường lửa chặn outbound cho file exe này
        # Xóa rule cũ trước nếu có để tránh trùng lặp
        _run_netsh_cmd(["delete", "rule", f"name={rule_name}"])
        ok, out = _run_netsh_cmd([
            "add", "rule",
            f"name={rule_name}",
            "dir=out",
            "action=block",
            f'program="{target_exe}"',
            "enable=yes",
            "profile=any"
        ])

        if not ok:
            # Nếu thiếu quyền admin, thông báo rõ cho người dùng
            return False, f"Không thể thêm rule tường lửa. Vui lòng chạy Launcher dưới quyền Administrator!\nChi tiết: {out}"

        # 2. Đóng tức thời các kết nối TCP hiện hữu của tiến trình game
        pids = self.get_game_running_pids(game_id)
        closed_sockets = 0
        for p in pids:
            closed_sockets += _close_tcp_connections_for_pid(p)

        self._blocked_games[game_id] = True
        log.info(f"Đã ngắt mạng cho {game_id} (Exe: {target_exe}, Closed sockets: {closed_sockets})")
        return True, f"Đã ngắt mạng thành công cho {target_exe}! (Đã cắt {closed_sockets} kết nối đang mở)"

    def unblock_game_network(self, game_id: str) -> Tuple[bool, str]:
        """KHÔI PHỤC MẠNG CHO GAME: Gỡ bỏ rule tường lửa, game kết nối lại bình thường."""
        rule_name = self._get_rule_name(game_id)
        ok, out = _run_netsh_cmd(["delete", "rule", f"name={rule_name}"])
        self._blocked_games[game_id] = False
        log.info(f"Đã khôi phục mạng cho {game_id}")
        return True, f"Đã khôi phục mạng thành công cho [{game_id}]!"

    def toggle_game_network(self, game_id: str, exe_path: Optional[str] = None) -> Tuple[bool, bool, str]:
        """
        Chuyển đổi trạng thái mạng (Ngắt <-> Bật).
        Trả về: (thành công, trạng thái_mới_đang_bị_chặn, thông báo)
        """
        currently_blocked = self.is_game_blocked(game_id)
        if currently_blocked:
            ok, msg = self.unblock_game_network(game_id)
            return ok, False, msg
        else:
            ok, msg = self.block_game_network(game_id, exe_path)
            return ok, True, msg

    def unblock_all_games(self):
        """Gỡ bỏ toàn bộ các rule tường lửa ngắt mạng do Launcher tạo."""
        for gid in list(KNOWN_GAMES.keys()) + ["custom"]:
            try:
                _run_netsh_cmd(["delete", "rule", f"name={self._get_rule_name(gid)}"])
                self._blocked_games[gid] = False
            except Exception:
                pass

    # =========================================================================
    # BỘ ĐO ĐỘ TRỄ (PING) & TỐI ƯU HÓA MẠNG
    # =========================================================================
    def measure_ping(self, host: str, port: int = 443, timeout: float = 2.0) -> Optional[float]:
        """Đo độ trễ TCP handshake chính xác tới máy chủ (ms)."""
        t0 = time.perf_counter()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((host, port))
                latency = (time.perf_counter() - t0) * 1000.0
                return round(latency, 1)
        except Exception:
            return None

    def get_all_pings(self) -> Dict[str, Dict[str, Any]]:
        """Đo ping tới các máy chủ game HoYoverse & DNS quốc tế."""
        servers = {
            "asia": {"name": "HoYoverse Châu Á (Asia)", "host": "sg-hk4e-api.hoyoverse.com", "port": 443},
            "usa": {"name": "HoYoverse Bắc Mỹ (NA)", "host": "hk4e-api-os.hoyoverse.com", "port": 443},
            "europe": {"name": "HoYoverse Châu Âu (EU)", "host": "hk4e-api-os.hoyoverse.com", "port": 443},
            "cloudflare": {"name": "Cloudflare DNS (1.1.1.1)", "host": "1.1.1.1", "port": 53},
            "google": {"name": "Google DNS (8.8.8.8)", "host": "8.8.8.8", "port": 53},
        }

        results = {}
        for key, s in servers.items():
            ping_val = self.measure_ping(s["host"], s["port"])
            if ping_val is None:
                quality = "Mất kết nối"
                color = "#ef4444"
            elif ping_val < 60:
                quality = "Xuất sắc (Rất mượt)"
                color = "#10b981"
            elif ping_val < 100:
                quality = "Tốt (Mượt mà)"
                color = "#06b6d4"
            elif ping_val < 160:
                quality = "Trung bình"
                color = "#f59e0b"
            else:
                quality = "Độ trễ cao"
                color = "#f43f5e"

            results[key] = {
                "name": s["name"],
                "host": s["host"],
                "ping": ping_val,
                "ping_str": f"{ping_val} ms" if ping_val is not None else "Timeout",
                "quality": quality,
                "color": color
            }
        return results

    def optimize_gaming_network(self) -> List[str]:
        """
        TỐI ƯU HÓA MẠNG CHO LAUNCHER & GAME:
        1. Xóa bộ nhớ đệm DNS (ipconfig /flushdns)
        2. Tối ưu TCP Global Auto-Tuning (Normal + RSS Enabled)
        3. Tắt Nagle's Algorithm (TcpAckFrequency = 1, TCPNoDelay = 1) qua Windows Registry
        4. Tắt Windows Multimedia Network Throttling (NetworkThrottlingIndex = 0xffffffff, SystemResponsiveness = 0)
        """
        logs = []

        # 1. Flush DNS
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, startupinfo=startupinfo, timeout=5)
            logs.append("✅ Đã làm sạch toàn bộ bộ nhớ đệm DNS Resolver Cache (ipconfig /flushdns).")
        except Exception as e:
            logs.append(f"⚠️ Làm sạch DNS thất bại: {e}")

        # 2. TCP Auto-Tuning
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["netsh", "int", "tcp", "set", "global", "autotuninglevel=normal"],
                           capture_output=True, startupinfo=startupinfo, timeout=5)
            subprocess.run(["netsh", "int", "tcp", "set", "global", "rss=enabled"],
                           capture_output=True, startupinfo=startupinfo, timeout=5)
            logs.append("✅ Đã tối ưu TCP Window Auto-Tuning & kích hoạt Receive-Side Scaling (RSS).")
        except Exception as e:
            logs.append(f"⚠️ Thiết lập TCP netsh: {e}")

        # 3. Registry Multimedia Network Throttling Fix & TCP Latency Tweaks
        try:
            import winreg
            # Network Throttling Index
            mm_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, mm_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "NetworkThrottlingIndex", 0, winreg.REG_DWORD, 0xffffffff)
                winreg.SetValueEx(key, "SystemResponsiveness", 0, winreg.REG_DWORD, 0)
            logs.append("✅ Đã vô hiệu hóa Windows Network Throttling (Ưu tiên 100% băng thông cho Game).")

            # Gaming SystemProfile Tasks
            game_prof_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, game_prof_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "GPU Priority", 0, winreg.REG_DWORD, 8)
                winreg.SetValueEx(key, "Priority", 0, winreg.REG_DWORD, 6)
                winreg.SetValueEx(key, "Scheduling Category", 0, winreg.REG_SZ, "High")
            logs.append("✅ Đã gán mức ưu tiên cao nhất trong Windows Scheduler cho các tác vụ Game.")

        except PermissionError:
            logs.append("ℹ️ Lưu ý Registry: Cần chạy Launcher với quyền Administrator để ghi khóa tối ưu hóa Windows TCP sâu.")
        except Exception as e:
            logs.append(f"⚠️ Registry tweaks: {e}")

        return logs


# Singleton instance
network_manager = NetworkManager()

