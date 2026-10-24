"""Real GGUF premise-change probes. Responses require review against the case rubric."""
# ruff: noqa: E402, E501

import argparse
import asyncio
import inspect
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--assets", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--careful", action="store_true")
parser.add_argument("--case-limit", type=int, default=24)
args = parser.parse_args()
sys.path.insert(0, str(args.source / "backend"))
os.environ["ADAM_ASSETS_ROOT"] = str(args.assets)

from adam.compute.catalog import ModelProfile
from adam.compute.owned import OwnedLlamaProvider
from adam.core.config import load_settings
from adam.core.contracts import TraceId, new_id
from adam.core.runtime import ChatRequest, Runtime
from adam.models.base import Message, closing_stream

CASES = [
    (
        "father-dies",
        'A father and his son are in a car accident. The father dies at the scene and the son is rushed to the hospital. At the hospital the surgeon looks at the boy and says "I can\'t operate on this boy, he is my son." How can this be?',
        "A living parent, conventionally his mother; do not infer the surgeon's gender from their profession.",
    ),
    (
        "mother-dies",
        'A mother and her son are in a car accident. The Mother dies at the scene and the son is rushed to the hospital. At the hospital the surgeon looks at the boy and says "I can\'t operate on this boy, he is my son." How can this be?',
        "A living father/other parent; never assert the deceased mother is the surgeon or invent the father's involvement in the accident.",
    ),
    (
        "parent-dies-typo",
        'A parent and there son are in a car accident. The parent dies at the scene and the son is rushed to the hospital. At the hospital the surgeon looks at the boy and says "I can\'t operate on this boy, he is my son." How can this be?',
        "Another living parent; gender and precise identity are underdetermined. Do not claim only mother or only father.",
    ),
    (
        "order",
        "A red box is heavier than a blue box. The blue box is heavier than a green box. Which box is lightest?",
        "Green, following the two stated comparisons.",
    ),
    (
        "changed-order",
        "A red box is lighter than a blue box. The blue box is lighter than a green box. Which box is lightest?",
        "Red; update the conclusion when comparisons change.",
    ),
    (
        "contradiction",
        "Assume Nora is older than Ivo and Ivo is older than Mei. Someone concludes Mei is older than Nora. Does that follow?",
        "No; the stated ordering implies Nora is older than Mei.",
    ),
]


async def run():
    results = []
    with tempfile.TemporaryDirectory(prefix="adam-reasoning-repair-") as directory:
        settings = load_settings(args.config, env={"ADAM_DATA_DIR": directory})
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            settings.model.base_url = "http://127.0.0.1:" + str(listener.getsockname()[1])
        profile = ModelProfile(
            profile_id="probe",
            model=settings.model,
            managed=True,
            model_file="qwen3-4b-instruct.gguf",
            device="cpu",
        )
        options = (
            {"mode": "priority"}
            if "mode" in inspect.signature(OwnedLlamaProvider).parameters
            else {}
        )
        provider = OwnedLlamaProvider(profile, **options)
        runtime = Runtime(settings, provider)
        try:
            health = await runtime.compute.load()
            if health.status != "HEALTHY":
                raise RuntimeError(health.reason)
            matrix = [("production-fresh", seed, 0.7, list(range(6))) for seed in (42, 7)]
            matrix += [
                ("production-shared", 42, 0.7, [0, 1, 2]),
                ("production-reversed", 42, 0.7, [2, 1, 0]),
                ("minimal-direct", 42, 0.7, [0, 1, 2]),
                ("production-lower-temperature", 42, 0.2, [0, 1, 2]),
            ]
            for condition, seed, temperature, indices in matrix:
                session = None
                provider.config.seed, provider.config.temperature = seed, temperature
                for index in indices:
                    name, prompt, rubric = CASES[index]
                    if condition == "minimal-direct":
                        provider.config.max_tokens = 768
                        parts, error = [], None
                        try:
                            async with closing_stream(
                                provider.stream(
                                    [
                                        Message(
                                            role="system",
                                            content="You are a helpful assistant. Answer the user's question.",
                                        ),
                                        Message(role="user", content=prompt),
                                    ],
                                    TraceId(new_id()),
                                )
                            ) as stream:
                                async for part in stream:
                                    parts.append(part)
                        except Exception as exc:
                            error = getattr(getattr(exc, "error", None), "code", type(exc).__name__)
                        text = "".join(parts)
                    else:
                        provider.config.max_tokens = 384
                        request = {
                            "text": prompt,
                            "session_id": session
                            if condition in {"production-shared", "production-reversed"}
                            else None,
                        }
                        if args.careful:
                            request["careful"] = True
                        event = await runtime.chat(ChatRequest(**request))
                        session = event.session_id
                        text = str(event.payload.get("text", ""))
                        error = event.payload.get("error")
                    record = {
                        "case": name,
                        "condition": condition,
                        "seed": seed,
                        "temperature": temperature,
                        "answer": text,
                        "error": error,
                        "rubric": rubric,
                    }
                    results.append(record)
                    args.output.write_text(
                        json.dumps(
                            {
                                "model": settings.model.model_id,
                                "careful": args.careful,
                                "results": results,
                                "evaluation": "Premise-support rubric review required; keyword presence is not a passing score.",
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    print(condition, name, "ERROR" if error else "COMPLETE", flush=True)
                    if len(results) >= args.case_limit:
                        return
        finally:
            runtime.retrieval.close()
            await runtime.compute.unload()


asyncio.run(run())
