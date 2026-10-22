"""MCP 2025-11-25 HTTPS tools subset. No processes, roots, sampling or elicitation."""

import json
import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from adam.core.contracts import new_id
from adam.core.privacy import contains_secret, register_secret
from adam.internet.network import InternetError, Network, safe_url

PROTOCOL = "2025-11-25"


def secret_payload(value: Any) -> bool:
    pending = [value]
    visited = 0
    names = {
        "password",
        "passwd",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "authorization",
        "bearer",
        "secret",
        "credential",
        "credentials",
        "token",
    }
    while pending:
        item = pending.pop()
        visited += 1
        if visited > 10000:
            return True
        if isinstance(item, dict):
            if any(re.sub(r"[^a-z]", "", str(key).lower()) in names for key in item):
                return True
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str) and contains_secret(item):
            return True
    return False


def schema_scope(schema: dict[str, Any]) -> None:
    pending: list[tuple[Any, int]] = [(schema, 0)]
    visited = 0
    forbidden = {
        "$ref",
        "$dynamicRef",
        "pattern",
        "patternProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "dependentSchemas",
        "contains",
    }
    while pending:
        value, depth = pending.pop()
        visited += 1
        if depth > 8 or visited > 300:
            raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED")
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED")
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)


class MCP:
    def __init__(self, network: Network, endpoint: str, names: list[str]) -> None:
        self.network, self.endpoint = network, safe_url(endpoint)
        self.names = set(names)
        self.session = ""
        self.tools: dict[str, dict[str, Any]] = {}

    def rpc(self, method: str, params: dict[str, Any], *, notification: bool = False) -> Any:
        identifier = new_id()
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            message["id"] = identifier
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if method != "initialize":
            headers["MCP-Protocol-Version"] = PROTOCOL
        if self.session:
            headers["MCP-Session-Id"] = self.session
        reply = self.network.request(
            self.endpoint,
            method="POST",
            body=json.dumps(message).encode(),
            headers=headers,
            redirects=False,
            allowed_origin=self.endpoint,
        )
        if reply.status not in {200, 202}:
            raise InternetError("INTERNET.PROVIDER_UNAVAILABLE")
        if notification:
            if reply.status != 202:
                raise InternetError("INTERNET.PROVIDER_PROTOCOL_DENIED")
            return None
        content_type = reply.headers.get("content-type", "").split(";")[0]
        try:
            messages = (
                [json.loads(reply.body)]
                if content_type == "application/json"
                else [
                    json.loads(line[5:].strip())
                    for line in reply.body.decode("utf-8").splitlines()
                    if line.startswith("data:") and line[5:].strip()
                ]
                if content_type == "text/event-stream"
                else []
            )
            # Server requests would ask ADAM for authority/data. Fail closed, never dispatch.
            if any("method" in value for value in messages):
                raise ValueError()
            found = [value for value in messages if value.get("id") == identifier]
            if len(found) != 1 or found[0].get("jsonrpc") != "2.0" or "error" in found[0]:
                raise ValueError()
            result = found[0]["result"]
            if not isinstance(result, dict):
                raise ValueError()
            if method == "initialize":
                session = reply.headers.get("mcp-session-id", "")
                if len(session) > 256 or any(not 33 <= ord(char) <= 126 for char in session):
                    raise ValueError()
                self.session = session
                if session:
                    register_secret(session)
            return result
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            raise InternetError("INTERNET.PROVIDER_PROTOCOL_DENIED") from None

    def discover(self) -> dict[str, dict[str, Any]]:
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "ADAM", "version": "0.14.0"},
            },
        )
        if result.get("protocolVersion") != PROTOCOL or "tools" not in result.get(
            "capabilities", {}
        ):
            raise InternetError("INTERNET.PROVIDER_PROTOCOL_DENIED")
        self.rpc("notifications/initialized", {}, notification=True)
        result = self.rpc("tools/list", {})
        if result.get("nextCursor") or not isinstance(result.get("tools"), list):
            raise InternetError("INTERNET.PROVIDER_LIMIT")
        if len(result["tools"]) > 100:
            raise InternetError("INTERNET.PROVIDER_LIMIT")
        tools = {}
        for tool in result["tools"]:
            if not isinstance(tool, dict):
                raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED")
            name = tool.get("name")
            if name not in self.names:
                continue
            schema = tool.get("inputSchema")
            if (
                name in tools
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name)
                or not isinstance(schema, dict)
                or schema.get("type") != "object"
            ):
                raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED")
            encoded = json.dumps(schema)
            # No reference resolution/network fetching; bound schema complexity before validation.
            if len(encoded) > 8192 or "$ref" in encoded or "$dynamicRef" in encoded:
                raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED")
            schema_scope(schema)
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise InternetError("INTERNET.PROVIDER_SCHEMA_DENIED") from None
            tools[name] = {
                "name": name,
                "inputSchema": schema,
                "description": str(tool.get("description", ""))[:1000],
                "risk": "EXTERNAL_SIDE_EFFECT_POSSIBLE",
                "trust": "UNTRUSTED_DATA",
            }
        if tools.keys() != self.names or secret_payload(tools):
            raise InternetError("INTERNET.PROVIDER_SCOPE_DENIED")
        self.tools = tools
        return tools

    def validate(self, name: str, arguments: dict[str, Any]) -> None:
        if name not in self.tools:
            raise InternetError("INTERNET.PROVIDER_SCOPE_DENIED")
        if len(json.dumps(arguments)) > 8192 or secret_payload(arguments):
            raise InternetError("INTERNET.SECRET_INPUT_DENIED")
        if not Draft202012Validator(self.tools[name]["inputSchema"]).is_valid(arguments):
            raise InternetError("INTERNET.PROVIDER_ARGUMENTS_DENIED")

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(name, arguments)
        discovered = self.rpc("tools/list", {})
        current = [tool for tool in discovered.get("tools", []) if tool.get("name") == name]
        if (
            len(current) != 1
            or discovered.get("nextCursor")
            or current[0].get("inputSchema") != self.tools[name]["inputSchema"]
        ):
            raise InternetError("INTERNET.STALE_PROVIDER")
        value = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(value, dict) or secret_payload(value):
            raise InternetError("INTERNET.SECRET_OUTPUT_DENIED")
        # Resource URLs and embedded instructions remain inert JSON, never opened/executed.
        return {
            "result": value,
            "trust": "UNTRUSTED_DATA",
            "epistemic_status": "REPORTED",
            "verification": "provider response received; external effects unverified",
        }
