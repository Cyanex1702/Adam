"""Disposable real-GGUF lifecycle QA; no model-quality or automatic-role certification."""

import argparse
import asyncio
import json
import os
import socket
import tempfile
from pathlib import Path

from adam import APP_VERSION
from adam.compute.catalog import Catalog, ModelProfile, publish
from adam.compute.diagnostics import process_status
from adam.compute.migration import ModelController, continuity
from adam.core.config import load_settings
from adam.core.runtime import ChatRequest, Runtime
from adam.models.llama_cpp import LlamaCppProvider


async def run(args):
    os.environ["ADAM_ASSETS_ROOT"] = str(args.assets.resolve())
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="adam-real-library-qa-") as directory:
        root = Path(directory)
        settings = load_settings(args.config, env={"ADAM_DATA_DIR": str(root / "data")})
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            settings.model.base_url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        first = ModelProfile(
            profile_id="qa-default",
            model=settings.model,
            managed=True,
            model_file="qwen3-4b-instruct.gguf",
        )
        publish(
            settings.data_dir,
            "config/model-catalog.json",
            Catalog(default_id=first.profile_id, profiles={first.profile_id: first}),
        )
        runtime = Runtime(settings, LlamaCppProvider(settings.model))
        controller = ModelController(runtime.compute)
        library = controller.library
        try:
            await controller.startup()
            check("first real model starts", not runtime.compute.error)
            check(
                "owned child protected by Windows job",
                process_status(runtime.compute)["crash_cleanup"],
            )
            check(
                "source tray indicator created",
                process_status(runtime.compute)["source_tray_visible"],
            )
            saved = await runtime.chat(
                ChatRequest(text="/remember preference qa editor = SyntheticStudio")
            )
            check("synthetic memory persisted", saved.event_type == "agent.completed")
            before = continuity(settings)
            entries = library.scan(str(args.assets / "models"))["entries"]
            real = [
                entry
                for entry in entries
                if Path(entry["path"]).name
                in {"qwen3-4b-instruct.gguf", "qwen3-4b-abliterated.gguf"}
            ]
            check("two regular installed GGUFs discovered", len(real) == 2)
            check("scan does not approve models", not any(entry["approved"] for entry in real))
            for entry in real:
                await library.approve(entry["id"], "quick")
            previous = runtime.compute.delegate.process
            second = next(entry for entry in real if "abliterated" in entry["path"])
            await library.activate(second["id"])
            check("previous owned process stops before replacement", previous.poll() is not None)
            check(
                "second real GGUF becomes healthy",
                (await runtime.compute.health_check()).status == "HEALTHY",
            )
            check("identity and synthetic memory unchanged", continuity(settings) == before)
            check(
                "saved startup default unchanged", controller.catalog.default_id == first.profile_id
            )
            bad_dir = root / "bad-model"
            bad_dir.mkdir()
            (bad_dir / "invalid.gguf").write_bytes(b"GGUF\x03\x00\x00\x00" + bytes(256))
            bad = next(
                entry
                for entry in library.scan(str(bad_dir))["entries"]
                if Path(entry["path"]).name == "invalid.gguf"
            )
            await library.approve(bad["id"], "reasoning")
            try:
                await library.activate(bad["id"])
            except ValueError:
                pass
            else:
                raise AssertionError("invalid GGUF reported success")
            check(
                "failed real load restores previous model",
                (await runtime.compute.health_check()).status == "HEALTHY"
                and controller.active_id == library.state.entries[second["id"]].profile_id,
            )
            check("failed candidate preserves private state", continuity(settings) == before)
        finally:
            process = getattr(runtime.compute.delegate, "process", None)
            await runtime.compute.unload()
            runtime.retrieval.close()
            check(
                "shutdown leaves no owned inference child",
                not process or process.poll() is not None,
            )
    args.output.write_text(
        json.dumps(
            {
                "release": APP_VERSION,
                "checks": checks,
                "passed": len(checks),
                "scope": "Two existing real GGUFs, private ephemeral port, synthetic profile. "
                "The abliterated model is used only for process switching, "
                "not recommended or quality-approved.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
