"""Development-only disposable UI fixture; never shipped in the native app."""

import os
import secrets
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from adam.core.config import FeatureFlags, Settings
from adam.desktop.service import desktop_app


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="adam-browser-wave9-") as directory:
        nonce = secrets.token_urlsafe(48)
        app = desktop_app(
            Settings(data_dir=Path(directory), features=FeatureFlags(voice=True, speaker_id=True)),
            nonce,
            probe=True,
        )
        app.ready.state.auth.initialize("synthetic-browser-owner-passphrase-91827")
        if os.environ.get("ADAM_FINAL_WAVES_QA") == "1":
            from adam.intelligence.service import Goal, Intelligence

            Intelligence(app.ready.state.runtime.memories).save_goal(
                Goal(title="Fictional QA goal already at 95 percent", project="Cedar QA", progress=95)
            )
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=1421, access_log=False, log_level="error")
        )
        worker = threading.Thread(target=server.run)
        worker.start()
        while not server.started and worker.is_alive():
            time.sleep(0.1)
        environment = dict(
            os.environ,
            ADAM_DESKTOP_QA_ORIGIN="http://127.0.0.1:1421",
            ADAM_DESKTOP_QA_NONCE=nonce,
            VITE_ADAM_BROWSER_QA="1",
        )
        try:
            subprocess.run(
                ["npm.cmd", "run", "dev"],
                cwd=Path(__file__).resolve().parents[1] / "apps/desktop",
                env=environment,
                check=True,
            )
        finally:
            server.should_exit = True
            worker.join(timeout=20)


if __name__ == "__main__":
    main()
