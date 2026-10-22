import os
import time

import pytest
from adam.core.privacy import register_secret
from adam.security.policy import Principal
from adam.tools.contracts import ToolCall
from adam.tools.registry import ToolError
from adam.tools.service import ActionService

OWNER = Principal(elevated=True)


def test_secret_files_hardlinks_and_expiration(tmp_path):
    service = ActionService(tmp_path)
    secret = "synthetic-never-display-secret-719"
    register_secret(secret)
    (service.scope.root / "secret.txt").write_text(secret)
    with pytest.raises(ToolError, match="SECRET_FILE_DENIED"):
        service.preview(ToolCall(name="files.read", arguments={"path": "secret.txt"}), OWNER)
    (service.scope.root / "source.txt").write_text("public synthetic content")
    os.link(service.scope.root / "source.txt", tmp_path / "outside-hardlink.txt")
    with pytest.raises(ToolError, match="FILE_UNSUPPORTED"):
        service.preview(ToolCall(name="files.read", arguments={"path": "source.txt"}), OWNER)
    action = service.preview(
        ToolCall(name="notes.create", arguments={"path": "new.txt", "text": "new"}), OWNER
    )
    service.approve(action.action_id, action.digest, OWNER)
    action = service.get(action.action_id)
    action.approved_until = time.time() - 1
    service.save(action)
    with pytest.raises(ToolError, match="APPROVAL_REQUIRED"):
        service.execute(action.action_id, OWNER)
    assert not (service.scope.root / "new.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows dispatch allowlist")
def test_dispatch_is_observed_as_uncertain_and_never_repeated(tmp_path, monkeypatch):
    service = ActionService(tmp_path)
    calls = []
    monkeypatch.setattr(service, "dispatcher", lambda name, value: calls.append((name, value)))
    action = service.preview(
        ToolCall(name="apps.open", arguments={"application": "notepad"}), OWNER
    )
    service.approve(action.action_id, action.digest, OWNER)
    result = service.execute(action.action_id, OWNER)
    assert result.result.status == "DISPATCHED"
    assert result.result.epistemic_status == "UNCERTAIN"
    with pytest.raises(ToolError, match="APPROVAL_REQUIRED"):
        service.execute(action.action_id, OWNER)
    assert len(calls) == 1
    (service.scope.root / "script.ps1").write_text("Write-Output 'synthetic'")
    with pytest.raises(ToolError, match="OPEN_TYPE_DENIED"):
        service.preview(ToolCall(name="files.open", arguments={"path": "script.ps1"}), OWNER)
