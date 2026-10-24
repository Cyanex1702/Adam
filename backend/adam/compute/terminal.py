import asyncio
from typing import TYPE_CHECKING, Literal, cast

from adam.compute.contracts import ComputeError
from adam.compute.diagnostics import describe, report

if TYPE_CHECKING:
    from adam.core.runtime import Runtime

HELP = """Chat naturally, or use a command:
  /new                 Start a fresh conversation; saved history remains
  /sessions            List saved conversations
  /resume ID           Continue a saved conversation
  /remember preference editor = Example Studio
                       Save an explicit preference
  /show memory         Inspect saved memory
  /forget TOPIC        Remove matching memories
  /ingest "PATH"       Add an allowed local document (owner)
  /ask QUESTION        Retrieve quotations from ingested documents
  /diagnostics         Explain resource/model problems and next steps
  /performance eco     Leave more CPU time for other applications (owner)
  /performance priority  Give ADAM more CPU time (owner)
  /reload              Retry loading the selected model (owner)
  /careful on|off       Experimental: extract premises, then answer in a second pass
  /models scan [FOLDER] Find local GGUF files without loading them (owner)
  /models approve ID quick|balanced|reasoning   Review a model and checksum it
  /models use ID       Load an approved model for this runtime
  /models auto on|off  Opt into task/resource-based model selection
  /tools               Inspect available tools; /tool previews a structured call
  /mode owner|guest|demo  Change workspace permissions
  /status              Inspect declared capabilities
  /quit                Exit and stop ADAM's owned model server
Tools and computer actions require their documented approval flow.
"""


async def command(text: str, runtime: "Runtime") -> bool:
    name, _, argument = text.strip().partition(" ")
    if name not in {"/help", "/diagnostics", "/performance", "/reload", "/models"}:
        return False
    if name == "/help":
        print(HELP)
        return True
    if runtime.principal.mode != "owner":
        print("Owner workspace required for machine diagnostics and model controls.")
        return True
    try:
        if name == "/models":
            operation, _, rest = argument.partition(" ")
            library = runtime.compute.controller.library
            async with library.lock:
                if operation == "scan":
                    await asyncio.to_thread(library.scan, rest.strip().strip('"') or None)
                elif operation == "approve":
                    fields = rest.split()
                    if len(fields) != 2 or fields[1] not in {"quick", "balanced", "reasoning"}:
                        print("Use /models approve ID quick|balanced|reasoning")
                        return True
                    await library.approve(
                        fields[0], cast(Literal["quick", "balanced", "reasoning"], fields[1])
                    )
                elif operation == "use":
                    await library.activate(rest.strip())
                elif operation == "auto" and rest.strip() in {"on", "off"}:
                    library.state.automatic = rest.strip() == "on"
                    library.save()
                elif operation not in {"", "list"}:
                    print(
                        "Use /models scan [FOLDER], list, approve ID ROLE, use ID, or auto on|off."
                    )
                    return True
                print("Automatic selection: " + ("on" if library.state.automatic else "off"))
                from pathlib import Path

                for item in library.state.entries.values():
                    print(
                        f"{item.id} · {Path(item.path).name} · {item.bytes / 1024**3:.2f} GB · "
                        f"{item.role} · {'approved' if item.approved else 'review required'}"
                    )
        elif name == "/performance":
            if argument not in {"eco", "priority"}:
                print(
                    "Choose /performance eco or /performance priority. Current: "
                    + runtime.compute.config.mode
                )
            else:
                await runtime.compute.set_mode(cast(Literal["eco", "priority"], argument))
                print(
                    "Performance mode: "
                    + argument
                    + ". Only ADAM's own inference process is affected."
                )
        elif name == "/reload":
            with runtime.compute.controller.disk_lock():
                health = await runtime.compute.load()
            print("Model: " + health.status + (" · " + health.reason if health.reason else ""))
        else:
            value = report(runtime.compute.settings, runtime.compute)
            resources = value["resources"]
            available = resources.get("ram_available_bytes")
            disk = resources.get("disk_free_bytes")
            print("ADAM diagnostics · " + value["performance_mode"].title() + " mode")
            print(
                "Available RAM: "
                + (f"{available / 1024**3:.2f} GB" if available is not None else "unavailable")
            )
            print(
                "Free disk: " + (f"{disk / 1024**3:.2f} GB" if disk is not None else "unavailable")
            )
            print("Model state: " + value["model"]["lifecycle"])
            for item in value["issues"]:
                print(f"[{item['code']}] {item['title']}\n  Next: {item['next_step']}")
            if not value["issues"]:
                print("Resource checks passed. Use /reload if the model has not been loaded.")
    except ComputeError as error:
        item = describe(error.code)
        print(f"[{error.code}] {item['title']}\nNext: {item['next_step']}")
    return True
