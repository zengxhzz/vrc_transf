import os
import sys
import tkinter as tk
from collections import deque
from functools import partial
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import ttk

from .audio import AudioSource, capture_device, capture_process, scan_devices, supports_process_capture, vrchat_pid
from .fullscreen import foreground_window, fullscreen_game_screen
from .osc import ChatboxSender
from .translation import QIANWEN_CN, DemoTranslator, QwenSettings, QwenTranslator, TranslationEvent, Translator

BACKGROUND = "#f8f8f3"
PANEL = BACKGROUND
BORDER = "#d8dcd3"
TEXT = "#202b25"
MUTED = "#606b62"
ACCENT = "#245f47"
TINT = "#e4ece4"
MINI_BG = "#18271f"
MINI_MUTED = "#b6c9ba"
ERROR = "#a92731"
GAME_PROCESS = "VRChat 进程"
QWEN = "Qwen3.8 LiveTranslate"
DEMO = "演示（无需 Key）"
LOCAL = "本地模型（暂不可用）"
LANGUAGES = {"简体中文": "zh", "English": "en", "日本語": "ja", "한국어": "ko"}
REGIONS = {
    "千问 AI 平台 · 中国内地": QIANWEN_CN,
    "百炼 · 北京": "cn-beijing",
    "百炼 · 新加坡": "ap-southeast-1",
}
FONT = "Microsoft YaHei UI"


class CaptionPanel:
    def __init__(self, parent, title: str):
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(3, weight=1)
        self.direction = ttk.Label(self.frame, text=title, style="PanelTitle.TLabel")
        self.direction.grid(row=0, sticky="w")
        self.route = ttk.Label(self.frame, style="Route.TLabel")
        self.route.grid(row=1, sticky="w", pady=(3, 0))
        self.status = ttk.Label(self.frame, style="PanelMuted.TLabel")
        self.status.grid(row=2, sticky="ew", pady=(4, 0))
        self.status.grid_remove()
        self.status.bind("<Configure>", lambda event: self.status.configure(wraplength=event.width))
        self.output = tk.Text(
            self.frame, font=(FONT, 16), background=PANEL, foreground=TEXT,
            relief="flat", borderwidth=0, wrap="word",
            width=1, height=1, spacing2=3, spacing3=6,
            selectbackground=TINT, selectforeground=TEXT,
            highlightthickness=0, state="disabled",
        )
        self.output.grid(row=3, sticky="nsew", pady=(22, 0))
        self.output.tag_configure("previous", foreground=MUTED, font=(FONT, 13))
        self.output.tag_configure("pending", foreground=ACCENT)
        self.output.tag_configure("empty", foreground=MUTED, font=(FONT, 11))
        self.history: deque[str] = deque(maxlen=100)
        self.pending = ""
        self.render()

    def set_status(self, text: str, error: bool = False):
        self.status.configure(text=text, style="Error.TLabel" if error else "PanelMuted.TLabel")
        if text:
            self.status.grid()
        else:
            self.status.grid_remove()

    def render(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        for index, line in enumerate(self.history):
            previous = index < len(self.history) - 1 or bool(self.pending)
            self.output.insert("end", line + ("\n\n" if previous else ""), "previous" if previous else ())
        if self.pending:
            self.output.insert("end", self.pending, "pending")
        elif not self.history:
            self.output.insert("end", "暂无字幕", "empty")
        self.output.configure(state="disabled")
        self.output.see("end")

    def update_text(self, event: TranslationEvent):
        if event.kind == "final":
            self.history.append(event.text)
        self.pending = event.text if event.kind == "partial" else ""
        self.render()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.stop = Event()
        self.events: Queue[tuple[str, TranslationEvent | str]] = Queue()
        self.active: set[str] = set()
        self.publish = False
        self.chatbox = ChatboxSender()
        self.microphones = {}
        self.outputs = {}
        self.backend = tk.StringVar(value=QWEN)
        self.fast_turns = tk.BooleanVar(value=True)
        self.key = tk.StringVar(value=os.environ.get("DASHSCOPE_API_KEY", ""))
        self.workspace = tk.StringVar(value=os.environ.get("DASHSCOPE_WORKSPACE_ID", ""))
        self.region = tk.StringVar(value=next(iter(REGIONS)))
        self.game_source = tk.StringVar()
        self.mic_source = tk.StringVar()
        self.game_language = tk.StringVar(value="日本語")
        self.mic_language = tk.StringVar(value="简体中文")
        self.game_enabled = tk.BooleanVar(value=True)
        self.mic_enabled = tk.BooleanVar(value=True)
        self.send_enabled = tk.BooleanVar(value=True)
        self.notice = tk.StringVar(value="就绪")
        self.settings_notice = tk.StringVar()
        self.follow_fullscreen = tk.BooleanVar(value=True)
        self.auto_game = None
        self.dismissed_game = None
        self.previous_main_state = "normal"
        self.controls: list[tuple[ttk.Widget, str]] = []
        self._build()
        self._build_mini()
        self._build_settings()
        self.refresh_devices()
        self.sync_controls()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_task = self.root.after(40, self.poll)
        self.fullscreen_task = self.root.after(600, self._watch_fullscreen)

    def _build(self):
        self.root.title("VRC Transf · VRChat 实时翻译")
        self.root.geometry("860x460")
        self.root.minsize(620, 340)
        self.root.configure(background=BACKGROUND)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=BACKGROUND, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, focuscolor=ACCENT)
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("DialogTitle.TLabel", font=(FONT, 17, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("PanelTitle.TLabel", font=(FONT, 13, "bold"))
        style.configure("Route.TLabel", foreground=MUTED, font=(FONT, 10))
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Error.TLabel", background=PANEL, foreground=ERROR)
        style.configure("TEntry", fieldbackground="white", insertcolor=TEXT, padding=(8, 6))
        style.map("TEntry", fieldbackground=[("disabled", "#eceee8")])
        style.configure("TCombobox", fieldbackground="white", arrowcolor=MUTED, padding=(8, 6))
        style.map("TCombobox", fieldbackground=[("disabled", "#eceee8"), ("readonly", "white")])
        self.root.option_add("*TCombobox*Listbox.font", "{" + FONT + "} 10")
        self.root.option_add("*TCombobox*Listbox.selectBackground", TINT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
        style.configure("TButton", background=BACKGROUND, padding=(12, 6), relief="flat", borderwidth=0, width=0)
        style.map("TButton", background=[("pressed", BORDER), ("active", TINT)])
        style.configure("Toolbar.TButton", padding=(13, 6), background="#ffffff",
                        relief="solid", borderwidth=1, bordercolor="#98a79b",
                        lightcolor="#ffffff", darkcolor="#ffffff")
        style.map("Toolbar.TButton", background=[("pressed", "#d0dfd2"), ("active", TINT)],
                  bordercolor=[("active", ACCENT)], relief=[("pressed", "sunken")])
        style.configure("Primary.TButton", background=ACCENT, foreground=PANEL, padding=(22, 8),
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("disabled", BORDER), ("active", "#194a37")],
                  foreground=[("disabled", MUTED)])
        style.layout("Round.TCheckbutton", style.layout("TRadiobutton"))
        style.configure("Round.TCheckbutton", padding=(2, 5), indicatorsize=15, indicatormargin=(0, 0, 8, 0),
                        indicatorbackground="white", indicatorforeground=ACCENT,
                        upperbordercolor=MUTED, lowerbordercolor=MUTED)
        style.map("Round.TCheckbutton", background=[("active", TINT)],
                  foreground=[("disabled", MUTED)], indicatorforeground=[("disabled", MUTED)])
        style.layout("TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        style.layout("TNotebook.Tab", [("Notebook.padding", {"sticky": "nswe", "children": [
            ("Notebook.focus", {"sticky": "nswe", "children": [("Notebook.label", {"sticky": "nswe"})]})
        ]})])
        style.configure("TNotebook", borderwidth=0, tabmargins=0, background=BACKGROUND,
                        bordercolor=BACKGROUND, lightcolor=BACKGROUND, darkcolor=BACKGROUND)
        style.configure("TNotebook.Tab", padding=(14, 7), background=BACKGROUND, foreground=MUTED)
        style.map("TNotebook.Tab", background=[("selected", TINT), ("active", TINT)],
                  foreground=[("selected", ACCENT)])

        page = ttk.Frame(self.root, padding=(30, 18))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        header = ttk.Frame(page)
        header.grid(row=0, sticky="ew", pady=(0, 14))
        mark = tk.Canvas(header, width=32, height=32, background=ACCENT, highlightthickness=0)
        for x, height in ((7, 6), (13, 16), (19, 11), (25, 4)):
            mark.create_line(x, 16 - height / 2, x, 16 + height / 2, fill="#ffffff", width=2, capstyle="round")
        mark.pack(side="left", padx=(0, 10))
        ttk.Label(header, text="VRC Transf", style="Title.TLabel").pack(side="left")
        self.settings_button = ttk.Button(header, text="打开设置", command=self.open_settings,
                                          style="Toolbar.TButton", cursor="hand2")
        self.settings_button.pack(side="right")
        self.mini_button = ttk.Button(header, text="打开迷你字幕", command=self.open_mini,
                                      style="Toolbar.TButton", cursor="hand2")
        self.mini_button.pack(side="right", padx=(0, 8))
        tk.Frame(page, height=1, background=BORDER).grid(row=1, sticky="ew")

        captions = ttk.Frame(page)
        captions.grid(row=2, sticky="nsew", pady=24)
        captions.columnconfigure((0, 2), weight=1, uniform="captions")
        captions.rowconfigure(0, weight=1)
        self.panels = {
            "game": CaptionPanel(captions, "游戏字幕"),
            "mic": CaptionPanel(captions, "麦克风译文"),
        }
        self.panels["game"].frame.grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        tk.Frame(captions, width=1, background=BORDER).grid(row=0, column=1, sticky="ns")
        self.panels["mic"].frame.grid(row=0, column=2, sticky="nsew", padx=(22, 0))

        tk.Frame(page, height=1, background=BORDER).grid(row=3, sticky="ew")
        footer = ttk.Frame(page)
        footer.grid(row=4, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)
        status = ttk.Label(footer, textvariable=self.notice, style="Muted.TLabel", wraplength=375)
        status.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        status.bind("<Configure>", lambda event: status.configure(wraplength=event.width))
        self.start_button = ttk.Button(footer, text="开始翻译", command=self.toggle, style="Primary.TButton")
        self.start_button.grid(row=0, column=1, sticky="e")

    def _build_mini(self):
        window = self.mini_window = tk.Toplevel(self.root)
        window.withdraw()
        window.title("VRC Transf · 迷你字幕")
        window.geometry("540x200")
        window.minsize(360, 170)
        window.attributes("-topmost", True)
        window.configure(background=MINI_BG, padx=18, pady=10)
        window.protocol("WM_DELETE_WINDOW", self.close_mini)
        window.bind("<Escape>", lambda _: self.close_mini())
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        self.mini_direction = tk.Label(window, background=MINI_BG, foreground=MINI_MUTED, font=(FONT, 10))
        self.mini_direction.grid(row=0, column=0, sticky="w")
        back = tk.Button(window, text="返回双栏", command=self.close_mini, font=(FONT, 10),
                         background=MINI_BG, foreground=MINI_MUTED, activebackground=ACCENT,
                         activeforeground="white", relief="flat", borderwidth=0, padx=8, pady=4)
        back.grid(row=0, column=1, sticky="e")
        self.mini_output = tk.Text(window, wrap="word", height=2, width=1, background=MINI_BG,
                                   foreground="#fafbf6", font=(FONT, 18, "bold"), spacing2=3,
                                   borderwidth=0, highlightthickness=0, state="disabled")
        self.mini_output.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(9, 0))
        self.mini_output.tag_configure("previous", foreground=MINI_MUTED, font=(FONT, 11), spacing3=6)
        self.mini_output.tag_configure("pending", foreground="#c7ead3")
        self.mini_status = tk.Label(window, background=MINI_BG, foreground=MINI_MUTED,
                                    anchor="w", justify="left", font=(FONT, 9))
        self.mini_status.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.mini_status.bind("<Configure>", lambda event: self.mini_status.configure(wraplength=event.width))

    def open_mini(self):
        self.previous_main_state = self.root.state()
        self.root.withdraw()
        self.mini_window.deiconify()
        self.mini_window.lift()
        self._refresh_mini()

    def close_mini(self):
        self.dismissed_game = self.auto_game
        self.auto_game = None
        self.mini_window.withdraw()
        self.root.state("zoomed" if self.previous_main_state == "zoomed" else "normal")
        self.root.lift()
        self.mini_button.focus_set()

    def _watch_fullscreen(self):
        try:
            self._sync_fullscreen()
        finally:
            self.fullscreen_task = self.root.after(600, self._watch_fullscreen)

    @staticmethod
    def _show_in_background(window, state="normal"):
        # A disabled Tk toplevel can be mapped on Windows without taking game input focus.
        window.attributes("-disabled", True)
        try:
            window.state(state)
            window.update_idletasks()
        finally:
            window.attributes("-disabled", False)

    def _sync_fullscreen(self):
        if sys.platform != "win32":
            return
        window = self.mini_window
        if not self.auto_game and (window.state() != "withdrawn" or self.settings_window.state() != "withdrawn"):
            return
        hwnd = foreground_window()
        if not hwnd:  # A foreground window can be briefly absent during Alt+Tab.
            return
        if self.auto_game and hwnd == int(window.wm_frame(), 16):
            hwnd = self.auto_game
        elif self.dismissed_game and hwnd == int(self.root.wm_frame(), 16):
            hwnd = self.dismissed_game
        screen = fullscreen_game_screen(hwnd) if self.follow_fullscreen.get() else None
        if not screen:
            self.dismissed_game = None
            if self.auto_game:
                self.auto_game = None
                window.withdraw()
                if self.previous_main_state != "iconic":
                    self._show_in_background(self.root, self.previous_main_state)
            return
        if hwnd in (self.dismissed_game, self.auto_game):
            return
        self.dismissed_game = None
        if not self.auto_game:
            self.previous_main_state = self.root.state()
            if self.previous_main_state != "iconic":
                self.root.withdraw()
        self.auto_game = hwnd
        width = window.winfo_width() if window.winfo_width() > 1 else 540
        height = window.winfo_height() if window.winfo_height() > 1 else 200
        x = max(screen.left, (screen.left + screen.right - width) // 2)
        y = max(screen.top, screen.bottom - height - 70)
        window.geometry(f"+{x}+{y}")
        self._refresh_mini()
        self._show_in_background(window)

    def _refresh_mini(self):
        panel = self.panels["game"]
        self.mini_direction.configure(text=panel.direction.cget("text"))
        lines = list(panel.history)[-2:]
        if panel.pending:
            lines = lines[-1:] + [panel.pending]
        self.mini_output.configure(state="normal")
        self.mini_output.delete("1.0", "end")
        if self.game_enabled.get() and lines:
            if len(lines) == 2:
                self.mini_output.insert("end", lines[0] + "\n", "previous")
            self.mini_output.insert("end", lines[-1], "pending" if panel.pending else ())
        else:
            self.mini_output.insert("end", "等待游戏字幕" if self.game_enabled.get() else "游戏音频已关闭")
        self.mini_output.configure(state="disabled")
        self.mini_output.see("end")
        self.mini_status.configure(text=panel.status.cget("text") or self.notice.get())

    def _build_settings(self):
        self.settings_window = tk.Toplevel(self.root)
        window = self.settings_window
        window.withdraw()
        window.transient(self.root)
        window.title("VRC Transf · 设置")
        window.configure(background=BACKGROUND)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close_settings)
        window.bind("<Escape>", lambda _: self.close_settings())

        page = ttk.Frame(window, padding=(25, 20))
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="设置", style="DialogTitle.TLabel").pack(anchor="w", pady=(0, 10))
        tabs = ttk.Notebook(page)
        tabs.pack(fill="both", expand=True)
        translation = ttk.Frame(tabs, padding=(0, 20))
        audio = ttk.Frame(tabs, padding=(0, 18))
        chatbox = ttk.Frame(tabs, padding=(0, 20))
        tabs.add(translation, text="翻译")
        tabs.add(audio, text="音频")
        tabs.add(chatbox, text="Chatbox")
        display = ttk.Frame(tabs, padding=(0, 20))
        tabs.add(display, text="显示")
        self._check(display, "VRChat 全屏时自动打开迷你字幕", self.follow_fullscreen,
                    lock_during_session=False).pack(fill="x")
        ttk.Label(display, text="离开游戏或退出全屏后，恢复原来的窗口状态。",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        for tab in (translation, audio):
            tab.columnconfigure(0, weight=1)

        provider = ttk.Frame(translation)
        provider.grid(row=0, sticky="ew")
        provider.columnconfigure((0, 1), weight=1, uniform="provider")
        backend = self._combo(provider, "翻译方式", self.backend, (QWEN, DEMO, LOCAL), 0, 23)
        backend.bind("<<ComboboxSelected>>", lambda _: self.sync_controls())
        self.region_box = self._combo(provider, "API 接入", self.region, tuple(REGIONS), 1, 20)
        self.region_box.bind("<<ComboboxSelected>>", lambda _: self.sync_controls())
        credentials = ttk.Frame(translation)
        credentials.grid(row=1, sticky="ew", pady=(10, 0))
        credentials.columnconfigure((0, 1), weight=1, uniform="credentials")
        self.key_box = self._entry(credentials, "API Key", self.key, 0, secret=True)
        self.workspace_box = self._entry(credentials, "Workspace ID（仅百炼）", self.workspace, 1)
        self.fast_turn_box = self._check(translation, "快速断句", self.fast_turns)
        self.fast_turn_box.grid(row=2, sticky="w", pady=(8, 0))
        ttk.Label(translation, text="适合轮流交谈。多人同时说话时可关闭，使用说话人分离。",
                  style="Muted.TLabel", wraplength=475).grid(row=3, sticky="w")
        self.provider_hint = ttk.Label(translation, style="Muted.TLabel", wraplength=475)
        self.provider_hint.grid(row=4, sticky="w", pady=(8, 0))

        self._check(audio, "翻译游戏音频", self.game_enabled).grid(row=0, sticky="ew", pady=(0, 5))
        game = ttk.Frame(audio)
        game.grid(row=1, sticky="ew")
        game.columnconfigure(0, weight=1)
        self.game_box = self._combo(game, "游戏音频", self.game_source, (), 0, 29)
        self._combo(game, "接收语言", self.game_language, tuple(LANGUAGES), 1, 14)
        self._check(audio, "翻译麦克风", self.mic_enabled).grid(row=2, sticky="ew", pady=(8, 5))
        mic = ttk.Frame(audio)
        mic.grid(row=3, sticky="ew")
        mic.columnconfigure(0, weight=1)
        self.mic_box = self._combo(mic, "麦克风", self.mic_source, (), 0, 29)
        self._combo(mic, "发送语言", self.mic_language, tuple(LANGUAGES), 1, 14)
        refresh = ttk.Button(audio, text="刷新设备", command=self.refresh_devices)
        refresh.grid(row=4, sticky="w", pady=(9, 0))
        self.controls.append((refresh, "normal"))

        self._check(chatbox, "麦克风译文发到 Chatbox", self.send_enabled).pack(fill="x")
        ttk.Label(chatbox, text="发送麦克风定稿译文。请先在 VRChat 的 Options → OSC 中启用 OSC。",
                  style="Muted.TLabel", wraplength=475).pack(anchor="w", pady=(6, 14))
        ttk.Button(chatbox, text="测试 Chatbox", command=self.test_chatbox).pack(anchor="w")

        footer = ttk.Frame(page)
        footer.pack(fill="x", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.settings_notice, style="Muted.TLabel",
                  wraplength=370).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Button(footer, text="完成", command=self.close_settings, style="Primary.TButton").grid(row=0, column=1)

    def open_settings(self):
        window = self.settings_window
        self.sync_controls()
        if not window.winfo_viewable():
            self.root.update_idletasks()
            width = max(window.winfo_reqwidth(), 535)
            height = window.winfo_reqheight()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
            window.geometry(f"{width}x{height}{x:+d}{y:+d}")
            window.deiconify()
        window.lift()
        window.update_idletasks()
        window.grab_set()
        window.focus_set()

    def close_settings(self):
        window = self.settings_window
        if window.grab_current() == window:
            window.grab_release()
        window.withdraw()
        self.settings_button.focus_set()
        self.sync_controls()

    def _check(self, parent, text, variable, *, lock_during_session=True):
        switch = ttk.Checkbutton(parent, text=text, variable=variable, style="Round.TCheckbutton", takefocus=True)
        if lock_during_session:
            self.controls.append((switch, "normal"))
        return switch

    def _combo(self, row, label, variable, values, column, width):
        ttk.Label(row, text=label, style="Muted.TLabel").grid(row=0, column=column, sticky="w", pady=(0, 4))
        widget = ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=width)
        widget.grid(row=1, column=column, sticky="ew", padx=(0, 11), pady=(0, 4))
        self.controls.append((widget, "readonly"))
        return widget

    def _entry(self, row, label, variable, column, secret=False):
        ttk.Label(row, text=label, style="Muted.TLabel").grid(row=0, column=column, sticky="w", pady=(0, 4))
        widget = ttk.Entry(row, textvariable=variable, show="•" if secret else "")
        widget.grid(row=1, column=column, sticky="ew", padx=(0, 11), pady=(0, 4))
        self.controls.append((widget, "normal"))
        return widget

    def refresh_devices(self):
        try:
            microphones, outputs = scan_devices()
        except (OSError, RuntimeError) as error:
            self.settings_notice.set(str(error))
            return
        self.microphones = {f"{device.name} · {device.index}": device for device in microphones}
        self.outputs = {
            f"播放设备 · {device.name.removesuffix(' [Loopback]')} · {device.index}": device
            for device in outputs
        }
        game_sources = (GAME_PROCESS, *self.outputs) if supports_process_capture() else tuple(self.outputs)
        self.mic_box.configure(values=tuple(self.microphones))
        self.game_box.configure(values=game_sources)
        if self.mic_source.get() not in self.microphones:
            default = next((key for key, device in self.microphones.items() if device.is_default), None)
            self.mic_source.set(default or next(iter(self.microphones), ""))
        if self.game_source.get() not in game_sources:
            default_output = next((key for key, device in self.outputs.items() if device.is_default), None)
            default_game = GAME_PROCESS if supports_process_capture() else default_output
            self.game_source.set(default_game or next(iter(game_sources), ""))
        if self.settings_window.winfo_viewable():
            self.settings_notice.set("音频设备已刷新")

    def sync_controls(self):
        mode = self.backend.get()
        cloud = mode == QWEN
        game, mic = self.panels["game"], self.panels["mic"]
        game.direction.configure(text=f"游戏声音  →  {self.game_language.get()}")
        mic.direction.configure(text=f"我的麦克风  →  {self.mic_language.get()}")
        game.route.configure(text="游戏音频已关闭" if not self.game_enabled.get() else "桌面字幕")
        mic_route = "定稿后发送至 Chatbox" if cloud and self.send_enabled.get() else "仅本机预览"
        mic.route.configure(text=mic_route if self.mic_enabled.get() else "麦克风已关闭")
        workspace_needed = REGIONS[self.region.get()] != QIANWEN_CN
        for widget, state in self.controls:
            settings_only = widget in (self.region_box, self.workspace_box, self.key_box, self.fast_turn_box)
            capture_only = widget in (self.game_box, self.mic_box)
            permitted = not self.active and (cloud or not (settings_only or capture_only))
            if widget is self.workspace_box and not workspace_needed:
                permitted = False
            widget.configure(state=state if permitted else "disabled")
        self.start_button.configure(
            text="停止" if self.active else ("运行演示" if mode == DEMO else "开始翻译"),
            state="disabled" if mode == LOCAL or (self.active and self.stop.is_set()) else "normal",
        )
        self.provider_hint.configure(text={
            QWEN: "启用的音频会发送至所选服务。播放设备模式采集该设备上的所有声音。",
            DEMO: "使用示例字幕预览两条链路。",
            LOCAL: "本地模型接口已预留。",
        }[mode])
        if self.active:
            self.settings_notice.set("停止翻译后可以修改设置")
        elif self.settings_notice.get() == "停止翻译后可以修改设置":
            self.settings_notice.set("")

    def _sources(self, demo: bool) -> dict[str, tuple[str, AudioSource | None]]:
        jobs = {}
        if self.game_enabled.get():
            source = self.game_source.get()
            game = None
            if not demo:
                if source == GAME_PROCESS:
                    game = partial(capture_process, vrchat_pid())
                elif source in self.outputs:
                    game = partial(capture_device, self.outputs[source])
                else:
                    raise ValueError("请选择游戏音频设备，或关闭游戏音频翻译")
            jobs["game"] = (LANGUAGES[self.game_language.get()], game)
        if self.mic_enabled.get():
            device = self.microphones.get(self.mic_source.get())
            if not demo and device is None:
                raise ValueError("请选择麦克风设备，或关闭麦克风翻译")
            jobs["mic"] = (LANGUAGES[self.mic_language.get()], partial(capture_device, device) if device else None)
        if not jobs:
            raise ValueError("请至少启用一路翻译")
        return jobs

    def toggle(self):
        if self.active:
            self.stop.set()
            self.notice.set("正在停止采集并接收剩余译文…")
            self.sync_controls()
            return
        mode = self.backend.get()
        if mode == LOCAL:
            return
        secret = self.key.get().strip()
        try:
            translator = DemoTranslator() if mode == DEMO else QwenTranslator(QwenSettings(
                secret, self.workspace.get().strip(), REGIONS[self.region.get()], fast_turns=self.fast_turns.get(),
            ))
            sources = self._sources(mode == DEMO)
        except (ValueError, OSError, RuntimeError, KeyError) as error:
            self.notice.set(str(error))
            return
        self.stop = Event()
        self.publish = mode == QWEN and self.send_enabled.get()
        self.active = set(sources)
        self.notice.set("正在运行演示。" if mode == DEMO else "正在连接翻译 API…")
        for role, panel in self.panels.items():
            panel.pending = ""
            panel.history.clear()
            panel.render()
            panel.set_status("")
        self.sync_controls()
        for role, (target, source) in sources.items():
            Thread(target=self._run, args=(translator, role, target, source, secret), daemon=True).start()

    def _run(self, translator: Translator, role: str, target: str, source: AudioSource | None, secret: str):
        try:
            for item in translator.stream(target, source, self.stop):
                self.events.put((role, item))
        except Exception as error:
            message = str(error) or type(error).__name__
            if secret:
                message = message.replace(secret, "••••")
            self.events.put((role, message))
        finally:
            self.events.put((role, ""))

    def test_chatbox(self):
        self.chatbox.enqueue("VRC Transf · OSC 连接测试")
        self.settings_notice.set("测试文字已排队，请查看 VRChat Chatbox")

    def poll(self):
        received = False
        try:
            for _ in range(64):
                role, item = self.events.get_nowait()
                received = True
                panel = self.panels[role]
                if isinstance(item, TranslationEvent):
                    if item.kind == "ready":
                        self.notice.set("正在翻译")
                    else:
                        panel.update_text(item)
                        if role == "mic" and item.kind == "final" and self.publish:
                            self.chatbox.enqueue(item.text, mergeable=True)
                elif item:
                    panel.set_status(item, error=True)
                    self.notice.set("翻译遇到问题，请查看对应声道")
                else:
                    self.active.discard(role)
                    if role == "mic":
                        self.chatbox.finish_session()
                    panel.pending = ""
                    panel.render()
                    if self.active and panel.status.cget("style") != "Error.TLabel":
                        panel.set_status("该路已停止")
                    if not self.active:
                        self.sync_controls()
                        errors = any(p.status.cget("style") == "Error.TLabel" for p in self.panels.values())
                        for finished in self.panels.values():
                            if finished.status.cget("style") != "Error.TLabel":
                                finished.set_status("")
                        if errors:
                            self.notice.set("翻译已结束，请查看声道提示")
                        elif self.notice.get() in ("正在翻译", "正在停止采集并接收剩余译文…", "正在运行演示。", "正在连接翻译 API…"):
                            self.notice.set("演示结束" if self.backend.get() == DEMO else "已停止")
        except Empty:
            pass
        try:
            self.chatbox.tick()
        except (OSError, ValueError) as error:
            self.notice.set(f"Chatbox 发送失败（{error}）")
            received = True
        if received and self.mini_window.winfo_viewable():
            self._refresh_mini()
        self.poll_task = self.root.after(40, self.poll)

    def close(self):
        self.stop.set()
        self.root.after_cancel(self.poll_task)
        self.root.after_cancel(self.fullscreen_task)
        self.chatbox.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
