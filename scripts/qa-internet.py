"""Live source/frozen owner Internet QA using disposable data and public read-only examples."""

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import httpx
from adam import APP_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    checks: list[str] = []
    password = "synthetic-internet-qa-passphrase-694281"

    def check(name: str, condition: bool) -> None:
        assert condition, name
        checks.append(name)

    with tempfile.TemporaryDirectory(prefix="adam-internet-qa-") as directory:
        for iteration in range(2):
            command = (
                [str(args.service.resolve())]
                if args.service
                else [sys.executable, "-m", "adam.desktop.service"]
            ) + ["--probe", "--data-dir", directory]
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                ready: queue.Queue[str] = queue.Queue()
                threading.Thread(
                    target=lambda process=child, channel=ready: channel.put(
                        process.stdout.readline()
                    ),
                    daemon=True,
                ).start()
                receipt = json.loads(ready.get(timeout=150))
                check("ready handshake " + str(iteration), receipt["event"] == "ready")
                with httpx.Client(
                    base_url=f"http://127.0.0.1:{receipt['port']}",
                    timeout=90,
                    headers={"x-adam-desktop": receipt["nonce"]},
                ) as client:
                    if iteration == 0:
                        check(
                            "owner setup",
                            client.post("/desktop/setup", json={"password": password}).status_code
                            == 200,
                        )
                    login = client.post("/auth/login", json={"password": password}).json()
                    client.headers["Authorization"] = "Bearer " + login["token"]
                    check(
                        "Internet off at launch " + str(iteration),
                        not client.get("/internet").json()["enabled"],
                    )
                    if iteration == 1:
                        continue
                    check(
                        "disabled retrieval denied",
                        client.post(
                            "/internet/fetch", json={"url": "https://example.com/"}
                        ).status_code
                        == 409,
                    )
                    check(
                        "enable requires reauthentication",
                        client.post("/internet/configure", json={"enabled": True}).status_code
                        == 409,
                    )
                    check(
                        "owner reauthentication",
                        client.post("/auth/elevate", json={"password": password}).status_code
                        == 200,
                    )
                    check(
                        "explicit enable",
                        client.post("/internet/configure", json={"enabled": True}).json()[
                            "enabled"
                        ],
                    )
                    fetched = client.post(
                        "/internet/fetch", json={"url": "https://example.com/"}
                    ).json()
                    check(
                        "live HTTPS evidence",
                        fetched.get("title") == "Example Domain"
                        and fetched.get("fetched_at", 0) > 0,
                    )
                    check(
                        "external evidence boundary",
                        fetched.get("trust") == "UNTRUSTED_DATA"
                        and fetched.get("source_kind") == "WEB",
                    )
                    check(
                        "private addresses denied",
                        client.post(
                            "/internet/fetch", json={"url": "https://127.0.0.1/"}
                        ).status_code
                        == 409,
                    )
                    check(
                        "local file URL denied",
                        client.post(
                            "/internet/fetch", json={"url": "file:///C:/Windows/win.ini"}
                        ).status_code
                        == 409,
                    )
                    search = client.post(
                        "/internet/search", json={"query": "Python", "provider": "hackernews"}
                    ).json()
                    check("live keyword search", bool(search.get("sources")))
                    check(
                        "search dates and attribution",
                        all(
                            value.get("fetched_at")
                            and value.get("published_at")
                            and value.get("url")
                            for value in search["sources"]
                        ),
                    )
                    check(
                        "secret query denied",
                        client.post(
                            "/internet/search",
                            json={"query": "api_key=synthetic-secret-value-987654321"},
                        ).status_code
                        == 409,
                    )
                    page = client.post(
                        "/internet/browser",
                        json={"operation": "navigate", "url": "https://example.com/"},
                    ).json()
                    check(
                        "text browser navigation",
                        page.get("title") == "Example Domain",
                    )
                    check(
                        "text browser read",
                        client.post("/internet/browser", json={"operation": "read"}).json()[
                            "sha256"
                        ]
                        == page["sha256"],
                    )
                    linked = client.post(
                        "/internet/browser",
                        json={"operation": "navigate", "url": "https://www.python.org/"},
                    ).json()
                    index = next(
                        index
                        for index, link in enumerate(linked["links"])
                        if link["url"] == "https://www.python.org/about/"
                    )
                    clicked = client.post(
                        "/internet/browser", json={"operation": "click", "index": index}
                    ).json()
                    check(
                        "text browser link navigation",
                        clicked.get("url") == "https://www.python.org/about/",
                    )
                    check(
                        "browser arbitrary operation denied",
                        client.post("/internet/browser", json={"operation": "upload"}).status_code
                        == 422,
                    )
                    check(
                        "browser close",
                        client.post("/internet/browser", json={"operation": "close"}).json()[
                            "closed"
                        ],
                    )
                    provider = client.post(
                        "/internet/connect",
                        json={
                            "url": "https://mcp.deepwiki.com/mcp",
                            "tools": ["read_wiki_structure"],
                        },
                    ).json()
                    check(
                        "live MCP discovery",
                        [value["name"] for value in provider.get("tools", [])]
                        == ["read_wiki_structure"],
                    )
                    check(
                        "undeclared tool denied",
                        client.post(
                            "/internet/preview",
                            json={
                                "kind": "provider",
                                "provider": provider["id"],
                                "tool": "ask_question",
                                "arguments": {},
                            },
                        ).status_code
                        == 409,
                    )
                    check(
                        "schema validation",
                        client.post(
                            "/internet/preview",
                            json={
                                "kind": "provider",
                                "provider": provider["id"],
                                "tool": "read_wiki_structure",
                                "arguments": {"repoName": 123},
                            },
                        ).status_code
                        == 409,
                    )
                    denied = client.post(
                        "/internet/preview",
                        json={
                            "kind": "provider",
                            "provider": provider["id"],
                            "tool": "read_wiki_structure",
                            "arguments": {
                                "repoName": "python/cpython",
                                "nested": {"apiKey": "synthetic-not-a-real-key"},
                            },
                        },
                    ).json()
                    check(
                        "nested credentials denied before schema or dispatch",
                        denied.get("error") == "INTERNET.SECRET_INPUT_DENIED",
                    )
                    action = client.post(
                        "/internet/preview",
                        json={
                            "kind": "provider",
                            "provider": provider["id"],
                            "tool": "read_wiki_structure",
                            "arguments": {"repoName": "python/cpython"},
                        },
                    ).json()
                    check("action preview", action.get("state") == "PREVIEW")
                    check(
                        "execution requires approval",
                        client.post(
                            "/internet/execute", json={"identifier": action["id"]}
                        ).status_code
                        == 409,
                    )
                    check(
                        "digest mismatch denied",
                        client.post(
                            "/internet/approve",
                            json={"identifier": action["id"], "digest": "0" * 64},
                        ).status_code
                        == 409,
                    )
                    check(
                        "exact approval",
                        client.post(
                            "/internet/approve",
                            json={"identifier": action["id"], "digest": action["digest"]},
                        ).json()["state"]
                        == "APPROVED",
                    )
                    result = client.post(
                        "/internet/execute", json={"identifier": action["id"]}
                    ).json()
                    check(
                        "live approved read-only MCP call",
                        result.get("state") == "REPORTED"
                        and result.get("result", {}).get("trust") == "UNTRUSTED_DATA",
                    )
                    check(
                        "no duplicate execution",
                        client.post(
                            "/internet/execute", json={"identifier": action["id"]}
                        ).status_code
                        == 409,
                    )
                    check(
                        "provider disconnect",
                        client.post(
                            "/internet/disconnect", json={"identifier": provider["id"]}
                        ).json()["disconnected"],
                    )
                    check("capabilities removed", not client.get("/internet").json()["providers"])
                    check(
                        "explicit disable clears data",
                        client.post("/internet/configure", json={"enabled": False}).json()[
                            "actions"
                        ]
                        == [],
                    )
                    check(
                        "local identity remains usable", client.get("/identity").status_code == 200
                    )
            finally:
                if child.poll() is None:
                    child.stdin.write("stop\n")
                    child.stdin.flush()
                    try:
                        child.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=15)
            check("owned service stopped " + str(iteration), child.returncode == 0)
    result = {
        "version": APP_VERSION,
        "mode": "frozen" if args.service else "source",
        "passed": True,
        "checks": checks,
        "limits": "Public read-only MCP example; no private-account effects, "
        "real-model quality or human UI certification.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(result, indent=2) + "\n").encode())
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
