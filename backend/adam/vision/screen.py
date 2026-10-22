"""One foreground window only. No desktop fallback, input injection or hidden polling."""

import base64
import ctypes
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from PIL import Image

from adam.security.auth import AuthError
from adam.vision.images import MAX_BYTES, MAX_PIXELS, VisionError

BLOCKED_APPS = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "keepass.exe",
        "keepassxc.exe",
        "1password.exe",
        "bitwarden.exe",
        "credentialuibroker.exe",
        "consent.exe",
        "logonui.exe",
        "adam-desktop.exe",
        "codex.exe",
    }
)
PRIVATE_TITLES = (
    "password",
    "passphrase",
    "sign in",
    "sign-in",
    "log in",
    "login",
    "bank",
    "payment",
    "credit card",
    "incognito",
    "inprivate",
    "private browsing",
)


def permitted(metadata: dict[str, Any], allowed: list[str], excluded: list[str]) -> None:
    process = str(metadata["app"]).casefold()
    title = str(metadata["title"]).casefold()
    if (
        process in BLOCKED_APPS
        or process not in allowed
        or any(term in title for term in (*PRIVATE_TITLES, *excluded))
        or metadata.get("protected")
        or metadata.get("minimized")
    ):
        raise VisionError("VISION.PRIVATE_WINDOW_DENIED")


def window_metadata(hwnd: int) -> dict[str, Any]:
    if sys.platform != "win32":
        raise VisionError("VISION.CAPTURE_UNAVAILABLE")
    import psutil  # type: ignore[import-untyped]
    import win32gui  # type: ignore[import-untyped]
    import win32process  # type: ignore[import-untyped]

    if not hwnd or not win32gui.IsWindowVisible(hwnd):
        raise VisionError("VISION.CAPTURE_UNAVAILABLE")
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    try:
        process = psutil.Process(pid)
        app = process.name().casefold()
        created = process.create_time()
    except (psutil.Error, OSError):
        raise VisionError("VISION.WINDOW_UNAVAILABLE") from None
    user = ctypes.WinDLL("user32", use_last_error=True)
    affinity = ctypes.c_ulong(0)
    user.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    # Unknown display affinity is denied, not treated as unprotected.
    known = user.GetWindowDisplayAffinity(hwnd, ctypes.byref(affinity))
    title = win32gui.GetWindowText(hwnd)
    return {
        "hwnd": hwnd,
        "pid": pid,
        "created": created,
        "app": app,
        "title": title[:512],
        "protected": not known or bool(affinity.value),
        "minimized": bool(win32gui.IsIconic(hwnd)),
        "rect": win32gui.GetWindowRect(hwnd),
    }


def foreground() -> dict[str, Any]:
    if sys.platform != "win32":
        raise VisionError("VISION.CAPTURE_UNAVAILABLE")
    import win32gui

    return window_metadata(int(win32gui.GetForegroundWindow()))


def _capture_worker(
    connection: Any, allowed: list[str], excluded: list[str], selected: dict[str, Any] | None
) -> None:
    """Separate killable process bounds synchronous PrintWindow and GDI cleanup."""
    try:
        import win32gui
        import win32ui  # type: ignore[import-untyped]

        connection.send({"worker_ready": True})

        before = window_metadata(selected["hwnd"]) if selected else foreground()
        permitted(before, allowed, excluded)
        if selected and before != selected:
            raise VisionError("VISION.WINDOW_CHANGED")
        hwnd = before["hwnd"]
        left, top, right, bottom = before["rect"]
        width, height = right - left, bottom - top
        if width < 2 or height < 2 or width * height > MAX_PIXELS or max(width, height) > 8192:
            raise VisionError("VISION.IMAGE_LIMIT")
        dc = win32gui.GetWindowDC(hwnd)
        source = target = bitmap = None
        try:
            source = win32ui.CreateDCFromHandle(dc)
            target = source.CreateCompatibleDC()
            bitmap = win32ui.CreateBitmap()
            bitmap.CreateCompatibleBitmap(source, width, height)
            target.SelectObject(bitmap)
            # Only the selected HWND renders. Never substitute a full-screen BitBlt.
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
            if not user.PrintWindow(hwnd, target.GetSafeHdc(), 2):
                raise VisionError("VISION.CAPTURE_UNAVAILABLE")
            after = window_metadata(before["hwnd"]) if selected else foreground()
            permitted(after, allowed, excluded)
            if before != after:
                raise VisionError("VISION.WINDOW_CHANGED")
            image = Image.frombytes(
                "RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1
            )
            if image.getextrema() == ((0, 0), (0, 0), (0, 0)):
                raise VisionError("VISION.CAPTURE_UNAVAILABLE")
            image.thumbnail((2000, 2000))
            output = io.BytesIO()
            image.save(output, "PNG")
            raw = output.getvalue()
            if len(raw) > MAX_BYTES:
                raise VisionError("VISION.IMAGE_LIMIT")
            connection.send(
                {
                    "png": raw,
                    "metadata": {
                        "app": before["app"],
                        "title": before["title"],
                        "pid": before["pid"],
                        "source_device": "local_desktop",
                        "source": "selected_window" if selected else "foreground_window",
                        "active_at_capture": win32gui.GetForegroundWindow() == hwnd,
                    },
                }
            )
        finally:
            if bitmap:
                win32gui.DeleteObject(bitmap.GetHandle())
            if target:
                target.DeleteDC()
            if source:
                source.DeleteDC()
            win32gui.ReleaseDC(hwnd, dc)
    except VisionError as exc:
        connection.send({"error": exc.code})
    except Exception:
        connection.send({"error": "VISION.CAPTURE_UNAVAILABLE"})
    finally:
        connection.close()


class _IndicatorHost:
    """Topmost non-activating notice remains visible even after ADAM loses focus."""

    def __init__(self) -> None:
        self.hwnd = 0
        self.ready = threading.Event()
        self.changed = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            import win32api  # type: ignore[import-untyped]
            import win32con  # type: ignore[import-untyped]
            import win32gui

            name = "ADAMVisionIndicator" + str(os.getpid()) + os.urandom(4).hex()

            def callback(hwnd: int, message: int, wparam: int, lparam: int) -> int:
                if message == win32con.WM_APP + 1:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
                    win32gui.UpdateWindow(hwnd)
                    self.changed.set()
                    return 0
                if message == win32con.WM_APP + 2:
                    win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                    self.changed.set()
                    return 0
                if message == win32con.WM_DESTROY:
                    win32gui.PostQuitMessage(0)
                    return 0
                if message == win32con.WM_PAINT:
                    dc, paint = win32gui.BeginPaint(hwnd)
                    win32gui.SetBkMode(dc, 1)
                    win32gui.SetTextColor(dc, 0xFFFFFF)
                    win32gui.DrawText(
                        dc,
                        "ADAM SCREEN CAPTURE\nOne window • local only",
                        -1,
                        (12, 8, 308, 68),
                        win32con.DT_LEFT,
                    )
                    win32gui.EndPaint(hwnd, paint)
                    return 0
                return int(win32gui.DefWindowProc(hwnd, message, wparam, lparam))

            wc = win32gui.WNDCLASS()
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.lpszClassName = name
            wc.lpfnWndProc = callback
            wc.hbrBackground = win32gui.CreateSolidBrush(0x3030A0)
            win32gui.RegisterClass(wc)
            try:
                self.hwnd = win32gui.CreateWindowEx(
                    win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW,
                    name,
                    "ADAM screen capture",
                    win32con.WS_POPUP,
                    20,
                    20,
                    320,
                    78,
                    0,
                    0,
                    wc.hInstance,
                    None,
                )
                self.ready.set()
                win32gui.PumpMessages()
            finally:
                self.hwnd = 0
                win32gui.UnregisterClass(name, wc.hInstance)
        except Exception:
            self.ready.set()

    def show(self, visible: bool) -> None:
        import win32con
        import win32gui

        if not self.ready.wait(2) or not self.hwnd:
            raise VisionError("VISION.INDICATOR_UNAVAILABLE")
        self.changed.clear()
        win32gui.PostMessage(self.hwnd, win32con.WM_APP + (1 if visible else 2), 0, 0)
        if not self.changed.wait(2) or bool(win32gui.IsWindowVisible(self.hwnd)) != visible:
            raise VisionError("VISION.INDICATOR_UNAVAILABLE")


_indicator_lock = threading.Lock()
_indicator_host: _IndicatorHost | None = None


class Indicator:
    """Reuse one message-pump thread; Windows releases its hidden window at process exit."""

    def start(self) -> None:
        global _indicator_host
        with _indicator_lock:
            if _indicator_host is None:
                _indicator_host = _IndicatorHost()
                _indicator_host.thread.start()
            _indicator_host.show(True)

    def close(self) -> None:
        with _indicator_lock:
            if _indicator_host is not None and _indicator_host.hwnd:
                _indicator_host.show(False)


class Screen:
    def available(self) -> bool:
        return sys.platform == "win32"

    def windows(self, allowed: list[str], excluded: list[str]) -> list[dict[str, Any]]:
        if not self.available():
            raise VisionError("VISION.CAPTURE_UNAVAILABLE")
        import psutil
        import win32gui
        import win32process

        result: list[dict[str, Any]] = []

        def inspect(hwnd: int, _: Any) -> bool:
            if len(result) >= 30:
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if psutil.Process(pid).name().casefold() not in allowed:
                    return True
                metadata = window_metadata(hwnd)
                permitted(metadata, allowed, excluded)
                result.append(metadata)
            except (VisionError, psutil.Error, OSError):
                pass
            return True

        win32gui.EnumWindows(inspect, None)
        return result

    def capture(
        self,
        allowed: list[str],
        excluded: list[str],
        guard: Callable[[], None],
        selected: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.available():
            raise VisionError("VISION.CAPTURE_UNAVAILABLE")
        notice = Indicator()
        process = None
        reader = None
        job = None
        try:
            notice.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                guard()
                time.sleep(0.05)
            guard()
            if getattr(sys, "frozen", False):
                command = [sys.executable, "--vision-worker"]
            else:
                import sysconfig

                # Avoid the Windows venv redirector: own the actual worker PID before capture.
                code = (
                    "import site,runpy;site.addsitedir("
                    + repr(sysconfig.get_path("purelib"))
                    + ");runpy.run_module('adam.vision.worker',run_name='__main__')"
                )
                command = [os.path.realpath(sys._base_executable), "-c", code]  # type: ignore[attr-defined]
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            import win32api
            import win32job  # type: ignore[import-untyped]

            job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, limits
            )
            # Assign before sending metadata: the worker cannot start capture outside its owned job.
            win32job.AssignProcessToJobObject(job, int(process._handle))  # type: ignore[attr-defined]
            assert process.stdin and process.stdout
            process.stdin.write(
                json.dumps({"allowed": allowed, "excluded": excluded, "selected": selected}) + "\n"
            )
            process.stdin.close()
            lines: queue.Queue[str] = queue.Queue(maxsize=3)

            def receive() -> None:
                assert process and process.stdout
                for _ in range(3):
                    line = process.stdout.readline(4_210_000)
                    lines.put(line)
                    if not line:
                        return

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()

            def read(timeout: float, code: str) -> dict[str, Any]:
                deadline = time.monotonic() + timeout
                while True:
                    guard()
                    try:
                        line = lines.get(timeout=0.05)
                    except queue.Empty:
                        if time.monotonic() > deadline:
                            raise VisionError(code) from None
                        continue
                    if not line or not line.endswith("\n"):
                        raise VisionError("VISION.CAPTURE_UNAVAILABLE")
                    result: dict[str, Any] = json.loads(line)
                    return result

            result = read(20, "VISION.CAPTURE_TIMEOUT")
            if result.get("worker_ready"):
                result = read(5, "VISION.CAPTURE_RENDER_TIMEOUT")
            guard()
            if "error" in result:
                raise VisionError(result["error"])
            result["png"] = base64.b64decode(result.pop("png_base64"), validate=True)
            return result
        except (VisionError, AuthError):
            raise
        except Exception:
            raise VisionError("VISION.CAPTURE_UNAVAILABLE") from None
        finally:
            children = []
            if process and process.poll() is None:
                import psutil

                try:
                    children = psutil.Process(process.pid).children(recursive=True)
                except psutil.Error:
                    pass
            if job is not None:
                import win32api

                win32api.CloseHandle(job)
            if process:
                for child in children:
                    try:
                        child.terminate()
                    except psutil.Error:
                        pass
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
                if reader:
                    reader.join(timeout=2)
                if process.stdout and (reader is None or not reader.is_alive()):
                    process.stdout.close()
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
            notice.close()
