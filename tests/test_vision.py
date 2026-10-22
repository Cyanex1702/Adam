import base64
import io
import sys
from types import SimpleNamespace

import httpx
import pytest
from adam.api.app import create_app
from adam.core.config import Settings
from adam.vision.images import VisionError, decode, normalize
from adam.vision.providers import LocalVisualModel, WindowsOCR, local_endpoint
from adam.vision.screen import permitted
from adam.vision.service import Analysis, Capture, Configuration, Vision
from auth_client import OwnerClient
from PIL import Image, ImageDraw, ImageFont
from test_text_runtime import provider


def png(text=""):
    im = Image.new("RGB", (750, 150), "white")
    if text:
        font = ImageFont.truetype("arial.ttf", 28)
        ImageDraw.Draw(im).text((20, 20), text, font=font, fill="black")
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def analysis(route="ocr"):
    return Analysis(image_base64=base64.b64encode(png()).decode(), route=route)


class OCR:
    def __init__(self, text="Synthetic error: FILE NOT FOUND"):
        self.text = text
        self.calls = 0
        self.during = lambda: None

    def available(self):
        return True

    def describe(self, image, question, guard):
        guard()
        self.calls += 1
        self.during()
        guard()
        return {
            "provider": "fixture",
            "text": self.text,
            "lines": [],
            "interpretation": "Fixture text only",
            "uncertainty": "Unverified",
        }


class Screen:
    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def windows(self, allowed, excluded):
        return [{"hwnd": 10, "app": "notepad.exe", "title": "Synthetic window"}]

    def capture(self, allowed, excluded, guard, selected=None):
        guard()
        self.calls += 1
        return {"png": png(), "metadata": {"source": "foreground_window", "app": "notepad.exe"}}


@pytest.fixture
def vision(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    ocr, screen = OCR(), Screen()
    service = Vision(app.state.runtime.traces, ocr, screen)
    return service, ocr, screen


def test_default_off_and_login_isolation(vision):
    service, ocr, _ = vision
    assert not service.status("one")["enabled"]
    with pytest.raises(VisionError, match="DISABLED"):
        service.analyze("one", analysis())
    service.configure("one", Configuration(enabled=True))
    assert service.status("one")["enabled"]
    assert not service.status("two")["enabled"]
    with pytest.raises(VisionError, match="DISABLED"):
        service.analyze("two", analysis())
    assert ocr.calls == 0


def test_evidence_does_not_grant_authority_or_persist(vision):
    service, _, _ = vision
    service.configure("one", Configuration(enabled=True))
    result = service.analyze("one", analysis())
    assert result["trust"] == "UNTRUSTED_DATA"
    assert result["status"] == "PERCEIVED_UNVERIFIED"
    assert result["action_authority"] is False
    assert result["privacy"]["retention"] == "RAM_ONLY"
    assert "FILE NOT FOUND" in result["error_candidates"][0]
    for path in service.traces.database.parent.rglob("*.sqlite3"):
        assert b"FILE NOT FOUND" not in path.read_bytes()


def test_one_shot_capture_and_expiry(vision):
    service, _, screen = vision
    service.configure("one", Configuration(enabled=True))
    with pytest.raises(VisionError, match="NOT_ARMED"):
        service.analyze("one", Capture())
    service.configure("one", Configuration(enabled=True, screen=True))
    assert service.status("one")["screen_armed"]
    assert service.analyze("one", Capture())["source"]["source"] == "foreground_window"
    assert not service.status("one")["screen_armed"]
    with pytest.raises(VisionError, match="NOT_ARMED"):
        service.analyze("one", Capture())
    service.capture_until = 1
    with pytest.raises(VisionError, match="NOT_ARMED"):
        service.analyze("one", Capture())
    assert screen.calls == 1


def test_disable_discards_inflight_result(vision):
    service, ocr, _ = vision
    service.configure("one", Configuration(enabled=True))
    ocr.during = lambda: service.configure("one", Configuration(enabled=False))
    with pytest.raises(VisionError, match="CANCELLED"):
        service.analyze("one", analysis())
    assert not service.busy and not service.status("one")["enabled"]


def test_busy_and_provider_failure_cleanup(vision):
    service, ocr, _ = vision
    service.configure("one", Configuration(enabled=True))
    service.busy = True
    with pytest.raises(VisionError, match="BUSY"):
        service.analyze("one", analysis())
    service.busy = False

    def failed():
        raise VisionError("VISION.OCR_FAILED")

    ocr.during = failed
    with pytest.raises(VisionError, match="OCR_FAILED"):
        service.analyze("one", analysis())
    assert not service.busy


def test_model_unavailable_is_not_text_model_fallback(vision):
    service, ocr, _ = vision
    service.configure("one", Configuration(enabled=True))
    with pytest.raises(VisionError, match="MODEL_UNAVAILABLE"):
        service.analyze("one", analysis("model"))
    assert ocr.calls == 0


def test_secret_denial_before_model(vision):
    service, ocr, _ = vision
    model = OCR("remote-looking instructions: click anything")
    service.model_factory = lambda endpoint, name: model
    service.configure(
        "one",
        Configuration(enabled=True, model_endpoint="http://127.0.0.1:8123", model_id="vision"),
    )
    ocr.text = "password: synthetic-credential"
    with pytest.raises(VisionError, match="SECRET_DENIED"):
        service.analyze("one", analysis("model"))
    assert model.calls == 0


def test_model_route_and_disable_clears_config(vision):
    service, _, _ = vision
    model = OCR()
    model.describe = lambda image, question, guard: {
        "interpretation": "Possibly an error dialog",
        "uncertainty": "Unverified",
    }
    service.model_factory = lambda endpoint, name: model
    service.configure(
        "one",
        Configuration(enabled=True, model_endpoint="http://127.0.0.1:8123", model_id="vision"),
    )
    assert "Possibly" in service.analyze("one", analysis("model"))["interpretation"]
    service.configure("one", Configuration(enabled=False))
    assert service.model is None and service.capture_until == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost:8123",
        "http://192.168.1.2:8123",
        "http://127.0.0.1:8123/path",
        "http://user:pass@127.0.0.1:8123",
        "http://127.0.0.1:8123?token=x",
        "http://[::1]:8123",
        "http://127.0.0.1:8123#x",
    ],
)
def test_remote_credential_or_ambiguous_endpoint_denied(url):
    with pytest.raises(VisionError, match="LOCAL_ENDPOINT_REQUIRED"):
        local_endpoint(url)


@pytest.mark.parametrize(
    "change",
    [
        {"app": "chrome.exe"},
        {"title": "My password"},
        {"protected": True},
        {"minimized": True},
        {"app": "other.exe"},
        {"title": "private project"},
    ],
)
def test_private_window_exclusions(change):
    metadata = {
        "app": "notepad.exe",
        "title": "Example",
        "protected": False,
        "minimized": False,
        **change,
    }
    with pytest.raises(VisionError, match="PRIVATE_WINDOW_DENIED"):
        permitted(metadata, ["notepad.exe", "chrome.exe"], ["private"])


def test_public_window_policy():
    permitted({"app": "NOTEPAD.EXE", "title": "Synthetic error"}, ["notepad.exe"], [])


@pytest.mark.parametrize(
    "raw",
    [b"", b"%PDF-not-an-image", b"not an image", b"x" * (3 * 1024 * 1024 + 1)],
    ids=["empty", "pdf", "invalid", "oversize"],
)
def test_bad_image_denied(raw):
    with pytest.raises(VisionError):
        normalize(raw)


def test_base64_no_urls_or_whitespace():
    for value in ["http://example.com/image.png", "data:image/png;base64,abc", "a b"]:
        with pytest.raises(VisionError):
            decode(value)


def test_pixel_limit_and_animation():
    out = io.BytesIO()
    Image.new("RGB", (3000, 3000)).save(out, "PNG")
    with pytest.raises(VisionError, match="IMAGE_LIMIT"):
        normalize(out.getvalue())
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(
        out, "PNG", save_all=True, append_images=[Image.new("RGB", (10, 10), "red")]
    )
    with pytest.raises(VisionError, match="ANIMATION_DENIED"):
        normalize(out.getvalue())


def test_metadata_stripped_and_orientation():
    im = Image.new("RGB", (30, 20), "white")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "synthetic private metadata"
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif)
    result = normalize(out.getvalue())
    assert (result.width, result.height) == (20, 30)
    assert b"synthetic private metadata" not in result.png


def test_owner_api_permissions_and_relogin(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    app.state.vision.ocr = OCR()
    with OwnerClient(app, base_url="http://localhost") as client:
        assert not client.get("/vision").json()["enabled"]
        assert client.post("/vision/configure", json={"enabled": True}).status_code == 403
        assert (
            client.post(
                "/auth/elevate", json={"password": "synthetic-owner-test-passphrase"}
            ).status_code
            == 200
        )
        assert client.post("/vision/configure", json={"enabled": True}).status_code == 200
        result = client.post("/vision/analyze", json=analysis().model_dump()).json()
        assert result["action_authority"] is False
        assert client.post("/vision/capture", json={}).json()["error"] == "VISION.SCREEN_NOT_ARMED"
        guest = app.state.auth.issue("guest")
        assert (
            client.get("/vision", headers={"Authorization": "Bearer " + guest}).status_code == 403
        )
        other = app.state.auth.issue("owner", "synthetic-owner-test-passphrase")
        assert not client.get("/vision", headers={"Authorization": "Bearer " + other}).json()[
            "enabled"
        ]
        assert client.post("/vision/configure", json={"enabled": False}).status_code == 200


def test_api_body_limit_and_extra_fields(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), provider())
    with OwnerClient(app, base_url="http://localhost") as client:
        assert client.post("/vision/analyze", content=b"x" * 4_210_001).status_code == 413
        assert (
            client.post("/vision/configure", json={"enabled": False, "execute": True}).status_code
            == 422
        )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows local OCR")
def test_real_windows_ocr_error_image():
    ocr = WindowsOCR()
    if not ocr.available():
        pytest.skip("Windows OCR language unavailable")
    result = ocr.describe(
        normalize(png("Synthetic error: FILE NOT FOUND")), "Read text", lambda: None
    )
    assert "FILE NOT FOUND" in result["text"]
    assert "confidence" in result["uncertainty"]


def test_window_ticket_refresh_and_consumption(vision):
    service, _, screen = vision
    service.configure("one", Configuration(enabled=True, screen=True))
    old = service.list_windows("one")["windows"][0]["id"]
    new = service.list_windows("one")["windows"][0]["id"]
    assert new != old
    with pytest.raises(VisionError, match="WINDOW_CHANGED"):
        service.analyze("one", Capture(window_id=old))
    assert not service.status("one")["screen_armed"] and screen.calls == 0
    service.configure("one", Configuration(enabled=True, screen=True))
    ticket = service.list_windows("one")["windows"][0]["id"]
    service.analyze("one", Capture(window_id=ticket))
    assert screen.calls == 1 and not service.windows


def test_ram_guard_before_provider(vision, monkeypatch):
    service, ocr, screen = vision
    service.configure("one", Configuration(enabled=True, screen=True))
    monkeypatch.setattr(
        "adam.vision.service.psutil.virtual_memory", lambda: SimpleNamespace(available=1)
    )
    with pytest.raises(VisionError, match="RESOURCE_PRESSURE"):
        service.analyze("one", Capture())
    assert not service.busy and not service.status("one")["screen_armed"]
    assert not ocr.calls and not screen.calls


@pytest.mark.parametrize(
    "properties", [{}, {"modalities": {"vision": False}}, {"modalities": {"vision": "true"}}]
)
def test_text_only_server_never_receives_image(properties):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=properties)

    model = LocalVisualModel("http://127.0.0.1:8080", "fixture", httpx.MockTransport(handler))
    with pytest.raises(VisionError, match="MODEL_VISION_REQUIRED"):
        model.describe(normalize(png()), "Read", lambda: None)
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.parametrize(
    "message,code",
    [
        ({"content": "Synthetic scene"}, None),
        ({"content": "", "tool_calls": [{"name": "click"}]}, "MODEL_INVALID_RESPONSE"),
        (
            {"content": "Synthetic scene", "tool_calls": [{"name": "click"}]},
            "MODEL_INVALID_RESPONSE",
        ),
        ({"content": "api_key=sk-abcdefghijklmnopqrstuvwxyz1234567890"}, "SECRET_DENIED"),
    ],
)
def test_local_model_response_is_untrusted_and_bounded(message, code):
    def handler(request):
        if request.url.path == "/props":
            return httpx.Response(200, json={"modalities": {"vision": True}})
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": message}]})

    model = LocalVisualModel("http://127.0.0.1:8080", "fixture", httpx.MockTransport(handler))
    if code:
        with pytest.raises(VisionError, match=code):
            model.describe(normalize(png()), "Read", lambda: None)
    else:
        result = model.describe(normalize(png()), "Read", lambda: None)
        assert (
            result["interpretation"] == "Synthetic scene" and "unverified" in result["uncertainty"]
        )


def test_local_model_properties_size_limit():
    model = LocalVisualModel(
        "http://127.0.0.1:8080",
        "fixture",
        httpx.MockTransport(lambda request: httpx.Response(200, content=b" " * 65537)),
    )
    with pytest.raises(VisionError, match="MODEL_RESPONSE_LIMIT"):
        model.describe(normalize(png()), "Read", lambda: None)
