"""Real Win32 controls and OCR against a disposable application, never personal windows."""

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import win32api
import win32con
import win32gui
from adam import APP_VERSION


class Fixture:
    def __init__(self):
        self.hwnd = 0
        self.ready = threading.Event()
        self.created_event = threading.Event()
        self.next_kind = ""
        self.created = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        name = "ADAMControlledQA" + str(os.getpid())
        module = win32api.GetModuleHandle(None)

        def callback(hwnd, message, wparam, lparam):
            if message == win32con.WM_APP + 1:
                private = self.next_kind == "password"
                self.created = win32gui.CreateWindow(
                    "Edit" if private else "Button",
                    "synthetic private fixture" if private else "Show result",
                    win32con.WS_CHILD
                    | win32con.WS_VISIBLE
                    | (win32con.ES_PASSWORD if private else win32con.BS_PUSHBUTTON),
                    220,
                    190 if private else 140,
                    180,
                    30,
                    hwnd,
                    5 if private else 4,
                    module,
                    None,
                )
                self.created_event.set()
                return 0
            if message == win32con.WM_COMMAND and wparam & 65535 == 3:
                win32gui.SetWindowText(self.result, "Shown: " + win32gui.GetWindowText(self.edit))
                return 0
            if message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.hInstance = module
        wc.lpszClassName = name
        wc.lpfnWndProc = callback
        wc.hbrBackground = win32con.COLOR_WINDOW + 1
        win32gui.RegisterClass(wc)
        try:
            self.hwnd = win32gui.CreateWindow(
                name,
                "ADAM computer QA",
                win32con.WS_OVERLAPPEDWINDOW,
                400,
                220,
                800,
                280,
                0,
                0,
                module,
                None,
            )
            style = win32con.WS_CHILD | win32con.WS_VISIBLE
            self.edit = win32gui.CreateWindow(
                "Edit",
                "Original",
                style | win32con.WS_BORDER,
                20,
                25,
                720,
                35,
                self.hwnd,
                1,
                module,
                None,
            )
            self.result = win32gui.CreateWindow(
                "Static", "Waiting", style, 20, 80, 720, 35, self.hwnd, 2, module, None
            )
            self.button = win32gui.CreateWindow(
                "Button",
                "Show result",
                style | win32con.BS_PUSHBUTTON,
                20,
                140,
                180,
                35,
                self.hwnd,
                3,
                module,
                None,
            )
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOWNOACTIVATE)
            win32gui.UpdateWindow(self.hwnd)
            self.ready.set()
            win32gui.PumpMessages()
        finally:
            self.hwnd = 0
            win32gui.UnregisterClass(name, module)

    def create(self, kind):
        self.next_kind = kind
        self.created_event.clear()
        win32gui.PostMessage(self.hwnd, win32con.WM_APP + 1, 0, 0)
        assert self.created_event.wait(5) and self.created
        return self.created

    def __enter__(self):
        self.thread.start()
        assert self.ready.wait(5) and self.hwnd
        return self

    def __exit__(self, *_):
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        self.thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checks = []

    def check(name, value):
        assert value, name
        checks.append(name)
        print("QA passed:", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="adam-computer-qa-") as temporary, Fixture() as fixture:
        command = (
            [str(args.service.resolve())]
            if args.service
            else [sys.executable, "-m", "adam.desktop.service"]
        ) + ["--probe", "--data-dir", temporary]
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True).start()
            ready = json.loads(lines.get(timeout=150))
            with httpx.Client(
                base_url=f"http://127.0.0.1:{ready['port']}",
                headers={"x-adam-desktop": ready["nonce"]},
                timeout=150,
            ) as client:
                password = "synthetic-computer-owner-238947"
                check(
                    "owner setup",
                    client.post("/desktop/setup", json={"password": password}).status_code == 200,
                )
                token = client.post("/auth/login", json={"password": password}).json()["token"]
                client.headers["Authorization"] = "Bearer " + token
                check("computer starts off", not client.get("/computer").json()["enabled"])
                check(
                    "enable needs reauthentication",
                    client.post("/computer/configure", json={"enabled": True}).status_code == 403,
                )
                client.post("/auth/elevate", json={"password": password}).raise_for_status()

                def enable():
                    response = client.post(
                        "/computer/configure",
                        json={"enabled": True, "allowed_apps": ["python.exe"]},
                    )
                    response.raise_for_status()

                def window():
                    windows = client.get("/computer/windows").json()["windows"]
                    return next(w["id"] for w in windows if w["title"] == "ADAM computer QA")

                def observe():
                    response = client.post("/computer/observe", json={"id": window()})
                    if response.status_code != 200:
                        raise AssertionError(response.json())
                    return response.json()

                enable()
                observed = observe()
                check(
                    "actual OCR and capture",
                    bool(observed["preview_base64"]) and bool(observed["text"]),
                )
                check(
                    "observe never acts",
                    win32gui.GetWindowText(fixture.edit) == "Original"
                    and not observed["action_authority"],
                )
                edit = next(c["id"] for c in observed["controls"] if "type" in c["actions"])
                button = next(c["id"] for c in observed["controls"] if "click" in c["actions"])
                status = next(c["id"] for c in observed["controls"] if c["class"] == "Static")
                steps = [
                    {
                        "target": edit,
                        "action": "type",
                        "text": "Synthetic hello",
                        "verify_target": edit,
                        "expected": "Synthetic hello",
                    },
                    {
                        "target": button,
                        "action": "click",
                        "verify_target": status,
                        "expected": "Shown: Synthetic hello",
                    },
                ]
                plan = client.post("/computer/plan", json={"steps": steps}).json()
                check("explicit preview", plan["status"] == "PREVIEW")
                check(
                    "execute blocked without approval",
                    client.post("/computer/execute", json={"id": plan["id"]}).status_code == 409,
                )
                dry = client.post(
                    "/computer/execute", json={"id": plan["id"], "dry_run": True}
                ).json()
                check(
                    "real dry run no input",
                    dry["status"] == "DRY_RUN_VERIFIED"
                    and win32gui.GetWindowText(fixture.edit) == "Original",
                )
                check(
                    "different digest denied",
                    client.post(
                        "/computer/approve", json={"id": plan["id"], "digest": "0" * 64}
                    ).status_code
                    == 409,
                )
                check(
                    "exact approval",
                    client.post(
                        "/computer/approve", json={"id": plan["id"], "digest": plan["digest"]}
                    ).status_code
                    == 200,
                )
                result = client.post("/computer/execute", json={"id": plan["id"]})
                if result.status_code != 200:
                    raise AssertionError(result.json())
                check(
                    "two steps verified",
                    result.json()["status"] == "VERIFIED" and result.json()["completed"] == 2,
                )
                check(
                    "independent native text and click effect",
                    win32gui.GetWindowText(fixture.edit) == "Synthetic hello"
                    and win32gui.GetWindowText(fixture.result) == "Shown: Synthetic hello",
                )
                check("post-action screenshot", bool(result.json()["preview_base64"]))
                check(
                    "once-only no retry",
                    client.post("/computer/execute", json={"id": plan["id"]}).status_code == 409,
                )
                duplicate = fixture.create("duplicate")
                ambiguous = observe()
                check(
                    "duplicate actionable labels denied",
                    not any("click" in c["actions"] for c in ambiguous["controls"]),
                )
                win32gui.SendMessage(duplicate, win32con.WM_CLOSE, 0, 0)
                private = fixture.create("password")
                denied = client.post("/computer/observe", json={"id": window()}).json()
                check(
                    "password control denied before capture",
                    denied.get("error") == "COMPUTER.PRIVATE_CONTROL_DENIED",
                )
                win32gui.SendMessage(private, win32con.WM_CLOSE, 0, 0)
                # An unexpected edit after observation must prevent any input.
                observed = observe()
                edit = next(c["id"] for c in observed["controls"] if "type" in c["actions"])
                draft = client.post(
                    "/computer/plan",
                    json={
                        "steps": [
                            {
                                "target": edit,
                                "action": "type",
                                "text": "Must not type",
                                "verify_target": edit,
                                "expected": "Must not type",
                            }
                        ]
                    },
                ).json()
                client.post(
                    "/computer/approve", json={"id": draft["id"], "digest": draft["digest"]}
                ).raise_for_status()
                win32gui.SetWindowText(fixture.edit, "Changed by disposable fixture")
                denied = client.post("/computer/execute", json={"id": draft["id"]}).json()
                check(
                    "unexpected UI change denied",
                    denied.get("error") == "COMPUTER.UI_CHANGED"
                    and win32gui.GetWindowText(fixture.edit) == "Changed by disposable fixture",
                )
                # Cancel while the capture notice is visible, before any action.
                ticket = window()
                outcome = queue.Queue()
                threading.Thread(
                    target=lambda: outcome.put(
                        client.post("/computer/observe", json={"id": ticket}).json()
                    ),
                    daemon=True,
                ).start()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    notice = win32gui.FindWindow(None, "ADAM screen capture")
                    if notice and win32gui.IsWindowVisible(notice):
                        break
                    time.sleep(0.05)
                client.post("/computer/configure", json={"enabled": False}).raise_for_status()
                check(
                    "cancel discards observation",
                    outcome.get(timeout=30).get("error") == "COMPUTER.CANCELLED",
                )
                check(
                    "cancel leaves field untouched",
                    win32gui.GetWindowText(fixture.edit) == "Changed by disposable fixture",
                )
                enable()
                ticket = window()
                win32gui.SetWindowText(fixture.hwnd, "Password synthetic QA")
                check(
                    "private window denied",
                    client.post("/computer/observe", json={"id": ticket}).json().get("error")
                    in {"VISION.PRIVATE_WINDOW_DENIED", "COMPUTER.WINDOW_CHANGED"},
                )
                client.post("/computer/configure", json={"enabled": False})
                check("disabled state", not client.get("/computer").json()["enabled"])
                for file in Path(temporary).rglob("*.sqlite3"):
                    check(
                        "no UI payload in " + file.name, b"Synthetic hello" not in file.read_bytes()
                    )
        finally:
            if child.poll() is None:
                child.stdin.write("stop\n")
                child.stdin.flush()
                try:
                    child.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
        check("owned service stopped", child.returncode == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "passed": True,
                "checks": checks,
                "limits": (
                    "Synthetic application only. No personal apps, "
                    "global input or human acceptance."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
