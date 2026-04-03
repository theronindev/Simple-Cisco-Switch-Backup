"""
Cisco Switch Config Backup  —  v3.0
Author : The Ronin Dev  (https://www.theronindev.dev)
Stack  : CustomTkinter · Netmiko · pystray · schedule · plyer

Features:
  • Per-switch credentials + global apply
  • System-tray: closes to tray, right-click menu
  • Auto-schedule: daily or weekly at a chosen time
  • Settings persisted to JSON between sessions
  • Failed backups → log file + Windows toast notification
"""

import os
import re
import json
import time
import logging
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from typing import Optional

import customtkinter as ctk
import schedule
import pystray
from PIL import Image, ImageDraw
from plyer import notification
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
)


# ══════════════════════════════════════════════════════════════════════════════
# Theme
# ══════════════════════════════════════════════════════════════════════════════
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

ACCENT       = "#00A8E8"
ACCENT_HOV   = "#0090C8"
BG_DARK      = "#0D1117"
BG_CARD      = "#161B22"
BG_ROW_ODD   = "#1A2030"
BG_ROW_EVEN  = "#161B22"
TEXT_PRI     = "#E6EDF3"
TEXT_DIM     = "#8B949E"
SUCCESS      = "#3FB950"
ERROR        = "#F85149"
WARNING      = "#D29922"
BORDER       = "#30363D"
LINK         = "#58A6FF"

FONT_MONO    = ("Consolas",          12)
FONT_LABEL   = ("Segoe UI",          12)
FONT_SEMIB   = ("Segoe UI Semibold", 13)
FONT_HEAD    = ("Segoe UI Bold",     16)

DAYS_OF_WEEK  = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]
SETTINGS_FILE = "cisco_backup_settings.json"


# ══════════════════════════════════════════════════════════════════════════════
# File logger
# ══════════════════════════════════════════════════════════════════════════════
_fh = logging.FileHandler("cisco_backup.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  [%(levelname)s]  %(message)s"))
logger = logging.getLogger("CiscoBackup")
logger.setLevel(logging.DEBUG)
logger.addHandler(_fh)


# ══════════════════════════════════════════════════════════════════════════════
# Settings helpers
# ══════════════════════════════════════════════════════════════════════════════
def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"save_settings failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Misc helpers
# ══════════════════════════════════════════════════════════════════════════════
def get_hostname(config: str, fallback_ip: str) -> str:
    m = re.search(r"^hostname\s+(\S+)", config, re.MULTILINE)
    return m.group(1) if m else fallback_ip.replace(".", "_")


def make_tray_image() -> Image.Image:
    """Draw a minimal tray icon with Pillow — no external file needed."""
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=(0, 168, 232))
    for y in [18, 30, 42]:                         # three switch-port lines
        d.rectangle([14, y, 48, y + 5], fill="white")
        d.ellipse([48, y - 1, 56, y + 6], fill="white")
    return img


# ══════════════════════════════════════════════════════════════════════════════
# Switch row widget
# ══════════════════════════════════════════════════════════════════════════════
class SwitchRow(ctk.CTkFrame):
    def __init__(self, parent, index: int, on_delete, **kwargs):
        super().__init__(parent, **kwargs)
        self.index     = index
        self.on_delete = on_delete
        self._repaint()

        self._lbl_num = ctk.CTkLabel(
            self, text=f"#{index + 1:02d}", font=("Consolas", 11),
            text_color=TEXT_DIM, width=32)
        self._lbl_num.grid(row=0, column=0, padx=(10, 4), pady=8)

        self.e_ip = ctk.CTkEntry(
            self, placeholder_text="IP Address", width=160,
            font=FONT_MONO, fg_color=BG_DARK, border_color=BORDER,
            text_color=TEXT_PRI)
        self.e_ip.grid(row=0, column=1, padx=4, pady=8)

        self.e_user = ctk.CTkEntry(
            self, placeholder_text="Username", width=130,
            font=FONT_MONO, fg_color=BG_DARK, border_color=BORDER,
            text_color=TEXT_PRI)
        self.e_user.grid(row=0, column=2, padx=4, pady=8)

        self.e_pass = ctk.CTkEntry(
            self, placeholder_text="Password", width=130, show="•",
            font=FONT_MONO, fg_color=BG_DARK, border_color=BORDER,
            text_color=TEXT_PRI)
        self.e_pass.grid(row=0, column=3, padx=4, pady=8)

        self._dot = ctk.CTkLabel(
            self, text="●", text_color=TEXT_DIM,
            font=("Segoe UI", 14), width=22)
        self._dot.grid(row=0, column=4, padx=(6, 2), pady=8)

        ctk.CTkButton(
            self, text="✕", width=30, height=28,
            fg_color="transparent", hover_color="#2D1F1F",
            text_color=ERROR, font=("Segoe UI Bold", 13),
            command=lambda: self.on_delete(self)
        ).grid(row=0, column=5, padx=(2, 8), pady=8)

    def _repaint(self):
        self.configure(
            fg_color=BG_ROW_ODD if self.index % 2 == 0 else BG_ROW_EVEN,
            corner_radius=8)

    def get_data(self) -> dict:
        return {"ip":       self.e_ip.get().strip(),
                "username": self.e_user.get().strip(),
                "password": self.e_pass.get().strip()}

    def set_data(self, ip="", username="", password=""):
        for entry, val in [(self.e_ip, ip), (self.e_user, username), (self.e_pass, password)]:
            entry.delete(0, "end")
            entry.insert(0, val)

    def set_credentials(self, username: str, password: str):
        self.e_user.delete(0, "end"); self.e_user.insert(0, username)
        self.e_pass.delete(0, "end"); self.e_pass.insert(0, password)

    def set_status(self, status: str):
        colors = {"idle": TEXT_DIM, "running": WARNING, "ok": SUCCESS, "error": ERROR}
        self._dot.configure(text_color=colors.get(status, TEXT_DIM))

    def update_index(self, i: int):
        self.index = i
        self._lbl_num.configure(text=f"#{i + 1:02d}")
        self._repaint()


# ══════════════════════════════════════════════════════════════════════════════
# Main application
# ══════════════════════════════════════════════════════════════════════════════
class CiscoBackupApp(ctk.CTk):

    DEFAULT_ROWS = 7

    def __init__(self):
        super().__init__()
        self.title("Cisco Switch Config Backup")
        self.geometry("840x940")
        self.minsize(800, 720)
        self.configure(fg_color=BG_DARK)

        self.output_dir  = tk.StringVar(value=os.path.join(os.getcwd(), "switch_configs"))
        self.rows: list[SwitchRow] = []
        self._running    = False
        self._tray: Optional[pystray.Icon] = None

        # schedule vars
        self.sv_enabled = tk.BooleanVar(value=False)
        self.sv_mode    = tk.StringVar(value="Daily")
        self.sv_day     = tk.StringVar(value="Monday")
        self.sv_hour    = tk.StringVar(value="02")
        self.sv_minute  = tk.StringVar(value="00")
        self.sv_next    = tk.StringVar(value="—")

        self._build_ui()
        self._restore_settings()
        self._start_scheduler_thread()
        self._setup_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ══════════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)   # log expands

        self._build_header()
        self._build_global_creds()
        self._build_switch_list()
        self._build_schedule_panel()
        self._build_log()
        self._build_run_button()

    # ── Header ────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(hdr, text="⚙", font=("Segoe UI", 30),
                     text_color=ACCENT).grid(row=0, column=0, padx=(20, 10), pady=14)

        titles = ctk.CTkFrame(hdr, fg_color="transparent")
        titles.grid(row=0, column=1, sticky="w", pady=10)

        ctk.CTkLabel(titles, text="Cisco Switch Config Backup",
                     font=FONT_HEAD, text_color=TEXT_PRI).pack(anchor="w")

        dev = ctk.CTkLabel(titles, text="by: The Ronin Dev",
                           font=("Segoe UI", 10), text_color=LINK, cursor="hand2")
        dev.pack(anchor="w")
        dev.bind("<Button-1>", lambda e: webbrowser.open("https://www.theronindev.dev"))
        dev.bind("<Enter>", lambda e: dev.configure(
            text_color="#ffffff", font=("Segoe UI", 10, "underline")))
        dev.bind("<Leave>", lambda e: dev.configure(
            text_color=LINK, font=("Segoe UI", 10)))


    # ── Global credentials ────────────────────────────────────────────────────
    def _build_global_creds(self):
        f = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        f.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 0))
        f.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(f, text="Global Credentials",
                     font=FONT_SEMIB, text_color=ACCENT
                     ).grid(row=0, column=0, padx=(16, 20), pady=12, sticky="w")

        ctk.CTkLabel(f, text="Username:", font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=1, padx=(0, 4))
        self.g_user = ctk.CTkEntry(f, placeholder_text="e.g. admin", width=130,
                                   font=FONT_MONO, fg_color=BG_DARK,
                                   border_color=BORDER, text_color=TEXT_PRI)
        self.g_user.grid(row=0, column=2, padx=(0, 14), pady=12)

        ctk.CTkLabel(f, text="Password:", font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=3, padx=(0, 4))
        self.g_pass = ctk.CTkEntry(f, placeholder_text="••••••", width=130, show="•",
                                   font=FONT_MONO, fg_color=BG_DARK,
                                   border_color=BORDER, text_color=TEXT_PRI)
        self.g_pass.grid(row=0, column=4, padx=(0, 14), pady=12)

        ctk.CTkButton(f, text="Apply to All ↓", width=120, height=32,
                      fg_color=ACCENT, hover_color=ACCENT_HOV,
                      font=("Segoe UI Semibold", 12), text_color="white",
                      command=self._apply_global
                      ).grid(row=0, column=5, padx=(0, 16), pady=12)

    # ── Switch list ───────────────────────────────────────────────────────────
    def _build_switch_list(self):
        outer = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        outer.grid(row=2, column=0, sticky="nsew", padx=16, pady=(10, 0))
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, minsize=260, weight=0)

        # column headers
        hrow = ctk.CTkFrame(outer, fg_color="transparent")
        hrow.grid(row=0, column=0, sticky="ew", padx=8, pady=(10, 2))
        for col, (lbl, w) in enumerate(
                [("", 32), ("IP Address", 160), ("Username", 130),
                 ("Password", 130), ("", 22), ("", 30)]):
            ctk.CTkLabel(hrow, text=lbl, font=("Segoe UI Semibold", 11),
                         text_color=TEXT_DIM, width=w, anchor="w"
                         ).grid(row=0, column=col, padx=4)

        self.scroll = ctk.CTkScrollableFrame(
            outer, fg_color="transparent",
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=ACCENT)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        self.scroll.grid_columnconfigure(0, weight=1)

        # footer
        foot = ctk.CTkFrame(outer, fg_color="transparent")
        foot.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 12))
        foot.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(foot, text="＋  Add Switch", width=130, height=32,
                      fg_color="transparent", border_width=1,
                      border_color=ACCENT, text_color=ACCENT,
                      hover_color="#0A1A2A", font=("Segoe UI Semibold", 12),
                      command=self._add_row
                      ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(foot, text="Output folder:",
                     font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=1, padx=(20, 6), sticky="e")
        ctk.CTkEntry(foot, textvariable=self.output_dir, width=240,
                     font=("Consolas", 11), fg_color=BG_DARK,
                     border_color=BORDER, text_color=TEXT_PRI
                     ).grid(row=0, column=2, padx=(0, 6))
        ctk.CTkButton(foot, text="Browse", width=70, height=30,
                      fg_color=BG_DARK, hover_color=BG_ROW_ODD,
                      border_width=1, border_color=BORDER,
                      font=FONT_LABEL, text_color=TEXT_DIM,
                      command=self._browse_folder
                      ).grid(row=0, column=3)

    # ── Schedule panel ────────────────────────────────────────────────────────
    def _build_schedule_panel(self):
        sf = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        sf.grid(row=3, column=0, sticky="ew", padx=16, pady=(10, 0))
        sf.grid_columnconfigure(0, weight=1)

        # header
        hdr = ctk.CTkFrame(sf, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        hdr.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="🕐  Auto Schedule",
                     font=FONT_SEMIB, text_color=ACCENT).grid(row=0, column=0, sticky="w")
        ctk.CTkSwitch(hdr, text="Enable", variable=self.sv_enabled,
                      font=FONT_LABEL, text_color=TEXT_PRI,
                      progress_color=ACCENT, button_color="#FFFFFF",
                      command=self._on_sched_change
                      ).grid(row=0, column=1, sticky="e")

        # options
        opts = ctk.CTkFrame(sf, fg_color="transparent")
        opts.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))

        # Repeat mode
        ctk.CTkLabel(opts, text="Repeat:", font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkSegmentedButton(
            opts, values=["Daily", "Weekly"],
            variable=self.sv_mode, font=FONT_LABEL,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOV,
            unselected_color=BG_DARK, fg_color=BG_DARK,
            command=lambda _: self._on_sched_change()
        ).grid(row=0, column=1, padx=(0, 22))

        # Day (weekly only)
        self._lbl_day = ctk.CTkLabel(opts, text="Day:", font=FONT_LABEL, text_color=TEXT_DIM)
        self._lbl_day.grid(row=0, column=2, padx=(0, 6))
        self._day_menu = ctk.CTkOptionMenu(
            opts, variable=self.sv_day, values=DAYS_OF_WEEK, width=120,
            fg_color=BG_DARK, button_color=BORDER, button_hover_color=ACCENT,
            font=FONT_LABEL, text_color=TEXT_PRI,
            command=lambda _: self._on_sched_change())
        self._day_menu.grid(row=0, column=3, padx=(0, 22))

        # Time HH:MM
        ctk.CTkLabel(opts, text="Time (HH:MM):", font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=4, padx=(0, 6))
        tf = ctk.CTkFrame(opts, fg_color="transparent")
        tf.grid(row=0, column=5, padx=(0, 22))

        self._e_hour = ctk.CTkEntry(tf, textvariable=self.sv_hour, width=46,
                                    font=FONT_MONO, justify="center",
                                    fg_color=BG_DARK, border_color=BORDER,
                                    text_color=TEXT_PRI)
        self._e_hour.pack(side="left")
        ctk.CTkLabel(tf, text=":", font=("Segoe UI Bold", 16),
                     text_color=TEXT_DIM).pack(side="left", padx=2)
        self._e_min = ctk.CTkEntry(tf, textvariable=self.sv_minute, width=46,
                                   font=FONT_MONO, justify="center",
                                   fg_color=BG_DARK, border_color=BORDER,
                                   text_color=TEXT_PRI)
        self._e_min.pack(side="left")
        for w in (self._e_hour, self._e_min):
            w.bind("<FocusOut>", lambda e: self._on_sched_change())

        # Next run display
        ctk.CTkLabel(opts, text="Next run:", font=FONT_LABEL, text_color=TEXT_DIM
                     ).grid(row=0, column=6, padx=(0, 6))
        ctk.CTkLabel(opts, textvariable=self.sv_next,
                     font=("Consolas", 12), text_color=WARNING
                     ).grid(row=0, column=7)

        self._refresh_day_widget()

    # ── Log area ──────────────────────────────────────────────────────────────
    def _build_log(self):
        lf = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        lf.grid(row=4, column=0, sticky="nsew", padx=16, pady=(10, 0))
        lf.grid_columnconfigure(0, weight=1)
        lf.grid_rowconfigure(1, weight=1)

        lhdr = ctk.CTkFrame(lf, fg_color="transparent")
        lhdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        lhdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(lhdr, text="Output Log", font=FONT_SEMIB,
                     text_color=ACCENT).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(lhdr, text="Clear", width=56, height=24,
                      fg_color="transparent", border_width=1,
                      border_color=BORDER, text_color=TEXT_DIM,
                      hover_color=BG_ROW_ODD, font=("Segoe UI", 11),
                      command=self._clear_log
                      ).grid(row=0, column=1)

        self.log_box = ctk.CTkTextbox(lf, font=FONT_MONO, fg_color=BG_DARK,
                                      text_color=TEXT_PRI, border_width=0,
                                      wrap="word", state="disabled")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        for tag, color in [("ok", SUCCESS), ("error", ERROR),
                           ("warn", WARNING), ("info", ACCENT), ("dim", TEXT_DIM)]:
            self.log_box.tag_config(tag, foreground=color)

    # ── Run button ────────────────────────────────────────────────────────────
    def _build_run_button(self):
        self.btn_run = ctk.CTkButton(
            self, text="▶  Start Backup", height=46,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            font=("Segoe UI Bold", 14), text_color="white",
            command=self._start_backup)
        self.btn_run.grid(row=5, column=0, sticky="ew", padx=16, pady=12)

    # ══════════════════════════════════════════════════════════════════════════
    # Settings persist
    # ══════════════════════════════════════════════════════════════════════════
    def _restore_settings(self):
        s = load_settings()
        if not s:
            self._add_default_rows()
            return

        if "output_dir" in s:
            self.output_dir.set(s["output_dir"])

        switches = s.get("switches", [])
        if switches:
            for sw in switches:
                self._add_row()
                self.rows[-1].set_data(**sw)
        else:
            self._add_default_rows()

        sc = s.get("schedule", {})
        if sc:
            self.sv_enabled.set(sc.get("enabled", False))
            self.sv_mode.set(sc.get("mode", "Daily"))
            self.sv_day.set(sc.get("day", "Monday"))
            self.sv_hour.set(sc.get("hour", "02"))
            self.sv_minute.set(sc.get("minute", "00"))
            self._on_sched_change()

    def _collect_settings(self) -> dict:
        return {
            "output_dir": self.output_dir.get(),
            "switches":   [r.get_data() for r in self.rows if r.get_data()["ip"]],
            "schedule": {
                "enabled": self.sv_enabled.get(),
                "mode":    self.sv_mode.get(),
                "day":     self.sv_day.get(),
                "hour":    self.sv_hour.get(),
                "minute":  self.sv_minute.get(),
            },
        }

    def _save(self):
        save_settings(self._collect_settings())

    # ══════════════════════════════════════════════════════════════════════════
    # Schedule logic
    # ══════════════════════════════════════════════════════════════════════════
    def _on_sched_change(self, *_):
        self._refresh_day_widget()
        self._apply_schedule()
        self._refresh_next_run()
        self._save()

    def _refresh_day_widget(self):
        weekly = self.sv_mode.get() == "Weekly"
        self._lbl_day.configure(text_color=TEXT_DIM if weekly else BORDER)
        self._day_menu.configure(state="normal" if weekly else "disabled")

    def _valid_time(self) -> Optional[str]:
        try:
            h = int(self.sv_hour.get())
            m = int(self.sv_minute.get())
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except ValueError:
            pass
        return None

    def _apply_schedule(self):
        schedule.clear()
        if not self.sv_enabled.get():
            self.sv_next.set("—")
            return
        t = self._valid_time()
        if not t:
            self.sv_next.set("Invalid time")
            return
        if self.sv_mode.get() == "Daily":
            schedule.every().day.at(t).do(self._scheduled_backup)
        else:
            getattr(schedule.every(), self.sv_day.get().lower()).at(t).do(
                self._scheduled_backup)

    def _refresh_next_run(self):
        job = next(iter(schedule.jobs), None)
        if job and job.next_run:
            self.sv_next.set(job.next_run.strftime("%a %d %b  %H:%M"))
        else:
            self.sv_next.set("—")

    def _start_scheduler_thread(self):
        def _loop():
            while True:
                schedule.run_pending()
                self.after(0, self._refresh_next_run)
                time.sleep(30)
        threading.Thread(target=_loop, daemon=True).start()

    def _scheduled_backup(self):
        self._log("⏰  Scheduled backup started.", "info")
        pairs = [(r, r.get_data()) for r in self.rows if r.get_data()["ip"]]
        if not pairs:
            self._log("Scheduler: no switches configured.", "warn")
            return
        ok, failed = self._run_core(pairs)
        summary = f"Scheduled backup: ✓{ok} OK  ✗{len(failed)} failed"
        self._log(summary, "info" if not failed else "warn")
        self._toast("Cisco Backup — Scheduled", summary)
        for ip, err in failed:
            logger.error(f"[SCHEDULED] {ip}: {err}")
            self._toast("Cisco Backup — Error", f"{ip}: {err}")

    # ══════════════════════════════════════════════════════════════════════════
    # System tray
    # ══════════════════════════════════════════════════════════════════════════
    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show Window",    self._tray_show, default=True),
            pystray.MenuItem("Run Backup Now", lambda i, i2: threading.Thread(
                target=self._start_backup, daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",           self._tray_exit),
        )
        self._tray = pystray.Icon(
            "CiscoBackup", make_tray_image(), "Cisco Switch Backup", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _tray_show(self, *_):
        self.after(0, self.deiconify)
        self.after(0, self.lift)

    def _tray_exit(self, *_):
        self._save()
        if self._tray:
            self._tray.stop()
        self.after(0, self.destroy)

    def _on_close(self):
        """X button → save & hide to tray."""
        self._save()
        self.withdraw()

    # ══════════════════════════════════════════════════════════════════════════
    # Row management
    # ══════════════════════════════════════════════════════════════════════════
    def _add_default_rows(self):
        for _ in range(self.DEFAULT_ROWS):
            self._add_row()

    def _add_row(self):
        idx = len(self.rows)
        row = SwitchRow(self.scroll, idx, self._delete_row)
        row.grid(row=idx, column=0, sticky="ew", pady=2)
        self.rows.append(row)

    def _delete_row(self, row: SwitchRow):
        if len(self.rows) == 1:
            return
        row.grid_forget()
        row.destroy()
        self.rows.remove(row)
        for i, r in enumerate(self.rows):
            r.grid(row=i, column=0, sticky="ew", pady=2)
            r.update_index(i)

    # ══════════════════════════════════════════════════════════════════════════
    # Action helpers
    # ══════════════════════════════════════════════════════════════════════════
    def _apply_global(self):
        u, p = self.g_user.get().strip(), self.g_pass.get().strip()
        if not u and not p:
            self._log("Global fields are empty — nothing applied.", "warn")
            return
        for r in self.rows:
            r.set_credentials(u, p)
        self._log(f"Global credentials applied to {len(self.rows)} switches.", "info")

    def _browse_folder(self):
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.output_dir.set(d)

    def _log(self, msg: str, tag: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        def _do():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{ts}] ", "dim")
            self.log_box.insert("end", msg + "\n", tag)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _toast(self, title: str, msg: str):
        try:
            notification.notify(title=title, message=msg,
                                app_name="Cisco Backup", timeout=6)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # Backup core
    # ══════════════════════════════════════════════════════════════════════════
    def _start_backup(self):
        if self._running:
            return
        pairs = [(r, r.get_data()) for r in self.rows if r.get_data()["ip"]]
        if not pairs:
            self._log("No switches configured.", "warn")
            return
        self._running = True
        self.after(0, lambda: self.btn_run.configure(
            state="disabled", text="⏳  Running…"))
        for r, _ in pairs:
            r.set_status("idle")
        threading.Thread(target=self._backup_thread, args=(pairs,), daemon=True).start()

    def _backup_thread(self, pairs):
        ok, failed = self._run_core(pairs)
        self._log("─" * 52, "dim")
        self._log(f"Done.  ✓ {ok} succeeded   ✗ {len(failed)} failed",
                  "info" if not failed else "warn")
        self._running = False
        self.after(0, lambda: self.btn_run.configure(
            state="normal", text="▶  Start Backup"))

    def _run_core(self, pairs: list) -> tuple:
        out = self.output_dir.get().strip() or "switch_configs"
        os.makedirs(out, exist_ok=True)
        ok, failed = 0, []

        self._log(f"Backing up {len(pairs)} switch(es) …", "info")
        self._log(f"Output: {out}", "dim")
        self._log("─" * 52, "dim")

        for row, data in pairs:
            ip, user, pwd = data["ip"], data["username"], data["password"]
            if not ip:
                continue
            if not user or not pwd:
                self._log(f"SKIP {ip} — missing credentials.", "warn")
                self.after(0, row.set_status, "error")
                failed.append((ip, "Missing credentials"))
                continue

            self.after(0, row.set_status, "running")
            self._log(f"Connecting {ip} …")

            device = {
                "device_type":     "cisco_ios_telnet",
                "host":            ip,
                "username":        user,
                "password":        pwd,
                "timeout":         15,
                "session_timeout": 60,
            }
            try:
                conn      = ConnectHandler(**device)
                config    = conn.send_command("show running-config", read_timeout=60)
                conn.disconnect()

                hostname  = get_hostname(config, ip)
                path      = os.path.join(out, f"{hostname}.txt")

                # ── Compare with existing file ────────────────────────────
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        old_config = f.read()

                    if config.strip() == old_config.strip():
                        # identical — skip write
                        self.after(0, row.set_status, "ok")
                        self._log(
                            f"✓  {ip}  →  {hostname}.txt  [NO CHANGE]", "dim")
                        logger.info(f"{ip} → {hostname}.txt  no change")
                        ok += 1
                        continue

                    # different — calculate diff size and overwrite
                    old_lines = old_config.strip().splitlines()
                    new_lines = config.strip().splitlines()
                    added   = len([l for l in new_lines if l not in old_lines])
                    removed = len([l for l in old_lines if l not in new_lines])
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(config)
                    self.after(0, row.set_status, "ok")
                    self._log(
                        f"✓  {ip}  →  {hostname}.txt  "
                        f"[UPDATED  +{added} / -{removed} lines]", "ok")
                    logger.info(
                        f"{ip} → {hostname}.txt  updated (+{added}/-{removed} lines)")
                    if self.sv_enabled.get():          # notify only on scheduled runs
                        self._toast(
                            "Cisco Backup — Config Changed",
                            f"{hostname}: +{added} lines added, -{removed} removed")

                else:
                    # brand-new file
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(config)
                    self.after(0, row.set_status, "ok")
                    self._log(f"✓  {ip}  →  {hostname}.txt  [NEW]", "ok")
                    logger.info(f"{ip} → {hostname}.txt  created (new)")

                ok += 1

            except NetmikoTimeoutException:
                err = "Connection timed out"
                self.after(0, row.set_status, "error")
                self._log(f"✗  {ip}  —  {err}", "error")
                logger.error(f"{ip}: {err}")
                failed.append((ip, err))

            except NetmikoAuthenticationException:
                err = "Authentication failed"
                self.after(0, row.set_status, "error")
                self._log(f"✗  {ip}  —  {err}", "error")
                logger.error(f"{ip}: {err}")
                failed.append((ip, err))

            except Exception as e:
                err = str(e)
                self.after(0, row.set_status, "error")
                self._log(f"✗  {ip}  —  {err}", "error")
                logger.error(f"{ip}: {err}")
                failed.append((ip, err))

        return ok, failed


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = CiscoBackupApp()
    app.mainloop()
