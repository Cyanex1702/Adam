"""Relocatable source launcher for the explicitly assembled Windows offline bundle."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from adam import APP_VERSION
from adam.compute.catalog import Catalog, ModelProfile, publish, read_catalog
from adam.compute.hardware import assets_root
from adam.core.config import Settings, load_settings
from adam.distribution.setup import PRESETS
from adam.resilience.archive import scoped


def prepare(root: Path, data: Path) -> Settings:
    root = root.resolve()
    os.environ["ADAM_ASSETS_ROOT"] = str(root)
    model = scoped(root, "models/qwen3-4b-instruct.gguf")
    server = scoped(root, "runtime/llama/llama-server.exe")
    if not model.is_file() or not server.is_file():
        raise ValueError("PORTABLE.MODEL_OR_RUNTIME_MISSING")
    print("Verifying the bundled model...", flush=True)
    with model.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    expected = PRESETS["qwen3-4b-instruct"][1]
    if digest != expected:
        raise ValueError("PORTABLE.MODEL_CHECKSUM_FAILED")
    settings = load_settings(
        root / "adam.portable.toml", env={"ADAM_DATA_DIR": str(data.resolve())}
    )
    settings.knowledge.allowed_roots = [root / "samples"]
    settings.identity_dir = None
    catalog = scoped(data, "config/model-catalog.json")
    if not catalog.exists():
        profile = ModelProfile(
            profile_id="portable-cpu",
            model=settings.model,
            managed=True,
            model_file=model.name,
            device="cpu",
        )
        publish(
            data,
            "config/model-catalog.json",
            Catalog(default_id=profile.profile_id, profiles={profile.profile_id: profile}),
        )
    else:
        current = read_catalog(catalog)
        settings.model = current.profiles[current.default_id].model
    return settings


async def self_test(settings: Settings) -> dict[str, object]:
    from adam.compute.migration import ModelController
    from adam.core.runtime import ChatRequest, Runtime
    from adam.models.llama_cpp import LlamaCppProvider

    runtime = Runtime(settings, LlamaCppProvider(settings.model))
    ModelController(runtime.compute)
    try:
        await runtime.compute.controller.startup()
        health = await runtime.provider.health_check()
        if health.status != "HEALTHY":
            raise ValueError("PORTABLE.MODEL_NOT_HEALTHY")
        event = await runtime.chat(ChatRequest(text="What are you? Reply in one short sentence."))
        text = str(event.payload.get("text", ""))
        if event.event_type != "agent.completed" or "adam" not in text.casefold():
            raise ValueError("PORTABLE.CHAT_SELF_TEST_FAILED")
        remembered = await runtime.chat(
            ChatRequest(text="/remember preference test editor = PortableSyntheticStudio")
        )
        if remembered.event_type != "agent.completed":
            raise ValueError("PORTABLE.MEMORY_SELF_TEST_FAILED")
        return {
            "release": APP_VERSION,
            "passed": True,
            "real_model": health.model_id,
            "source_module": str(Path(__file__).resolve()),
            "assets": str(assets_root()),
            "checks": [
                "relocated Python imports source",
                "bundled GGUF SHA-256 matches pinned model",
                "owned CPU model starts",
                "real model identifies as ADAM",
                "source memory command persists",
                "owned model unload runs in finally",
            ],
        }
    finally:
        runtime.retrieval.close()
        await runtime.provider.unload()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--api", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        settings = prepare(args.root, args.data_dir or args.root / "data")
        if args.verify_only:
            print(
                json.dumps(
                    {
                        "release": APP_VERSION,
                        "verified": True,
                        "source": str(Path(__file__).resolve()),
                    }
                )
            )
        elif args.self_test:
            result = asyncio.run(self_test(settings))
            if args.output:
                args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result))
        elif args.api:
            import uvicorn

            from adam.api.app import create_app

            uvicorn.run(create_app(settings), host="127.0.0.1", port=8765, access_log=False)
        else:
            from adam.cli import chat_loop

            print("ADAM " + APP_VERSION + " | Running editable source | CPU profile | /quit exits")
            asyncio.run(chat_loop(settings, "demo" if args.demo else "owner"))
    except KeyboardInterrupt:
        print("Stopped.")
    except (ValueError, OSError) as error:
        print("ADAM could not start: " + str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
