"""A source/API model's Windows tray indicator. No microphone or capture capability."""

import os
import threading
import uuid
from collections.abc import Callable
from typing import Any


class ModelIndicator:
    def __init__(self, stop: Callable[[], None], mode: str) -> None:
        self.stop_model, self.mode = stop, mode
        self.window: Any = None
        self.available = False
        self.ready = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> bool:
        if os.name != "nt" or os.environ.get("ADAM_DESKTOP_HOST") == "1":
            return False  # The native desktop owns its own service-wide tray indicator.
        self.thread = threading.Thread(target=self._run, daemon=True, name="adam-model-indicator")
        self.thread.start()
        self.ready.wait(timeout=3)
        return self.available

    def _run(self) -> None:
        import win32api  # type: ignore[import-untyped]
        import win32con  # type: ignore[import-untyped]
        import win32gui  # type: ignore[import-untyped]

        callback = win32con.WM_USER + 20
        class_name = "ADAMModelIndicator-" + uuid.uuid4().hex

        def message(window: Any, event: int, first: int, second: int) -> int:
            if event == callback and second in {win32con.WM_RBUTTONUP, win32con.WM_LBUTTONUP}:
                menu = win32gui.CreatePopupMenu()
                try:
                    win32gui.AppendMenu(
                        menu,
                        win32con.MF_STRING | win32con.MF_GRAYED,
                        0,
                        "ADAM model running · " + self.mode.title(),
                    )
                    win32gui.AppendMenu(
                        menu,
                        win32con.MF_STRING | win32con.MF_GRAYED,
                        0,
                        "This model process has no microphone access",
                    )
                    win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "Stop model and free RAM")
                    win32gui.SetForegroundWindow(window)
                    x, y = win32gui.GetCursorPos()
                    selected = win32gui.TrackPopupMenu(
                        menu, win32con.TPM_RETURNCMD, x, y, 0, window, None
                    )
                    if selected == 1:
                        self.stop_model()
                finally:
                    win32gui.DestroyMenu(menu)
                return 0
            if event == win32con.WM_CLOSE:
                win32gui.DestroyWindow(window)
                return 0
            if event == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return int(win32gui.DefWindowProc(window, event, first, second))

        try:
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = message
            win32gui.RegisterClass(window_class)
            self.window = win32gui.CreateWindow(
                class_name, "ADAM model status", 0, 0, 0, 0, 0, 0, 0, window_class.hInstance, None
            )
            icon = win32gui.LoadIcon(0, win32con.IDI_INFORMATION)
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD,
                (
                    self.window,
                    0,
                    win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                    callback,
                    icon,
                    "ADAM model running · " + self.mode + " · no microphone capture",
                ),
            )
            self.available = True
            self.ready.set()
            win32gui.PumpMessages()
        except Exception:
            self.available = False  # Terminal remains visible; background source is not enabled.
        finally:
            self.ready.set()
            if self.window:
                try:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.window, 0))
                except Exception:
                    pass
            self.window, self.available = None, False
            try:
                win32gui.UnregisterClass(class_name, win32api.GetModuleHandle(None))
            except Exception:
                pass

    def close(self) -> None:
        if self.window:
            import win32con
            import win32gui

            win32gui.PostMessage(self.window, win32con.WM_CLOSE, 0, 0)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
