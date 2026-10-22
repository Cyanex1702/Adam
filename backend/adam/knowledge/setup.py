"""Explicit setup operation; normal retrieval never uses the network."""

import hashlib
import os

import httpx

from adam.core.config import load_settings
from adam.knowledge.embedding import FILES, MODEL_ID


def main() -> None:
    directory = load_settings().knowledge.embedding_dir
    directory.mkdir(parents=True, exist_ok=True)
    repository, revision = MODEL_ID.split("@")
    with httpx.Client(follow_redirects=True, timeout=180) as client:
        for name, (remote, digest) in FILES.items():
            target = directory / name
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                print(f"Verified: {name}")
                continue
            temporary = directory / (name + ".part")
            checksum = hashlib.sha256()
            try:
                with client.stream(
                    "GET", f"https://huggingface.co/{repository}/resolve/{revision}/{remote}"
                ) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as stream:
                        for block in response.iter_bytes(1024 * 1024):
                            checksum.update(block)
                            stream.write(block)
                if checksum.hexdigest() != digest:
                    raise RuntimeError("Downloaded model checksum mismatch.")
                os.replace(temporary, target)
                print(f"Downloaded and verified: {name}")
            finally:
                temporary.unlink(missing_ok=True)
    print(f"Offline embedding model ready: {directory}")


if __name__ == "__main__":
    main()
