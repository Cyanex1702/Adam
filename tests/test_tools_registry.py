import pytest
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError, ToolRegistry


def test_registry_metadata_and_strict_arguments():
    registry = ToolRegistry()
    assert len(registry.list()) == 12
    for metadata in registry.list():
        assert metadata.required_capability and metadata.scope and metadata.verification
        assert metadata.arguments_schema["additionalProperties"] is False
    for call in [
        ToolCall(name="shell.exec"),
        ToolCall(name="notes.create", arguments={"path": "a.txt", "text": "ok", "approved": True}),
        ToolCall(name="apps.open", arguments={"application": "powershell"}),
    ]:
        with pytest.raises(ToolError):
            registry.validate(call)
    assert registry.validate(ToolCall(name="files.search")).arguments["limit"] == 100
