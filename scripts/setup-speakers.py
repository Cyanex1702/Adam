"""Download public, checksum-pinned speaker models; never capture or enroll audio."""

import hashlib
import os
import tarfile
from pathlib import Path

import httpx

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
ROOT = Path(os.environ["LOCALAPPDATA"]) / "ADAM/models/voice/speaker"
ASSETS = [
    (
        "nemo_en_titanet_small.onnx",
        "speaker-recongition-models/",
        "ad4a1802485d8b34c722d2a9d04249662f2ece5d28a7a039063ca22f515a789e",
    ),
    (
        "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
        "speaker-segmentation-models/",
        "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
    ),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, category, expected in ASSETS:
        target = ROOT / name
        if not target.is_file() or digest(target) != expected:
            partial = target.with_suffix(target.suffix + ".download")
            with httpx.stream(
                "GET", BASE + category + name, follow_redirects=True, timeout=180
            ) as response:
                response.raise_for_status()
                with partial.open("wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
            if digest(partial) != expected:
                raise RuntimeError("Speaker asset checksum mismatch: " + name)
            partial.replace(target)
    folder = "sherpa-onnx-pyannote-segmentation-3-0"
    with tarfile.open(ROOT / (folder + ".tar.bz2")) as archive:
        for name in ["model.int8.onnx", "LICENSE", "README.md"]:
            member = archive.getmember(folder + "/" + name)
            if not member.isfile() or member.size > 2_000_000:
                raise RuntimeError("Unexpected model archive member")
            archive.extract(member, ROOT, filter="data")
    if (
        digest(ROOT / folder / "model.int8.onnx")
        != "d582f4b4c6b48205de7e0643c57df0df5615a3c176189be3fc461e9d18827b5d"
    ):
        raise RuntimeError("Segmentation checksum mismatch")
    print("Speaker models verified (about 40 MiB runtime assets). Restart ADAM. No audio enrolled.")


if __name__ == "__main__":
    main()
