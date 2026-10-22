import asyncio

from adam.core.config import Settings
from adam.core.runtime import Runtime
from adam.security.auth import AuthManager
from adam.tools.terminal import handle_command
from test_text_runtime import provider


async def terminal_scenario(tmp_path, capsys):
    runtime = Runtime(Settings(data_dir=tmp_path), provider())
    auth = AuthManager(tmp_path)
    try:
        assert await handle_command('/tool {"name":"system.info"}', runtime, auth)
        assert "VERIFIED" in capsys.readouterr().out
        assert await handle_command(
            '/tool {"name":"notes.create","arguments":{"path":"note.txt","text":"hello"}}',
            runtime,
            auth,
        )
        assert "PREVIEW" in capsys.readouterr().out
        assert not (runtime.actions.scope.root / "note.txt").exists()
        assert await handle_command("/plan erase all", runtime, auth)
        assert "CLARIFICATION_REQUIRED" in capsys.readouterr().out
        assert await handle_command("/tool invalid-json", runtime, auth)
        assert "INVALID_COMMAND" in capsys.readouterr().out
        assert not await handle_command("ordinary chat", runtime, auth)
    finally:
        runtime.retrieval.close()


def test_terminal_explicit_preview_and_invalid_commands(tmp_path, capsys):
    asyncio.run(terminal_scenario(tmp_path, capsys))
