"""Private pipe worker; no API, store, model, screen fallback or input injection."""

import base64
import json
import sys
from typing import Any

from adam.vision.screen import _capture_worker


class Output:
    def send(self, value: dict[str, Any]) -> None:
        if "png" in value:
            value["png_base64"] = base64.b64encode(value.pop("png")).decode()
        print(json.dumps(value), flush=True)

    def close(self) -> None:
        pass


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline(16384))
        selected = request.get("selected")
        if selected:
            selected["rect"] = tuple(selected["rect"])
        _capture_worker(Output(), request["allowed"], request["excluded"], selected)
    except Exception:
        print(json.dumps({"error": "VISION.CAPTURE_UNAVAILABLE"}), flush=True)


if __name__ == "__main__":
    main()
