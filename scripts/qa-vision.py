"""Disposable source/frozen OCR and one-window capture QA; synthetic fixture only."""

import argparse
import base64
import io
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from adam import APP_VERSION
from PIL import Image, ImageDraw, ImageFont


class FixtureWindow:
    def __init__(self):
        self.hwnd = 0
        self.ready = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)

    def run(self):
        import win32api
        import win32con
        import win32gui

        name = "ADAMSyntheticVisionQA"
        brush = win32gui.CreateSolidBrush(0xFFFFFF)

        def paint(dc):
            win32gui.FillRect(dc, (0, 0, 900, 220), brush)
            win32gui.SetTextColor(dc, 0)
            win32gui.DrawText(
                dc, "ADAM synthetic error: FILE NOT FOUND", -1, (25, 30, 875, 150), win32con.DT_LEFT
            )

        def callback(hwnd, message, wparam, lparam):
            if message == win32con.WM_PAINT:
                dc, area = win32gui.BeginPaint(hwnd)
                paint(dc)
                win32gui.EndPaint(hwnd, area)
                return 0
            if message == win32con.WM_PRINTCLIENT:
                paint(wparam)
                return 0
            if message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = name
        wc.lpfnWndProc = callback
        wc.hbrBackground = brush
        win32gui.RegisterClass(wc)
        try:
            self.hwnd = win32gui.CreateWindow(
                name,
                "ADAM synthetic visual QA",
                win32con.WS_OVERLAPPEDWINDOW,
                450,
                200,
                900,
                220,
                0,
                0,
                wc.hInstance,
                None,
            )
            win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)
            win32gui.UpdateWindow(self.hwnd)
            self.ready.set()
            win32gui.PumpMessages()
        finally:
            self.hwnd = 0
            win32gui.UnregisterClass(name, wc.hInstance)

    def __enter__(self):
        self.worker.start()
        assert self.ready.wait(5) and self.hwnd, "synthetic QA window ready"
        return self

    def __exit__(self, *_):
        import win32con
        import win32gui

        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
        self.worker.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument(
        "--parent-job", action="store_true", help="Exercise native-style nested worker ownership"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    checks = []
    password = "synthetic-vision-qa-passphrase-836940"

    def check(name, condition):
        assert condition, name
        checks.append(name)
        print("QA passed:", name, flush=True)

    def image(text):
        picture = Image.new("RGB", (900, 160), "white")
        ImageDraw.Draw(picture).text(
            (20, 25), text, fill="black", font=ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 28)
        )
        out = io.BytesIO()
        picture.save(out, "PNG")
        return {"image_base64": base64.b64encode(out.getvalue()).decode()}

    with tempfile.TemporaryDirectory(prefix="adam-vision-qa-") as directory:
        for iteration in range(2):
            command = (
                [str(args.service.resolve())]
                if args.service
                else [sys.executable, "-m", "adam.desktop.service"]
            ) + ["--probe", "--data-dir", directory]
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            parent_job = None
            try:
                if args.parent_job:
                    import win32job

                    parent_job = win32job.CreateJobObject(None, "")
                    limits = win32job.QueryInformationJobObject(
                        parent_job, win32job.JobObjectExtendedLimitInformation
                    )
                    limits["BasicLimitInformation"]["LimitFlags"] = (
                        win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    )
                    win32job.SetInformationJobObject(
                        parent_job, win32job.JobObjectExtendedLimitInformation, limits
                    )
                    win32job.AssignProcessToJobObject(parent_job, int(child._handle))
                    check("native-style parent ownership " + str(iteration), True)
                ready = queue.Queue()
                threading.Thread(
                    target=lambda p=child, channel=ready: channel.put(p.stdout.readline()),
                    daemon=True,
                ).start()
                receipt = json.loads(ready.get(timeout=150))
                check("ready handshake " + str(iteration), receipt["event"] == "ready")
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{receipt['port']}",
                    timeout=60,
                    headers={"x-adam-desktop": receipt["nonce"]},
                ) as client:
                    if not iteration:
                        check(
                            "owner setup",
                            client.post("/desktop/setup", json={"password": password}).status_code
                            == 200,
                        )
                    token = client.post("/auth/login", json={"password": password}).json()["token"]
                    client.headers["Authorization"] = "Bearer " + token
                    check(
                        "default off " + str(iteration), not client.get("/vision").json()["enabled"]
                    )
                    if iteration:
                        continue
                    check(
                        "disabled image denied",
                        client.post("/vision/analyze", json=image("Synthetic error")).json()[
                            "error"
                        ]
                        == "VISION.DISABLED",
                    )
                    check(
                        "enable requires reauthentication",
                        client.post("/vision/configure", json={"enabled": True}).status_code == 403,
                    )
                    check(
                        "owner reauthentication",
                        client.post("/auth/elevate", json={"password": password}).status_code
                        == 200,
                    )
                    check(
                        "explicit image enable",
                        client.post("/vision/configure", json={"enabled": True}).json()["enabled"],
                    )
                    result = client.post(
                        "/vision/analyze", json=image("ADAM synthetic error: FILE NOT FOUND")
                    ).json()
                    check("real Windows OCR", "FILE NOT FOUND" in result.get("text", ""))
                    check(
                        "perception never authorizes actions",
                        result["action_authority"] is False and result["trust"] == "UNTRUSTED_DATA",
                    )
                    check(
                        "privacy metadata",
                        result["privacy"]["retention"] == "RAM_ONLY"
                        and result["source"]["source"] == "uploaded_image",
                    )
                    check(
                        "uncertainty reported",
                        "misread" in result["uncertainty"]
                        and result["status"] == "PERCEIVED_UNVERIFIED",
                    )
                    check(
                        "thumbnail and image digest",
                        len(result["image"]["sha256"]) == 64
                        and bool(result["image"]["preview_base64"]),
                    )
                    check(
                        "model unavailable is explicit",
                        client.post(
                            "/vision/analyze", json={**image("Synthetic"), "route": "model"}
                        ).json()["error"]
                        == "VISION.MODEL_UNAVAILABLE",
                    )
                    check(
                        "bad image denied",
                        client.post("/vision/analyze", json={"image_base64": "aGVsbG8="}).json()[
                            "error"
                        ]
                        == "VISION.INVALID_IMAGE",
                    )
                    check(
                        "recognizable secret result withheld",
                        client.post(
                            "/vision/analyze", json=image("password: synthetic-only-credential")
                        ).json()["error"]
                        == "VISION.SECRET_DENIED",
                    )
                    check(
                        "remote model endpoint denied",
                        client.post(
                            "/vision/configure",
                            json={
                                "enabled": True,
                                "model_endpoint": "https://example.com",
                                "model_id": "v",
                            },
                        ).json()["error"]
                        == "VISION.LOCAL_ENDPOINT_REQUIRED",
                    )
                    check(
                        "capture off without arming",
                        client.post("/vision/capture", json={}).json()["error"]
                        == "VISION.SCREEN_NOT_ARMED",
                    )
                    import win32gui

                    with FixtureWindow() as fixture:
                        config = {
                            "enabled": True,
                            "screen": True,
                            "allowed_apps": [Path(sys.executable).name],
                        }
                        check(
                            "explicit single capture arm",
                            client.post("/vision/configure", json=config).json()["screen_armed"],
                        )
                        listed = client.get("/vision/windows").json()["windows"]
                        fixture_ticket = next(
                            item["id"]
                            for item in listed
                            if item["title"] == "ADAM synthetic visual QA"
                        )
                        result = client.post(
                            "/vision/capture", json={"window_id": fixture_ticket}
                        ).json()
                        check(
                            "real isolated selected-window capture",
                            result.get("source", {}).get("title") == "ADAM synthetic visual QA"
                            and "FILE NOT FOUND" in result.get("text", ""),
                        )
                        check(
                            "capture consumed once",
                            not client.get("/vision").json()["screen_armed"],
                        )
                        client.post("/vision/configure", json=config)
                        listed = client.get("/vision/windows").json()["windows"]
                        fixture_ticket = next(
                            item["id"]
                            for item in listed
                            if item["title"] == "ADAM synthetic visual QA"
                        )
                        win32gui.SetWindowText(fixture.hwnd, "Password synthetic privacy QA")
                        check(
                            "private title blocks actual capture",
                            client.post(
                                "/vision/capture", json={"window_id": fixture_ticket}
                            ).json()["error"]
                            == "VISION.PRIVATE_WINDOW_DENIED",
                        )
                        win32gui.SetWindowText(fixture.hwnd, "ADAM synthetic visual QA")
                        client.post("/vision/configure", json=config)
                        listed = client.get("/vision/windows").json()["windows"]
                        fixture_ticket = next(
                            item["id"]
                            for item in listed
                            if item["title"] == "ADAM synthetic visual QA"
                        )
                        previous_foreground = win32gui.GetForegroundWindow()
                        outcome = queue.Queue()
                        threading.Thread(
                            target=lambda ch=outcome, conn=client, ticket=fixture_ticket: ch.put(
                                conn.post("/vision/capture", json={"window_id": ticket}).json()
                            ),
                            daemon=True,
                        ).start()
                        deadline = time.monotonic() + 5
                        indicator = 0
                        while time.monotonic() < deadline:
                            indicator = win32gui.FindWindow(None, "ADAM screen capture")
                            if indicator and win32gui.IsWindowVisible(indicator):
                                break
                            time.sleep(0.05)
                        check(
                            "native capture indicator visible",
                            bool(indicator) and win32gui.IsWindowVisible(indicator),
                        )
                        check(
                            "indicator does not steal foreground",
                            win32gui.GetForegroundWindow() == previous_foreground,
                        )
                        client.post("/vision/configure", json={"enabled": False})
                        check(
                            "cancel discards inflight capture",
                            outcome.get(timeout=20).get("error") == "VISION.CANCELLED",
                        )
                        time.sleep(0.2)
                        check(
                            "indicator hidden on cancellation",
                            not win32gui.IsWindowVisible(indicator),
                        )
                    check(
                        "camera and chat have no active visual input",
                        client.get("/vision").json()["camera"] == "UNAVAILABLE"
                        and not client.get("/vision").json()["active_visual_input"],
                    )
                    check(
                        "ordinary identity remains truthful",
                        client.get("/identity").json()["capabilities"]["vision"] == "UNAVAILABLE",
                    )
                    for db in Path(directory).rglob("*.sqlite3"):
                        check(
                            "no OCR payload in " + db.name, b"FILE NOT FOUND" not in db.read_bytes()
                        )
            finally:
                if child.poll() is None:
                    child.stdin.write("stop\n")
                    child.stdin.flush()
                    try:
                        child.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=15)
                if parent_job is not None:
                    import win32api

                    win32api.CloseHandle(parent_job)
            check("owned service stopped " + str(iteration), child.returncode == 0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        (
            json.dumps(
                {
                    "version": APP_VERSION,
                    "mode": "frozen" if args.service else "source",
                    "passed": True,
                    "checks": checks,
                    "limits": (
                        "Synthetic local window and real Windows OCR; "
                        "no personal windows, camera, visual-model quality or human acceptance."
                    ),
                },
                indent=2,
            )
            + "\n"
        ).encode()
    )
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
