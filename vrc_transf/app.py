import os
import tkinter as tk
from collections import deque
from functools import partial
from queue import Empty, Queue
from threading import Event, Thread
from tkinter import ttk

from .audio import AudioSource, capture_device, capture_process, scan_devices, supports_process_capture, vrchat_pid
from .osc import ChatboxSender
from .translation import QIANWEN_CN, DemoTranslator, QwenSettings, QwenTranslator, TranslationEvent, Translator

BACKGROUND = "#f4f6fa"
PANEL = "#ffffff"
BORDER = "#dee4ef"
TEXT = "#182237"
MUTED = "#59677e"
ACCENT = "#3159d3"
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
        self.frame = ttk.Frame(parent, padding=(18, 16), style="Panel.TFrame")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)
        ttk.Label(self.frame, text=title, style="PanelTitle.TLabel").grid(row=0, sticky="w")
        self.status = ttk.Label(self.frame, style="PanelMuted.TLabel")
        self.status.grid(row=1, sticky="ew", pady=(3, 0))
        self.status.grid_remove()
        self.status.bind("<Configure>", lambda event: self.status.configure(wraplength=event.width))
        self.output = tk.Text(
            self.frame, font=(FONT, 13), background=PANEL, foreground=TEXT,
            relief="flat", borderwidth=0, wrap="word",
            width=1, height=1, spacing2=3, spacing3=6,
            selectbackground="#dce6ff", selectforeground=TEXT,
            highlightthickness=0, state="disabled",
        )
        self.output.grid(row=2, sticky="nsew", pady=(14, 0))
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
        if self.history:
            self.output.insert("end", "\n\n".join(self.history) + "\n\n")
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
        self.key = tk.StringVar(value=os.environ.get("DASHSCOPE_API_KEY", ""))
        self.workspace = tk.StringVar(value=os.environ.get("DASHSCOPE_WORKSPACE_ID", ""))
        self.region = tk.StringVar(value=next(iter(REGIONS)))
        self.game_source = tk.StringVar()
        self.mic_source = tk.StringVar()
        self.game_language = tk.StringVar(value="简体中文")
        self.mic_language = tk.StringVar(value="English")
        self.game_enabled = tk.BooleanVar(value=True)
        self.mic_enabled = tk.BooleanVar(value=True)
        self.send_enabled = tk.BooleanVar(value=True)
        self.notice = tk.StringVar(value="就绪")
        self.settings_notice = tk.StringVar()
        self.controls: list[tuple[ttk.Widget, str]] = []
        self._build()
        self._build_settings()
        self.refresh_devices()
        self.sync_controls()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_task = self.root.after(40, self.poll)

    def _build(self):
        self.root.title("VRC Transf · VRChat 实时翻译")
        self.root.geometry("820x480")
        self.root.minsize(620, 340)
        self.root.configure(background=BACKGROUND)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), background=BACKGROUND, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, focuscolor=ACCENT)
        style.configure("Title.TLabel", font=(FONT, 20, "bold"))
        style.configure("DialogTitle.TLabel", font=(FONT, 17, "bold"))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Panel.TFrame", background=PANEL, borderwidth=1, relief="solid")
        style.configure("PanelTitle.TLabel", background=PANEL, font=(FONT, 12, "bold"))
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Error.TLabel", background=PANEL, foreground=ERROR)
        style.configure("TEntry", fieldbackground=PANEL, insertcolor=TEXT, padding=(8, 6))
        style.map("TEntry", fieldbackground=[("disabled", "#e9edf5")])
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, arrowcolor=MUTED, padding=(8, 6))
        style.map("TCombobox", fieldbackground=[("disabled", "#e9edf5"), ("readonly", PANEL)])
        self.root.option_add("*TCombobox*Listbox.font", "{" + FONT + "} 10")
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#dce6ff")
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
        style.configure("TButton", background=PANEL, padding=(13, 6), relief="flat", borderwidth=1)
        style.map("TButton", background=[("active", "#e9effc")])
        style.configure("Primary.TButton", background=ACCENT, foreground=PANEL, padding=(22, 8),
                        bordercolor=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Primary.TButton", background=[("disabled", "#e9edf5"), ("active", "#2448b8")],
                  foreground=[("disabled", MUTED)])
        style.configure("TCheckbutton", background=BACKGROUND, indicatorbackground=PANEL)
        style.map("TCheckbutton", indicatorbackground=[("disabled", "#e9edf5"), ("selected", "#dce6ff")],
                  background=[("active", BACKGROUND)])
        style.configure("TNotebook", borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab", padding=(16, 7))
        style.map("TNotebook.Tab", background=[("selected", "#e2eaff"), ("active", "#ecf1fb")],
                  foreground=[("selected", ACCENT)])

        page = ttk.Frame(self.root, padding=(22, 18))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        header = ttk.Frame(page)
        header.grid(row=0, sticky="ew", pady=(0, 16))
        ttk.Label(header, text="VRChat 实时翻译", style="Title.TLabel").pack(side="left")
        self.settings_button = ttk.Button(header, text="设置", command=self.open_settings)
        self.settings_button.pack(side="right")

        captions = ttk.Frame(page)
        captions.grid(row=1, sticky="nsew")
        captions.columnconfigure((0, 1), weight=1, uniform="captions")
        captions.rowconfigure(0, weight=1)
        self.panels = {
            "game": CaptionPanel(captions, "游戏字幕"),
            "mic": CaptionPanel(captions, "麦克风译文"),
        }
        self.panels["game"].frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.panels["mic"].frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        footer = ttk.Frame(page)
        footer.grid(row=2, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)
        status = ttk.Label(footer, textvariable=self.notice, style="Muted.TLabel", wraplength=375)
        status.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        status.bind("<Configure>", lambda event: status.configure(wraplength=event.width))
        self.start_button = ttk.Button(footer, text="开始翻译", command=self.toggle, style="Primary.TButton")
        self.start_button.grid(row=0, column=1, sticky="e")

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

        page = ttk.Frame(window, padding=(20, 16))
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="设置", style="DialogTitle.TLabel").pack(anchor="w", pady=(0, 10))
        tabs = ttk.Notebook(page)
        tabs.pack(fill="both", expand=True)
        translation = ttk.Frame(tabs, padding=(10, 16))
        audio = ttk.Frame(tabs, padding=(10, 14))
        chatbox = ttk.Frame(tabs, padding=(10, 16))
        tabs.add(translation, text="翻译")
        tabs.add(audio, text="音频")
        tabs.add(chatbox, text="Chatbox")
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
        self.provider_hint = ttk.Label(translation, style="Muted.TLabel", wraplength=475)
        self.provider_hint.grid(row=2, sticky="w", pady=(8, 0))

        self._check(audio, "翻译游戏音频", self.game_enabled).grid(row=0, sticky="w", pady=(0, 5))
        game = ttk.Frame(audio)
        game.grid(row=1, sticky="ew")
        game.columnconfigure(0, weight=1)
        self.game_box = self._combo(game, "游戏音频", self.game_source, (), 0, 29)
        self._combo(game, "接收语言", self.game_language, tuple(LANGUAGES), 1, 14)
        self._check(audio, "翻译麦克风", self.mic_enabled).grid(row=2, sticky="w", pady=(8, 5))
        mic = ttk.Frame(audio)
        mic.grid(row=3, sticky="ew")
        mic.columnconfigure(0, weight=1)
        self.mic_box = self._combo(mic, "麦克风", self.mic_source, (), 0, 29)
        self._combo(mic, "发送语言", self.mic_language, tuple(LANGUAGES), 1, 14)
        refresh = ttk.Button(audio, text="刷新设备", command=self.refresh_devices)
        refresh.grid(row=4, sticky="w", pady=(9, 0))
        self.controls.append((refresh, "normal"))

        self._check(chatbox, "麦克风译文发到 Chatbox", self.send_enabled).pack(anchor="w")
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

    def _check(self, parent, text, variable):
        widget = ttk.Checkbutton(parent, text=text, variable=variable)
        self.controls.append((widget, "normal"))
        return widget

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
        workspace_needed = REGIONS[self.region.get()] != QIANWEN_CN
        for widget, state in self.controls:
            settings_only = widget in (self.region_box, self.workspace_box, self.key_box)
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
                secret, self.workspace.get().strip(), REGIONS[self.region.get()],
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
            panel.set_status("正在启动" if role in self.active else "未启用")
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
        try:
            for _ in range(64):
                role, item = self.events.get_nowait()
                panel = self.panels[role]
                if isinstance(item, TranslationEvent):
                    if item.kind == "ready":
                        panel.set_status("正在翻译")
                        self.notice.set("正在翻译")
                    else:
                        panel.update_text(item)
                        if role == "mic" and item.kind == "final" and self.publish:
                            self.chatbox.enqueue(item.text)
                elif item:
                    panel.set_status(item, error=True)
                    self.notice.set(item)
                else:
                    self.active.discard(role)
                    panel.pending = ""
                    panel.render()
                    if panel.status.cget("style") != "Error.TLabel":
                        panel.set_status("已停止")
                    if not self.active:
                        self.sync_controls()
                        if self.notice.get() in ("正在翻译", "正在停止采集并接收剩余译文…"):
                            self.notice.set("已停止")
        except Empty:
            pass
        try:
            self.chatbox.tick()
        except (OSError, ValueError) as error:
            self.notice.set(f"Chatbox 发送失败（{error}）")
        self.poll_task = self.root.after(40, self.poll)

    def close(self):
        self.stop.set()
        self.root.after_cancel(self.poll_task)
        self.chatbox.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()
