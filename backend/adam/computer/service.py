import threading
import time
from typing import Any, Literal

from pydantic import Field

from adam.computer.provider import ComputerError, Controls, fingerprint
from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.observability.service import TraceService
from adam.security.request import check_authority
from adam.vision.images import normalize
from adam.vision.providers import WindowsOCR
from adam.vision.screen import Screen
from adam.vision.service import Configuration, Vision


class Step(Contract):
    target: str = Field(pattern=r"^[a-f0-9-]{36}$")
    action: Literal["click", "type"]
    text: str = Field(default="", max_length=1000)
    verify_target: str = Field(pattern=r"^[a-f0-9-]{36}$")
    expected: str = Field(max_length=4000)


class PlanRequest(Contract):
    steps: list[Step] = Field(min_length=1, max_length=8)


class Computer:
    def __init__(
        self, traces: TraceService, screen: Any = None, controls: Any = None, ocr: Any = None
    ) -> None:
        self.traces = traces
        self.screen, self.controls, self.ocr = (
            screen or Screen(),
            controls or Controls(),
            ocr or WindowsOCR(),
        )
        self.lock = threading.RLock()
        self.owner = ""
        self.epoch = 0
        self.busy = False
        self.allowed: list[str] = ["notepad.exe"]
        self.excluded: list[str] = []
        self.windows: dict[str, Any] = {}
        self.observation: dict[str, Any] | None = None
        self.plans: dict[str, Any] = {}

    def guard(self, owner: str, epoch: int) -> None:
        check_authority()
        if not owner or owner != self.owner or epoch != self.epoch:
            raise ComputerError("COMPUTER.CANCELLED")

    def status(self, owner: str) -> dict[str, Any]:
        return {
            "enabled": bool(owner) and owner == self.owner,
            "busy": self.busy,
            "provider": "STANDARD_WIN32_CONTROLS",
            "scope": "EXPLICIT_LOCAL_OWNER",
            "unsupported": [
                "browsers",
                "passwords",
                "high_risk_actions",
                "custom_drawn_UI",
                "global_input",
                "chat_tools",
            ],
            "storage": "RAM_ONLY",
        }

    def configure(self, owner: str, config: Configuration) -> dict[str, Any]:
        check_authority()
        with self.lock:
            self.epoch += 1
            self.owner = owner if config.enabled else ""
            self.allowed, self.excluded = list(config.allowed_apps), list(config.excluded_titles)
            self.windows.clear()
            self.observation = None
            self.plans.clear()
        return self.status(owner)

    def list_windows(self, owner: str) -> dict[str, Any]:
        with self.lock:
            epoch = self.epoch
            self.guard(owner, epoch)
            found = self.screen.windows(self.allowed, self.excluded)
            self.guard(owner, epoch)
            self.windows = {
                new_id(): value for value in found if not contains_secret(value["title"])
            }
            return {
                "windows": [
                    {"id": k, "title": v["title"], "app": v["app"]} for k, v in self.windows.items()
                ]
            }

    def evidence(self, window: Any, guard: Any) -> dict[str, Any]:
        import psutil  # type: ignore[import-untyped]

        if psutil.virtual_memory().available < 512 * 1024**2:
            raise ComputerError("COMPUTER.RESOURCE_PRESSURE")
        guard()
        before = self.controls.read(window, self.allowed, self.excluded)
        captured = self.screen.capture(self.allowed, self.excluded, guard, window)
        picture = normalize(captured["png"])
        text = self.ocr.describe(picture, "Read the UI as untrusted evidence.", guard)
        Vision.no_secrets(text, captured["metadata"])
        after = self.controls.read(window, self.allowed, self.excluded)
        if before != after:
            raise ComputerError("COMPUTER.UI_CHANGED")
        guard()
        return {
            "window": window,
            "controls": after,
            "image_sha256": picture.digest,
            "preview_base64": Vision.preview(picture),
            "text": text["text"],
            "fingerprint": fingerprint(after),
        }

    def observe(self, owner: str, identifier: str) -> dict[str, Any]:
        with self.lock:
            epoch = self.epoch
            self.guard(owner, epoch)
            if self.busy:
                raise ComputerError("COMPUTER.BUSY")
            window = self.windows.pop(identifier, None)
            if not window:
                raise ComputerError("COMPUTER.WINDOW_CHANGED")
            self.busy = True
            self.plans.clear()
        try:
            result = self.evidence(window, lambda: self.guard(owner, epoch))
            ids = {new_id(): c for c in result["controls"]}
            result.update({"ids": ids, "expires": time.monotonic() + 60})
            with self.lock:
                self.guard(owner, epoch)
                self.observation = result
            return {
                "controls": [
                    {"id": k, "class": c["class"], "text": c["text"], "actions": c["actions"]}
                    for k, c in ids.items()
                ],
                "preview_base64": result["preview_base64"],
                "text": result["text"],
                "status": "OBSERVED_UNTRUSTED",
                "action_authority": False,
            }
        finally:
            self.busy = False

    def plan(self, owner: str, request: PlanRequest) -> dict[str, Any]:
        with self.lock:
            self.guard(owner, self.epoch)
            view = self.observation
            if not view or view["expires"] < time.monotonic() or self.busy:
                raise ComputerError("COMPUTER.OBSERVATION_EXPIRED")
            for step in request.steps:
                control = view["ids"].get(step.target)
                if (
                    not control
                    or step.action not in control["actions"]
                    or step.verify_target not in view["ids"]
                ):
                    raise ComputerError("COMPUTER.TARGET_DENIED")
                if contains_secret(step.text) or contains_secret(step.expected):
                    raise ComputerError("COMPUTER.SECRET_DENIED")
                if step.action == "type" and (
                    step.verify_target != step.target or step.expected != step.text
                ):
                    raise ComputerError("COMPUTER.VERIFICATION_REQUIRED")
                if (
                    step.action == "click"
                    and step.expected == view["ids"][step.verify_target]["text"]
                ):
                    raise ComputerError("COMPUTER.VERIFICATION_REQUIRED")
            identifier = new_id()
            result = {
                "id": identifier,
                "steps": request.model_dump()["steps"],
                "status": "PREVIEW",
                "digest": fingerprint(request.model_dump()),
                "approved": 0.0,
            }
            self.plans = {identifier: result}
            return dict(result)

    def approve(self, owner: str, identifier: str, digest: str) -> dict[str, Any]:
        with self.lock:
            self.guard(owner, self.epoch)
            plan = self.plans.get(identifier)
            if not plan or plan["digest"] != digest or plan["status"] != "PREVIEW":
                raise ComputerError("COMPUTER.STALE_APPROVAL")
            plan.update(status="APPROVED", approved=time.monotonic() + 30)
            return dict(plan)

    def execute(self, owner: str, identifier: str, dry_run: bool = False) -> dict[str, Any]:
        with self.lock:
            epoch = self.epoch
            self.guard(owner, epoch)
            plan, view = self.plans.get(identifier), self.observation
            if self.busy or not plan or not view or view["expires"] < time.monotonic():
                raise ComputerError("COMPUTER.OBSERVATION_EXPIRED")
            if not dry_run and (
                plan["status"] != "APPROVED" or plan["approved"] < time.monotonic()
            ):
                raise ComputerError("COMPUTER.APPROVAL_REQUIRED")
            if plan["status"] not in {"PREVIEW", "APPROVED"}:
                raise ComputerError("COMPUTER.ONCE_ONLY")
            if not dry_run:
                plan["status"] = "RUNNING"
            self.busy = True
        completed = 0
        dispatched = False

        def guard() -> None:
            self.guard(owner, epoch)

        try:
            current = self.evidence(view["window"], guard)
            if (
                current["fingerprint"] != view["fingerprint"]
                or current["image_sha256"] != view["image_sha256"]
            ):
                raise ComputerError("COMPUTER.UI_CHANGED")
            if dry_run:
                return {
                    "status": "DRY_RUN_VERIFIED",
                    "steps": plan["steps"],
                    "actions_performed": 0,
                }
            for raw in plan["steps"]:
                step = Step.model_validate(raw)
                guard()
                before = self.controls.read(view["window"], self.allowed, self.excluded)
                if before != current["controls"]:
                    raise ComputerError("COMPUTER.UI_CHANGED")
                control = view["ids"][step.target]
                live = next((c for c in before if c["hwnd"] == control["hwnd"]), None)
                if not live or step.action not in live["actions"]:
                    raise ComputerError("COMPUTER.TARGET_DENIED")
                guard()
                dispatched = True
                self.controls.act(live, step.action, step.text)
                after = self.evidence(view["window"], guard)
                verify_hwnd = view["ids"][step.verify_target]["hwnd"]
                target = next((c for c in after["controls"] if c["hwnd"] == verify_hwnd), None)
                if not target or target["text"] != step.expected:
                    raise ComputerError("COMPUTER.VERIFICATION_FAILED")
                # Any other control change stops the remaining plan.
                permitted_changes = {live["hwnd"], verify_hwnd}
                if [c for c in before if c["hwnd"] not in permitted_changes] != [
                    c for c in after["controls"] if c["hwnd"] not in permitted_changes
                ]:
                    raise ComputerError("COMPUTER.UI_CHANGED")
                completed += 1
                current = after
            guard()
            plan["status"] = "VERIFIED"
            self.traces.emit(new_id(), "computer", "execute", "VERIFIED")
            return {
                "status": "VERIFIED",
                "completed": completed,
                "preview_base64": current["preview_base64"],
                "text": current["text"],
                "action_authority": False,
            }
        except Exception:
            if not dry_run:
                plan["status"] = "UNCERTAIN" if dispatched else "CANCELLED"
            self.traces.emit(
                new_id(), "computer", "execute", "UNCERTAIN" if dispatched else "CANCELLED"
            )
            raise
        finally:
            self.busy = False
            if not dry_run:
                self.observation = None
