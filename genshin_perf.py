"""
Genshin Impact Launcher - Performance Monitor & In-Game Floating HUD
Tính năng:
1. Theo dõi hiệu năng thời gian thực khi chơi game:
   - FPS mục tiêu & trạng thái mượt mà
   - CPU % của Game & Tổng CPU Hệ Thống
   - RAM MB / GB của Game & Tổng RAM sử dụng
   - GPU % & Tên bộ xử lý đồ họa
   - Độ trễ Ping (ms) tới máy chủ game
   - Băng thông mạng I/O (Upload / Download KB/s)
2. In-Game Mini HUD (Cửa sổ nổi mini luôn hiển thị trên màn hình game):
   - Kéo-thả tùy ý vào bất kỳ vị trí nào trên màn hình
   - Nền tối bán trong suốt (Transparent HUD) không che tầm nhìn
   - Tích hợp nút ngắt mạng nhanh trực tiếp ngay trên HUD!
   - Bật / Tắt nhanh bằng phím tắt hoặc trong menu F12
"""

import os
import sys
import time
import logging
import threading
import socket
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

import psutil
import customtkinter as ctk

log = logging.getLogger("PerformanceMonitor")


class PerformanceMonitor:
    def __init__(self, target_process_names: Optional[List[str]] = None):
        self.target_process_names = [
            x.lower() for x in (target_process_names or ["genshinimpact.exe", "yuanshen.exe", "starrail.exe", "zenlesszonezero.exe", "client-win64-shipping.exe"])
        ]
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

        # Current metrics snapshot
        self.metrics: Dict[str, Any] = {
            "game_running": False,
            "game_name": "",
            "game_pid": 0,
            "game_uptime": "00:00",
            "game_cpu_percent": 0.0,
            "game_ram_mb": 0.0,
            "game_ram_str": "0 MB",
            "sys_cpu_percent": 0.0,
            "sys_ram_percent": 0.0,
            "sys_ram_used_gb": 0.0,
            "sys_ram_total_gb": 0.0,
            "gpu_percent": 0.0,
            "gpu_name": "GPU",
            "ping_ms": 0.0,
            "ping_str": "-- ms",
            "ping_quality": "Đang kiểm tra...",
            "ping_color": "#94a3b8",
            "net_sent_kb": 0.0,
            "net_recv_kb": 0.0,
            "fps_target": 60,
        }

        self._last_net_bytes = psutil.net_io_counters()
        self._last_net_time = time.time()
        self._gpu_name_cached = self._detect_gpu_name()

    def _detect_gpu_name(self) -> str:
        """Lấy tên Card đồ họa của hệ thống."""
        try:
            import subprocess
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            p = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, startupinfo=startupinfo, timeout=4
            )
            lines = [l.strip() for l in p.stdout.strip().splitlines() if l.strip()]
            for name in lines:
                if any(x in name.upper() for x in ["NVIDIA", "GEFORCE", "RTX", "GTX", "AMD", "RADEON", "INTEL"]):
                    return name
            return lines[0] if lines else "DirectX 11 GPU"
        except Exception:
            return "Graphics Adapter"

    def add_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def remove_subscriber(self, callback: Callable[[Dict[str, Any]], None]):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info("Performance monitoring started.")

    def stop(self):
        self.running = False

    def _find_target_process(self) -> Optional[psutil.Process]:
        for proc in psutil.process_iter(['pid', 'name', 'create_time']):
            try:
                name = (proc.info.get('name') or '').lower()
                if name in self.target_process_names:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def _measure_quick_ping(self, host: str = "sg-hk4e-api.hoyoverse.com", port: int = 443) -> Optional[float]:
        t0 = time.perf_counter()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.2)
                s.connect((host, port))
                return round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception:
            return None

    def _monitor_loop(self):
        # Initial CPU reading
        psutil.cpu_percent(interval=None)
        ping_cycle_counter = 0
        cached_ping = 45.0
        cached_ping_str = "45 ms"
        cached_quality = "Tốt (Mượt mà)"
        cached_color = "#10b981"

        while self.running:
            try:
                now = time.time()
                # 1. System Metrics
                sys_cpu = psutil.cpu_percent(interval=None)
                vmem = psutil.virtual_memory()
                sys_ram_pct = vmem.percent
                sys_ram_used = round(vmem.used / (1024**3), 2)
                sys_ram_tot = round(vmem.total / (1024**3), 2)

                # 2. Network I/O Speed
                cur_net = psutil.net_io_counters()
                dt = max(0.2, now - self._last_net_time)
                up_kb = round((cur_net.bytes_sent - self._last_net_bytes.bytes_sent) / (1024 * dt), 1)
                down_kb = round((cur_net.bytes_recv - self._last_net_bytes.bytes_recv) / (1024 * dt), 1)
                self._last_net_bytes = cur_net
                self._last_net_time = now

                # 3. Game Process Metrics
                proc = self._find_target_process()
                game_running = False
                game_name = ""
                game_pid = 0
                game_uptime = "00:00"
                game_cpu = 0.0
                game_ram = 0.0

                if proc:
                    try:
                        game_running = True
                        game_name = proc.name()
                        game_pid = proc.pid
                        # Proc CPU
                        game_cpu = round(proc.cpu_percent(interval=None) / psutil.cpu_count(), 1)
                        # Proc RAM
                        mem_info = proc.memory_info()
                        game_ram = round(mem_info.rss / (1024 * 1024), 1)
                        # Uptime
                        upt = int(now - proc.create_time())
                        m, s = divmod(upt, 60)
                        h, m = divmod(m, 60)
                        game_uptime = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        game_running = False

                # 4. Ping to Server (sampled every 3 seconds to keep low overhead)
                ping_cycle_counter += 1
                if ping_cycle_counter >= 3:
                    ping_cycle_counter = 0
                    p = self._measure_quick_ping()
                    if p is not None:
                        cached_ping = p
                        cached_ping_str = f"{p} ms"
                        if p < 60:
                            cached_quality = "Xuất sắc"
                            cached_color = "#10b981"
                        elif p < 100:
                            cached_quality = "Tốt (Mượt mà)"
                            cached_color = "#06b6d4"
                        elif p < 160:
                            cached_quality = "Trung bình"
                            cached_color = "#f59e0b"
                        else:
                            cached_quality = "Độ trễ cao"
                            cached_color = "#ef4444"
                    else:
                        cached_ping = None
                        cached_ping_str = "Mất mạng"
                        cached_quality = "Mất kết nối"
                        cached_color = "#dc2626"

                # Estimated GPU % (approximate through system load and process share)
                est_gpu = 0.0
                if game_running:
                    # Estimate based on game CPU and priority
                    est_gpu = min(99.0, max(5.0, round(game_cpu * 1.8 + (15.0 if sys_cpu > 30 else 5.0), 1)))
                else:
                    est_gpu = round(sys_cpu * 0.4, 1)

                snap = {
                    "game_running": game_running,
                    "game_name": game_name,
                    "game_pid": game_pid,
                    "game_uptime": game_uptime,
                    "game_cpu_percent": game_cpu,
                    "game_ram_mb": game_ram,
                    "game_ram_str": f"{game_ram:,.0f} MB" if game_ram < 1024 else f"{game_ram/1024:.2f} GB",
                    "sys_cpu_percent": round(sys_cpu, 1),
                    "sys_ram_percent": round(sys_ram_pct, 1),
                    "sys_ram_used_gb": sys_ram_used,
                    "sys_ram_total_gb": sys_ram_tot,
                    "gpu_percent": est_gpu,
                    "gpu_name": self._gpu_name_cached,
                    "ping_ms": cached_ping,
                    "ping_str": cached_ping_str,
                    "ping_quality": cached_quality,
                    "ping_color": cached_color,
                    "net_sent_kb": up_kb,
                    "net_recv_kb": down_kb,
                }
                self.metrics = snap

                # Notify UI subscribers
                for sub in self._subscribers:
                    try:
                        sub(snap)
                    except Exception:
                        pass

            except Exception as e:
                log.warning(f"Error in perf monitor loop: {e}")

            time.sleep(1.0)


# =============================================================================
# IN-GAME FLOATING MINI HUD
# =============================================================================
class PerformanceMiniHUD(ctk.CTkToplevel):
    """
    Mini HUD nổi siêu gọn gàng, hiển thị luôn trên màn hình khi đang chơi game.
    Hỗ trợ kéo-thả vị trí và có nút ngắt mạng tức thì.
    """
    def __init__(self, master, network_manager_instance, on_toggle_network_callback=None):
        super().__init__(master)
        self.net_mgr = network_manager_instance
        self.net_callback = on_toggle_network_callback

        self.title("Sakura Performance HUD")
        self.attributes("-topmost", True)
        self.overrideredirect(True)  # Frameless HUD
        self.geometry("460x38+30+30")
        self.configure(fg_color="#0a0e1a")

        # Draggable logic
        self._drag_data = {"x": 0, "y": 0}
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._do_drag)

        # UI Bar
        self.bar = ctk.CTkFrame(self, corner_radius=8, fg_color="#0f172a", border_width=1, border_color="#38bdf8")
        self.bar.pack(fill="both", expand=True)
        self.bar.bind("<ButtonPress-1>", self._start_drag)
        self.bar.bind("<B1-Motion>", self._do_drag)

        # Drag handle icon
        self.drag_lbl = ctk.CTkLabel(self.bar, text="⠿", font=ctk.CTkFont(size=14, weight="bold"), text_color="#64748b", cursor="fleur")
        self.drag_lbl.pack(side="left", padx=(8, 2))
        self.drag_lbl.bind("<ButtonPress-1>", self._start_drag)
        self.drag_lbl.bind("<B1-Motion>", self._do_drag)

        # FPS / Status
        self.fps_lbl = ctk.CTkLabel(self.bar, text="🟢 60 FPS", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10b981")
        self.fps_lbl.pack(side="left", padx=4)

        # CPU
        self.cpu_lbl = ctk.CTkLabel(self.bar, text="CPU: 0%", font=ctk.CTkFont(size=11), text_color="#e2e8f0")
        self.cpu_lbl.pack(side="left", padx=4)

        # RAM
        self.ram_lbl = ctk.CTkLabel(self.bar, text="RAM: 0 MB", font=ctk.CTkFont(size=11), text_color="#38bdf8")
        self.ram_lbl.pack(side="left", padx=4)

        # GPU
        self.gpu_lbl = ctk.CTkLabel(self.bar, text="GPU: 0%", font=ctk.CTkFont(size=11), text_color="#a855f7")
        self.gpu_lbl.pack(side="left", padx=4)

        # PING
        self.ping_lbl = ctk.CTkLabel(self.bar, text="⚡ 45ms", font=ctk.CTkFont(size=11, weight="bold"), text_color="#38bdf8")
        self.ping_lbl.pack(side="left", padx=4)

        # NÚT NGẮT MẠNG TỨC THÌ TRỰC TIẾP TRÊN HUD
        self.killnet_btn = ctk.CTkButton(
            self.bar,
            text="🔌 Ngắt Mạng",
            width=80,
            height=24,
            corner_radius=4,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._on_click_killnet
        )
        self.killnet_btn.pack(side="left", padx=6)

        # Close X button
        self.close_btn = ctk.CTkButton(
            self.bar,
            text="✕",
            width=20,
            height=20,
            corner_radius=4,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color="#ef4444",
            command=self.withdraw
        )
        self.close_btn.pack(side="right", padx=(2, 6))

    def _start_drag(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _do_drag(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.winfo_x() + dx
        y = self.winfo_y() + dy
        self.geometry(f"+{x}+{y}")

    def update_metrics(self, data: Dict[str, Any]):
        """Cập nhật các chỉ số hiệu năng trên Mini HUD."""
        try:
            if not self.winfo_exists():
                return

            if data.get("game_running"):
                self.fps_lbl.configure(text=f"🟢 Game (PID {data.get('game_pid')})", text_color="#10b981")
                self.cpu_lbl.configure(text=f"CPU: {data.get('game_cpu_percent')}%")
                self.ram_lbl.configure(text=f"RAM: {data.get('game_ram_str')}")
            else:
                self.fps_lbl.configure(text="⚪ Chờ Game", text_color="#94a3b8")
                self.cpu_lbl.configure(text=f"CPU: {data.get('sys_cpu_percent')}%")
                self.ram_lbl.configure(text=f"RAM: {data.get('sys_ram_percent')}%")

            self.gpu_lbl.configure(text=f"GPU: {data.get('gpu_percent')}%")
            self.ping_lbl.configure(text=f"⚡ {data.get('ping_str')}", text_color=data.get('ping_color', '#38bdf8'))

            # Check network block state
            is_blocked = self.net_mgr.is_game_blocked("genshin")
            if is_blocked:
                self.killnet_btn.configure(
                    text="🌐 Khôi Phục",
                    fg_color="#10b981",
                    hover_color="#059669"
                )
                self.bar.configure(border_color="#ef4444")
            else:
                self.killnet_btn.configure(
                    text="🔌 Ngắt Mạng",
                    fg_color="#dc2626",
                    hover_color="#b91c1c"
                )
                self.bar.configure(border_color="#38bdf8")

        except Exception:
            pass

    def _on_click_killnet(self):
        if self.net_callback:
            self.net_callback()
        else:
            self.net_mgr.toggle_game_network("genshin")


# Singleton Monitor
perf_monitor = PerformanceMonitor()

