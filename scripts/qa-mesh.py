"""Shipped browser RPC + real WebCrypto/TLS against disposable source/frozen core."""

import argparse
import base64
import json
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

from adam import APP_VERSION
from adam.mesh.tls import prepare
from adam.voice.contracts import VoiceConfig
from adam.voice.providers import LocalSpeech


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--voice", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="adam-mesh-qa-") as directory:
        root = Path(directory)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        prepare(root, "127.0.0.1", port)
        (root / "tool-sandbox").mkdir()
        (root / "tool-sandbox/mobile-qa.txt").write_text("Disposable filename fixture")
        config = root / "settings.toml"
        config.write_text(
            (repo / "adam.compact.toml").read_text().replace("max_tokens = 768", "max_tokens = 96")
        )
        command = (
            [str(args.service.resolve())]
            if args.service
            else [sys.executable, "-m", "adam.desktop.service"]
        )
        command += ["--data-dir", directory, "--config", str(config)]
        if not args.real:
            command.append("--probe")
        child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            lines = queue.Queue()
            threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True).start()
            ready = json.loads(lines.get(timeout=180))
            audio = ""
            if args.voice:
                fixture = LocalSpeech(VoiceConfig()).root / "speaker/1-two-speakers-en.wav"
                with wave.open(str(fixture)) as source:
                    assert source.getframerate() == 16000 and source.getnchannels() == 1
                    audio = base64.b64encode(source.readframes(16000 * 10)).decode()
            node_config = {
                "desktop": f"http://127.0.0.1:{ready['port']}",
                "nonce": ready["nonce"],
                "password": "synthetic-mesh-qa-passphrase-918274",
                "ca": str(root / "mesh/tls/ca.pem"),
                "voice": args.voice,
                "real": args.real,
                "audio": audio,
            }
            result = subprocess.run(
                ["node", str(repo / "scripts/qa-mesh-client.mjs")],
                input=json.dumps(node_config),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode:
                raise RuntimeError(result.stderr[-2500:])
            evidence = json.loads(result.stdout)
            evidence.update(release=APP_VERSION, target="frozen" if args.service else "source")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(f"Mesh client: {evidence['passed']} checks passed")
        finally:
            if child.stdin:
                child.stdin.close()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            assert child.returncode == 0, "Owned core did not shut down cleanly"


if __name__ == "__main__":
    main()
