import base64
import re
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import psutil  # type: ignore[import-untyped]
from pydantic import Field, field_validator

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.observability.service import TraceService
from adam.security.request import check_authority
from adam.vision.images import MAX_BYTES, Picture, VisionError, decode, normalize
from adam.vision.providers import LocalVisualModel, VisionProvider, WindowsOCR, local_endpoint
from adam.vision.screen import Screen


class Configuration(Contract):
    enabled: bool
    screen: bool = False
    allowed_apps: list[str] = Field(default_factory=lambda: ["notepad.exe"], max_length=20)
    excluded_titles: list[str] = Field(default_factory=list, max_length=20)
    model_endpoint: str = Field(default="", max_length=100)
    model_id: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9_.:/-]*$")

    @field_validator("allowed_apps", "excluded_titles")
    @classmethod
    def normalized(cls, value: list[str], info: Any) -> list[str]:
        result = [item.strip().casefold() for item in value]
        if any(not item or len(item) > 100 or any(ord(ch) < 32 for ch in item) for item in result):
            raise ValueError("invalid exclusions")
        if info.field_name == "allowed_apps" and any(
            not re.fullmatch(r"[a-z0-9_. -]+\.exe", item) for item in result
        ):
            raise ValueError("use application basenames")
        return list(dict.fromkeys(result))


class Analysis(Contract):
    image_base64: str = Field(min_length=1, max_length=MAX_BYTES * 4 // 3 + 4)
    question: str = Field(
        default="Read the visible text and identify any error message.", max_length=1000
    )
    route: Literal["ocr", "model"] = "ocr"


class Capture(Contract):
    window_id: str = Field(default="", pattern=r"^(?:[a-f0-9-]{36})?$")
    question: str = Field(
        default="Read the visible text and identify any error message.", max_length=1000
    )
    route: Literal["ocr", "model"] = "ocr"


class Vision:
    def __init__(
        self,
        traces: TraceService,
        ocr: VisionProvider | None = None,
        screen: Screen | None = None,
        model_factory: Callable[[str, str], VisionProvider] = LocalVisualModel,
    ) -> None:
        self.traces = traces
        self.ocr = ocr or WindowsOCR()
        self.screen = screen or Screen()
        self.model_factory = model_factory
        self.model: VisionProvider | None = None
        self.lock = threading.RLock()
        self.owner = ""
        self.epoch = 0
        self.busy = False
        self.capture_until = 0.0
        self.allowed = ["notepad.exe"]
        self.excluded: list[str] = []
        self.windows: dict[str, dict[str, Any]] = {}

    def status(self, key: str) -> dict[str, Any]:
        with self.lock:
            enabled = bool(key) and key == self.owner
            return {
                "enabled": enabled,
                "screen_armed": enabled and self.capture_until > time.monotonic(),
                "busy": self.busy if enabled else False,
                "ocr": "AVAILABLE" if self.ocr.available() else "UNAVAILABLE",
                "visual_model": "CONFIGURED_UNVERIFIED"
                if enabled and self.model
                else "UNAVAILABLE",
                "screen_capture": "AVAILABLE" if self.screen.available() else "UNAVAILABLE",
                "camera": "UNAVAILABLE",
                "active_visual_input": False,
                "allowed_apps": self.allowed if enabled else [],
                "excluded_titles": self.excluded if enabled else [],
                "storage": "RAM_ONLY",
                "action_authority": False,
            }

    def configure(self, key: str, value: Configuration) -> dict[str, Any]:
        check_authority()
        model = None
        if value.enabled and value.model_endpoint:
            endpoint = local_endpoint(value.model_endpoint)
            if not value.model_id:
                raise VisionError("VISION.MODEL_ID_REQUIRED")
            model = self.model_factory(endpoint, value.model_id)
        if value.screen and (
            not value.enabled or not value.allowed_apps or not self.screen.available()
        ):
            raise VisionError("VISION.CAPTURE_UNAVAILABLE")
        with self.lock:
            self.epoch += 1
            self.windows.clear()
            self.owner = key if value.enabled else ""
            self.model = model
            self.allowed = value.allowed_apps if value.enabled else ["notepad.exe"]
            self.excluded = value.excluded_titles if value.enabled else []
            self.capture_until = time.monotonic() + 60 if value.screen else 0
        self.audit("configure", "COMPLETED")
        return self.status(key)

    def audit(self, event: str, status: str, error: str | None = None) -> None:
        self.traces.emit(new_id(), "vision", event, status, error_code=error)

    def list_windows(self, key: str) -> dict[str, Any]:
        check_authority()
        with self.lock:
            if not key or key != self.owner or self.capture_until < time.monotonic():
                raise VisionError("VISION.SCREEN_NOT_ARMED")
            epoch, allowed, excluded = self.epoch, list(self.allowed), list(self.excluded)
        windows = self.screen.windows(allowed, excluded)
        check_authority()
        with self.lock:
            if self.owner != key or self.epoch != epoch or self.capture_until < time.monotonic():
                raise VisionError("VISION.CANCELLED")
            self.windows = {
                new_id(): metadata
                for metadata in windows
                if not contains_secret(str(metadata.get("title", "")))
            }
            return {
                "windows": [
                    {"id": identifier, "app": metadata["app"], "title": metadata["title"]}
                    for identifier, metadata in self.windows.items()
                ],
                "expires_in_seconds": max(0, int(self.capture_until - time.monotonic())),
            }

    def analyze(self, key: str, value: Analysis | Capture) -> dict[str, Any]:
        check_authority()
        selected = None
        with self.lock:
            if not key or key != self.owner:
                raise VisionError("VISION.DISABLED")
            if self.busy:
                raise VisionError("VISION.BUSY")
            if isinstance(value, Capture):
                if self.capture_until < time.monotonic():
                    raise VisionError("VISION.SCREEN_NOT_ARMED")
                self.capture_until = 0  # Every capture consumes one opt-in, including failures.
                if value.window_id:
                    selected = self.windows.get(value.window_id)
                    self.windows.clear()
                    if selected is None:
                        raise VisionError("VISION.WINDOW_CHANGED")
                else:
                    self.windows.clear()
            if contains_secret(value.question):
                raise VisionError("VISION.SECRET_DENIED")
            if psutil.virtual_memory().available < 512 * 1024 * 1024:
                raise VisionError("VISION.RESOURCE_PRESSURE")
            if value.route == "model" and self.model is None:
                raise VisionError("VISION.MODEL_UNAVAILABLE")
            epoch, model = self.epoch, self.model
            allowed, excluded = list(self.allowed), list(self.excluded)
            self.busy = True

        def guard() -> None:
            check_authority()
            with self.lock:
                if self.owner != key or self.epoch != epoch:
                    raise VisionError("VISION.CANCELLED")

        try:
            metadata: dict[str, Any] = {
                "source_device": "local_desktop",
                "source": "uploaded_image",
            }
            if isinstance(value, Capture):
                self.audit("capture", "STARTED")
                result = self.screen.capture(allowed, excluded, guard, selected)
                picture = normalize(result["png"])
                metadata = result["metadata"]
            else:
                picture = decode(value.image_base64)
            guard()
            result = self.ocr.describe(picture, value.question, guard)
            # No interpretation can route recognized secret text to a model or return it to UI.
            self.no_secrets(result, metadata)
            if value.route == "model":
                assert model is not None
                guard()
                interpretation = model.describe(picture, value.question, guard)
                self.no_secrets(interpretation, {})
                result["interpretation"] = interpretation["interpretation"]
                result["provider"] = "windows_ocr+local_visual_model"
                result["uncertainty"] = interpretation["uncertainty"]
            text = str(result.get("text", ""))
            errors = [
                line[:500]
                for line in text.splitlines()
                if re.search(r"\b(error|exception|failed|not found|denied|traceback)\b", line, re.I)
            ]
            guard()
            self.audit("perception", "COMPLETED")
            return {
                **result,
                "event_id": new_id(),
                "timestamp": time.time(),
                "source": metadata,
                "privacy": {
                    "scope": "OWNER_LOCAL_ONLY",
                    "retention": "RAM_ONLY",
                    "camera_active": False,
                    "continuous_capture": False,
                },
                "image": {
                    "width": picture.width,
                    "height": picture.height,
                    "sha256": picture.digest,
                    "preview_base64": self.preview(picture),
                },
                "error_candidates": errors[:10],
                "trust": "UNTRUSTED_DATA",
                "status": "PERCEIVED_UNVERIFIED",
                "action_authority": False,
                "guidance": (
                    "Check the extracted text against the image before diagnosing an error. "
                    "No action was authorized or performed."
                ),
            }
        except VisionError as exc:
            self.audit("perception", "FAILED", exc.code)
            raise
        finally:
            with self.lock:
                self.busy = False

    @staticmethod
    def no_secrets(result: dict[str, Any], metadata: dict[str, Any]) -> None:
        import json

        if contains_secret(json.dumps(result, ensure_ascii=False)) or contains_secret(
            json.dumps(metadata, ensure_ascii=False)
        ):
            raise VisionError("VISION.SECRET_DENIED")

    @staticmethod
    def preview(picture: Picture) -> str:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(picture.png)) as image:
            image.thumbnail((900, 900))
            output = io.BytesIO()
            image.save(output, "JPEG", quality=75)
            return base64.b64encode(output.getvalue()).decode()
