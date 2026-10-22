"""Targeted standard Win32 controls only; never global mouse/keyboard injection."""

import ctypes
import hashlib
import json
import re
from typing import Any

from adam.core.privacy import contains_secret
from adam.vision.images import VisionError
from adam.vision.screen import permitted, window_metadata


class ComputerError(VisionError):
    pass


DANGEROUS = re.compile(
    r"save|clear|reset|open|browse|export|share|publish|password|passphrase|token|secret|delete|remove|send|submit|purchase|pay|transfer|install|run|execute|permission|allow|confirm|sign.?in|log.?in",
    re.I,
)
EDIT = {"Edit", "RichEdit20W", "RICHEDIT50W"}


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


class Controls:
    def read(
        self, window: dict[str, Any], allowed: list[str], excluded: list[str]
    ) -> list[dict[str, Any]]:
        import win32con  # type: ignore[import-untyped]
        import win32gui  # type: ignore[import-untyped]
        import win32process  # type: ignore[import-untyped]

        current = window_metadata(window["hwnd"])
        permitted(current, allowed, excluded)
        blocked = {
            "explorer.exe",
            "cmd.exe",
            "powershell.exe",
            "pwsh.exe",
            "windowsterminal.exe",
            "taskmgr.exe",
            "regedit.exe",
            "mmc.exe",
            "control.exe",
            "rundll32.exe",
            "msiexec.exe",
            "setup.exe",
            "wscript.exe",
            "cscript.exe",
            "conhost.exe",
        }
        if current["app"] in blocked or DANGEROUS.search(current["title"]):
            raise ComputerError("COMPUTER.PRIVATE_CONTROL_DENIED")
        if current != window:
            raise ComputerError("COMPUTER.WINDOW_CHANGED")
        result: list[dict[str, Any]] = []

        def child(hwnd: int, _: Any) -> bool:
            if len(result) >= 100:
                raise ComputerError("COMPUTER.CONTROL_LIMIT")
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid != window["pid"] or not win32gui.IsWindowVisible(hwnd):
                return True
            kind = win32gui.GetClassName(hwnd)
            if kind not in {*EDIT, "Button", "Static"}:
                return True
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            if kind in EDIT and style & win32con.ES_PASSWORD:
                raise ComputerError("COMPUTER.PRIVATE_CONTROL_DENIED")
            text = self.text(hwnd)
            if len(text) > 4000 or contains_secret(text):
                raise ComputerError("COMPUTER.PRIVATE_CONTROL_DENIED")
            enabled = bool(win32gui.IsWindowEnabled(hwnd))
            actions = []
            if enabled and not DANGEROUS.search(text):
                if kind in EDIT and not style & win32con.ES_READONLY:
                    actions = ["type"]
                elif kind == "Button" and style & 15 == win32con.BS_PUSHBUTTON:
                    actions = ["click"]
            result.append(
                {
                    "hwnd": hwnd,
                    "class": kind,
                    "text": text,
                    "rect": win32gui.GetWindowRect(hwnd),
                    "actions": actions,
                }
            )
            return True

        win32gui.EnumChildWindows(window["hwnd"], child, None)
        if window_metadata(window["hwnd"]) != window:
            raise ComputerError("COMPUTER.WINDOW_CHANGED")
        from collections import Counter

        labels = Counter((c["class"], c["text"]) for c in result if c["actions"])
        for control in result:
            if labels[(control["class"], control["text"])] > 1:
                control["actions"] = []
        return result

    @staticmethod
    def message(hwnd: int, message: int, wparam: int, lparam: Any) -> int:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.SendMessageTimeoutW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        user.SendMessageTimeoutW.restype = ctypes.c_void_p
        result = ctypes.c_size_t()
        pointer = ctypes.cast(lparam, ctypes.c_void_p) if lparam is not None else None
        if not user.SendMessageTimeoutW(
            hwnd, message, wparam, pointer, 0x22, 1500, ctypes.byref(result)
        ):
            raise ComputerError("COMPUTER.CONTROL_TIMEOUT")
        return result.value

    @classmethod
    def text(cls, hwnd: int) -> str:
        length = cls.message(hwnd, 14, 0, None)
        if length > 4000:
            raise ComputerError("COMPUTER.PRIVATE_CONTROL_DENIED")
        buffer = ctypes.create_unicode_buffer(length + 1)
        cls.message(hwnd, 13, length + 1, buffer)
        return buffer.value

    def act(self, control: dict[str, Any], kind: str, text: str) -> None:
        if (
            kind not in control["actions"]
            or contains_secret(text)
            or DANGEROUS.search(control["text"])
        ):
            raise ComputerError("COMPUTER.ACTION_DENIED")
        if kind == "type":
            self.message(control["hwnd"], 12, 0, ctypes.create_unicode_buffer(text))
        else:
            self.message(control["hwnd"], 0xF5, 0, None)
