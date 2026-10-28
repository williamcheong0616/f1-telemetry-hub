"""The app's own window, for the Mac app, which has no console window: what the console shows on Windows (the
dashboard's address, what to set in the game, where the data is), whether the game's data is arriving, and Open
dashboard / Quit. Closing the window quits the app, as closing the console does on Windows."""
from __future__ import annotations

import signal
import subprocess
import sys
import time
import webbrowser

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox, ttk
except ImportError:  # a Python built without Tk: the app still runs with --no-window
    tk = None

from . import APP_NAME, __version__

GUIDE_URL = "https://github.com/williamcheong0616/f1-telemetry-hub/blob/main/GUIDE.md"
DOT = {"good": "#1f9d55", "wait": "#d08700", "bad": "#d93025"}
MUTED = "#8a8a8a"
IPS_EVERY_S = 10  # the computer's addresses are looked up again now and then: Wi-Fi changes
MAC = sys.platform == "darwin"


class StatusWindow:
    def __init__(self, app, url: str):
        if tk is None:
            raise RuntimeError("this Python has no Tk, so the app can't show its window: start it with --no-window")
        self.app, self.url = app, url
        self.ips, self.ips_at = [], 0.0
        self.closed = False
        self.root = root = tk.Tk()
        root.title(APP_NAME)
        root.resizable(False, False)
        base = tkfont.nametofont("TkDefaultFont")
        size = abs(base.actual("size"))
        self.f_title = base.copy()
        self.f_title.configure(size=size + 7, weight="bold")
        self.f_bold = base.copy()
        self.f_bold.configure(weight="bold")
        self.f_small = base.copy()
        self.f_small.configure(size=max(9, size - 2))
        self._build()

        root.protocol("WM_DELETE_WINDOW", self.quit)
        if MAC:
            root.createcommand("tk::mac::Quit", self.quit)  # Cmd+Q, the Dock's Quit, logging out
            root.createcommand("tk::mac::ReopenApplication", self.show)  # a click on the Dock icon
            root.createcommand("tkAboutDialog", self.about)
            root.createcommand("tk::mac::ShowHelp", lambda: webbrowser.open(self.url + "#/guide"))  # Help menu
            root.bind_all("<Command-w>", lambda e: self.quit())
        for sig in (signal.SIGINT, signal.SIGTERM):  # Ctrl+C in a terminal, or being told to stop
            signal.signal(sig, self._on_signal)

    # ------------------------------------------------------------------ layout
    def _build(self):
        f = ttk.Frame(self.root, padding=(22, 18, 22, 16))
        f.grid(sticky="nsew")
        f.columnconfigure(1, weight=1)
        r = 0

        head = ttk.Frame(f)
        head.grid(row=r, column=0, columnspan=3, sticky="w")
        ttk.Label(head, text=APP_NAME, font=self.f_title).pack(side="left")
        ttk.Label(head, text=f"  v{__version__}", foreground=MUTED).pack(side="left", anchor="s", pady=(0, 3))
        r += 1

        st = ttk.Frame(f)
        st.grid(row=r, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.dot = ttk.Label(st, text="●", font=self.f_bold)
        self.dot.pack(side="left")
        self.state = ttk.Label(st, text="", font=self.f_bold)
        self.state.pack(side="left", padx=(6, 0))
        r += 1
        self.detail = ttk.Label(f, text="", foreground=MUTED, wraplength=440, justify="left")
        self.detail.grid(row=r, column=0, columnspan=3, sticky="w", pady=(2, 0))
        r += 1

        r = self._rule(f, r)
        ttk.Label(f, text="Dashboard", font=self.f_bold).grid(row=r, column=0, sticky="w")
        ttk.Label(f, text=self.url).grid(row=r, column=1, sticky="w", padx=(12, 0))
        self.open_btn = ttk.Button(f, text="Open dashboard", command=self.open_dashboard, default="active")
        self.open_btn.grid(row=r, column=2, sticky="e")
        self.root.bind("<Return>", lambda e: self.open_dashboard())
        r += 1
        self.lan = ttk.Label(f, text="", foreground=MUTED, justify="left")
        self.lan.grid(row=r, column=1, columnspan=2, sticky="w", padx=(12, 0))
        self.lan.grid_remove()  # shown with LAN access on: an empty line would leave a gap
        r += 1

        r = self._rule(f, r)
        ttk.Label(f, text="In the game: Settings › Telemetry Settings", font=self.f_bold).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
        r += 1
        self.values = {}
        rows = [("UDP Telemetry", "On"), ("UDP Broadcast Mode", "Off"), ("UDP IP Address", ""),
                ("UDP Port", ""), ("UDP Send Rate", "30–60 Hz"),
                ("UDP Format", "2025 (2026 with the 2026 Season Pack)"), ("Your Telemetry", "Public")]
        for name, value in rows:
            ttk.Label(f, text=name, foreground=MUTED).grid(row=r, column=0, sticky="w", padx=(0, 0))
            v = ttk.Label(f, text=value, font=self.f_bold)
            v.grid(row=r, column=1, columnspan=2, sticky="w", padx=(12, 0))
            self.values[name] = v
            r += 1
        self.ip_note = ttk.Label(f, text="", foreground=MUTED, font=self.f_small, wraplength=440, justify="left")
        self.ip_note.grid(row=r, column=0, columnspan=3, sticky="w", pady=(4, 0))
        r += 1

        r = self._rule(f, r)
        ttk.Label(f, text="Your data", font=self.f_bold).grid(row=r, column=0, sticky="nw")
        ttk.Label(f, text=str(self.app.data_dir), wraplength=290, justify="left").grid(
            row=r, column=1, sticky="w", padx=(12, 0))
        ttk.Button(f, text="Show in Finder" if MAC else "Open folder",
                   command=self.app.open_data_folder).grid(row=r, column=2, sticky="e")
        r += 1

        r = self._rule(f, r)
        ttk.Label(f, text="Keep this window open while you drive. Closing it quits the app.",
                  foreground=MUTED, font=self.f_small).grid(row=r, column=0, columnspan=2, sticky="w")
        ttk.Button(f, text="Quit", command=self.quit).grid(row=r, column=2, sticky="e")

    def _rule(self, parent, r):
        ttk.Separator(parent).grid(row=r, column=0, columnspan=3, sticky="ew", pady=12)
        return r + 1

    # ------------------------------------------------------------------ live state
    def _status(self):
        """(colour, headline, detail) for the line under the title."""
        app = self.app
        l = app.listener
        if l is None or l.error:
            return "bad", "Not listening for the game", l.error if l else "The listener didn't start."
        rep = app.replay_info()
        if rep.get("running"):
            return "good", "Replaying a recording", rep.get("name") or ""
        s = app.recorder.status_info()
        if s["connected"]:
            game = s.get("game") or {}
            source = "the demo" if s.get("demo") else f"F1 {game['year']}" if game.get("year") else "the game"
            return "good", f"Receiving telemetry from {source}", f"{s['pps']:.0f} packets a second"
        if s["packets"]:
            ago = int(s["last_packet_age"] or 0)
            return "wait", "The game has stopped sending", f"Last data {ago // 60} min {ago % 60} s ago."
        return "wait", "Waiting for the game", f"Listening on UDP port {l.port}: set the game as below."

    def _refresh(self):
        colour, headline, detail = self._status()
        self.dot.configure(foreground=DOT[colour])
        self.state.configure(text=headline)
        self.detail.configure(text=detail)

        from .app import local_ips  # app imports this module when it opens the window
        now = time.monotonic()
        if now - self.ips_at > IPS_EVERY_S:
            self.ips, self.ips_at = local_ips(), now
        port = self.app.listener.port if self.app.listener else self.app.settings["udp_port"]
        self.values["UDP Port"].configure(text=str(port))
        if MAC:  # the game can't run on a Mac: it sends to the Mac from a console or a PC
            self.values["UDP IP Address"].configure(text=" or ".join(self.ips[:2]) or "this Mac's IP address")
            self.ip_note.configure(text="Set these on the console or PC the game runs on. The address is this Mac's "
                                        "on your network" + ("" if self.ips else ": find it in System Settings › "
                                                                               "Network") + ".")
        else:
            self.values["UDP IP Address"].configure(text="127.0.0.1")
            self.ip_note.configure(text=f"127.0.0.1 when the game runs on this PC. On a console or another PC use "
                                        f"{' or '.join(self.ips)}." if self.ips else "")
        if self.app.settings.get("lan_access") and self.ips:
            self.lan.configure(text="Other devices: " + "\n".join(f"http://{ip}:{self.app.http_port}/"
                                                                   for ip in self.ips[:3]))
            self.lan.grid()
        else:
            self.lan.grid_remove()

    def _tick(self):
        try:
            self._refresh()
        except Exception as e:  # noqa: BLE001 - a bad refresh mustn't stop the window updating
            print(f"[warn] window refresh failed: {e!r}")
        self.root.after(1000, self._tick)

    # ------------------------------------------------------------------ actions
    def open_dashboard(self):
        webbrowser.open(self.url)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def about(self):
        messagebox.showinfo(APP_NAME, f"{APP_NAME} {__version__}",
                            detail="Telemetry dashboard, race engineer, coach and strategy for EA SPORTS F1 25. "
                                   "Everything stays on this computer.\n\n"
                                   "github.com/williamcheong0616/f1-telemetry-hub\nMIT licence.")

    def quit(self):
        if self.closed:
            return
        self.closed = True
        print("Shutting down...")
        self.root.destroy()

    def _on_signal(self, *_):
        if not self.closed:
            self.root.after(0, self.quit)

    def run(self):
        self._tick()
        self.root.update_idletasks()
        self.root.eval("tk::PlaceWindow . center")
        self.root.mainloop()


def show_error(message: str):
    """The app couldn't start: say so in a window, as there's no console to show it in."""
    detail = (f"{message}\n\nThe guide's Troubleshooting section covers the usual causes. "
              "The full details are in app.log in the app's data folder.")
    if tk is not None:
        try:
            root = tk.Tk()
            root.withdraw()
            if messagebox.askyesno(APP_NAME, f"{APP_NAME} could not start", detail=detail + "\n\nOpen the guide?",
                                   icon="error"):
                webbrowser.open(GUIDE_URL + "#troubleshooting")
            root.destroy()
            return
        except tk.TclError:
            pass
    if MAC:  # no Tk: the system's own alert
        text = f"{APP_NAME} could not start.\n\n{detail}".replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "{APP_NAME}" message "{text}" as critical'],
                       check=False, timeout=600)
