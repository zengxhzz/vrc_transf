import tkinter as tk
import unittest
from tkinter import ttk
from unittest.mock import patch

from vrc_transf.app import App, DEMO, REGIONS


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
