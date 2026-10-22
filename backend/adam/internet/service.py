"""Session-scoped external access, explicit approvals and cancellation boundaries."""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any, Literal
from urllib.parse import urlencode, urljoin, urlsplit

from pydantic import Field

from adam.core.contracts import Contract, new_id
from adam.core.privacy import contains_secret
from adam.internet.network import InternetError, Network, safe_url
from adam.internet.providers import MCP
from adam.internet.web import Web, document
from adam.observability.service import TraceService
from adam.security.policy import Principal
from adam.security.request import AUTHORITY, check_authority
from adam.tools.service import ActionService


class Configuration(Contract):
    enabled: bool


class URL(Contract):
    url: str = Field(min_length=1, max_length=2048)


class Search(Contract):
    query: str = Field(min_length=1, max_length=256)
    provider: Literal["hackernews", "wikipedia", "searxng"] = "hackernews"
    endpoint: str = Field(default="", max_length=2048)


class Connection(URL):
    tools: list[str] = Field(min_length=1, max_length=20)


class Identifier(Contract):
    identifier: str = Field(pattern=r"^[a-f0-9-]{36}$")


class Preview(Contract):
    kind: Literal["provider", "form"]
    provider: str = ""
    tool: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    form: int = Field(default=0, ge=0, le=19)


class Approval(Identifier):
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class BrowserCommand(Contract):
    operation: Literal["navigate", "read", "click", "type", "close"]
    url: str = ""
    index: int = Field(default=0, ge=0, le=99)
    field: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=2048)


class Internet:
    def __init__(self, traces: TraceService, network: Network | None = None) -> None:
        self.network = network or Network()
        self.web = Web(self.network)
        self.traces = traces
        self.lock = threading.RLock()
        self.owner = ""
        self.epoch = 0
        self.providers: dict[str, MCP] = {}
        self.page: dict[str, Any] | None = None
        self.revision = 0
        self.actions: dict[str, dict[str, Any]] = {}

    def require(self, owner: str) -> None:
        check_authority()
        if self.owner != owner or not owner:
            raise InternetError("INTERNET.DISABLED")

    def status(self, owner: str) -> dict[str, Any]:
        with self.lock:
            enabled = self.owner == owner and bool(owner)
            return {
                "enabled": enabled,
                "providers": [
                    {"id": key, "url": provider.endpoint, "tools": list(provider.tools.values())}
                    for key, provider in self.providers.items()
                ]
                if enabled
                else [],
                "actions": deepcopy(list(self.actions.values())) if enabled else [],
                "browser": "TEXT_HTML_NO_SCRIPTS",
                "search": "Hacker News, Wikipedia or owner-selected HTTPS SearXNG JSON endpoint",
            }

    def configure(self, owner: str, enabled: bool, principal: Principal) -> dict[str, Any]:
        ActionService.permission(principal, elevated=enabled)
        with self.lock:
            check_authority()
            self.epoch += 1
            self.owner = owner if enabled else ""
            self.providers.clear()
            self.actions.clear()
            self.page = None
            self.revision += 1
        return self.status(owner)

    def guarded(self, owner: str, function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self.lock:
            self.require(owner)
            epoch = self.epoch
        original = AUTHORITY.get()

        def guard() -> None:
            if original:
                original()
            if self.epoch != epoch or self.owner != owner:
                raise InternetError("INTERNET.CANCELLED")

        marker = AUTHORITY.set(guard)
        try:
            result = function()
            check_authority()
            return result
        finally:
            AUTHORITY.reset(marker)

    def retrieve(self, owner: str, value: Search | URL) -> dict[str, Any]:
        identifier = new_id()
        self.traces.emit(identifier, "internet", "retrieve", "RUNNING")
        try:
            return self.guarded(
                owner,
                lambda: (
                    self.web.search(value.query, value.provider, value.endpoint)
                    if isinstance(value, Search)
                    else self.web.fetch(value.url)
                ),
            )
        finally:
            self.traces.emit(identifier, "internet", "retrieve", "FINISHED")

    def connect(self, owner: str, value: Connection, principal: Principal) -> dict[str, Any]:
        ActionService.permission(principal, elevated=True)
        with self.lock:
            self.require(owner)
            if len(self.providers) >= 5:
                raise InternetError("INTERNET.PROVIDER_LIMIT")
            epoch = self.epoch
        provider = MCP(self.network, value.url, value.tools)
        self.guarded(owner, provider.discover)
        with self.lock:
            self.require(owner)
            if epoch != self.epoch or len(self.providers) >= 5:
                raise InternetError("INTERNET.CANCELLED")
            identifier = new_id()
            self.providers[identifier] = provider
        self.traces.emit(identifier, "internet", "provider_connect", "REPORTED")
        return {"id": identifier, "url": provider.endpoint, "tools": list(provider.tools.values())}

    def disconnect(self, owner: str, identifier: str) -> None:
        with self.lock:
            self.require(owner)
            self.providers.pop(identifier, None)
            for action in self.actions.values():
                if action["request"]["provider"] == identifier:
                    action["state"] = "CANCELLED"
        self.traces.emit(identifier, "internet", "provider_disconnect", "CANCELLED")

    def browser(self, owner: str, value: BrowserCommand) -> dict[str, Any]:
        identifier = new_id()
        self.traces.emit(identifier, "internet", "browser_" + value.operation, "RUNNING")
        try:
            result = self._browser(owner, value)
        except InternetError as exc:
            self.traces.emit(
                identifier, "internet", "browser_" + value.operation, "FAILED", error_code=exc.code
            )
            raise
        self.traces.emit(identifier, "internet", "browser_" + value.operation, "REPORTED")
        return result

    def _browser(self, owner: str, value: BrowserCommand) -> dict[str, Any]:
        with self.lock:
            self.require(owner)
            if value.operation == "close":
                self.page = None
                self.revision += 1
                return {"closed": True}
            if value.operation == "navigate":
                url = safe_url(value.url)
            else:
                if self.page is None:
                    raise InternetError("INTERNET.PAGE_REQUIRED")
                if value.operation == "read":
                    return deepcopy(self.page)
                if value.operation == "type":
                    try:
                        field = self.page["forms"][value.index]["fields"][value.field]
                        if field["type"] == "hidden" or contains_secret(value.text):
                            raise KeyError()
                        field["value"] = value.text
                        self.revision += 1
                        return deepcopy(self.page)
                    except (KeyError, IndexError):
                        raise InternetError("INTERNET.FIELD_DENIED") from None
                try:
                    url = self.page["links"][value.index]["url"]
                except IndexError:
                    raise InternetError("INTERNET.LINK_DENIED") from None
            revision = self.revision
        page = self.guarded(owner, lambda: self.web.fetch(url))
        with self.lock:
            self.require(owner)
            if revision != self.revision:
                raise InternetError("INTERNET.STALE_PAGE")
            self.page = page
            self.revision += 1
            return deepcopy(page)

    def form_request(self, index: int) -> dict[str, Any]:
        try:
            if self.page is None:
                raise KeyError()
            form = self.page["forms"][index]
            target = safe_url(urljoin(self.page["url"], form["action"]))
            if (
                form.get("unsupported")
                or form["method"] not in {"GET", "POST"}
                or form["encoding"] != "application/x-www-form-urlencoded"
                or urlsplit(target).netloc != urlsplit(self.page["url"]).netloc
            ):
                raise KeyError()
            fields = {key: value["value"] for key, value in form["fields"].items()}
            if len(fields) > 50 or contains_secret(json.dumps(fields)):
                raise KeyError()
            return {
                "url": target,
                "method": form["method"],
                "fields": fields,
                "page_url": self.page["url"],
                "sha256": self.page["sha256"],
                "revision": self.revision,
            }
        except (KeyError, IndexError):
            raise InternetError("INTERNET.FORM_DENIED") from None

    def preview(self, owner: str, value: Preview) -> dict[str, Any]:
        with self.lock:
            self.require(owner)
            if len(self.actions) >= 100:
                raise InternetError("INTERNET.ACTION_LIMIT")
            details: dict[str, Any]
            if value.kind == "provider":
                provider = self.providers.get(value.provider)
                if provider is None:
                    raise InternetError("INTERNET.PROVIDER_UNAVAILABLE")
                provider.validate(value.tool, value.arguments)
                details = {
                    "url": provider.endpoint,
                    "tool": provider.tools[value.tool],
                    "arguments": value.arguments,
                }
            else:
                details = self.form_request(value.form)
            identifier = new_id()
            digest = hashlib.sha256(
                json.dumps([value.model_dump(), details], sort_keys=True).encode()
            ).hexdigest()
            action = {
                "id": identifier,
                "digest": digest,
                "request": value.model_dump(),
                "details": details,
                "state": "PREVIEW",
                "expires": time.time() + 300,
                "risk": "EXTERNAL_SIDE_EFFECT_POSSIBLE",
                "result": None,
            }
            self.actions[identifier] = action
            self.traces.emit(identifier, "internet", "preview", "PREVIEW")
            return deepcopy(action)

    def approve(self, owner: str, value: Approval, principal: Principal) -> dict[str, Any]:
        ActionService.permission(principal, elevated=True)
        with self.lock:
            self.require(owner)
            action = self.actions.get(value.identifier)
            if (
                action is None
                or action["digest"] != value.digest
                or action["state"] != "PREVIEW"
                or action["expires"] < time.time()
            ):
                raise InternetError("INTERNET.APPROVAL_MISMATCH")
            action["state"] = "APPROVED"
            self.traces.emit(value.identifier, "internet", "approve", "APPROVED")
            return deepcopy(action)

    def cancel(self, owner: str, identifier: str) -> None:
        with self.lock:
            self.require(owner)
            action = self.actions.get(identifier)
            if action is None or action["state"] not in {"PREVIEW", "APPROVED", "RUNNING"}:
                raise InternetError("INTERNET.ACTION_TERMINAL")
            action["state"] = "CANCELLED"
            self.traces.emit(identifier, "internet", "cancel", "CANCELLED")

    def execute(self, owner: str, identifier: str, principal: Principal) -> dict[str, Any]:
        ActionService.permission(principal, elevated=True)
        with self.lock:
            self.require(owner)
            action = self.actions.get(identifier)
            if action is None or action["state"] != "APPROVED" or action["expires"] < time.time():
                raise InternetError("INTERNET.APPROVAL_REQUIRED")
            details, request = (
                deepcopy(action["details"]),
                Preview.model_validate(action["request"]),
            )
            if request.kind == "provider":
                provider = self.providers.get(request.provider)
                if provider is None or provider.tools.get(request.tool) != details["tool"]:
                    raise InternetError("INTERNET.STALE_PROVIDER")
            elif details != self.form_request(request.form):
                raise InternetError("INTERNET.STALE_PAGE")
            action["state"] = "RUNNING"
            self.traces.emit(identifier, "internet", "execute", "RUNNING")
        original = AUTHORITY.get()

        def guard() -> None:
            if original:
                original()
            if action["state"] != "RUNNING" or (
                request.kind == "provider" and self.providers.get(request.provider) is not provider
            ):
                raise InternetError("INTERNET.CANCELLED")

        marker = AUTHORITY.set(guard)
        try:

            def perform() -> dict[str, Any]:
                if request.kind == "provider":
                    return provider.call(request.tool, request.arguments)  # type: ignore[union-attr]
                current = self.web.fetch(details["page_url"])
                if current["sha256"] != details["sha256"]:
                    raise InternetError("INTERNET.STALE_PAGE")
                check_authority()
                encoded_fields = urlencode(details["fields"])
                payload: bytes | None = encoded_fields.encode()
                url = details["url"]
                if details["method"] == "GET":
                    url += ("&" if "?" in url else "?") + encoded_fields
                    payload = None
                response = self.network.request(
                    url,
                    method=details["method"],
                    body=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    redirects=False,
                    allowed_origin=details["url"],
                )
                result = document(response)
                return {
                    "page": result,
                    "epistemic_status": "REPORTED",
                    "verification": "response received; external effects unverified",
                }

            result = self.guarded(owner, perform)
            with self.lock:
                check_authority()
                action["result"], action["state"] = result, "REPORTED"
        except Exception as exc:
            with self.lock:
                action["state"] = "UNCERTAIN"
                action["error"] = (
                    exc.code if isinstance(exc, InternetError) else "INTERNET.ACTION_FAILED"
                )
                action["result"] = {
                    "verification": "May have reached external server; never retry automatically"
                }
                if request.kind == "provider":
                    self.providers.pop(request.provider, None)
        finally:
            AUTHORITY.reset(marker)
            self.traces.emit(identifier, "internet", "execute", action["state"])
        return deepcopy(action)
