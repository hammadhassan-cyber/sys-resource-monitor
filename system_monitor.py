import os
import sys
import csv
import time
import math
import threading
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from collections import deque
import psutil
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

try:
    from plyer import notification
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False


# ===================================================================
#  CONFIGURATION
# ===================================================================
DEFAULT_THRESHOLDS = {"cpu": 80.0, "ram": 80.0, "disk": 85.0}

DEFAULT_EMAIL = {
    "enabled": False,
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "",
    "sender_password": "",
    "recipient_email": "",
}

INTERVAL      = 1.0
MAX_HIST      = 120
GRAPH_EVERY   = 3
ALERT_CD      = 30
DRIVE_RECHECK = 60

LOG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "system_monitor_log.csv",
)

SKIP_FS = {
    "", "tmpfs", "devtmpfs", "proc", "sysfs", "cgroup", "cgroup2",
    "overlay", "squashfs", "iso9660", "fuseblk", "binfmt_misc",
    "mqueue", "debugfs", "tracefs", "hugetlbfs", "configfs",
    "pstore", "bpf", "rpc_pipefs", "nfsd", "autofs",
}
SKIP_PREFIXES = ("/sys", "/proc", "/dev", "/run", "/tmp", "/snap")

# ── Dark theme palette ────────────────────────────────────────────
BG0 = "#12121f"; BG1 = "#1a1a2e"; BG2 = "#222240"
FG0 = "#666688"; FG1 = "#9999bb"; FG2 = "#d0d0ee"
ACC = "#4FC3F7"; GRN = "#66BB6A"; AMB = "#FFA726"; RED = "#EF5350"

DRV_COLORS = [
    "#AB47BC", "#26C6DA", "#FF7043", "#9CCC65", "#EC407A",
    "#78909C", "#FFCA28", "#7E57C2", "#29B6F6", "#D4E157",
]


# ===================================================================
#  CIRCULAR GAUGE
# ===================================================================

class CircularGauge(tk.Canvas):
    """270° arc gauge with colour-coded fill and threshold dot."""

    ARC_START = 225
    ARC_SPAN  = 270

    def __init__(self, parent, *, label="", size=175, color=ACC,
                 threshold=80.0, **kw):
        super().__init__(parent, width=size, height=size + 26,
                         bg=BG0, highlightthickness=0, **kw)
        self.size = size
        self.label = label
        self.color = color
        self.threshold = threshold
        self.value = 0.0
        self.cx = size // 2
        self.cy = size // 2
        self.r  = (size // 2) - 15
        self.lw = 13
        self._static()

    def _static(self):
        self.delete("all")
        self.create_arc(
            self.cx - self.r, self.cy - self.r,
            self.cx + self.r, self.cy + self.r,
            start=self.ARC_START, extent=-self.ARC_SPAN,
            style="arc", outline=BG2, width=self.lw,
        )
        self.create_text(self.cx, self.cy - 6, text="0.0 %",
                         fill=FG2, font=("Consolas", 17, "bold"), tags="tv")
        self.create_text(self.cx, self.cy + 17, text=self.label,
                         fill=FG0, font=("Segoe UI", 9), tags="tl")

    def set_value(self, v):
        self.value = max(0.0, min(100.0, v))
        self.delete("av", "mk", "tv", "tl")

        if self.value >= self.threshold:
            c = RED
        elif self.value >= self.threshold * 0.75:
            c = AMB
        else:
            c = self.color

        ext = -self.ARC_SPAN * self.value / 100.0
        if ext < 0:
            self.create_arc(
                self.cx - self.r, self.cy - self.r,
                self.cx + self.r, self.cy + self.r,
                start=self.ARC_START, extent=ext,
                style="arc", outline=c, width=self.lw, tags="av",
            )

        ang = math.radians(
            self.ARC_START - self.ARC_SPAN * self.threshold / 100)
        tx = self.cx + (self.r + 5) * math.cos(ang)
        ty = self.cy - (self.r + 5) * math.sin(ang)
        self.create_oval(tx - 3, ty - 3, tx + 3, ty + 3,
                         fill=RED, outline="", tags="mk")

        self.create_text(self.cx, self.cy - 6,
                         text=f"{self.value:.1f} %",
                         fill=c, font=("Consolas", 17, "bold"), tags="tv")
        self.create_text(self.cx, self.cy + 17, text=self.label,
                         fill=FG0, font=("Segoe UI", 9), tags="tl")

    def set_threshold(self, t):
        self.threshold = t


# ===================================================================
#  SETTINGS DIALOG
# ===================================================================

class SettingsDialog(tk.Toplevel):

    def __init__(self, parent, thresholds, email_cfg):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("480x560")
        self.resizable(False, False)
        self.configure(bg=BG0)
        self.transient(parent)
        self.grab_set()
        self._thresh = dict(thresholds)
        self._email  = dict(email_cfg)
        self._saved  = False
        self._build()
        self._centre(parent)

    def _centre(self, p):
        self.update_idletasks()
        x = p.winfo_x() + (p.winfo_width()  - self.winfo_width())  // 2
        y = p.winfo_y() + (p.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _sec(self, t):
        tk.Label(self, text=t, bg=BG0, fg=ACC,
                 font=("Segoe UI", 11, "bold")).pack(
                     anchor="w", padx=22, pady=(16, 6))

    def _card(self):
        f = tk.Frame(self, bg=BG2, padx=14, pady=10)
        f.pack(fill="x", padx=22)
        return f

    def _row(self, p, label, default, show=""):
        r = tk.Frame(p, bg=BG2); r.pack(fill="x", pady=3)
        tk.Label(r, text=label, width=18, anchor="w", bg=BG2,
                 fg=FG1, font=("Segoe UI", 10)).pack(side="left")
        v = tk.StringVar(value=str(default))
        tk.Entry(r, textvariable=v, width=28, show=show, bg=BG1,
                 fg=FG2, insertbackground="white", relief="flat",
                 font=("Consolas", 10)).pack(side="right")
        return v

    def _build(self):
        self._sec("⚙  Alert Thresholds")
        c = self._card()
        self._tv = {k: self._row(c, f"{k.upper()} usage (%)", v)
                    for k, v in self._thresh.items()}

        self._sec("📧  Email Alerts")
        c2 = self._card()
        self._eon = tk.BooleanVar(value=self._email["enabled"])
        tk.Checkbutton(c2, text="Enable email alerts",
                       variable=self._eon, bg=BG2, fg=FG1,
                       selectcolor=BG1, activebackground=BG2,
                       activeforeground=FG1,
                       font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 6))
        self._ev = {}
        for lbl, key, sh in [
            ("SMTP Server",     "smtp_server",     ""),
            ("SMTP Port",       "smtp_port",       ""),
            ("Sender Email",    "sender_email",    ""),
            ("Sender Password", "sender_password", "•"),
            ("Recipient Email", "recipient_email", ""),
        ]:
            self._ev[key] = self._row(c2, lbl,
                                      self._email.get(key, ""), sh)

        bf = tk.Frame(self, bg=BG0); bf.pack(pady=22)
        tk.Button(bf, text="  Save  ", command=self._save, bg=ACC,
                  fg=BG0, font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=18, pady=4, cursor="hand2").pack(side="left", padx=8)
        tk.Button(bf, text="  Cancel  ", command=self.destroy, bg=BG2,
                  fg=FG1, font=("Segoe UI", 10), relief="flat",
                  padx=18, pady=4, cursor="hand2").pack(side="left", padx=8)

    def _save(self):
        try:
            for k in ("cpu", "ram", "disk"):
                v = float(self._tv[k].get())
                if not 0 < v <= 100:
                    raise ValueError(f"{k.upper()} must be 1–100")
                self._thresh[k] = v
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e), parent=self)
            return
        self._email["enabled"] = self._eon.get()
        for k, var in self._ev.items():
            self._email[k] = var.get()
        if self._email["enabled"]:
            miss = [k for k in ("smtp_server", "sender_email",
                                "sender_password", "recipient_email")
                    if not self._email.get(k)]
            if miss:
                messagebox.showwarning("Incomplete",
                    "Fill in all email fields or disable the toggle.",
                    parent=self)
                return
        self._saved = True
        self.destroy()

    @property
    def thresholds(self):
        return self._thresh if self._saved else None

    @property
    def email_config(self):
        return self._email if self._saved else None


# ===================================================================
#  LOG VIEWER DIALOG
# ===================================================================

class LogViewerDialog(tk.Toplevel):

    def __init__(self, parent, path):
        super().__init__(parent)
        self.title("Performance Logs")
        self.geometry("800x520")
        self.configure(bg=BG0)
        self.transient(parent)
        self.path = path
        self._build()
        self.after(100, self._load)

    def _build(self):
        tb = tk.Frame(self, bg=BG1, pady=6); tb.pack(fill="x")
        for txt, cmd, bg_c in [
            ("🔄 Refresh", self._load, ACC),
            ("📁 Open File", self._open, BG2),
            ("🗑  Clear", self._clear, RED),
        ]:
            tk.Button(tb, text=txt, command=cmd, bg=bg_c,
                      fg=BG0 if bg_c == ACC else FG2,
                      font=("Segoe UI", 9, "bold"), relief="flat",
                      padx=12, cursor="hand2").pack(side="left", padx=6)

        s = ttk.Style(); s.theme_use("clam")
        s.configure("L.Treeview", background=BG2, foreground=FG1,
                    fieldbackground=BG2, font=("Consolas", 9), rowheight=22)
        s.configure("L.Treeview.Heading", background=BG1, foreground=ACC,
                    font=("Segoe UI", 9, "bold"))
        s.map("L.Treeview", background=[("selected", "#3a3a6a")])

        w = tk.Frame(self, bg=BG0)
        w.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree = ttk.Treeview(w, show="headings", style="L.Treeview")
        vsb = ttk.Scrollbar(w, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def _load(self):
        self.tree.delete(*self.tree.get_children())
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, newline="") as f:
                rd = csv.reader(f)
                hdr = next(rd, None)
                if not hdr:
                    return
                self.tree["columns"] = list(hdr)
                for h in hdr:
                    self.tree.heading(h, text=h.title())
                    w = 175 if h == "timestamp" else (
                        195 if h == "status" else 85)
                    self.tree.column(h, width=w, anchor="center",
                                     minwidth=50)
                for row in reversed(list(rd)):
                    pad = row + [""] * (len(hdr) - len(row))
                    self.tree.insert("", "end", values=pad[:len(hdr)])
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _open(self):
        if os.path.isfile(self.path):
            {"win32": lambda: os.startfile(self.path),
             "darwin": lambda: os.system(f'open "{self.path}"')
             }.get(sys.platform,
                   lambda: os.system(f'xdg-open "{self.path}"'))()

    def _clear(self):
        if messagebox.askyesno("Confirm", "Delete all log entries?",
                               parent=self):
            try:
                with open(self.path, "w", newline="") as f:
                    f.write("")
                self._load()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self)


# ===================================================================
#  MAIN APPLICATION
# ===================================================================

class SystemMonitorApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("System Resource Monitor")
        self.geometry("960x760")
        self.minsize(880, 680)
        self.configure(bg=BG0)
        self.protocol("WM_DELETE_WINDOW", self._quit)

        self.thresholds = dict(DEFAULT_THRESHOLDS)
        self.email_cfg  = dict(DEFAULT_EMAIL)
        self.running    = False
        self._stop      = threading.Event()
        self._thread    = None
        self._tick      = 0

        self.drives = self._detect_drives()

        self.history = {k: deque(maxlen=MAX_HIST)
                        for k in ("ts", "cpu", "ram")}
        self.drive_hist = {}
        self._last_alert = {"cpu": 0.0, "ram": 0.0}

        self._make_menu()
        self._make_toolbar()
        self._make_gauges()
        self._make_drive_text()
        self._make_graph()
        self._make_statusbar()
        self._init_log()

    # ── drive detection ───────────────────────────────────────────

    def _detect_drives(self):
        drives = []
        for p in psutil.disk_partitions():
            if p.fstype in SKIP_FS:
                continue
            if "cdrom" in p.opts.lower():
                continue
            if any(p.mountpoint.startswith(pr) for pr in SKIP_PREFIXES):
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except (PermissionError, OSError):
                continue
            if u.total < 100_000_000:
                continue
            drives.append({
                "mountpoint": p.mountpoint,
                "device": p.device,
                "label": self._drv_label(p),
            })
        return drives

    @staticmethod
    def _drv_label(p):
        return p.mountpoint.replace("\\", "") if sys.platform == "win32" \
               else p.mountpoint

    @staticmethod
    def _gb(b):
        return f"{b / 1024**3:.1f} GB"

    # ── menu ──────────────────────────────────────────────────────

    def _m(self, p, lbl):
        m = tk.Menu(p, tearoff=0, bg=BG1, fg=FG1,
                    activebackground=ACC, activeforeground=BG0,
                    relief="flat")
        p.add_cascade(label=lbl, menu=m)
        return m

    def _make_menu(self):
        mb = tk.Menu(self, bg=BG1, fg=FG1,
                     activebackground=ACC, activeforeground=BG0,
                     relief="flat")
        self.config(menu=mb)

        fm = self._m(mb, "File")
        fm.add_command(label="▶  Start Monitoring", command=self.start)
        fm.add_command(label="⏸  Stop Monitoring",  command=self.stop)
        fm.add_separator()
        fm.add_command(label="Open Log File", command=self._open_log)
        fm.add_separator()
        fm.add_command(label="Exit", command=self._quit)

        sm = self._m(mb, "Settings")
        sm.add_command(label="Thresholds & Email…", command=self._settings)

        vm = self._m(mb, "View")
        vm.add_command(label="View Logs…",   command=self._view_logs)
        vm.add_command(label="Toggle Graph", command=self._toggle_graph)

        hm = self._m(mb, "Help")
        hm.add_command(label="About", command=lambda: messagebox.showinfo(
            "About",
            "System Resource Monitor  v2.1\n\n"
            "CPU / RAM / Multi-Disk dashboard\n"
            "with alerts, logging & live graphs.\n\n"
            "Python · Tkinter · psutil · matplotlib",
            parent=self))

    # ── toolbar ───────────────────────────────────────────────────

    def _make_toolbar(self):
        bar = tk.Frame(self, bg=BG1, pady=8); bar.pack(fill="x")
        self.btn_go = tk.Button(
            bar, text="▶  Start Monitoring", command=self.start,
            bg=ACC, fg=BG0, font=("Segoe UI", 10, "bold"),
            relief="flat", padx=14, pady=3, cursor="hand2")
        self.btn_go.pack(side="left", padx=(14, 4))
        self.btn_st = tk.Button(
            bar, text="⏸  Stop", command=self.stop,
            bg=BG2, fg=FG1, font=("Segoe UI", 10),
            relief="flat", padx=14, pady=3, cursor="hand2",
            state="disabled")
        self.btn_st.pack(side="left", padx=4)
        self.lbl_st = tk.Label(bar, text="● IDLE", bg=BG1, fg=FG0,
                               font=("Segoe UI", 10, "bold"))
        self.lbl_st.pack(side="left", padx=18)
        self.lbl_al = tk.Label(bar, text="", bg=BG1, fg=RED,
                               font=("Segoe UI", 9))
        self.lbl_al.pack(side="right", padx=14)
        self.lbl_ln = tk.Label(bar, text="Logs: 0", bg=BG1, fg=FG0,
                               font=("Consolas", 9))
        self.lbl_ln.pack(side="right", padx=8)

    # ── three circular gauges ─────────────────────────────────────

    def _make_gauges(self):
        gf = tk.Frame(self, bg=BG0); gf.pack(pady=(10, 0))

        self.g_cpu  = CircularGauge(gf, label="CPU",  color=ACC,
                                    threshold=self.thresholds["cpu"])
        self.g_ram  = CircularGauge(gf, label="RAM",  color=GRN,
                                    threshold=self.thresholds["ram"])
        self.g_disk = CircularGauge(gf, label="DISK", color=AMB,
                                    threshold=self.thresholds["disk"])

        for g in (self.g_cpu, self.g_ram, self.g_disk):
            g.pack(side="left", padx=30)

        # small info text under each gauge
        self.lbl_ci = tk.Label(gf, text="", bg=BG0, fg=FG0,
                               font=("Consolas", 8))
        self.lbl_ci.place(relx=0.5, rely=1.0, y=-2,
                          anchor="s", x=-230)
        self.lbl_ri = tk.Label(gf, text="", bg=BG0, fg=FG0,
                               font=("Consolas", 8))
        self.lbl_ri.place(relx=0.5, rely=1.0, y=-2,
                          anchor="s", x=0)
        self.lbl_di = tk.Label(gf, text="peak across all drives",
                               bg=BG0, fg=FG0, font=("Consolas", 8))
        self.lbl_di.place(relx=0.5, rely=1.0, y=-2,
                          anchor="s", x=230)

    # ── per-drive detail text (compact) ───────────────────────────

    def _make_drive_text(self):
        tk.Frame(self, bg=BG2, height=1).pack(fill="x", padx=60,
                                               pady=(12, 4))
        self.lbl_drives = tk.Label(
            self, text="", bg=BG0, fg=FG1,
            font=("Consolas", 9), justify="left", anchor="w")
        self.lbl_drives.pack(fill="x", padx=60)
        self._refresh_drive_text({})

    def _refresh_drive_text(self, drive_usages):
        parts = []
        for i, d in enumerate(self.drives):
            lbl = d["label"]
            pct = drive_usages.get(lbl)
            col = DRV_COLORS[i % len(DRV_COLORS)]
            if pct is not None:
                parts.append(f"  {lbl:8s} {pct:5.1f}%")
            else:
                parts.append(f"  {lbl:8s}  —")
        txt = "All Drives\n" + "\n".join(parts) if parts else "No drives detected"
        self.lbl_drives.config(text=txt)

    # ── graph ─────────────────────────────────────────────────────

    def _make_graph(self):
        self.gf = tk.Frame(self, bg=BG0)
        self.gf.pack(fill="both", expand=True, padx=14, pady=(4, 4))
        if HAS_MPL:
            self.fig = Figure(figsize=(8, 2.4), dpi=100, facecolor=BG0)
            self.ax  = self.fig.add_subplot(111)
            self._ax_style()
            self.fig.tight_layout(pad=1.5)
            self.mc = FigureCanvasTkAgg(self.fig, self.gf)
            self.mc.get_tk_widget().pack(fill="both", expand=True)
        else:
            tk.Label(self.gf,
                     text="pip install matplotlib  for live graphs",
                     bg=BG0, fg=FG0,
                     font=("Segoe UI", 11)).pack(expand=True)

    def _ax_style(self):
        ax = self.ax
        ax.set_facecolor(BG2)
        ax.tick_params(colors=FG0, labelsize=8)
        for s in ax.spines.values():
            s.set_color(BG2)
        ax.set_ylim(0, 105)
        ax.set_ylabel("Usage %", color=FG0, fontsize=9)
        ax.grid(True, color=BG2, alpha=0.6, linewidth=0.5)

    # ── status bar ────────────────────────────────────────────────

    def _make_statusbar(self):
        sb = tk.Frame(self, bg=BG1, pady=3); sb.pack(fill="x",
                                                       side="bottom")
        tk.Label(sb, bg=BG1, fg=FG0, font=("Consolas", 8),
                 text=f"Interval: {INTERVAL}s  ·  "
                      f"Drive re-check: every {DRIVE_RECHECK}s  ·  "
                      f"{LOG_FILE}").pack(side="left", padx=10)

    # ===================================================================
    #  LOGGING
    # ===================================================================

    def _init_log(self):
        try:
            if not os.path.isfile(LOG_FILE) or \
               os.path.getsize(LOG_FILE) == 0:
                labels = [d["label"] for d in self.drives]
                with open(LOG_FILE, "w", newline="") as f:
                    csv.writer(f).writerow(
                        ["timestamp", "cpu", "ram"] + labels + ["status"])
            self._log_n()
        except Exception as e:
            print(f"[WARN] log init: {e}")

    def _write_log(self, cpu, ram, dus, status):
        try:
            with open(LOG_FILE, "a", newline="") as f:
                w = csv.writer(f)
                row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                       f"{cpu:.1f}", f"{ram:.1f}"]
                for d in self.drives:
                    row.append(f"{dus.get(d['label'], 0):.1f}")
                row.append(status)
                w.writerow(row)
            self._log_n()
        except Exception as e:
            print(f"[WARN] log write: {e}")

    def _log_n(self):
        try:
            n = max(0, sum(1 for _ in open(LOG_FILE)) - 1)
            self.lbl_ln.config(text=f"Logs: {n}")
        except Exception:
            pass

    def _open_log(self):
        if os.path.isfile(LOG_FILE):
            {"win32": lambda: os.startfile(LOG_FILE),
             "darwin": lambda: os.system(f'open "{LOG_FILE}"')
             }.get(sys.platform,
                   lambda: os.system(f'xdg-open "{LOG_FILE}"'))()

    # ===================================================================
    #  MONITORING LOOP
    # ===================================================================
    def start(self):
        if self.running:
            return
        self.running = True
        self._stop.clear()
        self._tick = 0
        self.btn_go.config(state="disabled")
        self.btn_st.config(state="normal")
        self.lbl_st.config(text="● MONITORING", fg=GRN)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._stop.set()
        self.btn_go.config(state="normal")
        self.btn_st.config(state="disabled")
        self.lbl_st.config(text="● STOPPED", fg=AMB)

    def _loop(self):
        while not self._stop.is_set():
            try:
                cpu = psutil.cpu_percent(interval=0.4)
                vm  = psutil.virtual_memory()
                ram = vm.percent

                dus = {}
                ddetails = {}
                for d in self.drives:
                    try:
                        u = psutil.disk_usage(d["mountpoint"])
                        dus[d["label"]] = u.percent
                        ddetails[d["label"]] = u
                    except (PermissionError, OSError):
                        dus[d["label"]] = 0.0

                # gauge value = peak across all drives
                peak_disk = max(dus.values()) if dus else 0.0

                alerts = self._check(cpu, ram, dus)
                status = "; ".join(alerts) if alerts else "OK"

                self._write_log(cpu, ram, dus, status)

                self.history["ts"].append(
                    datetime.now().strftime("%H:%M:%S"))
                self.history["cpu"].append(cpu)
                self.history["ram"].append(ram)
                for lbl, val in dus.items():
                    if lbl not in self.drive_hist:
                        self.drive_hist[lbl] = deque(maxlen=MAX_HIST)
                    self.drive_hist[lbl].append(val)

                self._tick += 1
                if self._tick % DRIVE_RECHECK == 0:
                    self._maybe_redetect()

                redraw = (self._tick % GRAPH_EVERY == 0)
                self.after(0, self._ui, cpu, ram, peak_disk,
                           dus, ddetails, alerts, redraw)

            except Exception as e:
                print(f"[ERR] loop: {e}")

            self._stop.wait(INTERVAL)

    # ── hot-swap drives ───────────────────────────────────────────

    def _maybe_redetect(self):
        new = self._detect_drives()
        if [d["label"] for d in new] != \
           [d["label"] for d in self.drives]:
            self.drives = new
            self.after(0, self._rebuild)

    def _rebuild(self):
        self._refresh_drive_text({})
        self._init_log()

    # ── alerts ────────────────────────────────────────────────────

    def _check(self, cpu, ram, dus):
        now = time.time()
        fired = []
        for key, val, nm in [("cpu", cpu, "CPU"), ("ram", ram, "RAM")]:
            if val >= self.thresholds[key]:
                if now - self._last_alert[key] >= ALERT_CD:
                    self._last_alert[key] = now
                    fired.append(f"{nm} ALERT ({val:.1f}%)")
                    self._notify(nm, val)
        for lbl, val in dus.items():
            ak = f"d_{lbl}"
            if ak not in self._last_alert:
                self._last_alert[ak] = 0
            if val >= self.thresholds["disk"]:
                if now - self._last_alert[ak] >= ALERT_CD:
                    self._last_alert[ak] = now
                    fired.append(f"Disk {lbl} ALERT ({val:.1f}%)")
                    self._notify(f"Disk {lbl}", val)
        return fired

    def _notify(self, name, value):
        msg = f"{name} usage {value:.1f}% exceeds threshold"
        if HAS_PLYER:
            try:
                notification.notify(title="System Monitor Alert",
                                    message=msg, app_name="SysMon",
                                    timeout=8)
            except Exception:
                pass
        if self.email_cfg.get("enabled"):
            threading.Thread(target=self._email,
                             args=(name, value), daemon=True).start()

    def _email(self, name, value):
        try:
            c = self.email_cfg
            host = (os.uname().nodename if hasattr(os, "uname")
                    else os.getenv("COMPUTERNAME", "?"))
            body = (f"System Resource Alert\n{'─'*35}\n"
                    f"Resource : {name}\n"
                    f"Current  : {value:.1f}%\n"
                    f"Time     : {datetime.now():%Y-%m-%d %H:%M:%S}\n"
                    f"Host     : {host}\n")
            m = MIMEText(body)
            m["Subject"] = f"⚠ {name} Alert: {value:.1f}%"
            m["From"] = c["sender_email"]
            m["To"]   = c["recipient_email"]
            with smtplib.SMTP(c["smtp_server"], int(c["smtp_port"])) as s:
                s.starttls()
                s.login(c["sender_email"], c["sender_password"])
                s.send_message(m)
        except Exception as e:
            print(f"[ERR] email: {e}")

    # ── GUI refresh ───────────────────────────────────────────────

    def _ui(self, cpu, ram, peak_disk, dus, ddetails, alerts, rgraph):
        self.g_cpu.set_threshold(self.thresholds["cpu"])
        self.g_cpu.set_value(cpu)
        self.g_ram.set_threshold(self.thresholds["ram"])
        self.g_ram.set_value(ram)
        self.g_disk.set_threshold(self.thresholds["disk"])
        self.g_disk.set_value(peak_disk)

        self.lbl_ci.config(text=f"{psutil.cpu_count()} cores")
        vm = psutil.virtual_memory()
        self.lbl_ri.config(text=f"{self._gb(vm.used)} / {self._gb(vm.total)}")

        # find which drive is the peak
        peak_lbl = ""
        for lbl, val in dus.items():
            if val == peak_disk:
                peak_lbl = lbl
                break
        self.lbl_di.config(text=f"peak: {peak_lbl}")

        self._refresh_drive_text(dus)

        self.lbl_al.config(
            text=("⚠  " + "  |  ".join(alerts)) if alerts else "")

        if HAS_MPL and rgraph and len(self.history["ts"]) > 2:
            self._draw()

    def _draw(self):
        try:
            ax = self.ax; ax.clear(); self._ax_style()
            ts = list(self.history["ts"])
            x  = range(len(ts))
            step = max(1, len(ts) // 8)

            ax.plot(x, list(self.history["cpu"]),
                    color=ACC, lw=1.5, label="CPU", alpha=0.9)
            ax.plot(x, list(self.history["ram"]),
                    color=GRN, lw=1.5, label="RAM", alpha=0.9)

            for i, d in enumerate(self.drives):
                lbl = d["label"]
                if lbl in self.drive_hist:
                    ax.plot(x, list(self.drive_hist[lbl]),
                            color=DRV_COLORS[i % len(DRV_COLORS)],
                            lw=1.2, label=lbl, alpha=0.85, ls="--")

            for key, col in [("cpu", ACC), ("ram", GRN), ("disk", AMB)]:
                ax.axhline(y=self.thresholds[key], color=col,
                           ls=":", alpha=0.25, lw=0.8)

            nc = min(2 + len(self.drives), 6)
            ax.legend(loc="upper left", fontsize=7, ncol=nc,
                      facecolor=BG2, edgecolor=BG2, labelcolor=FG1)
            ax.set_xticks(list(x)[::step])
            ax.set_xticklabels(
                [ts[i] for i in range(0, len(ts), step)],
                rotation=30, fontsize=7)
            self.fig.tight_layout(pad=1.5)
            self.mc.draw_idle()
        except Exception:
            pass

    # ── dialogs ───────────────────────────────────────────────────

    def _settings(self):
        was = self.running
        if was:
            self.stop()
        dlg = SettingsDialog(self, self.thresholds, self.email_cfg)
        self.wait_window(dlg)
        if dlg.thresholds:
            self.thresholds = dlg.thresholds
        if dlg.email_config:
            self.email_cfg = dlg.email_config
        if was:
            self.start()

    def _view_logs(self):
        LogViewerDialog(self, LOG_FILE)

    def _toggle_graph(self):
        if self.gf.winfo_ismapped():
            self.gf.pack_forget()
        else:
            self.gf.pack(fill="both", expand=True, padx=14, pady=(4, 4))

    def _quit(self):
        self.stop()
        time.sleep(0.15)
        self.destroy()

# ===================================================================
if __name__ == "__main__":
    SystemMonitorApp().mainloop()
