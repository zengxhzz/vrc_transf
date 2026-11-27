import sys


def check_install(*, interactive_desktop):
    """Exercise the installed GUI and its native libraries without external services."""
    import ssl
    import time
    import tkinter as tk

    import pyaudiowpatch
    from capturekit._backends.windows.api import open_audio
    from vrc_transf.app import App, DEMO
    from vrc_transf.audio import PcmConverter

    if not callable(open_audio) or not pyaudiowpatch.get_portaudio_version():
        raise RuntimeError("Windows audio backend unavailable")
    converter = PcmConverter(48000, 2)
    pcm = converter.convert(bytes(4800 * 4)) + converter.finish()
    if len(pcm) != 3200 or not ssl.create_default_context().get_ca_certs():
        raise RuntimeError("Audio resampling or system TLS trust unavailable")

    root = tk.Tk()
    app = App(root)
    try:
        app.follow_fullscreen.set(False)
        app.open_settings()
        app.backend.set(DEMO)
        app.close_settings()
        app.start_button.invoke()
        deadline = time.monotonic() + 12
        while app.active and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        if app.active or not all(panel.history for panel in app.panels.values()):
            raise RuntimeError("Demo did not produce both captions")
        app.open_mini()
        root.update()
        if app.panels["game"].history[-1] not in app.mini_output.get("1.0", "end"):
            raise RuntimeError("Mini window did not show the game caption")
        if interactive_desktop and not app.mini_window.winfo_viewable():
            raise RuntimeError("Mini window did not open")
        app.close_mini()
    finally:
        app.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("--self-test", "--self-test-headless"):
        import traceback
        from pathlib import Path

        report = Path(sys.argv[2])
        try:
            check_install(interactive_desktop=sys.argv[1] == "--self-test")
        except Exception:
            report.write_text(traceback.format_exc(), encoding="utf-8")
            sys.exit(1)
        report.write_text("PASS", encoding="utf-8")
    else:
        from vrc_transf.app import main

        main()
