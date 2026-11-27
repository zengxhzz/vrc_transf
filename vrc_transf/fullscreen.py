"""Detect a foreground VRChat desktop window covering its monitor."""

import ctypes
import ntpath
import sys
from ctypes import wintypes as w
from typing import NamedTuple


class Screen(NamedTuple):
    left: int
    top: int
    right: int
    bottom: int


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("screen", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


if sys.platform == "win32":
    user = ctypes.WinDLL("user32")
    kernel = ctypes.WinDLL("kernel32")

    def _bind(library, name, result, *args):
        function = getattr(library, name)
        function.argtypes = args
        function.restype = result
        return function

    _foreground = _bind(user, "GetForegroundWindow", w.HWND)
    _window_pid = _bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, ctypes.POINTER(w.DWORD))
    _client = _bind(user, "GetClientRect", w.BOOL, w.HWND, ctypes.POINTER(w.RECT))
    _to_screen = _bind(user, "ClientToScreen", w.BOOL, w.HWND, ctypes.POINTER(w.POINT))
    _monitor = _bind(user, "MonitorFromWindow", w.HANDLE, w.HWND, w.DWORD)
    _info = _bind(user, "GetMonitorInfoW", w.BOOL, w.HANDLE, ctypes.POINTER(_MonitorInfo))
    _iconic = _bind(user, "IsIconic", w.BOOL, w.HWND)
    _visible = _bind(user, "IsWindowVisible", w.BOOL, w.HWND)
    _open = _bind(kernel, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
    _image = _bind(kernel, "QueryFullProcessImageNameW", w.BOOL, w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD))
    _close = _bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)


def foreground_window():
    return _foreground() if sys.platform == "win32" else None


def _is_vrchat(hwnd):
    pid = w.DWORD()
    if not _window_pid(hwnd, ctypes.byref(pid)):
        return False
    process = _open(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return False
    try:
        size = w.DWORD(32768)
        path = ctypes.create_unicode_buffer(size.value)
        return bool(_image(process, 0, path, ctypes.byref(size))) and ntpath.basename(path.value).lower() == "vrchat.exe"
    finally:
        _close(process)


def fullscreen_game_screen(hwnd):
    if not hwnd or sys.platform != "win32" or _iconic(hwnd) or not _visible(hwnd):
        return None
    monitor = _monitor(hwnd, 0)
    info = _MonitorInfo(size=ctypes.sizeof(_MonitorInfo))
    rect = w.RECT()
    if not monitor or not _info(monitor, ctypes.byref(info)) or not _client(hwnd, ctypes.byref(rect)):
        return None
    start, end = w.POINT(rect.left, rect.top), w.POINT(rect.right, rect.bottom)
    if not _to_screen(hwnd, ctypes.byref(start)) or not _to_screen(hwnd, ctypes.byref(end)):
        return None
    bounds = info.screen
    screen = Screen(bounds.left, bounds.top, bounds.right, bounds.bottom)
    client = (start.x, start.y, end.x, end.y)
    # Compare the drawable area, so an ordinary maximized window with a title bar is excluded.
    if all(abs(a - b) <= 1 for a, b in zip(client, screen)) and _is_vrchat(hwnd):
        return screen
    return None
