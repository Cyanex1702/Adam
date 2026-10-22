import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from adam.compute.catalog import ModelProfile
from adam.compute.contracts import ComputeError
from adam.compute.hardware import profile
from adam.compute.migration import ModelController
from adam.compute.resources import ManagedProvider
from adam.models.llama_cpp import LlamaCppProvider
from adam.resilience.cli import owner, settings_for
from adam.resilience.recovery import inspect
from adam.security.auth import AuthError


def main() -> None:
    parser = argparse.ArgumentParser(description="ADAM offline hardware and compute tools")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("command", choices=["hardware", "profiles", "register", "benchmark"])
    parser.add_argument("identifier", nargs="?")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    try:
        settings = settings_for(args.data_dir)
        if args.command == "hardware":
            result = profile(settings.data_dir, benchmark=args.benchmark)
        else:
            if inspect(settings)["mode"] != "HEALTHY":
                raise ComputeError("RECOVERY.READ_ONLY")
            owner(settings)
            controller = ModelController(
                ManagedProvider(LlamaCppProvider(settings.model), settings)
            )

            async def execute() -> dict[str, Any]:
                try:
                    if args.command == "profiles":
                        return controller.cards()
                    if args.command == "register":
                        source = Path(args.identifier or "")
                        if not source.is_file() or source.stat().st_size > 65536:
                            raise ComputeError("MODEL.PROFILE_INVALID")
                        return await controller.register(
                            ModelProfile.model_validate_json(source.read_bytes())
                        )
                    if args.command == "benchmark":
                        return await controller.benchmark(args.identifier or "current")
                    raise ComputeError("MODEL.COMMAND_INVALID")
                finally:
                    await controller.manager.delegate.unload()

            result = asyncio.run(execute())
        print(json.dumps(result, ensure_ascii=True, indent=2))
    except (ComputeError, AuthError) as error:
        print(json.dumps({"status": "FAILED", "error": error.code}))
        raise SystemExit(1) from None
    except (OSError, ValueError):
        print(json.dumps({"status": "FAILED", "error": "COMPUTE.INPUT_OR_IO_FAILED"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
