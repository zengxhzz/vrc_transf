import tkinter as tk
import sys
import unittest
from tkinter import ttk
from unittest.mock import patch

from vrc_transf.app import App, DEMO, REGIONS
from vrc_transf.fullscreen import Screen
from vrc_transf.translation import TranslationEvent


def fields_in(widget):
    for child in widget.winfo_children():
        if isinstance(child, tk.Toplevel):
            continue
        if isinstance(child, (ttk.Combobox, ttk.Entry, ttk.Checkbutton)):
            yield child
        yield from fields_in(child)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display unavailable: {error}")
        try:
            with patch("vrc_transf.app.scan_devices", return_value=([], [])):
                self.app = App(self.root)
        except Exception:
            self.root.destroy()
            raise
        self.addCleanup(self.app.close)
        self.root.update()

    def test_settings_are_hidden_on_launch_and_keep_values_when_reopened(self):
        self.assertFalse(list(fields_in(self.root)))
        self.assertFalse(self.app.settings_window.winfo_viewable())
        self.app.open_settings()
        self.root.update()
        self.assertTrue(self.app.settings_window.winfo_viewable())
        self.assertIn(self.app.key_box, list(fields_in(self.app.settings_window)))

        self.app.backend.set(DEMO)
        self.app.sync_controls()
        self.app.close_settings()
        self.assertIsNone(self.root.grab_current())
        self.assertEqual(self.app.start_button.cget("text"), "运行演示")
        self.app.open_settings()
        self.assertEqual(self.app.backend.get(), DEMO)

    def test_workspace_field_follows_provider_and_session_state(self):
        self.app.open_settings()
        self.assertTrue(self.app.workspace_box.instate(["disabled"]))
        self.app.region.set(next(name for name, value in REGIONS.items() if value == "cn-beijing"))
        self.app.sync_controls()
        self.assertTrue(self.app.workspace_box.instate(["!disabled"]))
        self.app.active.add("game")
        self.app.sync_controls()
        self.assertTrue(self.app.workspace_box.instate(["disabled"]))
        self.assertTrue(self.app.key_box.instate(["disabled"]))

    def test_round_setting_controls_toggle_independently(self):
        self.app.open_settings()
        switches = {str(w.cget("variable")): w for w in fields_in(self.app.settings_window)
                    if isinstance(w, ttk.Checkbutton)}
        for variable in (self.app.game_enabled, self.app.mic_enabled, self.app.send_enabled,
                         self.app.follow_fullscreen, self.app.fast_turns):
            widget = switches[str(variable)]
            with self.subTest(variable=str(variable)):
                self.assertTrue(widget.cget("text"))
                self.assertTrue(widget.instate(["selected"]))
                widget.invoke()
                self.assertFalse(variable.get())
                self.assertTrue(widget.instate(["!selected"]))
                self.assertTrue(all(w.instate(["selected"]) for w in switches.values() if w is not widget))
                variable.set(True)
                self.assertTrue(widget.instate(["selected"]))
        self.app.active.add("game")
        self.app.sync_controls()
        switches[str(self.app.mic_enabled)].invoke()
        self.assertTrue(self.app.mic_enabled.get())
        self.assertTrue(switches[str(self.app.follow_fullscreen)].instate(["!disabled"]))

    def test_routing_reflects_language_and_effective_chatbox_mode(self):
        self.app.mic_language.set("日本語")
        self.app.close_settings()
        self.assertIn("日本語", self.app.panels["mic"].direction.cget("text"))
        self.app.send_enabled.set(True)
        self.app.backend.set(DEMO)
        self.app.sync_controls()
        self.assertEqual(self.app.panels["mic"].route.cget("text"), "仅本机预览")
        self.app.mic_enabled.set(False)
        self.app.sync_controls()
        self.assertEqual(self.app.panels["mic"].route.cget("text"), "麦克风已关闭")

    def test_mini_window_follows_only_latest_game_lines_and_restores_main(self):
        self.app.open_mini()
        self.root.update()
        self.assertFalse(self.root.winfo_viewable())
        self.assertTrue(self.app.mini_window.winfo_viewable())
        self.assertTrue(self.app.mini_window.attributes("-topmost"))
        for line in ("first", "second", "third"):
            self.app.events.put(("game", TranslationEvent("final", line)))
        self.app.events.put(("mic", TranslationEvent("final", "private")))
        self.app.events.put(("game", TranslationEvent("partial", "draft")))
        self.root.after_cancel(self.app.poll_task)
        self.app.poll()
        self.assertEqual(self.app.mini_output.get("1.0", "end-1c"), "third\ndraft")
        self.app.close_mini()
        self.root.update()
        self.assertTrue(self.root.winfo_viewable())
        self.assertEqual(list(self.app.panels["game"].history), ["first", "second", "third"])

    @unittest.skipUnless(sys.platform == "win32", "Windows desktop fullscreen")
    def test_auto_mini_restores_on_alt_tab_but_manual_mini_stays(self):
        game_hwnd, other_hwnd = 111, 222
        def screen_for(hwnd):
            return Screen(0, 0, 1920, 1080) if hwnd == game_hwnd else None

        with patch("vrc_transf.app.foreground_window", return_value=game_hwnd) as foreground, \
                patch("vrc_transf.app.fullscreen_game_screen", side_effect=screen_for):
            self.app._sync_fullscreen()
            self.assertTrue(self.app.mini_window.winfo_viewable())
            foreground.return_value = int(self.app.mini_window.wm_frame(), 16)
            self.app._sync_fullscreen()
            self.assertTrue(self.app.mini_window.winfo_viewable())
            foreground.return_value = other_hwnd
            self.app._sync_fullscreen()
            self.assertTrue(self.root.winfo_viewable())
            self.assertFalse(self.app.mini_window.winfo_viewable())
            self.app.open_mini()
            self.root.update()
            for foreground.return_value in (game_hwnd, other_hwnd):
                self.app._sync_fullscreen()
                self.assertTrue(self.app.mini_window.winfo_viewable())

    @unittest.skipUnless(sys.platform == "win32", "Windows desktop fullscreen")
    def test_manual_return_suppresses_reopen_until_fullscreen_ends(self):
        with patch("vrc_transf.app.foreground_window", return_value=111), \
                patch("vrc_transf.app.fullscreen_game_screen", return_value=Screen(0, 0, 1280, 720)) as screen:
            self.app.follow_fullscreen.set(False)
            self.app._sync_fullscreen()
            self.assertFalse(self.app.mini_window.winfo_viewable())
            self.app.follow_fullscreen.set(True)
            self.app._sync_fullscreen()
            self.app.close_mini()
            self.app._sync_fullscreen()
            self.assertFalse(self.app.mini_window.winfo_viewable())
            screen.return_value = None
            self.app._sync_fullscreen()
            screen.return_value = Screen(0, 0, 1280, 720)
            self.app._sync_fullscreen()
            self.assertTrue(self.app.mini_window.winfo_viewable())
