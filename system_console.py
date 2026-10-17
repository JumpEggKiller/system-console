#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""System Console — 桌面 CPU + GPU + 网络 监控 HUD(1920x1080)。

布局:
- 左列:CPU(96 线程即时网格 + 总览/频率,任务管理器同款 WMI 总数)+ 内存
- 右侧:GPU 三卡横排(nvidia-smi,品牌色 + UTIL/VRAM/TEMP/PWR/FAN/CLK + 30s 历史)
- 右下:网络 — 实时上/下行速率(Mbps)+ 60s 双线图 + 累计流量
- 窗口固定 1920x1080,自绘标题条拖动;overrideredirect 无边框
- 位置记忆(%APPDATA%\\System Console\\position.json);F11 全屏 letterbox;Esc/Q/右键 退出
- 配色:Catppuccin Mocha
"""
import ctypes
import json
import os
import subprocess
import sys
import time

IS_WIN = sys.platform == "win32"

if getattr(sys, "frozen", False):
    BASE = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "System Console")
    os.makedirs(BASE, exist_ok=True)
    BUNDLE = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    BASE = os.path.dirname(os.path.abspath(__file__))
    BUNDLE = BASE
POS_FILE = os.path.join(BASE, "position.json")

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception as e:
    print("需要图形环境(tkinter):", e)
    sys.exit(1)

try:
    import psutil
except Exception as e:
    print("需要 psutil:", e)
    sys.exit(1)

# ── 配色:Catppuccin Mocha ──────────────────────────
BG = "#11111b"
PANEL = "#1e1e2e"
PANEL2 = "#181825"
BORDER = "#313244"
TXT = "#cdd6f4"
DIM = "#cba6f7"
DIM2 = "#6c7086"
CYAN = "#89b4fa"
GREEN = "#a6e3a1"
AMBER = "#f9e2af"
RED = "#f38ba8"
TEAL = "#94e2d5"
PEACH = "#fab387"
BAR_BG = "#313244"
HIST_BG = "#181825"

# ── 布局(1920x1080 坐标系,渲染时 × s)─────────────
WIN_W, WIN_H = 1920, 1080
M = 16
PAD = 14
TITLEBAR = 24
HDR = 34
FTR = 26
LEFT_W = 620          # 左列宽度(CPU + 内存)
CPU_FRAC = 0.62       # 左列内 CPU 占比
GPU_FRAC = 0.72       # 右列内 GPU 占比
GRID_COLS = 8
HIST_N = 60

BRAND_COLORS = {"NVIDIA": "#76b900", "AMD": "#ed1c24", "INTEL": "#00b4eb"}


def col_for(v):
    if v >= 85:
        return RED
    if v >= 50:
        return AMBER
    return GREEN


def brand_of(name):
    n = (name or "").upper()
    for b in BRAND_COLORS:
        if b in n or (b == "NVIDIA" and ("RTX" in n or "GTX" in n or "QUADRO" in n)):
            return b, BRAND_COLORS[b]
    return None, TXT


def cpu_model():
    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "name", "/value"], text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=4)
        for line in out.splitlines():
            if "=" in line and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "CPU"


def _find_nvidia_smi():
    import shutil
    p = shutil.which("nvidia-smi")
    if p:
        return p
    for cand in ("nvidia-smi.exe", "nvidia-smi"):
        b = os.path.join(BUNDLE, cand)
        if os.path.exists(b):
            return b
    return "nvidia-smi"


def _run_tool(p, *args, timeout=5):
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([p, *args], capture_output=True, text=True,
                       timeout=timeout, creationflags=cflags)
    return r.stdout


def gpu_sample():
    try:
        out = _run_tool(
            _find_nvidia_smi(),
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed,clocks.current.graphics,pci.bus_id",
            "--format=csv,noheader,nounits")
        gpus = []
        for line in out.splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) < 9:
                continue
            def f(x, d=0):
                try:
                    return float(x)
                except Exception:
                    return float(d)
            gpus.append({
                "idx": int(f(p[0])), "name": p[1], "util": int(f(p[2])),
                "vram": int(f(p[3])), "vram_tot": int(f(p[4])),
                "temp": int(f(p[5])), "pwr": f(p[6]), "fan": int(f(p[7])),
                "clk": int(f(p[8])), "slot": p[9] if len(p) > 9 and p[9] else None,
            })
        return gpus
    except Exception:
        return None


class TaskMgrCpu:
    """任务管理器同款:WMI 性能计数器 _Total(利用率 + 实时频率)。"""

    def __init__(self):
        self.wmi = None
        if not IS_WIN:
            return
        try:
            import win32com.client
            self.wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\cimv2")
        except Exception:
            self.wmi = None

    def sample(self):
        if not self.wmi:
            return None
        try:
            for o in self.wmi.InstancesOf(
                    "Win32_PerfFormattedData_Counters_ProcessorInformation"):
                if o.Name == "_Total":
                    base = float(o.ProcessorFrequency)
                    perf = float(o.PercentProcessorPerformance)
                    freq = base * perf / 100.0 if perf > 0 else base
                    return float(o.PercentProcessorTime), freq
        except Exception:
            self.wmi = None
        return None


def fmt_bps(b):
    if b >= 1e9:
        return f"{b/1e9:.2f} Gbps"
    if b >= 1e6:
        return f"{b/1e6:.1f} Mbps"
    return f"{b/1e3:.0f} Kbps"


def fmt_gb(b):
    return f"{b/1024**3:.1f} GB"


class App:
    POLL_MS = 1000

    def __init__(self, root):
        self.root = root
        self.root.title("System Console")
        self.root.overrideredirect(True)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = self._load_pos(sw)
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")
        self.root.update_idletasks()

        self.f_title = tkfont.Font(family="Consolas", size=12, weight="bold")
        self.f_hdr = tkfont.Font(family="Consolas", size=9)
        self._fcache = {}
        self._s = 1.0

        self.c = tk.Canvas(root, width=WIN_W, height=WIN_H,
                           bg=BG, highlightthickness=0)
        self.c.pack(fill="both", expand=True)

        self.tbar = tk.Canvas(root, width=WIN_W, height=TITLEBAR,
                              bg=PANEL2, highlightthickness=0)
        self.tbar.place(x=0, y=0, width=WIN_W, height=TITLEBAR)
        self._draw_titlebar()
        self.tbar.bind("<ButtonPress-1>", self._start_drag)
        self.tbar.bind("<B1-Motion>", self._on_drag)

        self.root.bind("<Button-3>", lambda e: self.close())
        self.root.bind("<Escape>", lambda e: self.close())
        self.root.bind("q", lambda e: self.close())
        self.root.bind("Q", lambda e: self.close())
        self.root.bind("<F11>", lambda e: self.toggle_full())
        self._drag = None
        self._fullscreen = False
        self._prev_geom = None

        self.ncpu = psutil.cpu_count() or 1
        self.grid_rows = -(-self.ncpu // GRID_COLS)
        self.model = cpu_model()
        self.tm = TaskMgrCpu()
        self.tm_util = None
        self.tm_freq = None

        self.cores = [0] * self.ncpu
        self.cpu_total = 0.0
        self.mem = None
        self._hist_mem = []           # 内存 % 历史
        self.gpus = []
        self.gpu_hist = []          # 每卡 util 历史(按 idx)
        self.net_hist = []          # (down_bps, up_bps)
        self._last_net = psutil.net_io_counters()
        self._net_tot = self._last_net
        self._warm = psutil.cpu_percent(interval=None, percpu=True)

        self._poll()
        self.root.after(self.POLL_MS, self._poll)

    # ── 字体(按 s 缩放,缓存)──
    def F(self, size, bold=False):
        pt = max(6, int(round(size * self._s)))
        w = "bold" if bold else "normal"
        key = (pt, w)
        if key not in self._fcache:
            self._fcache[key] = tkfont.Font(family="Consolas", size=pt, weight=w)
        return self._fcache[key]

    def _load_pos(self, sw):
        try:
            with open(POS_FILE, "r", encoding="utf-8") as f:
                p = json.load(f)
            x = int(p.get("x", 0)); y = int(p.get("y", 0))
            if 0 <= x < sw and 0 <= y < self.root.winfo_screenheight():
                return x, y
        except Exception:
            pass
        return 0, 0

    def _save_pos(self):
        try:
            with open(POS_FILE, "w", encoding="utf-8") as f:
                json.dump({"x": self.root.winfo_x(), "y": self.root.winfo_y()}, f)
        except Exception:
            pass

    def _draw_titlebar(self):
        self.tbar.delete("all")
        w = self.tbar.winfo_width() or WIN_W
        self.tbar.create_text(10, 12, text="SYSTEM CONSOLE", anchor="w",
                              font=self.f_title, fill=DIM)
        self.tbar.create_text(w - 10, 12, text="F11 全屏   Esc 退出",
                              anchor="e", font=self.f_hdr, fill=DIM2)

    def _start_drag(self, e):
        self._drag = (e.x, e.y)

    def _on_drag(self, e):
        if not self._drag:
            return
        dx, dy = self._drag
        self.root.geometry(f"+{self.root.winfo_x() + e.x - dx}+{self.root.winfo_y() + e.y - dy}")

    def _monitor_rect_for(self):
        """窗口当前所在显示器的矩形 (l, t, w, h, 虚拟屏幕坐标);失败返回 None。"""
        if not IS_WIN:
            return None
        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                            ("r", ctypes.c_long), ("b", ctypes.c_long)]

            GA_ROOT = 2
            hwnd = self.root.winfo_id()
            root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
            wr = RECT()
            if not user32.GetWindowRect(root, ctypes.byref(wr)):
                return None
            cx = (wr.l + wr.r) // 2
            cy = (wr.t + wr.b) // 2

            monitors = []
            cbtype = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(RECT), ctypes.c_ssize_t)

            def cb(hmon, hdc, lprc, lparam):
                rc = lprc.contents
                monitors.append((rc.l, rc.t, rc.r, rc.b))
                return True

            if not user32.EnumDisplayMonitors(0, 0, cbtype(cb), 0):
                return None
            for (l, t, r, b) in monitors:  # 中心点落在哪个显示器
                if l <= cx < r and t <= cy < b:
                    return (l, t, r - l, b - t)
            best, bd = None, None  # 兜底:最近的显示器
            for (l, t, r, b) in monitors:
                d = (((l + r) // 2) - cx) ** 2 + (((t + b) // 2) - cy) ** 2
                if bd is None or d < bd:
                    bd, best = d, (l, t, r - l, b - t)
            return best
        except Exception:
            return None

    def toggle_full(self):
        if not self._fullscreen:
            self._prev_geom = self.root.geometry()
            self._fullscreen = True
            mon = self._monitor_rect_for()
            if mon:
                l, t, w, h = mon
                self.root.geometry(f"{w}x{h}+{l}+{t}")
            else:
                self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        else:
            self._fullscreen = False
            if self._prev_geom:
                self.root.geometry(self._prev_geom)
                self._save_pos()

    # ── 轮询 ──
    def _poll(self):
        if not self.root.winfo_exists():
            return
        try:
            self.cores = psutil.cpu_percent(interval=None, percpu=True)
            self.cpu_total = psutil.cpu_percent(interval=None)
            s = self.tm.sample()
            if s:
                self.tm_util, self.tm_freq = s
            self.mem = psutil.virtual_memory()
            self._hist_mem.append(self.mem.percent)
            if len(self._hist_mem) > HIST_N:
                self._hist_mem.pop(0)
            g = gpu_sample()
            if g:
                self.gpus = g
                self.gpu_hist.append([x.get("util", 0) for x in g])
                if len(self.gpu_hist) > HIST_N:
                    self.gpu_hist.pop(0)
            n = psutil.net_io_counters()
            dt = 1.0
            down = (n.bytes_recv - self._last_net.bytes_recv) * 8 / dt
            up = (n.bytes_sent - self._last_net.bytes_sent) * 8 / dt
            self._last_net = n
            self._net_tot = n
            self.net_hist.append((max(0, down), max(0, up)))
            if len(self.net_hist) > HIST_N:
                self.net_hist.pop(0)
        except Exception:
            pass
        self._draw()
        self.root.after(self.POLL_MS, self._poll)

    # ── 渲染 ──
    def _draw(self):
        c = self.c
        c.delete("all")
        w = c.winfo_width() or WIN_W
        h = c.winfo_height() or WIN_H
        s = max(0.6, min(w / WIN_W, h / WIN_H))
        self._s = s
        cw = int(WIN_W * s)
        ch = int(WIN_H * s)
        ox = (w - cw) // 2
        oy = (h - ch) // 2
        tbar = int(TITLEBAR * s)
        hdr = int(HDR * s)
        ftr = int(FTR * s)
        self._header(c, cw, ox, oy + tbar, hdr, s)

        avail = ch - tbar - hdr - ftr
        lw = int(LEFT_W * s)
        rx = ox + lw + int(M * s)
        rw = cw - lw - int(M * s * 2)
        # 左列:CPU + 内存
        cpu_h = int(avail * CPU_FRAC)
        self._cpu_panel(c, ox, oy + tbar + hdr, lw, cpu_h, s)
        self._mem_panel(c, ox, oy + tbar + hdr + cpu_h, lw, avail - cpu_h, s)
        # 右列:GPU + 网络
        gpu_h = int(avail * GPU_FRAC)
        self._gpu_panel(c, rx, oy + tbar + hdr, rw, gpu_h, s)
        self._net_panel(c, rx, oy + tbar + hdr + gpu_h, rw, avail - gpu_h, s)
        self._footer(c, cw, ch, ox, oy, ftr, s)

    def _header(self, c, w, ox, oy, hdr, s):
        c.create_line(ox, oy + hdr, ox + w, oy + hdr, fill=BORDER)
        model = (self.model or "CPU")
        if len(model) > 40:
            model = model[:40] + "…"
        c.create_text(ox + int(M * s), oy + hdr // 2, text=f"CPU {self.ncpu}T",
                      anchor="w", font=self.F(11, True), fill=DIM)
        c.create_text(ox + int(110 * s), oy + hdr // 2, text=model, anchor="w",
                      font=self.F(9), fill=DIM2)
        c.create_text(ox + w - int(M * s), oy + hdr // 2,
                      text="F11 全屏    Esc 退出", anchor="e",
                      font=self.F(9), fill=DIM2)

    # ── 左列上:CPU ──
    def _cpu_panel(self, c, ox, oy, pw, ph, s):
        c.create_rectangle(ox, oy, ox + pw, oy + ph, fill=PANEL, outline=BORDER, width=1)
        bx = ox + int(PAD * s)
        bw = pw - int(PAD * s * 2)
        util = self.tm_util if self.tm_util is not None else self.cpu_total
        tc = col_for(util)
        c.create_text(bx, oy + int(PAD * s) + int(8 * s), text="CPU TOTAL", anchor="w",
                      font=self.F(10, True), fill=DIM)
        if self.tm_freq:
            c.create_text(bx + bw - int(110 * s), oy + int(PAD * s) + int(8 * s),
                          text=f"{self.tm_freq:.0f} MHz", anchor="e",
                          font=self.F(11, True), fill=CYAN)
        c.create_text(bx + bw, oy + int(PAD * s) + int(8 * s), text=f"{util:.0f}%",
                      anchor="e", font=self.F(16, True), fill=tc)
        yy = oy + int(PAD * s) + int(22 * s)
        bar_h = int(10 * s)
        c.create_rectangle(bx, yy, bx + bw, yy + bar_h, fill=BAR_BG, outline="")
        c.create_rectangle(bx, yy, bx + int(bw * min(100, util) / 100), yy + bar_h,
                           fill=tc, outline="")
        yy += bar_h + int(10 * s)

        grid_top = yy
        grid_h = oy + ph - int(PAD * s) - grid_top
        rows = self.grid_rows
        cols = GRID_COLS
        gap = max(1, int(2 * s))
        cell_w = (bw - gap * (cols - 1)) / cols
        cell_h = (grid_h - gap * (rows - 1)) / rows
        for idx in range(self.ncpu):
            r = idx // cols
            col = idx % cols
            cx = bx + int(col * (cell_w + gap))
            cy = grid_top + int(r * (cell_h + gap))
            v = self.cores[idx] if idx < len(self.cores) else 0
            vc = col_for(v)
            c.create_rectangle(cx, cy, cx + cell_w, cy + cell_h, fill=BAR_BG, outline="")
            fh = max(0, int((cell_h - int(12 * s)) * min(100, v) / 100))
            if fh > 0:
                c.create_rectangle(cx, cy + cell_h - fh, cx + cell_w, cy + cell_h,
                                   fill=vc, outline="")
            lab = f"{idx}"
            val = f"{v:.0f}"
            if cell_w >= self.F(9).measure(lab) + self.F(9, True).measure(val) + int(6 * s):
                c.create_text(cx + int(3 * s), cy + int(6 * s), text=lab, anchor="w",
                              font=self.F(9), fill=DIM)
                c.create_text(cx + cell_w - int(3 * s), cy + int(6 * s), text=val,
                              anchor="e", font=self.F(9, True), fill=vc)
            else:
                c.create_text(cx + cell_w // 2, cy + int(6 * s), text=val, anchor="e",
                              font=self.F(9, True), fill=vc)

    # ── 左列下:内存 ──
    def _mem_panel(self, c, ox, oy, pw, ph, s):
        if not self.mem:
            return
        c.create_rectangle(ox, oy, ox + pw, oy + ph, fill=PANEL, outline=BORDER, width=1)
        bx = ox + int(PAD * s)
        bw = pw - int(PAD * s * 2)
        i = int(PAD * s)
        pct = self.mem.percent
        mc = col_for(pct)
        c.create_text(bx, oy + i + int(8 * s), text="MEMORY", anchor="w",
                      font=self.F(10, True), fill=DIM)
        c.create_text(bx + bw, oy + i + int(8 * s), text=f"{pct:.0f}%",
                      anchor="e", font=self.F(16, True), fill=mc)
        yy = oy + i + int(22 * s)
        bar_h = int(14 * s)
        c.create_rectangle(bx, yy, bx + bw, yy + bar_h, fill=BAR_BG, outline="")
        c.create_rectangle(bx, yy, bx + int(bw * min(100, pct) / 100), yy + bar_h,
                           fill=mc, outline="")
        yy += bar_h + int(12 * s)
        sw = psutil.swap_memory()
        kv = [
            ("已用", fmt_gb(self.mem.used), mc),
            ("可用", fmt_gb(self.mem.available), GREEN),
            ("总计", fmt_gb(self.mem.total), TXT),
            ("空闲", fmt_gb(self.mem.free), TXT),
            ("交换", f"{fmt_gb(sw.used)} / {fmt_gb(sw.total)}", TXT),
            ("交换率", f"{sw.percent:.0f}%", CYAN),
        ]
        colw = bw / 3
        kv_h = int(34 * s)
        for ki, (lab, val, vc) in enumerate(kv):
            r = ki // 3
            col = ki % 3
            cx = bx + int(colw * col)
            cy = yy + r * kv_h
            c.create_text(cx, cy, text=lab, anchor="w", font=self.F(9), fill=DIM)
            c.create_text(cx, cy + int(14 * s), text=val, anchor="w",
                          font=self.F(12, True), fill=vc)
        yy += kv_h * 2 + int(10 * s)
        hist_h = oy + ph - i - yy
        if hist_h < int(20 * s):
            return
        c.create_rectangle(bx, yy, bx + bw, yy + hist_h, fill=HIST_BG, outline=BORDER, width=1)
        if self.hist_mem():
            nlen = len(self.hist_mem())
            step = bw / nlen
            for i2, v in enumerate(self.hist_mem()):
                bh = max(2, int((hist_h - int(2 * s)) * min(100, v) / 100))
                bx0 = bx + int(step * i2)
                c.create_rectangle(bx0, yy + hist_h - int(2 * s) - bh,
                                   bx0 + max(1, int(step) - 1), yy + hist_h - int(2 * s),
                                   fill=col_for(v), outline="")

    def hist_mem(self):
        return getattr(self, "_hist_mem", None) or []

    # ── 右列上:GPU ──
    def _gpu_panel(self, c, ox, oy, pw, ph, s):
        c.create_rectangle(ox, oy, ox + pw, oy + ph, fill=PANEL, outline=BORDER, width=1)
        if not self.gpus:
            c.create_text(ox + pw // 2, oy + ph // 2, text="GPU:采样中…(nvidia-smi)",
                          font=self.F(10), fill=DIM2)
            return
        n = len(self.gpus)
        per = ph // n
        for g in self.gpus:
            self._gpu_card(c, ox, oy, pw, per, g, s)
            oy += per

    def _gpu_card(self, c, ox, oy, pw, ph, g, s):
        bx = ox + int(PAD * s)
        bw = pw - int(PAD * s * 2)
        i = int(8 * s)
        if oy + ph < oy + i * 2:
            return
        c.create_line(ox + int(PAD * s), oy, ox + pw - int(PAD * s), oy, fill=BORDER)
        util = g.get("util", 0) or 0
        uc = col_for(util)
        vt = g.get("vram_tot") or 1
        vram = g.get("vram", 0)
        vp = min(100, int(vram / vt * 100)) if vt else 0
        yy = oy + i
        # 标题行:品牌色块 + 品牌 + 型号 + PCIe + 利用率
        brand, bcol = brand_of(g.get("name", ""))
        name_txt = g.get("name", "GPU")
        slot = g.get("slot")
        if slot and ":" in slot and len(slot) > 11:
            slot = slot.split(":", 1)[1]
        c.create_rectangle(bx, yy + 2, bx + int(8 * s), yy + int(13 * s), fill=bcol)
        tx = bx + int(12 * s)
        if brand:
            c.create_text(tx, yy + int(7 * s), text=brand, anchor="w",
                          font=self.F(9, True), fill=bcol)
            tx += self.F(9, True).measure(brand) + int(8 * s)
        nm = name_txt[:36]
        c.create_text(tx, yy + int(7 * s), text=nm, anchor="w",
                      font=self.F(11, True), fill=TXT)
        tx += self.F(11, True).measure(nm) + int(10 * s)
        if slot:
            c.create_text(tx, yy + int(7 * s), text=f"[PCIe {slot}]", anchor="w",
                          font=self.F(9), fill=DIM2)
        c.create_text(bx + bw, yy + int(7 * s), text=f"{util}%", anchor="e",
                      font=self.F(14, True), fill=uc)
        yy += int(20 * s)
        # UTIL 条
        c.create_text(bx, yy + int(5 * s), text="UTIL", anchor="w", font=self.F(9), fill=DIM)
        bar_x = bx + int(46 * s)
        bar_w = bw - int(46 * s)
        c.create_rectangle(bar_x, yy, bar_x + bar_w, yy + int(10 * s), fill=BAR_BG, outline="")
        c.create_rectangle(bar_x, yy, bar_x + int(bar_w * util / 100), yy + int(10 * s),
                           fill=uc, outline="")
        yy += int(18 * s)
        # VRAM 条 + 数值
        vcol = col_for(vp)
        c.create_text(bx, yy + int(5 * s), text="VRAM", anchor="w", font=self.F(9), fill=DIM)
        vbar_w = bw - int(46 * s) - int(150 * s)
        c.create_rectangle(bar_x, yy, bar_x + vbar_w, yy + int(10 * s), fill=BAR_BG, outline="")
        c.create_rectangle(bar_x, yy, bar_x + int(vbar_w * vp / 100), yy + int(10 * s),
                           fill=CYAN, outline="")
        c.create_text(bx + bw, yy + int(5 * s), text=f"{vram} / {vt} MiB   {vp}%",
                      anchor="e", font=self.F(11, True), fill=vcol)
        yy += int(18 * s)
        # KV:TEMP/PWR/FAN/CLK
        temp = g.get("temp", 0) or 0
        cols = [
            ("TEMP", f"{temp}C", AMBER if temp >= 83 else TXT),
            ("PWR", f"{g.get('pwr', 0):.0f}W", TXT),
            ("FAN", f"{g.get('fan', 0)}%", TXT),
            ("CLK", f"{g.get('clk', 0)}MHz", CYAN),
        ]
        colw = bw / 4
        for ci, (lab, val, vc) in enumerate(cols):
            cx = bx + int(colw * ci)
            c.create_text(cx, yy + int(4 * s), text=lab, anchor="w", font=self.F(9), fill=DIM)
            c.create_text(cx, yy + int(16 * s), text=val, anchor="w",
                          font=self.F(11, True), fill=vc)
        yy += int(26 * s)
        # 历史图(吸收剩余)
        hist_h = oy + ph - yy - i
        if hist_h < int(16 * s):
            return
        c.create_rectangle(bx, yy, bx + bw, yy + hist_h, fill=HIST_BG, outline=BORDER, width=1)
        rows = self.gpu_hist
        if rows:
            nlen = len(rows)
            step = bw / nlen
            ci = g.get("idx", 0)
            for i2, r in enumerate(rows):
                v = r[ci] if ci < len(r) else 0
                bh = max(2, int((hist_h - int(2 * s)) * min(100, v) / 100))
                bx0 = bx + int(step * i2)
                c.create_rectangle(bx0, yy + hist_h - int(2 * s) - bh,
                                   bx0 + max(1, int(step) - 1), yy + hist_h - int(2 * s),
                                   fill=col_for(v), outline="")

    # ── 右列下:网络 ──
    def _net_panel(self, c, ox, oy, pw, ph, s):
        c.create_rectangle(ox, oy, ox + pw, oy + ph, fill=PANEL, outline=BORDER, width=1)
        bx = ox + int(PAD * s)
        bw = pw - int(PAD * s * 2)
        i = int(PAD * s)
        down, up = self.net_hist[-1] if self.net_hist else (0, 0)
        # 标题行
        c.create_text(bx, oy + i + int(8 * s), text="NETWORK", anchor="w",
                      font=self.F(10, True), fill=DIM)
        c.create_text(bx + bw, oy + i + int(8 * s),
                      text=f"累计 ↓{fmt_gb(self._net_tot.bytes_recv)}  ↑{fmt_gb(self._net_tot.bytes_sent)}",
                      anchor="e", font=self.F(10), fill=DIM2)
        yy = oy + i + int(24 * s)
        # 实时速率:左下行,右上行
        half = bw // 2
        c.create_text(bx, yy + int(10 * s), text="↓ 下载", anchor="w",
                      font=self.F(10, True), fill=TEAL)
        c.create_text(bx + half - int(20 * s), yy + int(10 * s), text=fmt_bps(down),
                      anchor="e", font=self.F(14, True), fill=TEAL)
        c.create_text(bx + half + int(20 * s), yy + int(10 * s), text="↑ 上传", anchor="w",
                      font=self.F(10, True), fill=PEACH)
        c.create_text(bx + bw, yy + int(10 * s), text=fmt_bps(up), anchor="e",
                      font=self.F(14, True), fill=PEACH)
        yy += int(26 * s)
        # 60s 双线历史(自动量程)
        hist_h = oy + ph - i - yy
        if hist_h < int(30 * s):
            return
        c.create_rectangle(bx, yy, bx + bw, yy + hist_h, fill=HIST_BG, outline=BORDER, width=1)
        hist = self.net_hist
        if not hist:
            c.create_text(bx + bw // 2, yy + hist_h // 2, text="采样中…",
                          font=self.F(9), fill=DIM2)
            return
        peak = max([max(d, u) for d, u in hist] + [10e6])  # 至少 10 Mbps 量程
        nlen = len(hist)
        step = bw / nlen
        # 下行:柱;上行:柱(叠加,半透明感用不同色)
        for i2, (d, u) in enumerate(hist):
            bx0 = bx + int(step * i2)
            wd = max(1, int(step) - 1)
            dh = int((hist_h - int(2 * s)) * min(1.0, d / peak))
            uh = int((hist_h - int(2 * s)) * min(1.0, u / peak))
            if dh > 0:
                c.create_rectangle(bx0, yy + hist_h - int(2 * s) - dh,
                                   bx0 + wd, yy + hist_h - int(2 * s), fill=TEAL, outline="")
            if uh > 0:
                c.create_rectangle(bx0, yy + hist_h - int(2 * s) - uh,
                                   bx0 + wd, yy + hist_h - int(2 * s), fill=PEACH, outline="")
        # 量程标注
        c.create_text(bx + bw - int(4 * s), yy + int(10 * s), text=f"量程 {fmt_bps(peak)}",
                      anchor="e", font=self.F(8), fill=DIM2)

    # ── 底栏 ──
    def _footer(self, c, w, ch, ox, oy, ftr, s):
        y = oy + ch - ftr
        c.create_rectangle(ox, y, ox + w, oy + ch, fill=PANEL2, outline="")
        c.create_line(ox, y, ox + w, y, fill=BORDER)
        left = f"poll {1000 // self.POLL_MS}Hz   {time.strftime('%H:%M:%S')}"
        c.create_text(ox + int(M * s), y + ftr // 2, text=left, anchor="w",
                      font=self.F(9), fill=DIM)
        c.create_text(ox + w - int(M * s), y + ftr // 2,
                      text="psutil + nvidia-smi + WMI", anchor="e",
                      font=self.F(9), fill=DIM2)

    def close(self):
        self._save_pos()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    if "--test" in sys.argv:
        psutil.cpu_percent(interval=None, percpu=True)
        t = TaskMgrCpu()
        time.sleep(1)
        print(json.dumps({
            "cpu": {"total": psutil.cpu_percent(interval=None), "wmi": t.sample()},
            "mem_percent": psutil.virtual_memory().percent,
            "gpus": gpu_sample(),
            "net": psutil.net_io_counters()._asdict(),
        }, ensure_ascii=False, indent=2))
    elif "--selftest-gui" in sys.argv:
        root = tk.Tk()
        app = App(root)
        root.update()
        print("geom:", root.geometry())
        app.toggle_full(); root.update(); print("full:", root.geometry())
        app.toggle_full(); root.update(); print("restored:", root.geometry())
        root.destroy()
    else:
        main()
